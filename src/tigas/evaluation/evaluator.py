"""Evaluation component for offline experiment sweeps.

This module owns evaluation-only behaviors: frame dumping, quality proxies,
tradeoff curve generation, and video encoding.
"""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from tigas.evaluation.metrics import ssim_proxy
from tigas.orchestration.ablation_runner import HeadlessAblationRunner
from tigas.shared.types import ExperimentConfig


@dataclass(slots=True)
class EvaluationRunResult:
    summary: dict
    frames: list[np.ndarray]


class EvaluationRunner:
    """Runs repeatable offline evaluations without polluting runtime paths."""

    def __init__(self) -> None:
        self.runtime_runner = HeadlessAblationRunner()

    @staticmethod
    def _build_run_dir(output_root: Path, config: ExperimentConfig) -> Path:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        run_name = (
            f"{run_id}_{config.default_lod}_{config.width}x{config.height}"
            f"_s{config.max_points}_q{config.quant_bits}"
        )
        run_dir = output_root / run_name
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    @staticmethod
    def _write_ppm(path: Path, frame_rgb: np.ndarray) -> None:
        height, width, _ = frame_rgb.shape
        with path.open("wb") as handle:
            handle.write(f"P6\n{width} {height}\n255\n".encode("ascii"))
            handle.write(frame_rgb.tobytes())

    @staticmethod
    def _select_encoder(ffmpeg_path: str) -> str:
        completed = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError("Could not query ffmpeg encoders.")

        available: set[str] = set()
        for line in completed.stdout.splitlines():
            stripped = line.strip()
            if not stripped or not stripped.startswith("V"):
                continue
            parts = stripped.split()
            if len(parts) >= 2:
                available.add(parts[1])

        preferred = ["libx264", "h264_nvenc", "av1_nvenc", "mpeg4"]
        for encoder in preferred:
            if encoder in available:
                return encoder

        raise RuntimeError("No supported video encoder found (libx264/h264_nvenc/av1_nvenc/mpeg4).")

    @classmethod
    def _encode_video(cls, frames_dir: Path, output_path: Path, fps: int) -> tuple[Path, str]:
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            raise RuntimeError("ffmpeg is required by the evaluation component but was not found in PATH.")
        encoder = cls._select_encoder(ffmpeg)

        command = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-framerate",
            str(max(1, fps)),
            "-i",
            str(frames_dir / "frame_%05d.ppm"),
            "-c:v",
            encoder,
            "-pix_fmt",
            "yuv420p",
            str(output_path),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            raise RuntimeError(
                "ffmpeg video encoding failed: "
                f"return_code={completed.returncode}, stderr={completed.stderr.strip()}"
            )
        return output_path, encoder

    def run_one(
        self,
        config: ExperimentConfig,
        output_root: str,
        reference_frames: list[np.ndarray] | None = None,
        capture_frames: bool = False,
    ) -> EvaluationRunResult:
        """Run one evaluation config and write artifacts under output_root."""
        run_dir = self._build_run_dir(Path(output_root), config)
        frames_dir = run_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)

        frame_rows: list[dict] = []
        ssim_values: list[float] = []
        captured_frames: list[np.ndarray] = []

        def on_frame(
            frame_bytes: bytes,
            width: int,
            height: int,
            frame_id: int,
            datagram,
            render_ms: float,
        ) -> None:
            frame_rgb = np.frombuffer(frame_bytes, dtype=np.uint8).reshape((height, width, 3)).copy()
            self._write_ppm(frames_dir / f"frame_{frame_id:05d}.ppm", frame_rgb)

            active_pixels = np.count_nonzero(frame_rgb.sum(axis=2))
            coverage = float(active_pixels / (width * height))
            brightness = float(frame_rgb.mean() / 255.0)

            if reference_frames is not None and frame_id < len(reference_frames):
                ssim = ssim_proxy(reference_frames[frame_id], frame_rgb)
            else:
                ssim = float("nan")

            if not np.isnan(ssim):
                ssim_values.append(ssim)

            frame_rows.append(
                {
                    "frame_id": frame_id,
                    "timestamp_ms": datagram.timestamp_ms,
                    "render_time_ms": render_ms,
                    "coverage": coverage,
                    "brightness": brightness,
                    "ssim_vs_full": ssim,
                }
            )

            if capture_frames:
                captured_frames.append(frame_rgb)

        runtime_summary = self.runtime_runner.run_one(config, frame_callback=on_frame)

        metrics_csv = run_dir / "frame_metrics.csv"
        with metrics_csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "frame_id",
                    "timestamp_ms",
                    "render_time_ms",
                    "coverage",
                    "brightness",
                    "ssim_vs_full",
                ],
            )
            writer.writeheader()
            writer.writerows(frame_rows)

        video_path, encoder_used = self._encode_video(
            frames_dir=frames_dir,
            output_path=run_dir / "headless_render.mp4",
            fps=config.fps,
        )

        coverage_values = [float(row["coverage"]) for row in frame_rows]
        brightness_values = [float(row["brightness"]) for row in frame_rows]

        summary = {
            **runtime_summary,
            "output_dir": str(run_dir),
            "frames_dir": str(frames_dir),
            "frame_metrics_csv": str(metrics_csv),
            "coverage_mean": float(np.mean(coverage_values)) if coverage_values else 0.0,
            "brightness_mean": float(np.mean(brightness_values)) if brightness_values else 0.0,
            "ssim_vs_full_mean": float(np.mean(ssim_values)) if ssim_values else None,
            "video_path": str(video_path),
            "video_encoder": encoder_used,
        }

        summary_path = run_dir / "summary.json"
        with summary_path.open("w", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=2)
        summary["summary_path"] = str(summary_path)

        return EvaluationRunResult(summary=summary, frames=captured_frames)

    def run_tradeoff_curve(
        self,
        base_config: ExperimentConfig,
        output_root: str,
        sparsity_levels: list[float],
        resolutions: list[tuple[int, int]],
        quant_bits_list: list[int],
    ) -> dict:
        """Sweep sparsity/resolution/quantization and save a tradeoff curve."""
        root = Path(output_root)
        root.mkdir(parents=True, exist_ok=True)

        curve_rows: list[dict] = []

        for width, height in resolutions:
            baseline_config = replace(
                base_config,
                width=width,
                height=height,
                default_lod="full",
                quant_bits=max(quant_bits_list) if quant_bits_list else 8,
                max_points=max(1, int(base_config.max_points)),
            )
            baseline_result = self.run_one(
                config=baseline_config,
                output_root=output_root,
                reference_frames=None,
                capture_frames=True,
            )
            baseline_frames = baseline_result.frames
            baseline_summary = baseline_result.summary
            curve_rows.append(
                {
                    "resolution": f"{width}x{height}",
                    "abr_profile": baseline_summary.get("abr_profile"),
                    "lod": baseline_summary["config"]["default_lod"],
                    "sparsity": 1.0,
                    "quant_bits": baseline_summary["config"]["quant_bits"],
                    "point_count": baseline_summary["point_count"],
                    "render_ms_mean": baseline_summary["render_time_ms"]["mean"],
                    "render_ms_p95": baseline_summary["render_time_ms"]["p95"],
                    "coverage_mean": baseline_summary["coverage_mean"],
                    "brightness_mean": baseline_summary["brightness_mean"],
                    "ssim_vs_full_mean": 1.0,
                    "effective_fps": baseline_summary["effective_fps"],
                    "summary_path": baseline_summary["summary_path"],
                    "video_path": baseline_summary["video_path"],
                }
            )

            for sparsity in sparsity_levels:
                safe_sparsity = float(np.clip(sparsity, 0.01, 1.0))
                point_budget = max(1, int(base_config.max_points * safe_sparsity))
                for quant_bits in quant_bits_list:
                    eval_config = replace(
                        base_config,
                        width=width,
                        height=height,
                        default_lod="quant_8bit",
                        max_points=point_budget,
                        quant_bits=int(max(2, min(16, quant_bits))),
                    )
                    result = self.run_one(
                        config=eval_config,
                        output_root=output_root,
                        reference_frames=baseline_frames,
                        capture_frames=False,
                    )
                    summary = result.summary
                    curve_rows.append(
                        {
                            "resolution": f"{width}x{height}",
                            "abr_profile": summary.get("abr_profile"),
                            "lod": summary["config"]["default_lod"],
                            "sparsity": safe_sparsity,
                            "quant_bits": summary["config"]["quant_bits"],
                            "point_count": summary["point_count"],
                            "render_ms_mean": summary["render_time_ms"]["mean"],
                            "render_ms_p95": summary["render_time_ms"]["p95"],
                            "coverage_mean": summary["coverage_mean"],
                            "brightness_mean": summary["brightness_mean"],
                            "ssim_vs_full_mean": summary["ssim_vs_full_mean"],
                            "effective_fps": summary["effective_fps"],
                            "summary_path": summary["summary_path"],
                            "video_path": summary["video_path"],
                        }
                    )

        curve_csv = root / "tradeoff_curve.csv"
        with curve_csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "resolution",
                    "abr_profile",
                    "lod",
                    "sparsity",
                    "quant_bits",
                    "point_count",
                    "render_ms_mean",
                    "render_ms_p95",
                    "coverage_mean",
                    "brightness_mean",
                    "ssim_vs_full_mean",
                    "effective_fps",
                    "summary_path",
                    "video_path",
                ],
            )
            writer.writeheader()
            writer.writerows(curve_rows)

        curve_md = root / "tradeoff_curve.md"
        with curve_md.open("w", encoding="utf-8") as handle:
            handle.write(
                "| Resolution | ABR | LOD | Sparsity | Quant bits | Points | SSIM vs full | Coverage | Render mean ms | FPS | Summary |\n"
            )
            handle.write("|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|\n")
            for row in curve_rows:
                ssim_value = row["ssim_vs_full_mean"]
                ssim_text = f"{ssim_value:.4f}" if isinstance(ssim_value, float) else "n/a"
                handle.write(
                    f"| {row['resolution']} | {row.get('abr_profile') or 'none'} | {row['lod']} | {row['sparsity']:.2f} | {row['quant_bits']} "
                    f"| {row['point_count']} | {ssim_text} | {row['coverage_mean']:.4f} "
                    f"| {row['render_ms_mean']:.3f} | {row['effective_fps']:.2f} | {row['summary_path']} |\\n"
                )

        report = {
            "status": "ok",
            "curve_csv": str(curve_csv),
            "curve_md": str(curve_md),
            "num_runs": len(curve_rows),
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "base_config": asdict(base_config),
        }
        report_path = root / "evaluation_report.json"
        with report_path.open("w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
        report["report_path"] = str(report_path)
        return report
