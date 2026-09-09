"""
Worker-process helpers for parallel frame rendering.

Kept in its own module rather than inline in main.py so that
multiprocessing's `spawn` start method (default on Windows/macOS)
only has to import this lightweight module in each worker process,
instead of re-executing all of main.py (which would re-trigger the
YAML build step and the "Proceed?" prompt).
"""

from camera import Camera
from renderer import Renderer


# One Renderer per worker process, created lazily on first use and
# reused for every frame that worker handles. Reuse matters more
# than ever now: Renderer keeps persistent, incrementally-updated
# matplotlib artists (see renderer.py) specifically so it doesn't
# have to rebuild the whole scene from scratch on every frame.
_renderer = None


def _get_renderer(dpi):
    global _renderer
    if _renderer is None:
        _renderer = Renderer(dpi=dpi)
    return _renderer


def render_and_save_frame(args):
    """
    Render and save a single frame from precomputed, pickle-safe data.

    `args` is a plain tuple of all the arguments needed to render a frame, so that this
    function can be called from a multiprocessing.Pool worker process. The arguments are:
    - frame_path: The path to save the rendered frame.
    - dpi: The DPI to render at.
    - cam_x, cam_y, cam_zoom: The camera position and zoom.
    - route: The full route (list of segments).
    - traveled_route: The portion of the route that has been traveled so far.
    - position: The current position (lon, lat).
    - cities: The list of cities to render.
    - mode: The current mode of transportation.
    - completed_routes: The list of completed routes.
    - cursor_colors: The list of cursor colors.
    - show_labels: Whether to show city labels.
    - show_cursor: Whether to show the cursor.
    - show_current_route: Whether to show the current route.
    """

    (
        frame_path,
        dpi,
        cam_x,
        cam_y,
        cam_zoom,
        route,
        traveled_route,
        position,
        cities,
        mode,
        completed_routes,
        cursor_colors,
        show_labels,
        show_cursor,
        show_current_route
    ) = args

    # A throwaway camera "snapshot" -- set_position() assigns
    # directly with no smoothing, so this exactly reproduces the
    # camera state that was already computed in the sequential pass.
    camera_snapshot = Camera()
    camera_snapshot.set_position(cam_x, cam_y, cam_zoom)

    renderer = _get_renderer(dpi)

    renderer.draw(
        camera_snapshot,
        full_route=route,
        traveled_route=traveled_route,
        position=position,
        cities=cities,
        mode=mode,
        completed_routes=completed_routes,
        cursor_colors=cursor_colors,
        show_labels=show_labels,
        show_cursor=show_cursor,
        show_current_route=show_current_route,
    )

    renderer.save(frame_path)

    return frame_path