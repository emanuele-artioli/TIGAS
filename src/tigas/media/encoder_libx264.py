"""libx264 encoder placeholder backend."""

from __future__ import annotations

from tigas.media.coder_interface import EncoderBackend
from tigas.shared.types import EncodingPolicy, RawFrame


class Libx264Encoder(EncoderBackend):
    """Placeholder for software x264 encoding path."""

    @property
    def encoder_name(self) -> str:
        return "libx264"

    def encode(self, frame: RawFrame, policy: EncodingPolicy) -> bytes:
        raise NotImplementedError("Implement software libx264 encoding backend.")
