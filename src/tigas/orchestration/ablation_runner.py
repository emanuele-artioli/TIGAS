"""Headless runtime runner.

This module is runtime-focused: it drives renderer execution for a pose stream
and reports render timing without writing evaluation artifacts.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import asdict
from pathlib import Path
from typing import Callable

import numpy as np

from tigas.input_control.headless_replayer import HeadlessTraceReplayer
from tigas.renderer.backend_cpu import CpuFallbackBackend
from tigas.renderer.backend_gsplat import GsplatCudaBackend
from tigas.shared.types import ExperimentConfig, RenderRequest, UplinkDatagram

FrameCallback = Callable[[bytes, int, int, int, UplinkDatagram, float], None]


class HeadlessAblationRunner:
    """Runtime renderer loop for headless execution."""

    def _build_renderer(self, config: ExperimentConfig, point_cloud_path: Path):
        if config.renderer_backend == "gsplat_cuda":
            return GsplatCudaBackend(
                point_cloud_path=str(point_cloud_path),
                width=config.width,
                height=config.height,
                max_points=config.max_points,
                quant_bits=config.quant_bits,
            )

        return CpuFallbackBackend(
            point_cloud_path=str(point_cloud_path),
            width=config.width,
            height=config.height,
            max_points=config.max_points,
            quant_bits=config.quant_bits,
        )

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

    def _build_datagrams(self, config: ExperimentConfig, renderer) -> tuple[list[UplinkDatagram], str]:
        replayer = HeadlessTraceReplayer()
        trace_json = Path(config.trace_path) if config.trace_path else None
        if trace_json and trace_json.exists() and trace_json.suffix.lower() == ".json":
            samples = replayer.load_trace(str(trace_json))
            trace_source = str(trace_json)
        else:
            orbit_radius = max(renderer.scene_radius * 2.2, 0.4)
            samples = replayer.generate_orbit_samples(
                center=renderer.scene_center,
                radius=orbit_radius,
                num_frames=config.num_frames,
                fps=config.fps,
                requested_lod=config.default_lod,
            )
            trace_source = "generated_orbit"

        datagrams = replayer.build_datagrams(samples)
        if config.num_frames > 0 and len(datagrams) > config.num_frames:
            datagrams = datagrams[: config.num_frames]

        return datagrams, trace_source

    def run_one(self, config: ExperimentConfig, frame_callback: FrameCallback | None = None) -> dict:
        """Execute one runtime render pass and return timing summary."""
        point_cloud_path = self._resolve_point_cloud_path(config)

        renderer = self._build_renderer(config=config, point_cloud_path=point_cloud_path)
        renderer.initialize()
        point_count = renderer.loaded_point_count
        scene_radius = renderer.scene_radius
        backend_name = renderer.backend_name

        datagrams, trace_source = self._build_datagrams(config=config, renderer=renderer)

        render_times_ms: list[float] = []

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

                if frame_callback is not None:
                    frame_callback(
                        frame.data,
                        frame.width,
                        frame.height,
                        frame.frame_id,
                        datagram,
                        render_ms,
                    )
        finally:
            renderer.shutdown()

        wall_time_s = time.perf_counter() - wall_start
        frames_rendered = len(render_times_ms)
        if frames_rendered == 0:
            raise RuntimeError("Headless runtime rendered zero frames.")

        render_times_array = np.asarray(render_times_ms, dtype=np.float64)
        return {
            "status": "ok",
            "point_cloud_path": str(point_cloud_path),
            "trace_source": trace_source,
            "frames_rendered": frames_rendered,
            "resolution": {"width": config.width, "height": config.height},
            "renderer_backend": backend_name,
            "point_count": point_count,
            "scene_radius": scene_radius,
            "render_time_ms": {
                "mean": float(statistics.fmean(render_times_ms)),
                "median": float(statistics.median(render_times_ms)),
                "p95": float(np.percentile(render_times_array, 95)),
                "min": float(render_times_array.min()),
                "max": float(render_times_array.max()),
            },
            "wall_time_s": wall_time_s,
            "effective_fps": float(frames_rendered / wall_time_s) if wall_time_s > 0 else 0.0,
            "config": asdict(config),
        }

    def run_matrix(self, configs: list[ExperimentConfig]) -> list[dict]:
        """Execute a list of runtime render runs."""
        results: list[dict] = []
        for config in configs:
            results.append(self.run_one(config))
        return results
