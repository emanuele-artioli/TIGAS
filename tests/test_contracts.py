"""Contract tests for shared serialization boundaries."""

from tigas.input_control.protocol import UplinkDatagramProtocol
from tigas.shared.types import UplinkDatagram


def test_uplink_protocol_roundtrip() -> None:
    protocol = UplinkDatagramProtocol()
    datagram = UplinkDatagram(
        seq_id=7,
        timestamp_ms=123.0,
        camera_matrix_4x4=[1.0] * 16,
        requested_lod="full",
        target_bitrate_kbps=4500,
    )

    payload = protocol.encode(datagram)
    decoded = protocol.decode(payload)

    assert decoded.seq_id == datagram.seq_id
    assert decoded.target_bitrate_kbps == datagram.target_bitrate_kbps
    assert decoded.camera_matrix_4x4 == datagram.camera_matrix_4x4
