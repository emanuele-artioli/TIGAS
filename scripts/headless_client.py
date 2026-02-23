from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> int:
    parser = argparse.ArgumentParser(description="Internal helper for TIGAS test-mode headless browser checks")
    parser.add_argument("--url", default="https://localhost:4433/")
    parser.add_argument("--force-quic-origin", default="localhost:4433")
    parser.add_argument("--spki-hash", default="")
    parser.add_argument("--duration", type=int, default=60)
    parser.add_argument("--insecure", action="store_true")
    parser.add_argument("--status-output", type=Path)
    args = parser.parse_args()

    launch_args = ["--enable-quic", f"--origin-to-force-quic-on={args.force_quic_origin}"]
    if args.spki_hash:
        launch_args.append(f"--ignore-certificate-errors-spki-list={args.spki_hash}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=launch_args,
        )
        context = browser.new_context(ignore_https_errors=args.insecure)
        page = context.new_page()
        try:
            page.goto(args.url, wait_until="networkidle", timeout=15000)
        except Exception:
            page.goto(args.url, wait_until="load", timeout=15000)
        time.sleep(max(1, args.duration))
        browser.close()

    if args.status_output:
        args.status_output.parent.mkdir(parents=True, exist_ok=True)
        args.status_output.write_text(json.dumps({"headless_ok": True}, indent=2), encoding="utf-8")
    return 0


def _main() -> int:
    try:
        return main()
    except Exception as exc:
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--status-output", type=Path)
        known, _ = parser.parse_known_args()
        if known.status_output:
            known.status_output.parent.mkdir(parents=True, exist_ok=True)
            known.status_output.write_text(json.dumps({"headless_ok": False, "error": str(exc)}, indent=2), encoding="utf-8")
        raise


if __name__ == "__main__":
    raise SystemExit(_main())
