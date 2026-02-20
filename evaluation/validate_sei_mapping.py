from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
from pathlib import Path

SEI_PATTERN = re.compile(r"frame_id=(?P<frame_id>-?\d+);timestamp_ms=(?P<timestamp_ms>-?\d+)")


def run_cmd(cmd: list[str]) -> bytes:
    completed = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed: {' '.join(cmd)}\nSTDOUT:\n{completed.stdout.decode('utf-8', errors='ignore')}\nSTDERR:\n{completed.stderr.decode('utf-8', errors='ignore')}"
        )
    return completed.stdout


def extract_annexb(video_path: Path) -> bytes:
    return run_cmd([
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(video_path),
        "-c:v",
        "copy",
        "-bsf:v",
        "h264_mp4toannexb",
        "-f",
        "h264",
        "-",
    ])


def split_annexb_nalus(data: bytes) -> list[bytes]:
    starts: list[int] = []
    i = 0
    n = len(data)
    while i + 3 < n:
        if data[i : i + 3] == b"\x00\x00\x01":
            starts.append(i)
            i += 3
            continue
        if i + 4 < n and data[i : i + 4] == b"\x00\x00\x00\x01":
            starts.append(i)
            i += 4
            continue
        i += 1

    nalus: list[bytes] = []
    for idx, start in enumerate(starts):
        if data[start : start + 4] == b"\x00\x00\x00\x01":
            payload_start = start + 4
        else:
            payload_start = start + 3
        payload_end = starts[idx + 1] if idx + 1 < len(starts) else len(data)
        payload = data[payload_start:payload_end]
        if payload:
            nalus.append(payload)
    return nalus


def remove_emulation_prevention(rbsp: bytes) -> bytes:
    out = bytearray()
    zero_count = 0
    for value in rbsp:
        if zero_count >= 2 and value == 0x03:
            zero_count = 0
            continue
        out.append(value)
        if value == 0:
            zero_count += 1
        else:
            zero_count = 0
    return bytes(out)


def parse_h264_sei_messages(nal: bytes) -> list[str]:
    if not nal:
        return []
    rbsp = remove_emulation_prevention(nal[1:])
    offset = 0
    messages: list[str] = []
    while offset + 2 <= len(rbsp):
        payload_type = 0
        while offset < len(rbsp) and rbsp[offset] == 0xFF:
            payload_type += 255
            offset += 1
        if offset >= len(rbsp):
            break
        payload_type += rbsp[offset]
        offset += 1

        payload_size = 0
        while offset < len(rbsp) and rbsp[offset] == 0xFF:
            payload_size += 255
            offset += 1
        if offset >= len(rbsp):
            break
        payload_size += rbsp[offset]
        offset += 1

        if offset + payload_size > len(rbsp):
            break
        payload = rbsp[offset : offset + payload_size]
        offset += payload_size

        if payload_type == 5 and len(payload) >= 16:
            text = payload[16:].decode("utf-8", errors="ignore")
            messages.append(text)

        if offset < len(rbsp) and rbsp[offset] == 0x80:
            break
    return messages


def extract_sei_entries(video_path: Path) -> list[dict]:
    data = extract_annexb(video_path)
    nalus = split_annexb_nalus(data)

    entries: list[dict] = []
    for nal in nalus:
        nal_type = nal[0] & 0x1F
        if nal_type != 6:
            continue
        for text in parse_h264_sei_messages(nal):
            match = SEI_PATTERN.search(text)
            if not match:
                continue
            entries.append(
                {
                    "frame_id": int(match.group("frame_id")),
                    "timestamp_ms": int(match.group("timestamp_ms")),
                    "raw": text,
                }
            )
    return entries


def read_metadata_rows(metadata_csv: Path) -> list[tuple[int, int]]:
    rows: list[tuple[int, int]] = []
    with metadata_csv.open("r", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if len(row) < 2:
                continue
            rows.append((int(row[0]), int(row[1])))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate strict per-frame SEI mapping against metadata")
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--strict-exit", action="store_true")
    args = parser.parse_args()

    metadata_rows = read_metadata_rows(args.metadata)
    sei_entries = extract_sei_entries(args.video)

    comparable = min(len(metadata_rows), len(sei_entries))
    mismatches = 0
    for idx in range(comparable):
        expected = metadata_rows[idx]
        actual = (sei_entries[idx]["frame_id"], sei_entries[idx]["timestamp_ms"])
        if expected != actual:
            mismatches += 1

    strict_ok = len(metadata_rows) == len(sei_entries) and mismatches == 0 and len(metadata_rows) > 0

    report = {
        "metadata_rows": len(metadata_rows),
        "sei_entries": len(sei_entries),
        "mismatches": mismatches,
        "strict_ok": strict_ok,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if args.strict_exit:
        return 0 if strict_ok else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
