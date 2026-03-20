"""CUDA gsplat backend placeholder.

Planned behavior:

1. Load chosen Gaussian model variant from LOD registry.
2. Execute CUDA rendering for input pose and time offset.
3. Return raw frame buffer for encoding stage.
"""

from __future__ import annotations

from tigas.renderer.interface import RendererBackend
from tigas.shared.types import RawFrame, RenderRequest


class GsplatCudaBackend(RendererBackend):
    """Placeholder for GPU-accelerated gsplat renderer integration."""

    @property
    def backend_name(self) -> str:
        return "gsplat_cuda"

    def initialize(self) -> None:
        raise NotImplementedError("Implement CUDA gsplat initialization and model loading.")

    def render(self, request: RenderRequest) -> RawFrame:
        raise NotImplementedError("Implement CUDA render invocation with time_offset support.")

    def shutdown(self) -> None:
        raise NotImplementedError("Implement CUDA resource teardown.")
