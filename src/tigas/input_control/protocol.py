"""Datagram protocol placeholders for control uplink.

This file defines how uplink control information is encoded, decoded, and
validated before entering intelligence and rendering stages.
"""

from __future__ import annotations

import json

from tigas.shared.types import UplinkDatagram


class UplinkDatagramProtocol:
    """Serialize and deserialize control payloads for QUIC datagrams.

    Current scaffold uses JSON for readability. Production implementation can
    replace this with compact binary encoding as long as field semantics remain
    compatible with `schemas/uplink_datagram.schema.json`.
    """

    def encode(self, datagram: UplinkDatagram) -> bytes:
        """Encode a datagram instance into transport bytes."""
        payload = {
            "seq_id": datagram.seq_id,
            "timestamp_ms": datagram.timestamp_ms,
            "camera_matrix_4x4": datagram.camera_matrix_4x4,
            "requested_lod": datagram.requested_lod,
            "target_bitrate_kbps": datagram.target_bitrate_kbps,
        }
        return json.dumps(payload, separators=(",", ":")).encode("utf-8")

    def decode(self, payload: bytes) -> UplinkDatagram:
        """Decode transport bytes into the canonical datagram object."""
        data = json.loads(payload.decode("utf-8"))
        return UplinkDatagram(
            seq_id=int(data["seq_id"]),
            timestamp_ms=float(data["timestamp_ms"]),
            camera_matrix_4x4=list(data["camera_matrix_4x4"]),
            requested_lod=data["requested_lod"],
            target_bitrate_kbps=int(data["target_bitrate_kbps"]),
        )
