"""CPU fallback backend.

This backend is designed for headless environments where display-dependent GPU
paths are unavailable. It performs deterministic point projection from decoded
SuperSplat point clouds and emits RGB frames for experiment orchestration.
"""

from __future__ import annotations

import math

import numpy as np

from tigas.renderer.interface import RendererBackend
from tigas.renderer.supersplat_loader import DecodedPointCloud, load_supersplat_compressed_ply
from tigas.shared.types import RawFrame, RenderRequest


class CpuFallbackBackend(RendererBackend):
    """Headless CPU renderer for compressed SuperSplat point clouds."""

    def __init__(
        self,
        point_cloud_path: str | None = None,
        width: int = 960,
        height: int = 540,
        fov_degrees: float = 60.0,
        max_points: int = 120_000,
    ) -> None:
        self.point_cloud_path = point_cloud_path
        self.width = int(width)
        self.height = int(height)
        self.fov_degrees = float(fov_degrees)
        self.max_points = int(max_points)

        self._cloud: DecodedPointCloud | None = None
        self._xyz_h: np.ndarray | None = None
        self._rgb: np.ndarray | None = None
        self._point_indices = np.arange(0, 0, dtype=np.int64)
        self._frame_id = 0

        fov_radians = math.radians(self.fov_degrees)
        focal = (self.width * 0.5) / math.tan(fov_radians * 0.5)
        self._focal_x = float(focal)
        self._focal_y = float(focal)

    @property
    def backend_name(self) -> str:
        return "cpu"

    @property
    def scene_center(self) -> tuple[float, float, float]:
        if self._cloud is None:
            raise RuntimeError("Renderer has not been initialized.")
        return (float(self._cloud.center[0]), float(self._cloud.center[1]), float(self._cloud.center[2]))

    @property
    def scene_radius(self) -> float:
        if self._cloud is None:
            raise RuntimeError("Renderer has not been initialized.")
        return float(self._cloud.radius)

    @property
    def loaded_point_count(self) -> int:
        if self._cloud is None:
            return 0
        return int(self._cloud.point_count)

    def initialize(self) -> None:
        """Load and decode point cloud data for headless rendering."""
        if not self.point_cloud_path:
            raise ValueError("`point_cloud_path` is required for CPU headless rendering.")

        self._cloud = load_supersplat_compressed_ply(
            self.point_cloud_path,
            max_points=self.max_points,
        )

        xyz = self._cloud.xyz.astype(np.float32, copy=False)
        self._rgb = self._cloud.rgb.astype(np.uint8, copy=False)
        ones = np.ones((xyz.shape[0], 1), dtype=np.float32)
        self._xyz_h = np.concatenate((xyz, ones), axis=1)
        self._point_indices = np.arange(self._xyz_h.shape[0], dtype=np.int64)
        self._frame_id = 0

    def _select_lod_indices(self, lod_id: str) -> np.ndarray:
        if lod_id == "sampled_50":
            return self._point_indices[::2]
        if lod_id == "quant_8bit":
            return self._point_indices[::3]
        return self._point_indices

    def render(self, request: RenderRequest) -> RawFrame:
        if self._xyz_h is None or self._rgb is None:
            raise RuntimeError("Renderer is not initialized. Call `initialize()` first.")

        pose = np.asarray(request.pose_matrix_4x4, dtype=np.float32)
        if pose.size != 16:
            raise ValueError("pose_matrix_4x4 must contain exactly 16 values.")

        camera_to_world = pose.reshape((4, 4))
        world_to_camera = np.linalg.inv(camera_to_world).astype(np.float32)

        selected = self._select_lod_indices(request.lod_id)
        xyz_h = self._xyz_h[selected]
        rgb = self._rgb[selected]

        camera_space = xyz_h @ world_to_camera.T
        depth = -camera_space[:, 2]
        valid = depth > 1e-4

        projected_x = (camera_space[:, 0] / np.maximum(depth, 1e-6)) * self._focal_x + (self.width * 0.5)
        projected_y = (self.height * 0.5) - (camera_space[:, 1] / np.maximum(depth, 1e-6)) * self._focal_y

        px = projected_x.astype(np.int32)
        py = projected_y.astype(np.int32)

        valid &= px >= 0
        valid &= px < self.width
        valid &= py >= 0
        valid &= py < self.height

        frame_flat = np.zeros((self.width * self.height, 3), dtype=np.uint8)
        if np.any(valid):
            px_valid = px[valid]
            py_valid = py[valid]
            depth_valid = depth[valid]
            rgb_valid = rgb[valid]

            pixel_ids = py_valid * self.width + px_valid
            order = np.lexsort((depth_valid, pixel_ids))
            pixel_sorted = pixel_ids[order]

            keep = np.empty(order.shape[0], dtype=bool)
            keep[0] = True
            keep[1:] = pixel_sorted[1:] != pixel_sorted[:-1]
            chosen = order[keep]

            frame_flat[pixel_ids[chosen]] = rgb_valid[chosen]

        frame_rgb = frame_flat.reshape((self.height, self.width, 3))

        frame_id = self._frame_id
        self._frame_id += 1
        return RawFrame(
            frame_id=frame_id,
            width=self.width,
            height=self.height,
            pixel_format="rgb24",
            is_keyframe_hint=(frame_id % 30 == 0),
            data=frame_rgb.tobytes(),
        )

    def shutdown(self) -> None:
        """Release decoded arrays."""
        self._cloud = None
        self._xyz_h = None
        self._rgb = None
        self._point_indices = np.arange(0, 0, dtype=np.int64)
