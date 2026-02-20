from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def run_cmd(cmd: list[str]) -> None:
    completed = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}")


def package_dash(input_video: Path, output_dir: Path, fps: int) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    mpd_path = output_dir / "stream.mpd"

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_video),
        "-an",
        "-c:v",
        "copy",
        "-f",
        "dash",
        "-seg_duration",
        f"{1.0 / fps:.8f}",
        "-use_timeline",
        "0",
        "-use_template",
        "1",
        "-init_seg_name",
        "init.mp4",
        "-media_seg_name",
        "chunk_$Number$.m4s",
        str(mpd_path),
    ]
    run_cmd(cmd)


def main() -> int:
    parser = argparse.ArgumentParser(description="Package encoded stream to 1-frame CMAF DASH")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--fps", type=int, default=60)
    args = parser.parse_args()

    package_dash(args.input, args.output, args.fps)
    print(f"Wrote DASH manifest to {args.output / 'stream.mpd'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
