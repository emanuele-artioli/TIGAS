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
from tigas.instrumentation.tc_profiles import TcProfileManager
from tigas.intelligence.abr_client import (
    ThroughputEstimator,
    build_client_abr_controller,
    load_abr_profile,
    resolve_abr_profile,
)
from tigas.intelligence.abr_server import ServerAbrController
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

    @staticmethod
    def _resolve_trace_input(trace_arg: str | None, folder: str, suffix: str) -> Path | None:
        if not trace_arg:
            return None

        candidate = Path(trace_arg)
        if candidate.exists():
            return candidate

        project_root = Path(__file__).resolve().parents[3]
        folder_path = project_root / folder
        by_name = folder_path / f"{trace_arg}{suffix}"
        if by_name.exists():
            return by_name

        raise FileNotFoundError(
            f"Could not resolve trace '{trace_arg}'. Checked path and {folder_path}/{trace_arg}{suffix}."
        )

    def _build_datagrams(self, config: ExperimentConfig, renderer) -> tuple[list[UplinkDatagram], str]:
        replayer = HeadlessTraceReplayer()
        trace_json = self._resolve_trace_input(config.trace_path, "movement_traces", ".json")
        if trace_json and trace_json.suffix.lower() == ".json":
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

        network_trace = self._resolve_trace_input(
            config.network_trace_path,
            "network_traces",
            ".csv",
        )
        if network_trace is not None:
            bandwidth_kbps = replayer.load_network_trace(str(network_trace))
            samples = replayer.apply_network_trace(samples=samples, bandwidth_kbps=bandwidth_kbps)
            trace_source = f"{trace_source};network={network_trace}"

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

        abr_profile_name: str | None = None
        client_abr = None
        server_abr = None
        throughput_estimator = None
        if config.abr_profile_path:
            resolved_abr_profile = resolve_abr_profile(config.abr_profile_path)
            if resolved_abr_profile is not None:
                profile = load_abr_profile(resolved_abr_profile)
                abr_profile_name = profile.name
                client_abr = build_client_abr_controller(profile)
                server_abr = ServerAbrController(frame_budget_ms=1000.0 / max(1, config.fps))
                throughput_estimator = ThroughputEstimator(ewma_alpha=profile.ewma_alpha)

        tc_manager = TcProfileManager() if config.enable_tc and config.tc_interface else None
        tc_status = "disabled"
        last_tc_rate_kbps: int | None = None
        tc_applied = False

        render_times_ms: list[float] = []
        abr_target_kbps: list[int] = []
        abr_lod_choices: list[str] = []
        measured_throughput_kbps: list[float] = []
        buffer_level_ms = 2000.0
        max_buffer_ms = 6000.0
        previous_timestamp_ms: float | None = None
        previous_render_ms = 0.0

        wall_start = time.perf_counter()
        try:
            for datagram in datagrams:
                if previous_timestamp_ms is None:
                    frame_interval_ms = 1000.0 / max(1, config.fps)
                else:
                    frame_interval_ms = max(1.0, datagram.timestamp_ms - previous_timestamp_ms)
                previous_timestamp_ms = datagram.timestamp_ms

                baseline_target_kbps = int(max(1, datagram.target_bitrate_kbps))
                estimated_throughput_kbps = float(baseline_target_kbps)
                if throughput_estimator is not None:
                    estimated_throughput_kbps = throughput_estimator.current(baseline_target_kbps)

                if client_abr is not None and server_abr is not None:
                    client_decision = client_abr.decide(
                        throughput_kbps=estimated_throughput_kbps,
                        decode_latency_ms=previous_render_ms,
                        buffer_level_ms=buffer_level_ms,
                    )
                    server_decision = server_abr.decide(
                        render_time_ms=previous_render_ms,
                        encode_queue_depth=0,
                        gpu_utilization=0.0,
                        client_requested_lod=client_decision.requested_lod,
                        client_target_bitrate_kbps=client_decision.target_bitrate_kbps,
                    )
                    chosen_lod = server_decision.enforced_lod
                    chosen_target_kbps = int(max(1, server_decision.encoder_bitrate_kbps))
                    if config.network_trace_path:
                        chosen_target_kbps = min(chosen_target_kbps, baseline_target_kbps)
                else:
                    chosen_target_kbps = baseline_target_kbps
                    chosen_lod = datagram.requested_lod if config.default_lod == "adaptive" else config.default_lod

                if tc_manager is not None:
                    tc_rate_kbps = baseline_target_kbps if config.network_trace_path else chosen_target_kbps
                    if last_tc_rate_kbps != tc_rate_kbps:
                        try:
                            tc_manager.apply_rate_kbps(config.tc_interface or "", tc_rate_kbps)
                            tc_status = "active"
                            tc_applied = True
                            last_tc_rate_kbps = tc_rate_kbps
                        except Exception as exc:  # pragma: no cover - host-permission dependent
                            tc_status = f"disabled:{type(exc).__name__}"
                            tc_manager = None

                request = RenderRequest(
                    pose_matrix_4x4=datagram.camera_matrix_4x4,
                    lod_id=chosen_lod,
                    time_offset_ms=datagram.timestamp_ms,
                )

                render_start = time.perf_counter()
                frame = renderer.render(request)
                render_ms = (time.perf_counter() - render_start) * 1000.0
                render_times_ms.append(render_ms)
                previous_render_ms = render_ms
                abr_target_kbps.append(chosen_target_kbps)
                abr_lod_choices.append(chosen_lod)

                if frame_callback is not None:
                    frame_callback(
                        frame.data,
                        frame.width,
                        frame.height,
                        frame.frame_id,
                        datagram,
                        render_ms,
                    )

                if throughput_estimator is not None:
                    measured = throughput_estimator.observe(
                        delivered_bytes=len(frame.data),
                        elapsed_s=frame_interval_ms / 1000.0,
                    )
                    measured_throughput_kbps.append(measured)
                    frame_bits = float(len(frame.data) * 8)
                    download_time_ms = frame_bits / max(1.0, float(chosen_target_kbps))
                    buffer_level_ms = float(
                        np.clip(buffer_level_ms + frame_interval_ms - download_time_ms, 0.0, max_buffer_ms)
                    )
        finally:
            if tc_manager is not None and tc_applied and config.tc_interface:
                try:
                    tc_manager.clear(config.tc_interface)
                except Exception as exc:  # pragma: no cover - host-permission dependent
                    tc_status = f"clear_failed:{type(exc).__name__}"
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
            "network_trace_path": config.network_trace_path,
            "target_bitrate_kbps_mean": float(
                np.mean([d.target_bitrate_kbps for d in datagrams])
            ),
            "abr_target_bitrate_kbps_mean": float(np.mean(abr_target_kbps)) if abr_target_kbps else None,
            "abr_throughput_kbps_mean": float(np.mean(measured_throughput_kbps))
            if measured_throughput_kbps
            else None,
            "frames_rendered": frames_rendered,
            "resolution": {"width": config.width, "height": config.height},
            "renderer_backend": backend_name,
            "point_count": point_count,
            "scene_radius": scene_radius,
            "abr_profile": abr_profile_name,
            "abr_lod_distribution": {
                lod: int(abr_lod_choices.count(lod)) for lod in sorted(set(abr_lod_choices))
            }
            if abr_lod_choices
            else {},
            "tc": {
                "enabled": bool(config.enable_tc and config.tc_interface),
                "interface": config.tc_interface,
                "status": tc_status,
            },
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
