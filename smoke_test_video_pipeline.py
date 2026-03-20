#!/usr/bin/env python3
"""Smoke test for TIGAS low-latency H.264 frame pipeline."""

from __future__ import annotations

import random
import time

import numpy as np

from tigas_video_pipeline import (
    AbrSample,
    EncoderConfig,
    LatencyAwareAbrController,
    StreamManager,
    VideoDecoder,
    VideoEncoder,
)


def _make_test_frame(frame_id: int, width: int, height: int) -> np.ndarray:
    x = np.linspace(0, 255, width, dtype=np.uint16)
    y = np.linspace(0, 255, height, dtype=np.uint16)
    xx, yy = np.meshgrid(x, y)

    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:, :, 0] = ((xx + frame_id * 3) % 256).astype(np.uint8)
    frame[:, :, 1] = ((yy + frame_id * 5) % 256).astype(np.uint8)
    frame[:, :, 2] = (((xx // 2 + yy // 2) + frame_id * 7) % 256).astype(np.uint8)
    return frame


def run_smoke_test(frame_count: int = 24) -> None:
    width, height, fps = 640, 360, 30
    encoder = VideoEncoder(
        EncoderConfig(
            width=width,
            height=height,
            fps=fps,
            prefer_hardware=False,
            codec_candidates=("libx264", "h264"),
            initial_bitrate_bps=3_000_000,
            initial_crf=26,
        )
    )
    stream_manager = StreamManager(encoder=encoder, mtu_bytes=1200)
    decoder = VideoDecoder(frame_timeout_ms=80.0, prefer_hardware=False, codec_candidates=("h264",))
    abr = LatencyAwareAbrController(
        target_mtp_ms=100.0,
        min_bitrate_bps=700_000,
        max_bitrate_bps=8_000_000,
        initial_bitrate_bps=encoder.bitrate_bps,
        initial_crf=encoder.crf,
        update_interval_frames=2,
    )

    rng = random.Random(1234)
    decoded_count = 0
    total_packets = 0
    total_bytes = 0

    for frame_id in range(frame_count):
        frame = _make_test_frame(frame_id, width, height)
        encoded, packets = stream_manager.encode_frame_to_quic_packets(frame, frame_id)
        total_packets += len(packets)
        total_bytes += encoded.total_bytes

        # Small random loss to validate loss-tolerant behavior.
        for packet in packets:
            if rng.random() < 0.02:
                continue
            decoded = decoder.ingest_quic_packet(packet)
            if decoded is not None:
                decoded_count += 1

        # Simulate a network estimate for ABR updates.
        estimated_network_ms = (encoded.total_bytes * 8.0 / 20_000_000.0) * 1000.0 + 6.0
        abr.observe(
            AbrSample(
                frame_id=frame_id,
                frame_bytes=encoded.total_bytes,
                network_ms=estimated_network_ms,
                render_ms=3.0,
                encode_ms=encoded.encode_ms,
                decode_ms=1.5,
                packet_loss_ratio=0.02,
            ),
            encoder=encoder,
        )

    if total_packets <= 0:
        raise RuntimeError("Smoke test failed: no packets produced")
    if total_bytes <= 0:
        raise RuntimeError("Smoke test failed: no encoded bytes produced")
    if decoded_count <= 0:
        raise RuntimeError("Smoke test failed: no frames decoded")

    print("Smoke test passed")
    print(f"codec={encoder.codec_name} decoded_frames={decoded_count}/{frame_count}")
    print(f"total_packets={total_packets} total_bytes={total_bytes}")
    print(f"final_bitrate={encoder.bitrate_bps} final_crf={encoder.crf}")


if __name__ == "__main__":
    started = time.perf_counter()
    run_smoke_test()
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    print(f"elapsed_ms={elapsed_ms:.2f}")