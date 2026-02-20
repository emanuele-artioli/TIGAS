from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path


def run_cmd(cmd: list[str], cwd: Path | None = None) -> None:
    completed = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}")
    if completed.stdout.strip():
        print(completed.stdout.strip())


def spawn(cmd: list[str], cwd: Path | None = None) -> subprocess.Popen:
    return subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run full-stack TIGAS test mode (encode + H3 server + headless client)")
    parser.add_argument("--movement", required=True, type=Path)
    parser.add_argument("--network", required=True, type=Path)
    parser.add_argument("--ply", required=True, type=Path)
    parser.add_argument("--output", default=Path("artifacts/full_stack_test"), type=Path)
    parser.add_argument("--codec", default="libx264")
    parser.add_argument("--max-frames", type=int, default=300)
    parser.add_argument("--min-vmaf", type=float, default=80.0)
    parser.add_argument("--crf-ladder", type=str, default="")
    parser.add_argument("--disable-cuda", action="store_true")
    parser.add_argument("--duration", type=int, default=25)
    parser.add_argument("--cert", default=Path("certs/server.crt"), type=Path)
    parser.add_argument("--key", default=Path("certs/server.key"), type=Path)
    parser.add_argument("--use-network-shaping", action="store_true")
    parser.add_argument("--interface", default="eth0")
    parser.add_argument("--strict-headless", action="store_true")
    parser.add_argument("--require-sei-strict", action="store_true")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    python_exe = sys.executable

    run_cmd([
        python_exe,
        "scripts/run_test_mode.py",
        "--movement",
        str(args.movement.resolve()),
        "--network",
        str(args.network.resolve()),
        "--ply",
        str(args.ply.resolve()),
        "--output",
        str((repo_root / args.output).resolve()),
        "--codec",
        args.codec,
        "--max-frames",
        str(args.max_frames),
        "--min-vmaf",
        str(args.min_vmaf),
        *( ["--crf-ladder", args.crf_ladder] if args.crf_ladder else []),
        *( ["--require-sei-strict"] if args.require_sei_strict else []),
        *(["--disable-cuda"] if args.disable_cuda else []),
    ], cwd=repo_root)

    cert_path = (repo_root / args.cert).resolve()
    key_path = (repo_root / args.key).resolve()
    if not cert_path.exists() or not key_path.exists():
        run_cmd(["bash", "scripts/generate_dev_cert.sh", "certs"], cwd=repo_root)

    server_proc = spawn([
        "/opt/homebrew/bin/go" if Path("/opt/homebrew/bin/go").exists() else "go",
        "run",
        "./cmd/tigas-server",
        "--cert",
        str(cert_path),
        "--key",
        str(key_path),
        "--static",
        str((repo_root / "client").resolve()),
        "--segments",
        str((repo_root / args.output).resolve()),
        "--movement",
        str((repo_root / "movement_traces").resolve()),
        "--control-log",
        str((repo_root / args.output / "control_messages.bin").resolve()),
    ], cwd=repo_root / "server")

    shaper_proc = None
    if args.use_network_shaping:
        shaper_proc = spawn([
            python_exe,
            "scripts/network_shaper.py",
            "--interface",
            args.interface,
            "--trace",
            str(args.network.resolve()),
            "--latency-ms",
            "50",
            "--loss-percent",
            "1.0",
        ], cwd=repo_root)

    try:
        time.sleep(2)
        run_cmd([
            python_exe,
            "scripts/headless_client.py",
            "--url",
            "https://localhost:4433/",
            "--duration",
            str(args.duration),
            "--insecure",
            *([] if args.strict_headless else ["--allow-failure"]),
            "--status-output",
            str((repo_root / args.output / "headless_status.json").resolve()),
        ], cwd=repo_root)
    finally:
        if shaper_proc and shaper_proc.poll() is None:
            shaper_proc.terminate()
            shaper_proc.wait(timeout=10)
        if server_proc.poll() is None:
            server_proc.terminate()
            server_proc.wait(timeout=10)

    print("Full-stack test completed.")
    print(f"Artifacts: {(repo_root / args.output).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
