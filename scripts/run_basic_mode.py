from __future__ import annotations

import argparse
import base64
import hashlib
import os
import signal
import subprocess
import time
import urllib.parse
from pathlib import Path


def run_cmd(cmd: list[str], cwd: Path | None = None) -> None:
    completed = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}")
    if completed.stdout.strip():
        print(completed.stdout.strip())


def spawn(cmd: list[str], cwd: Path | None = None) -> subprocess.Popen:
    return subprocess.Popen(cmd, cwd=cwd, start_new_session=True)


def stop_process_group(proc: subprocess.Popen, timeout_seconds: float = 10.0) -> None:
    try:
        pgid = os.getpgid(proc.pid)
    except ProcessLookupError:
        return

    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return

    try:
        proc.wait(timeout=timeout_seconds)
        return
    except subprocess.TimeoutExpired:
        pass

    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        return

    try:
        proc.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        pass


def parse_port(addr: str) -> int:
    value = addr.strip()
    if value.startswith(":"):
        value = value[1:]
    if not value or not value.isdigit():
        raise RuntimeError(f"Invalid --addr value: {addr}. Expected ':PORT' or 'PORT'.")
    return int(value)


def command_name_for_pid(pid: int) -> str:
    result = subprocess.run(
        ["ps", "-o", "comm=", "-p", str(pid)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip().split("/")[-1]


def pids_on_port(port: int) -> list[int]:
    result = subprocess.run(
        ["lsof", "-nP", "-t", f"-iUDP:{port}", f"-iTCP:{port}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 and not result.stdout.strip():
        return []

    pids: list[int] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.isdigit():
            pids.append(int(line))
    return sorted(set(pids))


def terminate_pid(pid: int, timeout_seconds: float = 5.0) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
            time.sleep(0.1)
        except ProcessLookupError:
            return

    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return


def cleanup_stale_tigas_server(addr: str) -> None:
    port = parse_port(addr)
    stale_pids = pids_on_port(port)
    if not stale_pids:
        return

    allowed_commands = {"tigas-ser", "tigas-server", "go"}
    blocked: list[tuple[int, str]] = []

    for pid in stale_pids:
        cmd_name = command_name_for_pid(pid)
        if cmd_name in allowed_commands:
            print(f"Detected stale TIGAS listener on :{port} (pid={pid}, cmd={cmd_name}). Terminating it.")
            terminate_pid(pid)
        else:
            blocked.append((pid, cmd_name or "unknown"))

    still_busy = pids_on_port(port)
    if still_busy:
        detail = ", ".join(f"pid={pid}" for pid in still_busy)
        if blocked:
            blocked_detail = ", ".join(f"pid={pid} cmd={cmd}" for pid, cmd in blocked)
            raise RuntimeError(
                f"Port :{port} is busy by non-TIGAS process(es): {blocked_detail}. Free the port manually, then retry."
            )
        raise RuntimeError(f"Port :{port} remains busy after cleanup attempt ({detail}).")


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
    parser.add_argument("--dash-cors-origin", default="*", help="Access-Control-Allow-Origin value for /dash/* (needed for external dash.js players)")
    parser.add_argument("--dash-archive-mode", action="store_true", help="Keep full DASH history in MPD and on disk for seeking")
    args = parser.parse_args()

    args.dash_archive_mode = True
    if args.dash_window_size > 0:
        args.dash_window_size = 0

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

    cleanup_stale_tigas_server(args.addr)

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
        "--dash-cors-origin",
        args.dash_cors_origin,
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
            *( ["--dash-archive-mode"] if args.dash_archive_mode else []),
            *( ["--disable-cuda"] if args.disable_cuda else []),
        ]
        listen_addr = args.addr if args.addr.startswith(':') else f':{args.addr}'
        mpd_url = f"https://localhost{listen_addr}/dash/stream.mpd"
        reference_url = (
            "https://reference.dashif.org/dash.js/nightly/samples/dash-if-reference-player/index.html"
            f"?mpd={urllib.parse.quote(mpd_url, safe='')}"
            "&autoLoad=true&autoPlay=true&muted=true"
        )

        print(f"Server ready at https://localhost{listen_addr}/")
        print("Basic mode now uses the DASH-IF reference player by default.")
        print("Seekable archive enabled: full DASH history kept in MPD and segment files.")
        print(f"MPD URL: {mpd_url}")
        print("This MPD is generic and can be used by any dash.js player, not only the reference player.")

        run_cmd([
            "bash",
            "scripts/launch_quic_chrome.sh",
            reference_url,
            f"localhost{listen_addr}",
        ], cwd=repo_root)

        print("Opened Chrome profile configured for local QUIC/SPKI trust and reference player autoload.")
        run_cmd(renderer_cmd, cwd=repo_root)
        listen_port = args.addr if args.addr.startswith(":") else f":{args.addr}"
        if args.linger_seconds > 0 and server_proc.poll() is None:
            print(f"Producer finished. Keeping server alive for {args.linger_seconds}s at https://localhost{listen_port}/")
            time.sleep(args.linger_seconds)
        print(f"Basic mode completed. Open https://localhost{listen_port}/ during run.")
        print(f"Artifacts: {output_dir}")
        return 0
    finally:
        stop_process_group(server_proc)


if __name__ == "__main__":
    raise SystemExit(main())
