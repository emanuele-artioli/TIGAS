"""Server-side ABR guardrail policy.

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
    """Frame-time-aware guardrail policy with conservative overload fallback."""

    def __init__(
        self,
        frame_budget_ms: float = 33.3,
        max_queue_depth: int = 3,
        overload_gpu_utilization: float = 95.0,
        bitrate_backoff: float = 0.75,
    ) -> None:
        self.frame_budget_ms = max(1.0, frame_budget_ms)
        self.max_queue_depth = max(1, max_queue_depth)
        self.overload_gpu_utilization = max(0.0, overload_gpu_utilization)
        self.bitrate_backoff = min(1.0, max(0.1, bitrate_backoff))

    def decide(
        self,
        render_time_ms: float,
        encode_queue_depth: int,
        gpu_utilization: float,
        client_requested_lod: str,
        client_target_bitrate_kbps: int,
    ) -> ServerAbrDecision:
        """Return enforced policy balancing latency and quality."""
        overloaded = (
            render_time_ms > self.frame_budget_ms
            or encode_queue_depth > self.max_queue_depth
            or gpu_utilization > self.overload_gpu_utilization
        )

        if overloaded:
            fallback_lod = "sampled_50"
            if client_requested_lod in {"quant_8bit", "sampled_50"}:
                fallback_lod = client_requested_lod
            return ServerAbrDecision(
                enforced_lod=fallback_lod,
                encoder_bitrate_kbps=max(300, int(client_target_bitrate_kbps * self.bitrate_backoff)),
                reason="overload_guardrail",
            )

        return ServerAbrDecision(
            enforced_lod=client_requested_lod,
            encoder_bitrate_kbps=max(300, int(client_target_bitrate_kbps)),
            reason="pass_through",
        )
