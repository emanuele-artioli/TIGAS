from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def run_cmd(cmd: list[str]) -> None:
    completed = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}")


def package_dash(input_videos: list[Path], output_dir: Path, fps: int, window_size: int = 5) -> None:
    if not input_videos:
        raise ValueError("At least one input video is required")

    output_dir.mkdir(parents=True, exist_ok=True)
    mpd_path = output_dir / "stream.mpd"

    cmd = ["ffmpeg", "-y"]
    for input_video in input_videos:
        cmd.extend(["-i", str(input_video)])

    if len(input_videos) == 1:
        map_args = ["-map", "0:v"]
        adaptation_sets = "id=0,streams=v"
    else:
        map_args = []
        stream_refs = []
        for idx in range(len(input_videos)):
            map_args.extend(["-map", f"{idx}:v"])
            stream_refs.append(str(idx))
        adaptation_sets = f"id=0,streams={','.join(stream_refs)}"

    cmd.extend([
        "-an",
        *map_args,
        "-c:v",
        "copy",
        "-f",
        "dash",
        "-streaming",
        "1",
        "-ldash",
        "1",
        "-window_size",
        str(window_size),
        "-extra_window_size",
        "0",
        "-remove_at_exit",
        "0",
        "-seg_duration",
        f"{1.0 / fps:.8f}",
        "-use_timeline",
        "0",
        "-use_template",
        "1",
        "-init_seg_name",
        "init_$RepresentationID$.mp4",
        "-media_seg_name",
        "chunk_$RepresentationID$_$Number$.m4s",
        "-adaptation_sets",
        adaptation_sets,
        str(mpd_path),
    ])
    run_cmd(cmd)


def main() -> int:
    parser = argparse.ArgumentParser(description="Package encoded stream to 1-frame CMAF DASH")
    parser.add_argument("--inputs", required=True, nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--window-size", type=int, default=5)
    args = parser.parse_args()

    package_dash(args.inputs, args.output, args.fps, args.window_size)
    print(f"Wrote DASH manifest to {args.output / 'stream.mpd'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
