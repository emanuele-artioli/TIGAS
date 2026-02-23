from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

from mode_common import (
    build_live_renderer_cmd,
    build_renderer,
    ensure_certificates,
    normalize_addr,
    run_cmd,
    start_tigas_server,
    stop_process_group,
    wait_for_server_startup,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run TIGAS test mode (basic-mode live path + headless + frame capture + quality evaluation)")
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
    parser.add_argument("--addr", default=":4433")
    parser.add_argument("--cert", default=Path("certs/server-chain.crt"), type=Path)
    parser.add_argument("--key", default=Path("certs/server.key"), type=Path)
    parser.add_argument("--dash-cors-origin", default="*")
    parser.add_argument("--dash-window-size", type=int, default=0)
    parser.add_argument("--dash-archive-mode", action="store_true")
    parser.add_argument("--headless-duration", type=int, default=0, help="Seconds to keep headless client connected; 0 auto-computes from frames/fps")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    python_exe = sys.executable
    build_dir = (repo_root / args.build_dir).resolve()
    output_dir = (repo_root / args.output).resolve()
    output_live_dir = (output_dir / "live").resolve()
    output_eval_dir = (output_dir / "evaluation").resolve()
    output_frames_dir = (output_dir / "frames").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_live_dir.mkdir(parents=True, exist_ok=True)
    output_eval_dir.mkdir(parents=True, exist_ok=True)
    output_frames_dir.mkdir(parents=True, exist_ok=True)

    args.dash_archive_mode = True
    if args.dash_window_size > 0:
        args.dash_window_size = 0

    cert_path = (repo_root / args.cert).resolve()
    key_path = (repo_root / args.key).resolve()
    spki_hash = ensure_certificates(repo_root, args.cert, args.key)

    renderer_bin = build_renderer(repo_root, build_dir)

    server_proc = start_tigas_server(
        repo_root=repo_root,
        addr=args.addr,
        cert_path=cert_path,
        key_path=key_path,
        segments_dir=output_live_dir,
        movement_dir=(repo_root / "movement_traces").resolve(),
        control_log_path=(output_live_dir / "control_messages.bin").resolve(),
        dash_cors_origin=args.dash_cors_origin,
    )

    listen_addr = normalize_addr(args.addr)
    headless_status = output_live_dir / "headless_status.json"
    headless_duration = args.headless_duration if args.headless_duration > 0 else max(5, int(args.max_frames / max(1, args.fps)) + 3)

    try:
        wait_for_server_startup(server_proc, args.addr)

        headless_proc = subprocess.Popen(
            [
                python_exe,
                "scripts/headless_client.py",
                "--url",
                f"https://localhost{listen_addr}/",
                "--force-quic-origin",
                f"localhost{listen_addr}",
                "--spki-hash",
                spki_hash,
                "--duration",
                str(headless_duration),
                "--insecure",
                "--status-output",
                str(headless_status),
            ],
            cwd=repo_root,
        )

        try:
            live_renderer_cmd = build_live_renderer_cmd(
                renderer_bin=renderer_bin,
                movement=args.movement,
                output_dir=output_live_dir,
                ply=args.ply,
                max_frames=args.max_frames,
                fps=args.fps,
                codec=args.codec,
                crf=args.crf,
                dash_window_size=args.dash_window_size,
                dash_archive_mode=args.dash_archive_mode,
                disable_cuda=args.disable_cuda,
            )
            run_cmd(live_renderer_cmd, cwd=repo_root)
            wait_code = headless_proc.wait(timeout=headless_duration + 20)
            if wait_code != 0:
                raise RuntimeError(f"headless client exited with code {wait_code}")
        finally:
            if headless_proc.poll() is None:
                headless_proc.terminate()
                try:
                    headless_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    headless_proc.kill()
                    headless_proc.wait(timeout=5)
    finally:
        stop_process_group(server_proc)

    eval_renderer_cmd = [
        str(renderer_bin),
        "--movement",
        str(args.movement.resolve()),
        "--output-dir",
        str(output_eval_dir),
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
    ]
    run_cmd(eval_renderer_cmd, cwd=repo_root)

    gt_video = output_eval_dir / "ground_truth_lossless.mkv"
    lossy_video = output_eval_dir / "test_stream_lossy.mp4"

    gt_frames_dir = output_frames_dir / "ground_truth"
    lossy_frames_dir = output_frames_dir / "lossy"
    gt_frames_dir.mkdir(parents=True, exist_ok=True)
    lossy_frames_dir.mkdir(parents=True, exist_ok=True)

    run_cmd([
        "ffmpeg",
        "-y",
        "-i",
        str(gt_video),
        str(gt_frames_dir / "frame_%06d.png"),
    ], cwd=repo_root)

    run_cmd([
        "ffmpeg",
        "-y",
        "-i",
        str(lossy_video),
        str(lossy_frames_dir / "frame_%06d.png"),
    ], cwd=repo_root)

    lossy_inputs = [lossy_video]
    lossy_inputs.extend(sorted(output_eval_dir.glob("test_stream_lossy_p*.mp4")))

    run_cmd(
        [
            python_exe,
            "scripts/package_dash.py",
            "--inputs",
            *(str(path) for path in lossy_inputs),
            "--output",
            str(output_eval_dir),
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
            str(lossy_video),
            "--output",
            str(output_eval_dir / "sei_messages.json"),
        ],
        cwd=repo_root,
    )

    run_cmd(
        [
            python_exe,
            "evaluation/validate_frame_alignment.py",
            "--video",
            str(lossy_video),
            "--metadata",
            str(output_eval_dir / "frame_metadata.csv"),
            "--sei-json",
            str(output_eval_dir / "sei_messages.json"),
            "--output",
            str(output_eval_dir / "alignment_report.json"),
        ],
        cwd=repo_root,
    )

    run_cmd(
        [
            python_exe,
            "evaluation/validate_sei_mapping.py",
            "--video",
            str(lossy_video),
            "--metadata",
            str(output_eval_dir / "frame_metadata.csv"),
            "--output",
            str(output_eval_dir / "sei_mapping_report.json"),
            *( ["--strict-exit"] if args.require_sei_strict else []),
        ],
        cwd=repo_root,
    )

    run_cmd(
        [
            python_exe,
            "evaluation/vmaf_eval.py",
            "--lossy",
            str(lossy_video),
            "--reference",
            str(gt_video),
            "--vmaf-json",
            str(output_eval_dir / "vmaf_results.json"),
            "--summary-json",
            str(output_eval_dir / "summary.json"),
            "--min-vmaf",
            str(args.min_vmaf),
        ],
        cwd=repo_root,
    )

    summary = json.loads((output_eval_dir / "summary.json").read_text(encoding="utf-8"))
    alignment_report = json.loads((output_eval_dir / "alignment_report.json").read_text(encoding="utf-8"))
    sei_mapping_report = json.loads((output_eval_dir / "sei_mapping_report.json").read_text(encoding="utf-8"))
    headless_report = json.loads(headless_status.read_text(encoding="utf-8")) if headless_status.exists() else {"headless_ok": False}

    with args.network.open("r", encoding="utf-8") as handle:
        bandwidth_values = [float(row[0]) for row in csv.reader(handle) if row and row[0].strip()]

    summary["network_mean_kbps"] = sum(bandwidth_values) / len(bandwidth_values) if bandwidth_values else 0.0
    summary["network_min_kbps"] = min(bandwidth_values) if bandwidth_values else 0.0
    summary["network_max_kbps"] = max(bandwidth_values) if bandwidth_values else 0.0
    summary["frame_alignment_ok"] = bool(alignment_report.get("aligned", False))
    summary["sei_present"] = bool(alignment_report.get("has_sei", False))
    summary["sei_strict_mapping_ok"] = bool(sei_mapping_report.get("strict_ok", False))
    summary["headless_ok"] = bool(headless_report.get("headless_ok", False))
    summary["live_artifacts"] = {
        "mpd": str(output_live_dir / "stream.mpd"),
        "headless_status": str(headless_status),
    }
    summary["evaluation_artifacts"] = {
        "ground_truth_video": str(gt_video),
        "lossy_video": str(lossy_video),
        "ground_truth_frames": str(gt_frames_dir),
        "lossy_frames": str(lossy_frames_dir),
    }

    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    checks_ok = bool(summary.get("good_quality")) and bool(summary.get("frame_alignment_ok")) and bool(summary.get("headless_ok"))
    if args.require_sei_strict:
        checks_ok = checks_ok and bool(summary.get("sei_strict_mapping_ok"))
    return 0 if checks_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
