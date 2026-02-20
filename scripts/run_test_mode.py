from __future__ import annotations

import argparse
import csv
import json
import subprocess
from pathlib import Path


def run_cmd(cmd: list[str], cwd: Path | None = None) -> None:
    completed = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}")
    if completed.stdout.strip():
        print(completed.stdout.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description="Run TIGAS test mode end-to-end")
    parser.add_argument("--movement", required=True, type=Path)
    parser.add_argument("--network", required=True, type=Path)
    parser.add_argument("--ply", required=True, type=Path)
    parser.add_argument("--build-dir", default=Path("native/renderer_encoder/build"), type=Path)
    parser.add_argument("--output", default=Path("artifacts/test_mode"), type=Path)
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--max-frames", type=int, default=1200)
    parser.add_argument("--codec", default="h264_nvenc")
    parser.add_argument("--crf", type=int, default=26)
    parser.add_argument("--min-vmaf", type=float, default=80.0)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    build_dir = (repo_root / args.build_dir).resolve()
    output_dir = (repo_root / args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    run_cmd(["cmake", "-S", "native/renderer_encoder", "-B", str(build_dir)], cwd=repo_root)
    run_cmd(["cmake", "--build", str(build_dir), "-j"], cwd=repo_root)

    renderer_bin = build_dir / "tigas_renderer_encoder"
    if not renderer_bin.exists():
        raise RuntimeError(f"renderer binary not found at {renderer_bin}")

    run_cmd(
        [
            str(renderer_bin),
            "--movement",
            str(args.movement.resolve()),
            "--output-dir",
            str(output_dir),
            "--ply",
            str(args.ply.resolve()),
            "--max-frames",
            str(args.max_frames),
            "--fps",
            str(args.fps),
            "--codec",
            args.codec,
            "--crf",
            str(args.crf),
        ],
        cwd=repo_root,
    )

    run_cmd(
        [
            "python3",
            "scripts/package_dash.py",
            "--input",
            str(output_dir / "test_stream_lossy.mp4"),
            "--output",
            str(output_dir),
            "--fps",
            str(args.fps),
        ],
        cwd=repo_root,
    )

    run_cmd(
        [
            "python3",
            "evaluation/extract_sei.py",
            "--video",
            str(output_dir / "test_stream_lossy.mp4"),
            "--output",
            str(output_dir / "sei_messages.json"),
        ],
        cwd=repo_root,
    )

    run_cmd(
        [
            "python3",
            "evaluation/vmaf_eval.py",
            "--lossy",
            str(output_dir / "test_stream_lossy.mp4"),
            "--reference",
            str(output_dir / "ground_truth_lossless.mkv"),
            "--vmaf-json",
            str(output_dir / "vmaf_results.json"),
            "--summary-json",
            str(output_dir / "summary.json"),
            "--min-vmaf",
            str(args.min_vmaf),
        ],
        cwd=repo_root,
    )

    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    with args.network.open("r", encoding="utf-8") as handle:
        bandwidth_values = [float(row[0]) for row in csv.reader(handle) if row and row[0].strip()]
    summary["network_mean_kbps"] = sum(bandwidth_values) / len(bandwidth_values) if bandwidth_values else 0.0
    summary["network_min_kbps"] = min(bandwidth_values) if bandwidth_values else 0.0
    summary["network_max_kbps"] = max(bandwidth_values) if bandwidth_values else 0.0
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0 if summary.get("good_quality") else 2


if __name__ == "__main__":
    raise SystemExit(main())
