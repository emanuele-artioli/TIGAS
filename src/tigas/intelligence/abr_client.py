"""Client-side ABR controller placeholder.

Client ABR estimates available throughput and chooses request-level knobs such
as target bitrate and preferred LOD. The output is piggybacked on uplink
control datagrams.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ClientAbrDecision:
    """ABR decision fields to include in outgoing control datagram."""

    target_bitrate_kbps: int
    requested_lod: str


class ClientAbrController:
    """Throughput-driven bitrate and LOD estimator placeholder."""

    def decide(
        self,
        throughput_kbps: float,
        decode_latency_ms: float,
        buffer_level_ms: float,
    ) -> ClientAbrDecision:
        """Return bitrate and LOD request based on client conditions."""
        raise NotImplementedError(
            "Implement client ABR policy with smoothing and safety margins."
        )
