import os
import sys
import shutil
import time
import platform
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from tqdm import tqdm, trange
from plyer import notification
import urllib.request

# Provide a unique application name and contact info (as required by OSM policy)
opener = urllib.request.build_opener()
opener.addheaders = [('User-Agent', 'MyMapAnimationScript/1.0 (saptak.das625@gmail.com)')]
urllib.request.install_opener(opener)

from util import root_dir, data_dir, output_dir
from build_trip import make_json_trip_file_from_yaml
from trip import Trip
from camera import Camera
from camera_controller import CameraController
from route_generator import RouteGenerator
from animator import animate_frames
from frame_worker import render_and_save_frame

USE_FFMPEG = True  # Set to False to skip video generation (just generate frames)

def main():

    start_time = time.time()

    yaml_file = os.path.join(data_dir, "yaml", "europe_week1.yaml")
    json_file = os.path.join(data_dir, "json", "trip.json")

    # ---------------------------------------------------------
    # Build trip from YAML
    # ---------------------------------------------------------
    make_json_trip_file_from_yaml(yaml_file, json_file, plot=True)

    if 'y' not in input("Proceed with animation? (y/n): ").lower():
        print("Animation aborted.")
        sys.exit(0)

    # ---------------------------------------------------------
    # Load trip
    # ---------------------------------------------------------

    trip = Trip(json_file)

    camera = Camera()
    camera_controller = CameraController()
    route_generator = RouteGenerator()

    routes = []
    durations = []
    modes = []
    cities = []
    for segment_i, segment in enumerate(trip.segments):

        route = route_generator.generate(
            segment,
            points=300
        )
        routes.append(route)
        durations.append(segment["duration"])
        modes.append(segment["mode"])
        start = route[0]
        end = route[-1]

        # `cities` ends up as one entry per stop in the whole trip,
        # in order: [stop0, stop1, ..., stopN]. Segment i travels
        # from cities[i] to cities[i+1]. This full ordered list is
        # what lets us show "every stop visited so far" during
        # playback, just by slicing it -- see below.
        cities.append((segment["from"]["name"], start[0], start[1]))

        if segment_i == len(trip.segments) - 1:
            cities.append((segment["to"]["name"], end[0], end[1]))

        if segment_i == 0:
            camera.set_position(start[0], start[1], zoom=6)

    # ---------------------------------------------------------
    # Animation settings
    # ---------------------------------------------------------

    fps = trip.fps
    dpi = trip.dpi

    intro_duration = 1
    intro_frames = int(intro_duration * fps)

    outro_duration = 3
    outro_frames = int(outro_duration * fps)

    # ---------------------------------------------------------
    # Prepare output folder
    # ---------------------------------------------------------

    frames_dir = os.path.join(output_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)

    for filename in os.listdir(frames_dir):
        file_path = os.path.join(frames_dir, filename)
        try:
            if os.path.isfile(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
        except Exception as e:
            print(f"Failed deleting {file_path}: {e}")

    video_file = os.path.join(output_dir, "travel.mp4")
    if os.path.exists(video_file):
        os.remove(video_file)

    frame_counter = 0

    # --------------------------------------------------------
    # Prefer `fork` on POSIX systems: it clones the already-
    # running, already-imported parent process directly, so
    # workers skip re-importing matplotlib and rebuilding its
    # font cache on first use. `spawn` (the default on Windows,
    # and on macOS since Python 3.8) has to redo that import
    # work in every worker, which shows up as a slow first batch
    # of tasks -- often misread as "no speedup" on whatever
    # section happens to run first.
    # --------------------------------------------------------

    if platform.system() != "Windows":
        mp_context = multiprocessing.get_context("fork")
    else:
        mp_context = None

    worker_count = os.cpu_count() or 1
    print(f"Rendering with {worker_count} worker processes "
          f"(start method: {mp_context.get_start_method() if mp_context else 'spawn'})")

    # One process pool for the entire run -- workers stay warm
    # (and keep their cached Renderer, with its persistent
    # incrementally-updated artists) across intro, every segment,
    # and outro, instead of paying process-startup cost repeatedly.
    with ProcessPoolExecutor(max_workers=worker_count, mp_context=mp_context) as executor:

        # =====================================================
        # INTRO
        # =====================================================
        #
        # The camera never moves during the intro -- every frame
        # is byte-for-byte identical except its filename. Render
        # it exactly once and copy the file for the rest, instead
        # of paying full render+encode cost per frame.
        #
        # Shows just the very first stop's pin (nothing else has
        # been "reached" yet), and the cursor icon for the trip's
        # first mode of travel.

        first_route = routes[0]
        first_start = first_route[0]

        intro_first_path = os.path.join(frames_dir, f"frame_{frame_counter:05}.png")
        render_and_save_frame((
            intro_first_path,
            dpi,
            camera.x, camera.y, camera.zoom,
            first_route, [], first_start,
            cities[:1], modes[0], [], False,
            True, True, True
        ))
        frame_counter += 1


        for _ in trange(intro_frames - 1, desc="Generating intro"):
            frame_path = os.path.join(frames_dir, f"frame_{frame_counter:05}.png")
            shutil.copyfile(intro_first_path, frame_path)
            frame_counter += 1

        # =====================================================
        # TRAVEL ANIMATION
        # =====================================================

        for segment_ind, (route, duration, mode) in enumerate(zip(routes, durations, modes)):

            travel_frames = int(duration * fps)

            # Routes for every segment already finished before this
            # one -- fixed for the whole segment, so compute once.
            completed_routes = routes[:segment_ind]

            # -------------------------------------------------
            # Pass 1 (sequential, cheap): advance the camera
            # frame by frame and record only what rendering
            # needs. This MUST stay sequential -- move_towards()
            # smooths from the camera's own previous state, and
            # CameraController carries state across calls (e.g.
            # flight entry-zoom capture). Parallelizing this
            # part would desync the camera path.
            # -------------------------------------------------

            frame_args = []

            for frame in trange(travel_frames, desc=f"Simulating camera ({segment_ind+1}/{len(routes)})"):

                t = frame / (travel_frames - 1)
                index = int(t * (len(route) - 1))
                position = route[index]
                traveled_route = route[:index + 1]
                arrived = (frame == travel_frames - 1)

                camera_controller.update(
                    camera, mode, route, t,
                    total_frames=travel_frames
                )

                if arrived and mode == "plane":
                    dest = route[-1]
                    camera.set_position(
                        dest[0], dest[1],
                        zoom=camera_controller.flight["end_zoom"]
                    )

                frame_path = os.path.join(frames_dir, f"frame_{frame_counter:05}.png")

                # Every stop already reached, plus -- only once we
                # actually arrive -- this segment's destination.
                # Stays visible on every later segment too, since
                # this slice only ever grows as segment_ind grows.
                visible_cities = cities[segment_ind:segment_ind + 2]

                frame_args.append((
                    frame_path,
                    dpi,
                    camera.x, camera.y, camera.zoom,
                    route, traveled_route, position,
                    visible_cities, mode, completed_routes, arrived,
                    True, True, True
                ))

                frame_counter += 1

            # -------------------------------------------------
            # Pass 2 (parallel): drawing + PNG encoding is the
            # slow, CPU-bound, per-frame-independent part -- now
            # that every frame's camera state and filename are
            # already pinned down, farm it out across processes.
            # -------------------------------------------------

            list(tqdm(
                executor.map(render_and_save_frame, frame_args),
                total=len(frame_args),
                desc=f"Rendering travel ({segment_ind+1}/{len(routes)})"
            ))

        # =====================================================
        # OUTRO
        # =====================================================
        #
        # The outro starts EXACTLY at the final destination.
        #
        # Phase 1:
        #   Zoom out while remaining centered on the destination.
        #
        # Phase 2:
        #   Continue zooming out while smoothly moving toward the
        #   center of the entire trip.
        #
        # Final state:
        #   All destination markers visible.
        #   No labels.
        #   No cursor.
        #   No current/final route.
        #

        last_route = routes[-1]
        last_end = last_route[-1]

        # -----------------------------------------------------
        # Find the geographic center of all destinations.
        # -----------------------------------------------------

        all_x = [city[1] for city in cities]
        all_y = [city[2] for city in cities]

        min_x = min(all_x)
        max_x = max(all_x)

        min_y = min(all_y)
        max_y = max(all_y)

        full_trip_center_x = (
            min_x + max_x
        ) / 2.0

        full_trip_center_y = (
            min_y + max_y
        ) / 2.0

        # -----------------------------------------------------
        # Calculate zoom required to fit every destination.
        #
        # The map is 9:16 portrait, so horizontal width has to
        # be converted into the equivalent vertical extent.
        # -----------------------------------------------------

        aspect = 9 / 16

        trip_width = max_x - min_x
        trip_height = max_y - min_y

        required_height = max(
            trip_height,
            trip_width / aspect,
        )

        # Extra breathing room around the outermost markers.
        required_height *= 1.20

        if required_height > 0:

            full_trip_zoom = (
                1000000 /
                required_height
            )

        else:

            full_trip_zoom = camera.zoom

        # Prevent an excessively distant view.
        full_trip_zoom = max(
            0.05,
            min(20.0, full_trip_zoom)
        )

        # -----------------------------------------------------
        # IMPORTANT:
        #
        # Do NOT use camera.x / camera.y as the starting point.
        #
        # Ground travel uses smoothing/lookahead, so the camera
        # can still be offset from the actual destination on the
        # final frame.
        #
        # Start the outro at the literal final route coordinate.
        # -----------------------------------------------------

        start_x = last_end[0]
        start_y = last_end[1]
        start_zoom = camera.zoom

        # -----------------------------------------------------
        # Outro timing.
        # -----------------------------------------------------

        # Fraction of outro spent zooming out while staying
        # centered on the final destination.
        zoom_hold_fraction = 0.9

        outro_frame_args = []

        for frame in trange(
            outro_frames,
            desc="Simulating outro"
        ):

            if outro_frames <= 1:
                t = 1.0
            else:
                t = frame / (outro_frames - 1)

            # -------------------------------------------------
            # Phase 1:
            #
            # Stay exactly over the final destination while the
            # camera pulls back.
            # -------------------------------------------------

            if t < zoom_hold_fraction:

                phase = t
                # Smoothstep.
                eased = (
                    phase *
                    phase *
                    (3.0 - 2.0 * phase)
                )

                camera_x = start_x
                camera_y = start_y

                camera_zoom = (
                    start_zoom +
                    (
                        full_trip_zoom -
                        start_zoom
                    ) * eased
                )

            # -------------------------------------------------
            # Phase 2:
            #
            # Once sufficiently zoomed out, begin moving the
            # camera toward the center of the entire trip.
            # -------------------------------------------------

            else:

                phase = (
                    t - zoom_hold_fraction
                ) / (
                    1.0 - zoom_hold_fraction
                )

                zoom_phase = t

                # Smoothstep.
                eased = (
                    phase *
                    phase *
                    (3.0 - 2.0 * phase)
                )

                zoom_eased = (
                    zoom_phase *
                    zoom_phase *
                    (3.0 - 2.0 * zoom_phase)
                )

                camera_x = (
                    start_x +
                    (
                        full_trip_center_x -
                        start_x
                    ) * eased
                )

                camera_y = (
                    start_y +
                    (
                        full_trip_center_y -
                        start_y
                    ) * eased
                )

                # Finish at the full-trip zoom.
                camera_zoom = (
                    start_zoom +
                    (
                        full_trip_zoom -
                        start_zoom
                    ) * zoom_eased
                )

            frame_path = os.path.join(
                frames_dir,
                f"frame_{frame_counter:05}.png"
            )

            outro_frame_args.append((
                frame_path,
                dpi,
                camera_x,
                camera_y,
                camera_zoom,
                [],
                [],
                last_end,
                cities,
                modes[-1],
                [],
                True,
                False,  # show_labels
                False,  # show_cursor
                False,  # show_current_route
            ))

            frame_counter += 1

        # -----------------------------------------------------
        # Render outro frames in parallel.
        # -----------------------------------------------------

        list(tqdm(
            executor.map(
                render_and_save_frame,
                outro_frame_args
            ),
            total=len(outro_frame_args),
            desc="Rendering outro"
        ))

    print(f"Generated {frame_counter} frames")

    if not USE_FFMPEG:
        print('Skipping video generation.')
    else:
        print('Starting video generation...')
        animate_frames(fps)
        print('Video generation completed. Check the output folder for the video file.')
    print(f"Total time taken: {time.time() - start_time:.2f} seconds")

    notification.notify(
        title='Map Animator',
        message=f'Video generation completed after {time.time() - start_time:.2f} seconds. Check the output folder for the video file.',
        timeout=10
    )

if __name__ == "__main__":
    main()