"""QUIC uplink placeholder.

Receives or sends control datagrams depending on server or client role. The
implementation is expected to use unreliable datagrams to minimize control-path
latency and tolerate occasional loss.
"""

from __future__ import annotations

from tigas.shared.types import UplinkDatagram


class QuicUplinkEndpoint:
    """Placeholder endpoint for datagram-based control traffic."""

    def send(self, datagram: UplinkDatagram) -> None:
        """Send one control datagram."""
        raise NotImplementedError("Implement QUIC datagram send path.")

    def receive(self) -> UplinkDatagram:
        """Receive one control datagram and decode it to canonical type."""
        raise NotImplementedError("Implement QUIC datagram receive path.")
