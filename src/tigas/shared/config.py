"""Top-level configuration placeholders for modular TIGAS orchestration.

The configuration layer should remain declarative and serializable. Concrete
module factories consume these dataclasses and instantiate runtime backends.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class TransportConfig:
    """Settings for QUIC and MoQ communication surfaces."""

    quic_host: str = "0.0.0.0"
    quic_port: int = 4433
    moq_namespace: str = "tigas/stream"


@dataclass(slots=True)
class RenderConfig:
    """Renderer and model-selection settings.

    `backend` is expected to map to one of: gsplat_cuda, webgpu, cpu.
    """

    backend: str = "cpu"
    default_lod: str = "full"
    target_fps: int = 30


@dataclass(slots=True)
class EncoderConfig:
    """Media coder defaults used when ABR does not provide overrides."""

    codec: str = "libx264"
    target_bitrate_kbps: int = 4000
    gop_size: int = 30


@dataclass(slots=True)
class PredictorConfig:
    """Pose predictor selection and tuning knobs."""

    name: str = "noop"
    process_noise: float = 1e-3
    measurement_noise: float = 1e-2


@dataclass(slots=True)
class RuntimeConfig:
    """Composite runtime configuration consumed by orchestrator."""

    transport: TransportConfig = field(default_factory=TransportConfig)
    render: RenderConfig = field(default_factory=RenderConfig)
    encoder: EncoderConfig = field(default_factory=EncoderConfig)
    predictor: PredictorConfig = field(default_factory=PredictorConfig)
