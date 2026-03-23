"""CLI entrypoint for headless TIGAS experiments."""

from __future__ import annotations

import argparse
import json

from tigas.orchestration.ablation_runner import HeadlessAblationRunner
from tigas.shared.types import ExperimentConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a headless TIGAS experiment")
    parser.add_argument("--ply-path", required=True, help="Path to .ply point cloud")
    parser.add_argument(
        "--trace-json",
        default="",
        help="Optional movement trace JSON. If omitted, an orbit trace is generated.",
    )
    parser.add_argument("--output-dir", default="outputs/headless", help="Output root directory")
    parser.add_argument("--num-frames", type=int, default=120, help="Number of frames to render")
    parser.add_argument("--fps", type=int, default=30, help="Frame rate used for timestamps/video")
    parser.add_argument("--width", type=int, default=960, help="Output frame width")
    parser.add_argument("--height", type=int, default=540, help="Output frame height")
    parser.add_argument("--max-points", type=int, default=120000, help="Point budget for rendering")
    parser.add_argument(
        "--quant-bits",
        type=int,
        default=8,
        help="Bit-depth used for quantized LOD rendering",
    )
    parser.add_argument(
        "--renderer-backend",
        default="cpu",
        choices=["cpu", "gsplat_cuda"],
        help="Renderer backend implementation",
    )
    parser.add_argument(
        "--default-lod",
        default="full",
        choices=["full", "sampled_50", "quant_8bit", "adaptive"],
        help="Requested LOD profile",
    )
    parser.add_argument(
        "--codec",
        default="libx264",
        choices=["h264_nvenc", "av1_nvenc", "libx264", "videotoolbox_h264"],
        help="Experiment codec label",
    )
    parser.add_argument("--predictor", default="noop", help="Predictor label for run metadata")
    parser.add_argument(
        "--network-profile",
        default="wifi",
        help="Network profile label for run metadata",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = ExperimentConfig(
        trace_path=args.trace_json,
        codec=args.codec,
        predictor=args.predictor,
        network_profile=args.network_profile,
        default_lod=args.default_lod,
        asset_path=args.ply_path,
        output_dir=args.output_dir,
        num_frames=args.num_frames,
        fps=args.fps,
        width=args.width,
        height=args.height,
        max_points=args.max_points,
        renderer_backend=args.renderer_backend,
        quant_bits=args.quant_bits,
    )
    summary = HeadlessAblationRunner().run_one(config)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
