from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
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
    parser.add_argument("--disable-cuda", action="store_true")
    parser.add_argument("--require-sei-strict", action="store_true")
    parser.add_argument("--crf-ladder", type=str, default="")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    python_exe = sys.executable
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
            *( ["--crf-ladder", args.crf_ladder] if args.crf_ladder else []),
            *(["--disable-cuda"] if args.disable_cuda else []),
        ],
        cwd=repo_root,
    )

    lossy_inputs = [output_dir / "test_stream_lossy.mp4"]
    lossy_inputs.extend(sorted(output_dir.glob("test_stream_lossy_p*.mp4")))

    run_cmd(
        [
            python_exe,
            "scripts/package_dash.py",
            "--inputs",
            *(str(path) for path in lossy_inputs),
            "--output",
            str(output_dir),
            "--fps",
            str(args.fps),
        ],
        cwd=repo_root,
    )

    run_cmd(
        [
            python_exe,
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
            python_exe,
            "evaluation/validate_frame_alignment.py",
            "--video",
            str(output_dir / "test_stream_lossy.mp4"),
            "--metadata",
            str(output_dir / "frame_metadata.csv"),
            "--sei-json",
            str(output_dir / "sei_messages.json"),
            "--output",
            str(output_dir / "alignment_report.json"),
        ],
        cwd=repo_root,
    )

    run_cmd(
        [
            python_exe,
            "evaluation/validate_sei_mapping.py",
            "--video",
            str(output_dir / "test_stream_lossy.mp4"),
            "--metadata",
            str(output_dir / "frame_metadata.csv"),
            "--output",
            str(output_dir / "sei_mapping_report.json"),
            *( ["--strict-exit"] if args.require_sei_strict else []),
        ],
        cwd=repo_root,
    )

    run_cmd(
        [
            python_exe,
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
    alignment_report = json.loads((output_dir / "alignment_report.json").read_text(encoding="utf-8"))
    sei_mapping_report = json.loads((output_dir / "sei_mapping_report.json").read_text(encoding="utf-8"))
    with args.network.open("r", encoding="utf-8") as handle:
        bandwidth_values = [float(row[0]) for row in csv.reader(handle) if row and row[0].strip()]
    summary["network_mean_kbps"] = sum(bandwidth_values) / len(bandwidth_values) if bandwidth_values else 0.0
    summary["network_min_kbps"] = min(bandwidth_values) if bandwidth_values else 0.0
    summary["network_max_kbps"] = max(bandwidth_values) if bandwidth_values else 0.0
    summary["frame_alignment_ok"] = bool(alignment_report.get("aligned", False))
    summary["sei_present"] = bool(alignment_report.get("has_sei", False))
    summary["sei_strict_mapping_ok"] = bool(sei_mapping_report.get("strict_ok", False))
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    checks_ok = bool(summary.get("good_quality")) and bool(summary.get("frame_alignment_ok"))
    if args.require_sei_strict:
        checks_ok = checks_ok and bool(summary.get("sei_strict_mapping_ok"))
    return 0 if checks_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
