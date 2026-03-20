"""h264_nvenc encoder placeholder backend."""

from __future__ import annotations

from tigas.media.coder_interface import EncoderBackend
from tigas.shared.types import EncodingPolicy, RawFrame


class H264NvencEncoder(EncoderBackend):
    """Placeholder for NVIDIA H.264 hardware encoder integration."""

    @property
    def encoder_name(self) -> str:
        return "h264_nvenc"

    def encode(self, frame: RawFrame, policy: EncodingPolicy) -> bytes:
        raise NotImplementedError("Implement FFmpeg or NVENC binding integration.")
