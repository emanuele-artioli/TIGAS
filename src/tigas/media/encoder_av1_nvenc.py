"""av1_nvenc encoder placeholder backend."""

from __future__ import annotations

from tigas.media.coder_interface import EncoderBackend
from tigas.shared.types import EncodingPolicy, RawFrame


class Av1NvencEncoder(EncoderBackend):
    """Placeholder for NVIDIA AV1 hardware encoder integration."""

    @property
    def encoder_name(self) -> str:
        return "av1_nvenc"

    def encode(self, frame: RawFrame, policy: EncodingPolicy) -> bytes:
        raise NotImplementedError("Implement AV1 NVENC backend integration.")
