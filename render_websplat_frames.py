#!/usr/bin/env python3
"""Render hardcoded web-splat poses and stream per-frame H.264 packets."""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

from tigas_video_pipeline import (
    AbrSample,
    EncoderConfig,
    LatencyAwareAbrController,
    StreamManager,
    VideoDecoder,
    VideoEncoder,
)

WEBSPLAT_PROJECT_ROOT = Path("/home/itec/emanuele/web-splat")
if str(WEBSPLAT_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(WEBSPLAT_PROJECT_ROOT))

from websplat_generator import WebSplatGenerator

PLY_PATH = Path(
    "/home/itec/emanuele/Datasets/3DGS/garden/point_cloud/iteration_30000/point_cloud.ply"
)
SCENE_PATH = Path("/home/itec/emanuele/Datasets/3DGS/garden/cameras.json")

OUTPUT_JPG_DIR = Path("/home/itec/emanuele/TIGAS/outputs/websplat_jpg_frames")
OUTPUT_H264_PACKET_DIR = Path("/home/itec/emanuele/TIGAS/outputs/websplat_h264_packets")
OUTPUT_H264_DECODED_DIR = Path("/home/itec/emanuele/TIGAS/outputs/websplat_h264_decoded")

CAMERA_POSES_JSON = """
[
    {
        "x": -3.30326227674897,
        "y": 1.1459637860858836,
        "z": -0.799459662873427,
        "roll_deg": 49.84636687,
        "pitch_deg": 38.02498847,
        "yaw_deg": 55.47224673
    },
    {
        "x": -3.747014766310446,
        "y": 1.023277531795199,
        "z": 0.46018699117578293,
        "roll_deg": 77.2295525,
        "pitch_deg": 69.0727607,
        "yaw_deg": 61.42464165
    },
    {
        "x": 0.9254777855307261,
        "y": 2.9276458372690697,
        "z": -3.282922615677503,
        "roll_deg": -3.98431288,
        "pitch_deg": 20.49735464,
        "yaw_deg": -4.79945193
    },
    {
        "x": 3.031529505653127,
        "y": -0.0537913821049901,
        "z": -1.18015447121763,
        "roll_deg": -46.6605102,
        "pitch_deg": 12.85115286,
        "yaw_deg": -50.80019678
    },
    {
        "x": -3.4166628460181556,
        "y": 1.7659905606502877,
        "z": -0.9752561451985035,
        "roll_deg": 40.2668318,
        "pitch_deg": 37.78713117,
        "yaw_deg": 51.81521852
    }
]
"""


def parse_camera_poses(pose_json: str) -> list[tuple[float, float, float, float, float, float]]:
    """Parse hardcoded JSON camera poses into 6DoF tuples."""
    raw_poses = json.loads(pose_json)
    poses: list[tuple[float, float, float, float, float, float]] = []

    for idx, pose in enumerate(raw_poses):
        required = ("x", "y", "z", "roll_deg", "pitch_deg", "yaw_deg")
        missing = [k for k in required if k not in pose]
        if missing:
            raise ValueError(f"Pose index {idx} is missing keys: {missing}")

        poses.append(
            (
                float(pose["x"]),
                float(pose["y"]),
                float(pose["z"]),
                float(pose["roll_deg"]),
                float(pose["pitch_deg"]),
                float(pose["yaw_deg"]),
            )
        )

    if not poses:
        raise ValueError("No camera poses found in CAMERA_POSES_JSON")

    return poses


def save_frame_as_jpg(frame_rgb, output_path: Path) -> None:
    """Save RGB/RGBA uint8 numpy frame as JPEG."""
    image = Image.fromarray(frame_rgb[:, :, :3], mode="RGB")
    image.save(output_path, format="JPEG", quality=95, optimize=True)


