"""Transport session placeholder.

Coordinates stream identifiers, connection lifecycle, and transport-level
telemetry emitted to instrumentation.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class TransportSessionState:
    """Minimal session metadata shared across transport submodules."""

    session_id: str
    connected: bool
    uplink_datagrams: int = 0
    published_fragments: int = 0


class TransportSessionManager:
    """Placeholder session manager for QUIC and MoQ runtime coordination."""

    def open(self) -> TransportSessionState:
        raise NotImplementedError("Implement transport session initialization.")

    def close(self, state: TransportSessionState) -> None:
        raise NotImplementedError("Implement transport session teardown.")
