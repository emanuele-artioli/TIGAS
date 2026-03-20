"""VideoToolbox encoder placeholder backend."""

from __future__ import annotations

from tigas.media.coder_interface import EncoderBackend
from tigas.shared.types import EncodingPolicy, RawFrame


class VideoToolboxEncoder(EncoderBackend):
    """Placeholder for Apple VideoToolbox hardware encoding path."""

    @property
    def encoder_name(self) -> str:
        return "videotoolbox_h264"

    def encode(self, frame: RawFrame, policy: EncodingPolicy) -> bytes:
        raise NotImplementedError("Implement macOS VideoToolbox encoder integration.")
