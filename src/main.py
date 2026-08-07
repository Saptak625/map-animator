import os
import shutil
from tqdm import trange
import time

from util import root_dir, output_dir
from trip import Trip
from camera import Camera
from camera_controller import CameraController
from renderer import Renderer
from route_generator import RouteGenerator
from animator import animate_frames

start_time = time.time()
# ---------------------------------------------------------
# Load trip
# ---------------------------------------------------------

trip = Trip(
    os.path.join(
        root_dir,
        "data",
        "trips",
        "europe_test.json"
    )
)


camera = Camera()
camera_controller = CameraController()
renderer = Renderer()
route_generator = RouteGenerator()

routes = []
for segment_i, segment in enumerate(trip.segments):

    route = route_generator.generate(
        segment,
        points=300
    )
    routes.append(route)

    start = route[0]
    end = route[-1]

    if segment_i == 0:
        # Set initial camera position to the first segment's start
        # ---------------------------------------------------------
        # Initialize camera
        # ---------------------------------------------------------

        camera.set_position(
            start[0],
            start[1],
            zoom=6
        )


# ---------------------------------------------------------
# City labels
# ---------------------------------------------------------

cities = [

    (
        segment["from"]["name"],
        start[0],
        start[1]
    ),

    (
        segment["to"]["name"],
        end[0],
        end[1]
    )

]



# ---------------------------------------------------------
# Animation settings
# ---------------------------------------------------------

fps = trip.fps


intro_duration = 2

intro_frames = int(
    intro_duration * fps
)


travel_frames = int(
    segment["duration"] * fps
)



# ---------------------------------------------------------
# Prepare output folder
# ---------------------------------------------------------

frames_dir = os.path.join(
    output_dir,
    "frames"
)


os.makedirs(
    frames_dir,
    exist_ok=True
)



# Clear old frames

for filename in os.listdir(frames_dir):

    file_path = os.path.join(
        frames_dir,
        filename
    )

    try:

        if os.path.isfile(file_path):

            os.unlink(file_path)

        elif os.path.isdir(file_path):

            shutil.rmtree(file_path)


    except Exception as e:

        print(
            f"Failed deleting {file_path}: {e}"
        )



# Remove previous video

video_file = os.path.join(
    output_dir,
    "travel.mp4"
)


if os.path.exists(video_file):

    os.remove(video_file)



frame_counter = 0



# =========================================================
# INTRO
# =========================================================

for _ in trange(
    intro_frames,
    desc="Generating intro"
):


    renderer.draw(

        camera,

        full_route=route,

        traveled_route=[],

        position=start,

        cities=cities,

        arrived=False

    )


    renderer.save(

        os.path.join(
            frames_dir,
            f"frame_{frame_counter:05}.png"
        )

    )


    frame_counter += 1



# =========================================================
# TRAVEL ANIMATION
# =========================================================
for route in routes:
    for frame in trange(
        travel_frames,
        desc="Generating travel"
    ):


        t = frame/(travel_frames-1)



        # current route index

        index = int(
            t*(len(route)-1)
        )



        position = route[index]



        # route already traveled

        traveled_route = route[
            :index+1
        ]



        arrived = (
            frame == travel_frames-1
        )



        # update camera

        camera_controller.update(

            camera,

            segment["mode"],

            route,

            t

        )



        renderer.draw(

            camera,

            full_route=route,

            traveled_route=traveled_route,

            position=position,

            cities=cities,

            arrived=arrived

        )


        renderer.save(

            os.path.join(
                frames_dir,
                f"frame_{frame_counter:05}.png"
            )

        )


        frame_counter += 1



# =========================================================
# OUTRO HOLD
# =========================================================

outro_duration = 2

outro_frames = int(
    outro_duration * fps
)


for _ in trange(
    outro_frames,
    desc="Generating outro"
):


    renderer.draw(

        camera,

        full_route=route,

        traveled_route=route,

        position=end,

        cities=cities,

        arrived=True

    )


    renderer.save(

        os.path.join(
            frames_dir,
            f"frame_{frame_counter:05}.png"
        )

    )


    frame_counter += 1



print(
    f"Generated {frame_counter} frames"
)

print('Starting video generation...')
animate_frames(fps)
print('Video generation completed. Check the output folder for the video file.')
print(
    f"Total time taken: {time.time() - start_time:.2f} seconds"
)