def write_quic_packet_dump(frame_id: int, packets: list[bytes], output_dir: Path) -> Path:
    """Persist packetized frame payloads as a length-prefixed binary blob."""
    output_path = output_dir / f"frame_{frame_id:04d}.qpk"
    with output_path.open("wb") as handle:
        for packet in packets:
            handle.write(len(packet).to_bytes(4, "big", signed=False))
            handle.write(packet)
    return output_path


def sanitize_frame_for_h264(
    frame_rgba,
    target_size: tuple[int, int] | None = None,
    max_size: tuple[int, int] | None = None,
) -> tuple:
    """Convert to RGB and normalize size for yuv420 H.264 encoders."""
    rgb = frame_rgba[:, :, :3]
    src_h, src_w = rgb.shape[:2]
    src_size = (src_w, src_h)

    resize_needed = False
    crop_even_only = False

    if target_size is None:
        dst_w, dst_h = src_w, src_h
        if max_size is not None:
            max_w, max_h = max_size
            if max_w <= 0 or max_h <= 0:
                raise ValueError(f"Invalid max_size: {max_size}")
            if src_w > max_w or src_h > max_h:
                scale = min(max_w / float(src_w), max_h / float(src_h))
                dst_w = max(2, int(src_w * scale))
                dst_h = max(2, int(src_h * scale))
                resize_needed = True

        if dst_w % 2 != 0:
            dst_w -= 1
        if dst_h % 2 != 0:
            dst_h -= 1
        if not resize_needed and (dst_w != src_w or dst_h != src_h):
            crop_even_only = True
    else:
        dst_w, dst_h = target_size
        if dst_w <= 0 or dst_h <= 0:
            raise ValueError(f"Invalid target_size: {target_size}")
        resize_needed = (dst_w != src_w) or (dst_h != src_h)

    if dst_w <= 0 or dst_h <= 0:
        raise ValueError(f"Cannot encode frame with non-positive size from source {src_w}x{src_h}")
    if dst_w % 2 != 0 or dst_h % 2 != 0:
        raise ValueError(f"H.264 yuv420 requires even dimensions, got {dst_w}x{dst_h}")

    if resize_needed:
        resized = Image.fromarray(rgb, mode="RGB").resize((dst_w, dst_h), resample=Image.Resampling.BILINEAR)
        out = np.asarray(resized, dtype=np.uint8)
        operation = "resized"
    elif crop_even_only:
        out = rgb[:dst_h, :dst_w]
        operation = "cropped-even"
    else:
        out = rgb
        operation = "none"

    return out, src_size, (dst_w, dst_h), operation


def run_jpeg_baseline(poses: list[tuple[float, float, float, float, float, float]]) -> None:
    OUTPUT_JPG_DIR.mkdir(parents=True, exist_ok=True)
    with WebSplatGenerator(
        point_cloud_path=PLY_PATH,
        scene_path=SCENE_PATH,
        project_root=WEBSPLAT_PROJECT_ROOT,
        release=True,
    ) as renderer:
        for idx, frame in enumerate(renderer.render_many(poses)):
            jpg_path = OUTPUT_JPG_DIR / f"frame_{idx:04d}.jpg"
            save_frame_as_jpg(frame, jpg_path)
            print(f"Saved {jpg_path}")


