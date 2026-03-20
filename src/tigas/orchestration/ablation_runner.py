"""Headless ablation runner placeholder.

Runs trace-driven experiments across combinations of codec, predictor, network,
and LOD policies while collecting standardized metrics outputs.
"""

from __future__ import annotations

import csv
import json
import shutil
import statistics
import subprocess
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from tigas.input_control.headless_replayer import HeadlessTraceReplayer
from tigas.renderer.backend_cpu import CpuFallbackBackend
from tigas.shared.types import ExperimentConfig, RenderRequest


def _write_ppm(path: Path, frame_rgb: np.ndarray) -> None:
    """Write uint8 RGB frame to a binary PPM file."""
    height, width, _ = frame_rgb.shape
    with path.open("wb") as handle:
        handle.write(f"P6\n{width} {height}\n255\n".encode("ascii"))
        handle.write(frame_rgb.tobytes())


class HeadlessAblationRunner:
    """Runner for scripted headless ablation experiments."""

    def _resolve_point_cloud_path(self, config: ExperimentConfig) -> Path:
        if config.asset_path:
            candidate = Path(config.asset_path)
            if candidate.exists():
                return candidate

        trace_candidate = Path(config.trace_path)
        if trace_candidate.exists() and trace_candidate.suffix.lower() == ".ply":
            return trace_candidate

        raise FileNotFoundError(
            "Could not resolve a point-cloud path. Set `asset_path` to a valid .ply file."
        )

    def _build_output_dir(self, config: ExperimentConfig, cloud_path: Path) -> Path:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        run_name = f"{run_id}_{cloud_path.stem}_{config.default_lod}_{config.codec}"
        output_dir = Path(config.output_dir) / run_name
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def _maybe_encode_video(self, frames_dir: Path, output_path: Path, fps: int) -> Path | None:
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            return None

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
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(output_path),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            return None
        return output_path

    def run_one(self, config: ExperimentConfig) -> dict:
        """Execute one experiment and return summary metadata."""
        point_cloud_path = self._resolve_point_cloud_path(config)
        output_dir = self._build_output_dir(config, point_cloud_path)
        frames_dir = output_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)

        renderer = CpuFallbackBackend(
            point_cloud_path=str(point_cloud_path),
            width=config.width,
            height=config.height,
            max_points=config.max_points,
        )
        renderer.initialize()
        point_count = renderer.loaded_point_count
        scene_radius = renderer.scene_radius

        replayer = HeadlessTraceReplayer()
        trace_json = Path(config.trace_path) if config.trace_path else None
        if trace_json and trace_json.exists() and trace_json.suffix.lower() == ".json":
            samples = replayer.load_trace(str(trace_json))
        else:
            orbit_radius = max(renderer.scene_radius * 2.2, 0.4)
            samples = replayer.generate_orbit_samples(
                center=renderer.scene_center,
                radius=orbit_radius,
                num_frames=config.num_frames,
                fps=config.fps,
                requested_lod=config.default_lod,
            )

        datagrams = replayer.build_datagrams(samples)
        if config.num_frames > 0 and len(datagrams) > config.num_frames:
            datagrams = datagrams[: config.num_frames]

        frame_metrics: list[dict] = []
        render_times_ms: list[float] = []
        coverage_values: list[float] = []
        brightness_values: list[float] = []

        wall_start = time.perf_counter()
        try:
            for datagram in datagrams:
                lod = datagram.requested_lod if config.default_lod == "adaptive" else config.default_lod
                request = RenderRequest(
                    pose_matrix_4x4=datagram.camera_matrix_4x4,
                    lod_id=lod,
                    time_offset_ms=datagram.timestamp_ms,
                )

                render_start = time.perf_counter()
                frame = renderer.render(request)
                render_ms = (time.perf_counter() - render_start) * 1000.0
                render_times_ms.append(render_ms)

                frame_rgb = np.frombuffer(frame.data, dtype=np.uint8).reshape(
                    (frame.height, frame.width, 3)
                )
                active_pixels = np.count_nonzero(frame_rgb.sum(axis=2))
                coverage = float(active_pixels / (frame.width * frame.height))
                brightness = float(frame_rgb.mean() / 255.0)
                coverage_values.append(coverage)
                brightness_values.append(brightness)

                _write_ppm(frames_dir / f"frame_{frame.frame_id:05d}.ppm", frame_rgb)

                frame_metrics.append(
                    {
                        "frame_id": frame.frame_id,
                        "timestamp_ms": datagram.timestamp_ms,
                        "render_time_ms": render_ms,
                        "coverage": coverage,
                        "brightness": brightness,
                    }
                )
        finally:
            renderer.shutdown()

        wall_time_s = time.perf_counter() - wall_start
        frames_rendered = len(frame_metrics)
        if frames_rendered == 0:
            raise RuntimeError("Headless experiment rendered zero frames.")

        metrics_csv = output_dir / "frame_metrics.csv"
        with metrics_csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["frame_id", "timestamp_ms", "render_time_ms", "coverage", "brightness"],
            )
            writer.writeheader()
            writer.writerows(frame_metrics)

        render_times_array = np.asarray(render_times_ms, dtype=np.float64)
        summary = {
            "status": "ok",
            "point_cloud_path": str(point_cloud_path),
            "trace_source": str(trace_json) if (trace_json and trace_json.exists()) else "generated_orbit",
            "output_dir": str(output_dir),
            "frames_dir": str(frames_dir),
            "frame_metrics_csv": str(metrics_csv),
            "frames_rendered": frames_rendered,
            "resolution": {"width": config.width, "height": config.height},
            "point_count": point_count,
            "scene_radius": scene_radius,
            "render_time_ms": {
                "mean": float(statistics.fmean(render_times_ms)),
                "median": float(statistics.median(render_times_ms)),
                "p95": float(np.percentile(render_times_array, 95)),
                "min": float(render_times_array.min()),
                "max": float(render_times_array.max()),
            },
            "coverage_mean": float(statistics.fmean(coverage_values)),
            "brightness_mean": float(statistics.fmean(brightness_values)),
            "wall_time_s": wall_time_s,
            "effective_fps": float(frames_rendered / wall_time_s) if wall_time_s > 0 else 0.0,
            "config": asdict(config),
        }

        video_path = self._maybe_encode_video(
            frames_dir=frames_dir,
            output_path=output_dir / "headless_render.mp4",
            fps=config.fps,
        )
        summary["video_path"] = str(video_path) if video_path else None

        summary_path = output_dir / "summary.json"
        with summary_path.open("w", encoding="utf-8") as handle:
            json.dump(summary, handle, indent=2)
        summary["summary_path"] = str(summary_path)

        return summary

    def run_matrix(self, configs: list[ExperimentConfig]) -> list[dict]:
        """Execute a list of experiments and collect summaries."""
        results: list[dict] = []
        for config in configs:
            results.append(self.run_one(config))
        return results
