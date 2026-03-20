"""Headless trace generation tests."""

from tigas.input_control.headless_replayer import HeadlessTraceReplayer


def test_generate_orbit_samples_and_datagrams() -> None:
    replayer = HeadlessTraceReplayer()
    samples = replayer.generate_orbit_samples(
        center=(0.0, 0.0, 0.0),
        radius=1.0,
        num_frames=12,
        fps=24,
        requested_lod="full",
        target_bitrate_kbps=3500,
    )

    assert len(samples) == 12
    assert all(len(sample.camera_matrix_4x4) == 16 for sample in samples)
    assert samples[0].timestamp_ms == 0.0

    datagrams = replayer.build_datagrams(samples)
    assert len(datagrams) == 12
    assert datagrams[-1].seq_id == 11
    assert datagrams[-1].target_bitrate_kbps == 3500
