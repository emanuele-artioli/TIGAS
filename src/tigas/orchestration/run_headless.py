"""CLI entrypoint for runtime-only headless TIGAS rendering."""

from __future__ import annotations

import argparse
import json

from tigas.orchestration.ablation_runner import HeadlessAblationRunner
from tigas.shared.types import ExperimentConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a runtime-only headless TIGAS render")
    parser.add_argument("--ply-path", required=True, help="Path to .ply point cloud")
    parser.add_argument(
        "--movement-trace",
        default="",
        help="Movement trace path or trace name in movement_traces (e.g. Circular)",
    )
    parser.add_argument(
        "--network-trace",
        default="",
        help="Network trace CSV path or name in network_traces (e.g. lte_steps)",
    )
    parser.add_argument(
        "--abr-profile",
        default="",
        help="ABR profile JSON path or profile name in abr_profiles (throughput, bola, robustmpc)",
    )
    parser.add_argument(
        "--enable-tc",
        action="store_true",
        help="Enable best-effort Linux tc shaping using network trace target rates",
    )
    parser.add_argument(
        "--tc-interface",
        default="",
        help="Network interface to shape when --enable-tc is set (for example eth0 or lo)",
    )
    parser.add_argument("--output-dir", default="outputs/headless", help="Reserved for compatibility")
    parser.add_argument("--num-frames", type=int, default=120, help="Number of frames to render")
    parser.add_argument("--fps", type=int, default=30, help="Frame rate used for timestamps")
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
        trace_path=args.movement_trace,
        codec=args.codec,
        predictor=args.predictor,
        network_profile=args.network_profile,
        default_lod=args.default_lod,
        asset_path=args.ply_path,
        network_trace_path=args.network_trace,
        abr_profile_path=args.abr_profile,
        enable_tc=bool(args.enable_tc),
        tc_interface=args.tc_interface,
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
