from __future__ import annotations

import argparse
import subprocess
import time
from pathlib import Path


def run_cmd(cmd: list[str], cwd: Path | None = None) -> None:
    completed = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}")
    if completed.stdout.strip():
        print(completed.stdout.strip())


def spawn(cmd: list[str], cwd: Path | None = None) -> subprocess.Popen:
    return subprocess.Popen(cmd, cwd=cwd)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run TIGAS basic mode (live rendering/encoding/CMAF streaming)")
    parser.add_argument("--movement", required=True, type=Path)
    parser.add_argument("--ply", required=True, type=Path)
    parser.add_argument("--output", default=Path("artifacts/basic"), type=Path)
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--max-frames", type=int, default=300)
    parser.add_argument("--codec", default="libx264")
    parser.add_argument("--crf", type=int, default=20)
    parser.add_argument("--disable-cuda", action="store_true")
    parser.add_argument("--dash-window-size", type=int, default=5)
    parser.add_argument("--linger-seconds", type=int, default=120, help="How long to keep QUIC server alive after producer finishes (0 disables linger)")
    parser.add_argument("--addr", default=":4433")
    parser.add_argument("--cert", default=Path("certs/server-chain.crt"), type=Path)
    parser.add_argument("--key", default=Path("certs/server.key"), type=Path)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    output_dir = (repo_root / args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    cert_path = (repo_root / args.cert).resolve()
    key_path = (repo_root / args.key).resolve()
    if not cert_path.exists() or not key_path.exists():
        run_cmd(["bash", "scripts/generate_dev_cert.sh", "certs"], cwd=repo_root)

    # Compute SPKI hash for Chrome QUIC certificate trust
    spki_file = repo_root / "certs" / "spki.hash"
    if spki_file.exists():
        spki_hash = spki_file.read_text().strip()
    else:
        import hashlib, base64
        spki_der = subprocess.run(
            ["openssl", "x509", "-in", str(cert_path), "-pubkey", "-noout"],
            capture_output=True, text=True, check=True
        ).stdout
        der_bytes = subprocess.run(
            ["openssl", "pkey", "-pubin", "-outform", "der"],
            input=spki_der, capture_output=True, check=True
        ).stdout
        spki_hash = base64.b64encode(hashlib.sha256(der_bytes).digest()).decode()

    run_cmd(["cmake", "-S", "native/renderer_encoder", "-B", "native/renderer_encoder/build"], cwd=repo_root)
    run_cmd(["cmake", "--build", "native/renderer_encoder/build", "-j"], cwd=repo_root)

    server_proc = spawn([
        "/opt/homebrew/bin/go" if Path("/opt/homebrew/bin/go").exists() else "go",
        "run",
        "./cmd/tigas-server",
        "--addr",
        args.addr,
        "--cert",
        str(cert_path),
        "--key",
        str(key_path),
        "--static",
        str((repo_root / "client").resolve()),
        "--segments",
        str(output_dir),
        "--movement",
        str((repo_root / "movement_traces").resolve()),
        "--control-log",
        str((output_dir / "control_messages.bin").resolve()),
    ], cwd=repo_root / "server")

    try:
        time.sleep(1.0)
        if server_proc.poll() is not None:
            raise RuntimeError(
                "tigas-server exited during startup. Check terminal output above (common causes: wrong cwd, invalid cert paths, port already in use)."
            )
        time.sleep(0.5)
        if server_proc.poll() is not None:
            raise RuntimeError(
                f"tigas-server exited after startup on {args.addr}. Check server logs above."
            )

        renderer_cmd = [
            str((repo_root / "native/renderer_encoder/build/tigas_renderer_encoder").resolve()),
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
            "--live-dash",
            "--dash-window-size",
            str(args.dash_window_size),
            *( ["--disable-cuda"] if args.disable_cuda else []),
        ]
        listen_addr = args.addr if args.addr.startswith(':') else f':{args.addr}'
        print(f"Server ready at https://localhost{listen_addr}/")
        print(f"Launch Chrome with:  --origin-to-force-quic-on=localhost{listen_addr}  --ignore-certificate-errors-spki-list={spki_hash}")
        print(f"  Or run:  bash scripts/launch_quic_chrome.sh https://localhost{listen_addr}/")
        run_cmd(renderer_cmd, cwd=repo_root)
        listen_port = args.addr if args.addr.startswith(":") else f":{args.addr}"
        if args.linger_seconds > 0 and server_proc.poll() is None:
            print(f"Producer finished. Keeping server alive for {args.linger_seconds}s at https://localhost{listen_port}/")
            time.sleep(args.linger_seconds)
        print(f"Basic mode completed. Open https://localhost{listen_port}/ during run.")
        print(f"Artifacts: {output_dir}")
        return 0
    finally:
        if server_proc.poll() is None:
            server_proc.terminate()
            server_proc.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
