from __future__ import annotations

import argparse
import time
import urllib.parse
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
    _ = ensure_certificates(repo_root, args.cert, args.key)

    renderer_bin = build_renderer(repo_root, (repo_root / "native/renderer_encoder/build").resolve())

    server_proc = start_tigas_server(
        repo_root=repo_root,
        addr=args.addr,
        cert_path=cert_path,
        key_path=key_path,
        segments_dir=output_dir,
        movement_dir=(repo_root / "movement_traces").resolve(),
        control_log_path=(output_dir / "control_messages.bin").resolve(),
        dash_cors_origin=args.dash_cors_origin,
    )

    try:
        wait_for_server_startup(server_proc, args.addr)

        renderer_cmd = build_live_renderer_cmd(
            renderer_bin=renderer_bin,
            movement=args.movement,
            output_dir=output_dir,
            ply=args.ply,
            max_frames=args.max_frames,
            fps=args.fps,
            codec=args.codec,
            crf=args.crf,
            dash_window_size=args.dash_window_size,
            dash_archive_mode=args.dash_archive_mode,
            disable_cuda=args.disable_cuda,
        )
        listen_addr = normalize_addr(args.addr)
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
        listen_port = normalize_addr(args.addr)
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
