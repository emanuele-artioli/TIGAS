"""CPU fallback backend.

This backend is designed for headless environments where display-dependent GPU
paths are unavailable. It performs deterministic Gaussian-like splat rendering
from decoded point clouds and emits RGB frames for experiment orchestration.
"""

from __future__ import annotations

import math

import numpy as np

from tigas.renderer.interface import RendererBackend
from tigas.renderer.supersplat_loader import DecodedPointCloud, load_any_3dgs_ply
from tigas.shared.types import RawFrame, RenderRequest


class CpuFallbackBackend(RendererBackend):
    """Headless CPU renderer for standard and compressed 3DGS point clouds."""

    def __init__(
        self,
        point_cloud_path: str | None = None,
        width: int = 960,
        height: int = 540,
        fov_degrees: float = 60.0,
        max_points: int = 120_000,
        quant_bits: int = 8,
    ) -> None:
        self.point_cloud_path = point_cloud_path
        self.width = int(width)
        self.height = int(height)
        self.fov_degrees = float(fov_degrees)
        self.max_points = int(max_points)
        self.quant_bits = int(max(2, min(16, quant_bits)))

        self._cloud: DecodedPointCloud | None = None
        self._xyz_h: np.ndarray | None = None
        self._rgb: np.ndarray | None = None
        self._scale_xyz: np.ndarray | None = None
        self._opacity: np.ndarray | None = None
        self._point_indices = np.arange(0, 0, dtype=np.int64)
        self._frame_id = 0
        self._quantized_xyz_h: np.ndarray | None = None
        self._quantized_rgb: np.ndarray | None = None
        self._quantized_scale_xyz: np.ndarray | None = None
        self._quantized_opacity: np.ndarray | None = None

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

        self._cloud = load_any_3dgs_ply(
            self.point_cloud_path,
            max_points=self.max_points,
        )

        xyz = self._cloud.xyz.astype(np.float32, copy=False)
        self._rgb = self._cloud.rgb.astype(np.uint8, copy=False)
        self._scale_xyz = self._cloud.scale_xyz.astype(np.float32, copy=False)
        self._opacity = self._cloud.opacity.astype(np.float32, copy=False)
        ones = np.ones((xyz.shape[0], 1), dtype=np.float32)
        self._xyz_h = np.concatenate((xyz, ones), axis=1)
        self._point_indices = np.arange(self._xyz_h.shape[0], dtype=np.int64)
        self._prepare_quantized_lod_buffers()
        self._frame_id = 0

    @staticmethod
    def _quantize_to_bits(values: np.ndarray, bits: int, min_values: np.ndarray, max_values: np.ndarray) -> np.ndarray:
        levels = float((1 << bits) - 1)
        span = np.maximum(max_values - min_values, 1e-9)
        normalized = np.clip((values - min_values) / span, 0.0, 1.0)
        quantized = np.round(normalized * levels) / levels
        return quantized * span + min_values

    def _prepare_quantized_lod_buffers(self) -> None:
        if (
            self._xyz_h is None
            or self._rgb is None
            or self._scale_xyz is None
            or self._opacity is None
        ):
            raise RuntimeError("Renderer is not initialized. Call `initialize()` first.")

        xyz = self._xyz_h[:, :3]
        xyz_q = self._quantize_to_bits(
            xyz,
            self.quant_bits,
            xyz.min(axis=0),
            xyz.max(axis=0),
        ).astype(np.float32)
        ones = np.ones((xyz_q.shape[0], 1), dtype=np.float32)
        self._quantized_xyz_h = np.concatenate((xyz_q, ones), axis=1)

        scale_log = np.log(np.clip(self._scale_xyz, 1e-9, None))
        scale_log_q = self._quantize_to_bits(
            scale_log,
            self.quant_bits,
            scale_log.min(axis=0),
            scale_log.max(axis=0),
        )
        self._quantized_scale_xyz = np.exp(scale_log_q).astype(np.float32)

        rgb_float = self._rgb.astype(np.float32) / 255.0
        rgb_q = self._quantize_to_bits(
            rgb_float,
            self.quant_bits,
            np.zeros((1, 3), dtype=np.float32),
            np.ones((1, 3), dtype=np.float32),
        )
        self._quantized_rgb = np.round(np.clip(rgb_q, 0.0, 1.0) * 255.0).astype(np.uint8)

        opacity = self._opacity.reshape((-1, 1))
        opacity_q = self._quantize_to_bits(
            opacity,
            self.quant_bits,
            np.zeros((1, 1), dtype=np.float32),
            np.ones((1, 1), dtype=np.float32),
        )
        self._quantized_opacity = np.clip(opacity_q[:, 0], 1e-4, 1.0).astype(np.float32)

    def _select_lod_indices(self, lod_id: str) -> np.ndarray:
        if lod_id == "sampled_50":
            return self._point_indices[::2]
        return self._point_indices

    @staticmethod
    def _gaussian_kernel_1d(sigma: float) -> np.ndarray:
        safe_sigma = float(max(0.35, sigma))
        radius = max(1, int(round(2.5 * safe_sigma)))
        positions = np.arange(-radius, radius + 1, dtype=np.float32)
        kernel = np.exp(-(positions**2) / (2.0 * safe_sigma * safe_sigma))
        kernel /= np.sum(kernel)
        return kernel

    def _blur_2d(self, image: np.ndarray, kernel: np.ndarray) -> np.ndarray:
        radius = kernel.shape[0] // 2
        if image.ndim == 2:
            image = image[:, :, None]

        padded_x = np.pad(image, ((0, 0), (radius, radius), (0, 0)), mode="constant")
        blurred_x = np.zeros_like(image, dtype=np.float32)
        for idx, weight in enumerate(kernel):
            blurred_x += padded_x[:, idx : idx + self.width, :] * float(weight)

        padded_y = np.pad(blurred_x, ((radius, radius), (0, 0), (0, 0)), mode="constant")
        blurred_y = np.zeros_like(blurred_x, dtype=np.float32)
        for idx, weight in enumerate(kernel):
            blurred_y += padded_y[idx : idx + self.height, :, :] * float(weight)

        if blurred_y.shape[2] == 1:
            return blurred_y[:, :, 0]
        return blurred_y

    def render(self, request: RenderRequest) -> RawFrame:
        if (
            self._xyz_h is None
            or self._rgb is None
            or self._scale_xyz is None
            or self._opacity is None
        ):
            raise RuntimeError("Renderer is not initialized. Call `initialize()` first.")

        pose = np.asarray(request.pose_matrix_4x4, dtype=np.float32)
        if pose.size != 16:
            raise ValueError("pose_matrix_4x4 must contain exactly 16 values.")

        camera_to_world = pose.reshape((4, 4))
        world_to_camera = np.linalg.inv(camera_to_world).astype(np.float32)

        selected = self._select_lod_indices(request.lod_id)
        if request.lod_id == "quant_8bit":
            if (
                self._quantized_xyz_h is None
                or self._quantized_rgb is None
                or self._quantized_scale_xyz is None
                or self._quantized_opacity is None
            ):
                raise RuntimeError("Quantized buffers are unavailable.")
            xyz_h = self._quantized_xyz_h[selected]
            rgb = self._quantized_rgb[selected]
            scale_xyz = self._quantized_scale_xyz[selected]
            opacity = self._quantized_opacity[selected]
        else:
            xyz_h = self._xyz_h[selected]
            rgb = self._rgb[selected]
            scale_xyz = self._scale_xyz[selected]
            opacity = self._opacity[selected]

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
            rgb_valid = rgb[valid].astype(np.float32) / 255.0
            opacity_valid = np.clip(opacity[valid], 0.02, 1.0).astype(np.float32)
            scale_valid = scale_xyz[valid]

            pixel_ids = (py_valid * self.width + px_valid).astype(np.int64)
            accum_weight_flat = np.zeros((self.width * self.height,), dtype=np.float32)
            accum_color_flat = np.zeros((self.width * self.height, 3), dtype=np.float32)

            np.add.at(accum_weight_flat, pixel_ids, opacity_valid)
            np.add.at(accum_color_flat[:, 0], pixel_ids, rgb_valid[:, 0] * opacity_valid)
            np.add.at(accum_color_flat[:, 1], pixel_ids, rgb_valid[:, 1] * opacity_valid)
            np.add.at(accum_color_flat[:, 2], pixel_ids, rgb_valid[:, 2] * opacity_valid)

            accum_weight = accum_weight_flat.reshape((self.height, self.width))
            accum_color = accum_color_flat.reshape((self.height, self.width, 3))

            mean_scale = np.mean(scale_valid, axis=1)
            projected_sigma = (self._focal_x * mean_scale) / np.maximum(depth_valid, 1e-6)
            sigma_px = float(np.clip(np.median(projected_sigma) * 1.1, 0.55, 3.0))
            kernel = self._gaussian_kernel_1d(sigma_px)

            smooth_weight = self._blur_2d(accum_weight, kernel)
            smooth_color = self._blur_2d(accum_color, kernel)

            eps = 1e-6
            normalized = smooth_color / np.maximum(smooth_weight[:, :, None], eps)
            alpha = np.clip(smooth_weight, 0.0, 1.0)
            frame_float = np.clip(normalized * alpha[:, :, None], 0.0, 1.0)
            frame_flat = np.round(frame_float.reshape((-1, 3)) * 255.0).astype(np.uint8)

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
        self._scale_xyz = None
        self._opacity = None
        self._quantized_xyz_h = None
        self._quantized_rgb = None
        self._quantized_scale_xyz = None
        self._quantized_opacity = None
        self._point_indices = np.arange(0, 0, dtype=np.int64)
