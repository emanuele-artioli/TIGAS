"""CUDA gsplat backend for headless rendering.

This backend loads decoded 3DGS points and rasterizes them with gsplat on
CUDA-capable systems.
"""

from __future__ import annotations

import math
import os
import shutil
import sys
import sysconfig
from pathlib import Path

import numpy as np

from tigas.renderer.interface import RendererBackend
from tigas.renderer.supersplat_loader import DecodedPointCloud, load_any_3dgs_ply
from tigas.shared.types import RawFrame, RenderRequest


class GsplatCudaBackend(RendererBackend):
    """Headless CUDA renderer powered by gsplat."""

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
        self._torch = None
        self._rasterization = None
        self._device = None
        self._means = None
        self._quats = None
        self._scales = None
        self._opacities = None
        self._colors = None
        self._camera_intrinsics = None
        self._frame_id = 0
        self._quantized_means = None
        self._quantized_scales = None
        self._quantized_opacities = None
        self._quantized_colors = None

    @staticmethod
    def _prepend_env_path(var_name: str, path: Path) -> None:
        path_str = str(path)
        if not path_str:
            return

        existing = os.environ.get(var_name, "")
        parts = [entry for entry in existing.split(os.pathsep) if entry]
        if path_str in parts:
            return
        parts.insert(0, path_str)
        os.environ[var_name] = os.pathsep.join(parts)

    @classmethod
    def _configure_cuda_build_environment(cls) -> None:
        """Expose CUDA include/lib paths for gsplat JIT compilation."""
        conda_prefix = Path(sys.prefix)
        cls._prepend_env_path("PATH", conda_prefix / "bin")
        target_root = conda_prefix / "targets" / "x86_64-linux"
        target_include = target_root / "include"
        target_lib = target_root / "lib"

        conda_include = conda_prefix / "include"
        conda_lib = conda_prefix / "lib"

        for include_dir in (target_include, conda_include):
            if include_dir.exists():
                cls._prepend_env_path("CPATH", include_dir)
                cls._prepend_env_path("CPLUS_INCLUDE_PATH", include_dir)

        for lib_dir in (target_lib, conda_lib):
            if lib_dir.exists():
                cls._prepend_env_path("LIBRARY_PATH", lib_dir)
                cls._prepend_env_path("LD_LIBRARY_PATH", lib_dir)

        # Fallback for pip-provided CUDA headers if toolkit headers are missing.
        if not (target_include / "cuda_runtime.h").exists():
            purelib = Path(sysconfig.get_paths().get("purelib", ""))
            nvidia_root = purelib / "nvidia"
            if nvidia_root.exists():
                for include_dir in sorted(nvidia_root.glob("**/include")):
                    cls._prepend_env_path("CPATH", include_dir)
                    cls._prepend_env_path("CPLUS_INCLUDE_PATH", include_dir)

                for lib_dir in sorted(nvidia_root.glob("**/lib")):
                    cls._prepend_env_path("LIBRARY_PATH", lib_dir)
                    cls._prepend_env_path("LD_LIBRARY_PATH", lib_dir)

                for lib64_dir in sorted(nvidia_root.glob("**/lib64")):
                    cls._prepend_env_path("LIBRARY_PATH", lib64_dir)
                    cls._prepend_env_path("LD_LIBRARY_PATH", lib64_dir)

        if "CUDA_HOME" not in os.environ or not os.environ["CUDA_HOME"]:
            nvcc_path = shutil.which("nvcc")
            if nvcc_path:
                os.environ["CUDA_HOME"] = str(Path(nvcc_path).resolve().parent.parent)

        if "CUDA_PATH" not in os.environ and os.environ.get("CUDA_HOME"):
            os.environ["CUDA_PATH"] = os.environ["CUDA_HOME"]

    @staticmethod
    def _to_uint8_frame(rgb_float: np.ndarray) -> np.ndarray:
        clamped = np.clip(rgb_float, 0.0, 1.0)
        return np.round(clamped * 255.0).astype(np.uint8)

    @staticmethod
    def _quantize_to_bits(values: np.ndarray, bits: int, min_values: np.ndarray, max_values: np.ndarray) -> np.ndarray:
        levels = float((1 << bits) - 1)
        span = np.maximum(max_values - min_values, 1e-9)
        normalized = np.clip((values - min_values) / span, 0.0, 1.0)
        quantized = np.round(normalized * levels) / levels
        return quantized * span + min_values

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

    @property
    def backend_name(self) -> str:
        return "gsplat_cuda"

    def initialize(self) -> None:
        if not self.point_cloud_path:
            raise ValueError("`point_cloud_path` is required for gsplat rendering.")

        self._configure_cuda_build_environment()
        try:
            import torch
            from gsplat import rasterization
        except Exception as exc:
            raise RuntimeError(
                "Unable to import gsplat or torch. Ensure both packages are installed in the active environment."
            ) from exc

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is not available. gsplat backend requires a CUDA-capable runtime.")

        self._torch = torch
        self._rasterization = rasterization
        self._device = torch.device("cuda")

        self._cloud = load_any_3dgs_ply(
            file_path=self.point_cloud_path,
            max_points=self.max_points,
        )

        means = torch.from_numpy(self._cloud.xyz.astype(np.float32, copy=False)).to(self._device)
        scales = torch.from_numpy(
            np.clip(self._cloud.scale_xyz.astype(np.float32, copy=False), 1e-6, 10.0)
        ).to(self._device)
        opacities = torch.from_numpy(
            np.clip(self._cloud.opacity.astype(np.float32, copy=False), 1e-4, 1.0)
        ).to(self._device)
        colors = torch.from_numpy(self._cloud.rgb.astype(np.float32, copy=False) / 255.0).to(self._device)

        quats = torch.zeros((means.shape[0], 4), dtype=torch.float32, device=self._device)
        quats[:, 0] = 1.0

        fov_radians = math.radians(self.fov_degrees)
        focal = (self.width * 0.5) / math.tan(fov_radians * 0.5)
        camera_intrinsics = torch.tensor(
            [
                [focal, 0.0, self.width * 0.5],
                [0.0, focal, self.height * 0.5],
                [0.0, 0.0, 1.0],
            ],
            dtype=torch.float32,
            device=self._device,
        )

        self._means = means
        self._quats = quats
        self._scales = scales
        self._opacities = opacities
        self._colors = colors
        self._camera_intrinsics = camera_intrinsics
        self._prepare_quantized_tensors()
        self._frame_id = 0

    def _prepare_quantized_tensors(self) -> None:
        if (
            self._means is None
            or self._scales is None
            or self._opacities is None
            or self._colors is None
        ):
            raise RuntimeError("Renderer is not initialized. Call `initialize()` first.")

        means_np = self._means.detach().cpu().numpy()
        means_q = self._quantize_to_bits(
            means_np,
            self.quant_bits,
            means_np.min(axis=0),
            means_np.max(axis=0),
        ).astype(np.float32)

        scales_np = self._scales.detach().cpu().numpy()
        scales_log = np.log(np.clip(scales_np, 1e-9, None))
        scales_log_q = self._quantize_to_bits(
            scales_log,
            self.quant_bits,
            scales_log.min(axis=0),
            scales_log.max(axis=0),
        )
        scales_q = np.exp(scales_log_q).astype(np.float32)

        colors_np = self._colors.detach().cpu().numpy()
        colors_q = self._quantize_to_bits(
            colors_np,
            self.quant_bits,
            np.zeros((1, 3), dtype=np.float32),
            np.ones((1, 3), dtype=np.float32),
        ).astype(np.float32)

        opacity_np = self._opacities.detach().cpu().numpy().reshape((-1, 1))
        opacity_q = self._quantize_to_bits(
            opacity_np,
            self.quant_bits,
            np.zeros((1, 1), dtype=np.float32),
            np.ones((1, 1), dtype=np.float32),
        )[:, 0]
        opacity_q = np.clip(opacity_q, 1e-4, 1.0).astype(np.float32)

        self._quantized_means = self._torch.from_numpy(means_q).to(self._device)
        self._quantized_scales = self._torch.from_numpy(scales_q).to(self._device)
        self._quantized_colors = self._torch.from_numpy(colors_q).to(self._device)
        self._quantized_opacities = self._torch.from_numpy(opacity_q).to(self._device)

    def _select_lod_tensor(self, tensor, lod_id: str):
        if lod_id == "sampled_50":
            return tensor[::2]
        return tensor

    def render(self, request: RenderRequest) -> RawFrame:
        if (
            self._torch is None
            or self._rasterization is None
            or self._means is None
            or self._quats is None
            or self._scales is None
            or self._opacities is None
            or self._colors is None
            or self._camera_intrinsics is None
            or self._device is None
        ):
            raise RuntimeError("Renderer is not initialized. Call `initialize()` first.")

        pose = np.asarray(request.pose_matrix_4x4, dtype=np.float32)
        if pose.size != 16:
            raise ValueError("pose_matrix_4x4 must contain exactly 16 values.")

        camera_to_world = pose.reshape((4, 4))
        world_to_camera = np.linalg.inv(camera_to_world).astype(np.float32)
        # Pose matrices arrive in row-major camera-to-world layout.
        # gsplat expects world-to-camera view matrices in transposed form.
        viewmats = self._torch.from_numpy(world_to_camera.T).to(self._device).unsqueeze(0)
        intrinsics = self._camera_intrinsics.unsqueeze(0)

        means = self._select_lod_tensor(self._means, request.lod_id)
        quats = self._select_lod_tensor(self._quats, request.lod_id)
        scales = self._select_lod_tensor(self._scales, request.lod_id)
        opacities = self._select_lod_tensor(self._opacities, request.lod_id)
        colors = self._select_lod_tensor(self._colors, request.lod_id)

        if request.lod_id == "quant_8bit":
            if (
                self._quantized_means is None
                or self._quantized_scales is None
                or self._quantized_opacities is None
                or self._quantized_colors is None
            ):
                raise RuntimeError("Quantized tensors are unavailable.")
            means = self._quantized_means
            scales = self._quantized_scales
            opacities = self._quantized_opacities
            colors = self._quantized_colors

        render_colors, _, _ = self._rasterization(
            means=means,
            quats=quats,
            scales=scales,
            opacities=opacities,
            colors=colors,
            viewmats=viewmats,
            Ks=intrinsics,
            width=self.width,
            height=self.height,
            near_plane=0.01,
            far_plane=1e6,
            packed=True,
            render_mode="RGB",
            rasterize_mode="antialiased",
        )

        frame_rgb = self._to_uint8_frame(render_colors[0].detach().cpu().numpy())

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
        self._cloud = None
        self._means = None
        self._quats = None
        self._scales = None
        self._opacities = None
        self._colors = None
        self._camera_intrinsics = None
        self._quantized_means = None
        self._quantized_scales = None
        self._quantized_opacities = None
        self._quantized_colors = None
        self._frame_id = 0

        if self._torch is not None and self._torch.cuda.is_available():
            self._torch.cuda.empty_cache()

        self._torch = None
        self._rasterization = None
        self._device = None
