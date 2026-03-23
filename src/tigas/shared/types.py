"""Canonical data contracts used by the TIGAS pipeline.

These models represent cross-module boundaries. Keeping them centralized makes
ablation experiments safer because implementations can change while interfaces
remain stable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Literal, Optional

LodId = Literal["full", "sampled_50", "quant_8bit", "adaptive"]
CodecId = Literal["h264_nvenc", "av1_nvenc", "libx264", "videotoolbox_h264"]
ObjectPriority = Literal["high", "normal"]
RendererBackendId = Literal["cpu", "gsplat_cuda"]


@dataclass(slots=True)
class UplinkDatagram:
    """Control payload sent by browser or trace replayer through QUIC datagrams."""

    seq_id: int
    timestamp_ms: float
    camera_matrix_4x4: list[float]
    requested_lod: LodId
    target_bitrate_kbps: int


@dataclass(slots=True)
class PosePrediction:
    """Pose estimate aligned to render horizon (typically t + RTT)."""

    predicted_matrix_4x4: list[float]
    prediction_horizon_ms: float
    confidence: float


@dataclass(slots=True)
class RenderRequest:
    """Unified rendering request for both 3DGS and 4DGS backends."""

    pose_matrix_4x4: list[float]
    lod_id: LodId
    time_offset_ms: float


@dataclass(slots=True)
class RawFrame:
    """Renderer output frame before compression and packaging."""

    frame_id: int
    width: int
    height: int
    pixel_format: str
    is_keyframe_hint: bool
    data: bytes


@dataclass(slots=True)
class EncodingPolicy:
    """Runtime encoder policy chosen by ABR and server safeguards."""

    codec: CodecId
    target_bitrate_kbps: int
    gop_size: int
    qp_hint: Optional[int] = None


@dataclass(slots=True)
class CmafFragment:
    """Output object to be carried over MoQ transport."""

    fragment_id: int
    track_id: int
    payload: bytes
    priority: ObjectPriority
    timestamp_ms: float


@dataclass(slots=True)
class MetricEvent:
    """Non-blocking metrics event emitted by hot-path components."""

    component: str
    event_type: str
    timestamp_ns: int
    seq_id: Optional[int] = None
    duration_us: Optional[float] = None
    value: Optional[float] = None
    tags: Dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ExperimentConfig:
    """Single ablation run configuration used by headless orchestrator."""

    trace_path: str
    codec: CodecId
    predictor: str
    network_profile: str
    default_lod: LodId
    asset_path: Optional[str] = None
    network_trace_path: Optional[str] = None
    abr_profile_path: Optional[str] = None
    enable_tc: bool = False
    tc_interface: Optional[str] = None
    output_dir: str = "outputs/headless"
    num_frames: int = 120
    fps: int = 30
    width: int = 960
    height: int = 540
    max_points: int = 120000
    renderer_backend: RendererBackendId = "cpu"
    quant_bits: int = 8
