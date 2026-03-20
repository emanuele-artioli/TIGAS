"""WebGPU-compatible backend placeholder.

This backend targets broader hardware support where CUDA is unavailable. The
implementation may delegate to native bindings or external rendering services
as long as the `RendererBackend` contract is preserved.
"""

from __future__ import annotations

from tigas.renderer.interface import RendererBackend
from tigas.shared.types import RawFrame, RenderRequest


class WebGpuBackend(RendererBackend):
    """Placeholder for a general GPU renderer implementation."""

    @property
    def backend_name(self) -> str:
        return "webgpu"

    def initialize(self) -> None:
        raise NotImplementedError("Implement WebGPU backend startup and asset loading.")

    def render(self, request: RenderRequest) -> RawFrame:
        raise NotImplementedError("Implement WebGPU render path for pose and LOD input.")

    def shutdown(self) -> None:
        raise NotImplementedError("Implement WebGPU backend shutdown.")
