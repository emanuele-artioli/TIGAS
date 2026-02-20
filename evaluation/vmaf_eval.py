from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def run_cmd(cmd: list[str]) -> None:
    completed = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}")


def evaluate_vmaf(lossy_video: Path, reference_video: Path, output_json: Path) -> dict:
    ffmpeg_cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(lossy_video),
        "-i",
        str(reference_video),
        "-lavfi",
        f"[0:v][1:v]libvmaf=log_fmt=json:log_path={output_json}",
        "-f",
        "null",
        "-",
    ]
    run_cmd(ffmpeg_cmd)
    return json.loads(output_json.read_text(encoding="utf-8"))


def summarize(vmaf_json: dict, min_vmaf: float) -> dict:
    pooled = vmaf_json.get("pooled_metrics", {})
    vmaf = pooled.get("vmaf", {})
    motion = pooled.get("integer_motion", {})
    return {
        "vmaf_mean": float(vmaf.get("mean", 0.0)),
        "vmaf_min": float(vmaf.get("min", 0.0)),
        "vmaf_max": float(vmaf.get("max", 0.0)),
        "motion_mean": float(motion.get("mean", 0.0)),
        "good_quality": float(vmaf.get("mean", 0.0)) >= min_vmaf,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute true VMAF with ffmpeg/libvmaf")
    parser.add_argument("--lossy", required=True, type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--vmaf-json", required=True, type=Path)
    parser.add_argument("--summary-json", required=True, type=Path)
    parser.add_argument("--min-vmaf", type=float, default=80.0)
    args = parser.parse_args()

    args.vmaf_json.parent.mkdir(parents=True, exist_ok=True)
    args.summary_json.parent.mkdir(parents=True, exist_ok=True)

    vmaf_data = evaluate_vmaf(args.lossy, args.reference, args.vmaf_json)
    summary = summarize(vmaf_data, args.min_vmaf)
    args.summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0 if summary["good_quality"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