def run_h264_pipeline(
    poses: list[tuple[float, float, float, float, float, float]],
    args: argparse.Namespace,
) -> None:
    OUTPUT_H264_PACKET_DIR.mkdir(parents=True, exist_ok=True)
    if args.save_decoded:
        OUTPUT_H264_DECODED_DIR.mkdir(parents=True, exist_ok=True)

    decoder = VideoDecoder(frame_timeout_ms=80.0, prefer_hardware=not args.force_software)
    abr = LatencyAwareAbrController(
        target_mtp_ms=args.target_mtp_ms,
        min_bitrate_bps=int(args.min_bitrate_mbps * 1_000_000),
        max_bitrate_bps=int(args.max_bitrate_mbps * 1_000_000),
        min_crf=args.min_crf,
        max_crf=args.max_crf,
        initial_bitrate_bps=int(args.initial_bitrate_mbps * 1_000_000),
        initial_crf=args.initial_crf,
    )

    random_gen = random.Random(1234)
    encoder: VideoEncoder | None = None
    stream_manager: StreamManager | None = None
    target_size: tuple[int, int] | None = None

    decoded_frames = 0
    total_encoded_bytes = 0
    total_packets = 0
    total_render_ms = 0.0
    total_encode_ms = 0.0
    total_decode_ms = 0.0

    with WebSplatGenerator(
        point_cloud_path=PLY_PATH,
        scene_path=SCENE_PATH,
        project_root=WEBSPLAT_PROJECT_ROOT,
        release=True,
    ) as renderer:
        render_iter = iter(renderer.render_many(poses))
        for frame_id in range(len(poses)):
            render_started = time.perf_counter()
            frame = next(render_iter)
            render_ms = (time.perf_counter() - render_started) * 1000.0
            rgb_frame, src_size, encoded_size, operation = sanitize_frame_for_h264(
                frame,
                target_size=target_size,
                max_size=(args.max_encode_width, args.max_encode_height),
            )
            if target_size is None:
                target_size = encoded_size
                if operation != "none":
                    print(
                        f"Adjusted WebSplat frame size ({operation}) for H.264: "
                        f"{src_size[0]}x{src_size[1]} -> {encoded_size[0]}x{encoded_size[1]}"
                    )

            if encoder is None:
                height, width = rgb_frame.shape[:2]
                codec_candidates: list[str] | None = None
                if args.codec_candidates.strip():
                    codec_candidates = [token.strip() for token in args.codec_candidates.split(",") if token.strip()]

                encoder = VideoEncoder(
                    EncoderConfig(
                        width=width,
                        height=height,
                        fps=args.fps,
                        prefer_hardware=not args.force_software,
                        codec_candidates=codec_candidates,
                        initial_bitrate_bps=int(args.initial_bitrate_mbps * 1_000_000),
                        initial_crf=args.initial_crf,
                    )
                )
                stream_manager = StreamManager(encoder, mtu_bytes=args.mtu_bytes)
                print(
                    f"Encoder initialized codec={encoder.codec_name} fps={args.fps} "
                    f"bitrate={encoder.bitrate_bps} crf={encoder.crf}"
                )

            if stream_manager is None or encoder is None:
                raise RuntimeError("stream manager was not initialized")

            encoded, packets = stream_manager.encode_frame_to_quic_packets(rgb_frame, frame_id)
            write_quic_packet_dump(frame_id, packets, OUTPUT_H264_PACKET_DIR)

            delivered_packets: list[bytes] = []
            for packet in packets:
                if random_gen.random() < args.simulate_loss:
                    continue
                delivered_packets.append(packet)

            decoded = None
            for packet in delivered_packets:
                maybe_frame = decoder.ingest_quic_packet(packet)
                if maybe_frame is not None:
                    decoded = maybe_frame

            decode_ms = 0.0
            if decoded is not None:
                decoded_frames += 1
                decode_ms = decoded.decode_ms
                if args.save_decoded:
                    decoded_path = OUTPUT_H264_DECODED_DIR / f"frame_{decoded.frame_id:04d}.jpg"
                    save_frame_as_jpg(decoded.frame_rgb, decoded_path)

            network_ms = (
                (encoded.total_bytes * 8.0) / max(args.simulate_throughput_mbps * 1_000_000.0, 1.0) * 1000.0
            ) + max(0.0, args.simulate_rtt_ms * 0.5)

            sample = AbrSample(
                frame_id=frame_id,
                frame_bytes=encoded.total_bytes,
                network_ms=network_ms,
                render_ms=render_ms,
                encode_ms=encoded.encode_ms,
                decode_ms=decode_ms,
                packet_loss_ratio=args.simulate_loss,
            )
            decision = abr.observe(sample, encoder)
            if decision is not None:
                print(
                    f"[ABR] frame={frame_id} bitrate={decision.bitrate_bps} "
                    f"crf={decision.crf} reason={decision.reason}"
                )

            mtp_ms = render_ms + encoded.encode_ms + network_ms + decode_ms
            lost_packets = len(packets) - len(delivered_packets)
            print(
                f"frame={frame_id:04d} bytes={encoded.total_bytes} packets={len(packets)} "
                f"lost={lost_packets} codec={encoded.codec_name} "
                f"render_ms={render_ms:.2f} encode_ms={encoded.encode_ms:.2f} "
                f"decode_ms={decode_ms:.2f} est_mtp_ms={mtp_ms:.2f}"
            )

            total_encoded_bytes += encoded.total_bytes
            total_packets += len(packets)
            total_render_ms += render_ms
            total_encode_ms += encoded.encode_ms
            total_decode_ms += decode_ms

    frame_count = len(poses)
    avg_render = total_render_ms / max(frame_count, 1)
    avg_encode = total_encode_ms / max(frame_count, 1)
    avg_decode = total_decode_ms / max(frame_count, 1)
    avg_packet_size = total_encoded_bytes / max(total_packets, 1)

    print("----- H.264 Pipeline Summary -----")
    print(f"frames={frame_count} decoded={decoded_frames} decoder={decoder.decoder_name}")
    print(f"encoded_bytes={total_encoded_bytes} packets={total_packets} avg_packet={avg_packet_size:.1f}")
    print(f"avg_render_ms={avg_render:.2f} avg_encode_ms={avg_encode:.2f} avg_decode_ms={avg_decode:.2f}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render WebSplat poses and stream per-frame H.264 packets")
    parser.add_argument("--mode", choices=["h264", "jpeg"], default="h264")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--mtu-bytes", type=int, default=1500)
    parser.add_argument("--max-encode-width", type=int, default=4096)
    parser.add_argument("--max-encode-height", type=int, default=2304)
    parser.add_argument("--force-software", action="store_true", help="Disable hardware codec preference")
    parser.add_argument(
        "--codec-candidates",
        type=str,
        default="",
        help="Comma-separated codec override, e.g. 'h264_nvenc,libx264,h264'",
    )

    parser.add_argument("--target-mtp-ms", type=float, default=100.0)
    parser.add_argument("--initial-bitrate-mbps", type=float, default=4.0)
    parser.add_argument("--min-bitrate-mbps", type=float, default=0.5)
    parser.add_argument("--max-bitrate-mbps", type=float, default=15.0)
    parser.add_argument("--initial-crf", type=int, default=25)
    parser.add_argument("--min-crf", type=int, default=17)
    parser.add_argument("--max-crf", type=int, default=38)

    parser.add_argument("--simulate-loss", type=float, default=0.0, help="Packet loss ratio in [0, 1]")
    parser.add_argument("--simulate-throughput-mbps", type=float, default=40.0)
    parser.add_argument("--simulate-rtt-ms", type=float, default=12.0)
    parser.add_argument("--save-decoded", action="store_true", help="Save locally decoded frames as JPEG")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    if not PLY_PATH.exists():
        raise FileNotFoundError(f"PLY file not found: {PLY_PATH}")
    if not SCENE_PATH.exists():
        raise FileNotFoundError(f"Scene file not found: {SCENE_PATH}")

    if not (0.0 <= args.simulate_loss <= 1.0):
        raise ValueError("--simulate-loss must be between 0 and 1")
    if args.mtu_bytes < 256:
        raise ValueError("--mtu-bytes must be >= 256")
    if args.max_encode_width < 2 or args.max_encode_height < 2:
        raise ValueError("--max-encode-width and --max-encode-height must be >= 2")

    poses = parse_camera_poses(CAMERA_POSES_JSON)
    if args.mode == "jpeg":
        run_jpeg_baseline(poses)
    else:
        run_h264_pipeline(poses, args)


if __name__ == "__main__":
    main()
