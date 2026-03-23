"""Traffic control profile helpers.

Provides Linux tc wrappers for reproducible network shaping in headless runs.
Calls are best-effort and should be guarded by CLI flags because tc may require
elevated capabilities depending on host configuration.
"""

from __future__ import annotations

import subprocess


class TcProfileManager:
    """Linux tc profile application and cleanup utilities."""

    @staticmethod
    def _run(command: list[str]) -> None:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            stderr = completed.stderr.strip()
            raise RuntimeError(f"tc command failed: {' '.join(command)}; stderr={stderr}")

    def apply_rate_kbps(
        self,
        interface_name: str,
        rate_kbps: int,
        burst_kbit: int = 64,
        latency_ms: int = 50,
    ) -> None:
        """Apply token-bucket shaping for a single target bitrate."""
        safe_rate = max(1, int(rate_kbps))
        safe_burst = max(1, int(burst_kbit))
        safe_latency = max(1, int(latency_ms))
        self._run(
            [
                "tc",
                "qdisc",
                "replace",
                "dev",
                interface_name,
                "root",
                "tbf",
                "rate",
                f"{safe_rate}kbit",
                "burst",
                f"{safe_burst}kbit",
                "latency",
                f"{safe_latency}ms",
            ]
        )

    def apply(self, interface_name: str, profile_name: str) -> None:
        """Apply a named static profile for convenience."""
        profile = profile_name.lower().strip()
        if profile == "lte":
            self.apply_rate_kbps(interface_name=interface_name, rate_kbps=12000, latency_ms=40)
            return
        if profile == "wifi":
            self.apply_rate_kbps(interface_name=interface_name, rate_kbps=25000, latency_ms=20)
            return
        if profile == "3g":
            self.apply_rate_kbps(interface_name=interface_name, rate_kbps=2000, latency_ms=120)
            return
        raise ValueError(f"Unsupported tc profile '{profile_name}'.")

    def clear(self, interface_name: str) -> None:
        """Clear active qdisc from interface."""
        self._run(["tc", "qdisc", "del", "dev", interface_name, "root"])
