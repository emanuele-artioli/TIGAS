from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def run_cmd(cmd: list[str]) -> str:
    completed = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}")
    return completed.stdout


def extract(video_path: Path) -> list[dict]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_frames",
        "-show_entries",
        "frame=pts_time,side_data_list",
        "-of",
        "json",
        str(video_path),
    ]
    raw = run_cmd(cmd)
    data = json.loads(raw)
    frames = data.get("frames", [])

    output: list[dict] = []
    for idx, frame in enumerate(frames):
        side_data = frame.get("side_data_list", [])
        for entry in side_data:
            side_data_type = str(entry.get("side_data_type", ""))
            if "User Data Unregistered SEI" in side_data_type:
                output.append({"frame_index": idx, "pts_time": frame.get("pts_time"), "sei": entry})
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract user-data-unregistered SEI messages with ffprobe")
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    messages = extract(args.video)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(messages, indent=2), encoding="utf-8")
    print(json.dumps({"sei_messages": len(messages)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
