import os
import subprocess

from util import root_dir, output_dir

ffmpeg_path = os.path.join(root_dir, "ffmpeg-master-latest-win64-gpl-shared", "bin", "ffmpeg.exe")

# Use ffmpeg to create a video from a sequence of images.
def animate_frames(fps: int):
    subprocess.run([
        ffmpeg_path,
        "-framerate",
        f"{fps}",
        "-i",
        os.path.join(output_dir, "frames", "frame_%05d.png"),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        os.path.join(output_dir, "travel.mp4")
    ])