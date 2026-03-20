"""Server-side ABR controller placeholder.

Server ABR protects latency under overload by enforcing conservative LOD or
encoder settings when render and encode queues exceed safe thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ServerAbrDecision:
    """Runtime enforcement knobs returned by server ABR."""

    enforced_lod: str
    encoder_bitrate_kbps: int
    reason: str


class ServerAbrController:
    """Frame-time-aware guardrail policy placeholder."""

    def decide(
        self,
        render_time_ms: float,
        encode_queue_depth: int,
        gpu_utilization: float,
        client_requested_lod: str,
        client_target_bitrate_kbps: int,
    ) -> ServerAbrDecision:
        """Return enforced policy balancing latency and quality."""
        raise NotImplementedError(
            "Implement server ABR with thresholds and hysteresis handling."
        )
