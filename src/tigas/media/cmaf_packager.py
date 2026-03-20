"""CMAF fragment packaging placeholder.

This module should convert encoded access units into transport-ready CMAF
fragments with timestamps and priority metadata.
"""

from __future__ import annotations

from tigas.media.coder_interface import CmafPackager
from tigas.media.priority import assign_object_priority
from tigas.shared.types import CmafFragment, RawFrame


class BasicCmafPackager(CmafPackager):
    """Placeholder packager producing simple fragment wrappers."""

    def __init__(self) -> None:
        self._next_fragment_id = 0

    def package(self, encoded_frame: bytes, frame: RawFrame) -> CmafFragment:
        """Create one fragment record from encoded bytes and frame metadata."""
        fragment = CmafFragment(
            fragment_id=self._next_fragment_id,
            track_id=1,
            payload=encoded_frame,
            priority=assign_object_priority(frame.is_keyframe_hint),
            timestamp_ms=float(frame.frame_id),
        )
        self._next_fragment_id += 1
        return fragment
