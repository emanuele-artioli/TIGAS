"""Renderer backend interface.

All rendering implementations must accept the same `RenderRequest` shape to
keep 3DGS and 4DGS pipeline integration consistent.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from tigas.shared.types import RawFrame, RenderRequest


class RendererBackend(ABC):
    """Abstract renderer contract for pluggable backend implementations."""

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """Return a stable backend identifier for telemetry and config."""

    @abstractmethod
    def initialize(self) -> None:
        """Initialize backend resources and model handles."""

    @abstractmethod
    def render(self, request: RenderRequest) -> RawFrame:
        """Render a frame for the given pose, LOD, and time offset."""

    @abstractmethod
    def shutdown(self) -> None:
        """Release backend resources."""
