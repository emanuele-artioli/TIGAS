"""CLI entrypoint for offline evaluation sweeps."""

from __future__ import annotations

import argparse
import json

from tigas.evaluation.evaluator import EvaluationRunner
from tigas.shared.types import ExperimentConfig


def _parse_sparsity_levels(raw: str) -> list[float]:
    values = [item.strip() for item in raw.split(",") if item.strip()]
    if not values:
        raise ValueError("At least one sparsity level is required.")
    return [float(item) for item in values]


def _parse_quant_bits(raw: str) -> list[int]:
    values = [item.strip() for item in raw.split(",") if item.strip()]
    if not values:
        raise ValueError("At least one quant bit value is required.")
    return [int(item) for item in values]


def _parse_resolutions(raw: str) -> list[tuple[int, int]]:
    values = [item.strip() for item in raw.split(",") if item.strip()]
    if not values:
        raise ValueError("At least one resolution is required.")

    result: list[tuple[int, int]] = []
    for item in values:
        if "x" not in item:
            raise ValueError(f"Invalid resolution format: {item}")
        width_text, height_text = item.lower().split("x", 1)
        result.append((int(width_text), int(height_text)))
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run offline TIGAS evaluation sweeps")
    parser.add_argument("--ply-path", required=True, help="Path to .ply point cloud")
    parser.add_argument(
        "--movement-trace",
        default="",
        help="Movement trace path or trace name in movement_traces (e.g. Circular)",
    )
    parser.add_argument("--trace-json", default="", help="Deprecated alias for --movement-trace")
    parser.add_argument(
        "--network-trace",
        default="",
        help="Network trace CSV path or name in network_traces (e.g. lte_steps)",
    )
    parser.add_argument("--output-dir", default="outputs/evaluation", help="Evaluation output root")
    parser.add_argument("--num-frames", type=int, default=120, help="Frames per run")
    parser.add_argument("--fps", type=int, default=30, help="Frame rate for rendering and video")
    parser.add_argument("--max-points", type=int, default=300000, help="Point budget for full run")
    parser.add_argument(
        "--renderer-backend",
        default="gsplat_cuda",
        choices=["cpu", "gsplat_cuda"],
        help="Renderer backend used for evaluation",
    )
    parser.add_argument(
        "--sparsity-levels",
        default="1.0,0.75,0.5,0.25",
        help="Comma-separated sparsity fractions for point budget",
    )
    parser.add_argument(
        "--resolutions",
        default="960x540,1280x720",
        help="Comma-separated resolution list (e.g. 960x540,1280x720)",
    )
    parser.add_argument(
        "--quant-bits-list",
        default="8,6,4,3",
        help="Comma-separated quantization bits for quantized runs",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    movement_trace = args.movement_trace if args.movement_trace else args.trace_json
    sparsity_levels = _parse_sparsity_levels(args.sparsity_levels)
    resolutions = _parse_resolutions(args.resolutions)
    quant_bits_list = _parse_quant_bits(args.quant_bits_list)

    base_config = ExperimentConfig(
        trace_path=movement_trace,
        codec="libx264",
        predictor="noop",
        network_profile="wifi",
        default_lod="full",
        asset_path=args.ply_path,
        network_trace_path=args.network_trace,
        output_dir=args.output_dir,
        num_frames=args.num_frames,
        fps=args.fps,
        width=resolutions[0][0],
        height=resolutions[0][1],
        max_points=args.max_points,
        renderer_backend=args.renderer_backend,
        quant_bits=max(quant_bits_list),
    )

    report = EvaluationRunner().run_tradeoff_curve(
        base_config=base_config,
        output_root=args.output_dir,
        sparsity_levels=sparsity_levels,
        resolutions=resolutions,
        quant_bits_list=quant_bits_list,
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
