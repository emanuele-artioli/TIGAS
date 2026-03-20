"""Renderer scaffold tests."""

import pytest

from tigas.renderer.backend_cpu import CpuFallbackBackend
from tigas.shared.types import RenderRequest


def test_cpu_backend_name() -> None:
    backend = CpuFallbackBackend()
    assert backend.backend_name == "cpu"


def test_cpu_backend_render_is_placeholder() -> None:
    backend = CpuFallbackBackend()
    request = RenderRequest(pose_matrix_4x4=[1.0] * 16, lod_id="full", time_offset_ms=0.0)

    with pytest.raises(RuntimeError):
        backend.render(request)
