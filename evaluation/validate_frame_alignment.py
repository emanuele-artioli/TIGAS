from __future__ import annotations

import argparse
import csv
import json
import subprocess
from pathlib import Path


def run_cmd(cmd: list[str]) -> str:
    completed = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}")
    return completed.stdout


def count_video_frames(video_path: Path) -> int:
    raw = run_cmd([
        "ffprobe",
        "-v",
        "error",
        "-count_frames",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=nb_read_frames",
        "-of",
        "json",
        str(video_path),
    ])
    data = json.loads(raw)
    streams = data.get("streams", [])
    if not streams:
        return 0
    return int(streams[0].get("nb_read_frames", 0) or 0)


def count_metadata_rows(csv_path: Path) -> int:
    with csv_path.open("r", encoding="utf-8") as handle:
        return sum(1 for row in csv.reader(handle) if row)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate frame alignment between encoded stream and metadata")
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--sei-json", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    frame_count = count_video_frames(args.video)
    metadata_count = count_metadata_rows(args.metadata)

    sei_messages = 0
    if args.sei_json.exists():
        sei_messages = len(json.loads(args.sei_json.read_text(encoding="utf-8")))

    aligned = frame_count == metadata_count and frame_count > 0
    report = {
        "video_frames": frame_count,
        "metadata_rows": metadata_count,
        "sei_messages": sei_messages,
        "aligned": aligned,
        "has_sei": sei_messages > 0,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if aligned else 2


if __name__ == "__main__":
    raise SystemExit(main())
