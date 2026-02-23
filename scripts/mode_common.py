from __future__ import annotations

import base64
import hashlib
import os
import signal
import subprocess
import time
from pathlib import Path


def run_cmd(cmd: list[str], cwd: Path | None = None) -> str:
    completed = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}")
    stdout = completed.stdout.strip()
    if stdout:
        print(stdout)
    return stdout


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


def normalize_addr(addr: str) -> str:
    return addr if addr.startswith(":") else f":{addr}"


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
        if line and line.isdigit():
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
        if blocked:
            blocked_detail = ", ".join(f"pid={pid} cmd={cmd}" for pid, cmd in blocked)
            raise RuntimeError(
                f"Port :{port} is busy by non-TIGAS process(es): {blocked_detail}. Free the port manually, then retry."
            )
        detail = ", ".join(f"pid={pid}" for pid in still_busy)
        raise RuntimeError(f"Port :{port} remains busy after cleanup attempt ({detail}).")


def ensure_certificates(repo_root: Path, cert: Path, key: Path) -> str:
    cert_path = (repo_root / cert).resolve()
    key_path = (repo_root / key).resolve()
    if not cert_path.exists() or not key_path.exists():
        run_cmd(["bash", "scripts/generate_dev_cert.sh", "certs"], cwd=repo_root)

    spki_file = repo_root / "certs" / "spki.hash"
    if spki_file.exists():
        return spki_file.read_text().strip()

    spki_der = subprocess.run(
        ["openssl", "x509", "-in", str(cert_path), "-pubkey", "-noout"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    der_bytes = subprocess.run(
        ["openssl", "pkey", "-pubin", "-outform", "der"],
        input=spki_der,
        capture_output=True,
        check=True,
    ).stdout
    return base64.b64encode(hashlib.sha256(der_bytes).digest()).decode()


def build_renderer(repo_root: Path, build_dir: Path) -> Path:
    run_cmd(["cmake", "-S", "native/renderer_encoder", "-B", str(build_dir)], cwd=repo_root)
    run_cmd(["cmake", "--build", str(build_dir), "-j"], cwd=repo_root)

    renderer_bin = build_dir / "tigas_renderer_encoder"
    if not renderer_bin.exists():
        raise RuntimeError(f"renderer binary not found at {renderer_bin}")
    return renderer_bin


def start_tigas_server(
    repo_root: Path,
    addr: str,
    cert_path: Path,
    key_path: Path,
    segments_dir: Path,
    movement_dir: Path,
    control_log_path: Path,
    dash_cors_origin: str,
) -> subprocess.Popen:
    cleanup_stale_tigas_server(addr)

    return spawn([
        "/opt/homebrew/bin/go" if Path("/opt/homebrew/bin/go").exists() else "go",
        "run",
        "./cmd/tigas-server",
        "--addr",
        addr,
        "--cert",
        str(cert_path),
        "--key",
        str(key_path),
        "--static",
        str((repo_root / "client").resolve()),
        "--segments",
        str(segments_dir),
        "--movement",
        str(movement_dir),
        "--control-log",
        str(control_log_path),
        "--dash-cors-origin",
        dash_cors_origin,
    ], cwd=repo_root / "server")


def wait_for_server_startup(server_proc: subprocess.Popen, addr: str) -> None:
    time.sleep(1.0)
    if server_proc.poll() is not None:
        raise RuntimeError(
            "tigas-server exited during startup. Check terminal output above (common causes: wrong cwd, invalid cert paths, port already in use)."
        )
    time.sleep(0.5)
    if server_proc.poll() is not None:
        raise RuntimeError(
            f"tigas-server exited after startup on {addr}. Check server logs above."
        )


def build_live_renderer_cmd(
    renderer_bin: Path,
    movement: Path,
    output_dir: Path,
    ply: Path,
    max_frames: int,
    fps: int,
    codec: str,
    crf: int,
    dash_window_size: int,
    dash_archive_mode: bool,
    disable_cuda: bool,
) -> list[str]:
    return [
        str(renderer_bin.resolve()),
        "--movement",
        str(movement.resolve()),
        "--output-dir",
        str(output_dir),
        "--ply",
        str(ply.resolve()),
        "--max-frames",
        str(max_frames),
        "--fps",
        str(fps),
        "--codec",
        codec,
        "--crf",
        str(crf),
        "--live-dash",
        "--dash-window-size",
        str(dash_window_size),
        *(["--dash-archive-mode"] if dash_archive_mode else []),
        *(["--disable-cuda"] if disable_cuda else []),
    ]
