from __future__ import annotations

import argparse
import time

from playwright.sync_api import sync_playwright


def main() -> int:
    parser = argparse.ArgumentParser(description="Run TIGAS client in headless Chrome")
    parser.add_argument("--url", default="https://localhost:4433/")
    parser.add_argument("--duration", type=int, default=60)
    parser.add_argument("--insecure", action="store_true")
    args = parser.parse_args()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--enable-quic", "--origin-to-force-quic-on=localhost:4433"])
        context = browser.new_context(ignore_https_errors=args.insecure)
        page = context.new_page()
        page.goto(args.url, wait_until="networkidle")
        time.sleep(max(1, args.duration))
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
