"""Headless replay mode placeholder.

This module replays trace samples as if they were live browser updates, making
ablation experiments deterministic and reproducible.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass

from tigas.shared.types import UplinkDatagram


@dataclass(slots=True)
class TraceSample:
    """Single timeline sample loaded from movement trace files."""

    timestamp_ms: float
    camera_matrix_4x4: list[float]
    requested_lod: str
    target_bitrate_kbps: int


class HeadlessTraceReplayer:
    """Load and replay trace data while preserving temporal ordering."""

    @staticmethod
    def _normalize(vector: tuple[float, float, float]) -> tuple[float, float, float]:
        length = math.sqrt(vector[0] ** 2 + vector[1] ** 2 + vector[2] ** 2)
        if length < 1e-8:
            return (0.0, 0.0, 0.0)
        return (vector[0] / length, vector[1] / length, vector[2] / length)

    @staticmethod
    def _cross(
        a: tuple[float, float, float],
        b: tuple[float, float, float],
    ) -> tuple[float, float, float]:
        return (
            a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0],
        )

    def _look_at_camera_to_world(
        self,
        eye: tuple[float, float, float],
        target: tuple[float, float, float],
    ) -> list[float]:
        """Build a camera-to-world matrix with a stable up-vector strategy."""
        forward = self._normalize(
            (target[0] - eye[0], target[1] - eye[1], target[2] - eye[2])
        )

        world_up = (0.0, 1.0, 0.0)
        right = self._normalize(self._cross(forward, world_up))
        if right == (0.0, 0.0, 0.0):
            world_up = (0.0, 0.0, 1.0)
            right = self._normalize(self._cross(forward, world_up))

        up = self._normalize(self._cross(right, forward))
        camera_forward = (-forward[0], -forward[1], -forward[2])

        return [
            right[0],
            up[0],
            camera_forward[0],
            eye[0],
            right[1],
            up[1],
            camera_forward[1],
            eye[1],
            right[2],
            up[2],
            camera_forward[2],
            eye[2],
            0.0,
            0.0,
            0.0,
            1.0,
        ]

    def load_trace(self, trace_path: str) -> list[TraceSample]:
        """Parse a movement trace JSON file into typed samples."""
        with open(trace_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)

        if isinstance(data, list):
            return self._load_position_trace(data)

        samples: list[TraceSample] = []
        for item in data.get("samples", []):
            samples.append(
                TraceSample(
                    timestamp_ms=float(item["timestamp_ms"]),
                    camera_matrix_4x4=list(item["camera_matrix_4x4"]),
                    requested_lod=str(item.get("requested_lod", "full")),
                    target_bitrate_kbps=int(item.get("target_bitrate_kbps", 4000)),
                )
            )
        return samples

    def _load_position_trace(self, rows: list[dict]) -> list[TraceSample]:
        """Parse movement traces with x/y/z/tMs structure into camera matrices."""
        if not rows:
            return []

        points = [
            (
                float(item.get("x", 0.0)),
                float(item.get("y", 0.0)),
                float(item.get("z", 0.0)),
            )
            for item in rows
        ]
        center = (
            sum(p[0] for p in points) / len(points),
            sum(p[1] for p in points) / len(points),
            sum(p[2] for p in points) / len(points),
        )

        samples: list[TraceSample] = []
        for idx, item in enumerate(rows):
            eye = points[idx]
            matrix = self._look_at_camera_to_world(eye=eye, target=center)
            timestamp = float(item.get("tMs", idx * 33.333))
            samples.append(
                TraceSample(
                    timestamp_ms=timestamp,
                    camera_matrix_4x4=matrix,
                    requested_lod=str(item.get("requested_lod", "full")),
                    target_bitrate_kbps=int(item.get("target_bitrate_kbps", 4000)),
                )
            )
        return samples

    def load_network_trace(self, trace_path: str) -> list[int]:
        """Load a network trace CSV (or newline-separated values) as kbps samples."""
        bandwidth_kbps: list[int] = []
        with open(trace_path, "r", encoding="utf-8") as handle:
            reader = csv.reader(handle)
            for row in reader:
                if not row:
                    continue
                token = row[0].strip()
                if not token:
                    continue
                try:
                    value = int(round(float(token)))
                except ValueError:
                    continue
                bandwidth_kbps.append(max(1, value))
        return bandwidth_kbps

    def apply_network_trace(
        self,
        samples: list[TraceSample],
        bandwidth_kbps: list[int],
    ) -> list[TraceSample]:
        """Apply network trace values to per-sample target bitrate."""
        if not samples or not bandwidth_kbps:
            return samples

        applied: list[TraceSample] = []
        for idx, sample in enumerate(samples):
            bitrate = bandwidth_kbps[idx % len(bandwidth_kbps)]
            applied.append(
                TraceSample(
                    timestamp_ms=sample.timestamp_ms,
                    camera_matrix_4x4=sample.camera_matrix_4x4,
                    requested_lod=sample.requested_lod,
                    target_bitrate_kbps=int(bitrate),
                )
            )
        return applied

    def build_datagrams(self, samples: list[TraceSample]) -> list[UplinkDatagram]:
        """Convert trace samples into canonical uplink datagrams."""
        datagrams: list[UplinkDatagram] = []
        for seq_id, sample in enumerate(samples):
            datagrams.append(
                UplinkDatagram(
                    seq_id=seq_id,
                    timestamp_ms=sample.timestamp_ms,
                    camera_matrix_4x4=sample.camera_matrix_4x4,
                    requested_lod=sample.requested_lod,
                    target_bitrate_kbps=sample.target_bitrate_kbps,
                )
            )
        return datagrams

    def generate_orbit_samples(
        self,
        center: tuple[float, float, float],
        radius: float,
        num_frames: int = 120,
        fps: int = 30,
        elevation_scale: float = 0.25,
        requested_lod: str = "full",
        target_bitrate_kbps: int = 4000,
    ) -> list[TraceSample]:
        """Generate a deterministic orbit trace for headless render experiments."""
        samples: list[TraceSample] = []
        safe_frame_count = max(1, num_frames)
        safe_fps = max(1, fps)

        for frame_idx in range(safe_frame_count):
            angle = (2.0 * math.pi * frame_idx) / safe_frame_count
            eye = (
                center[0] + radius * math.cos(angle),
                center[1] + radius * elevation_scale,
                center[2] + radius * math.sin(angle),
            )
            matrix = self._look_at_camera_to_world(eye, center)
            samples.append(
                TraceSample(
                    timestamp_ms=(frame_idx * 1000.0) / safe_fps,
                    camera_matrix_4x4=matrix,
                    requested_lod=requested_lod,
                    target_bitrate_kbps=target_bitrate_kbps,
                )
            )
        return samples
