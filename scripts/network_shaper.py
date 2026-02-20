from __future__ import annotations

import argparse
import csv
import os
import subprocess
import time
from pathlib import Path


def run_cmd(cmd: list[str]) -> None:
    completed = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}")


def clear_qdisc(interface: str) -> None:
    subprocess.run(["tc", "qdisc", "del", "dev", interface, "root"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def apply_trace(interface: str, trace_file: Path, latency_ms: int, loss_percent: float) -> None:
    with trace_file.open("r", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if not row:
                continue
            kbps = max(1, int(float(row[0])))
            clear_qdisc(interface)
            run_cmd(["tc", "qdisc", "add", "dev", interface, "root", "handle", "1:", "netem", "delay", f"{latency_ms}ms", "loss", f"{loss_percent}%"])
            run_cmd(["tc", "qdisc", "add", "dev", interface, "parent", "1:1", "handle", "10:", "tbf", "rate", f"{kbps}kbit", "burst", "32kbit", "latency", "400ms"])
            time.sleep(1.0)


def require_root() -> None:
    if os.geteuid() != 0:
        raise PermissionError("network_shaper.py must run as root (use sudo)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply per-second network shaping from trace via tc")
    parser.add_argument("--interface", required=True)
    parser.add_argument("--trace", required=True, type=Path)
    parser.add_argument("--latency-ms", type=int, default=50)
    parser.add_argument("--loss-percent", type=float, default=1.0)
    parser.add_argument("--max-seconds", type=int, default=0, help="0 means full trace length")
    parser.add_argument("--cleanup-only", action="store_true")
    args = parser.parse_args()

    require_root()
    if args.cleanup_only:
        clear_qdisc(args.interface)
        return 0

    if args.max_seconds > 0:
        sliced = args.trace.parent / (args.trace.stem + f".slice{args.max_seconds}.tmp.csv")
        with args.trace.open("r", encoding="utf-8") as src, sliced.open("w", encoding="utf-8") as dst:
            for idx, line in enumerate(src):
                if idx >= args.max_seconds:
                    break
                dst.write(line)
        trace_path = sliced
    else:
        trace_path = args.trace

    try:
        apply_trace(args.interface, trace_path, args.latency_ms, args.loss_percent)
    finally:
        clear_qdisc(args.interface)
        if args.max_seconds > 0 and trace_path.exists():
            trace_path.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
