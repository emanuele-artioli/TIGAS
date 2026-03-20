"""Media coder interfaces.

Defines the separation between raw frame encoding and CMAF packaging. Concrete
encoders should emit intermediate access units that can be fragmented and
prioritized independently for MoQ transport.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from tigas.shared.types import CmafFragment, EncodingPolicy, RawFrame


class EncoderBackend(ABC):
    """Abstract encoder backend contract."""

    @property
    @abstractmethod
    def encoder_name(self) -> str:
        """Return stable encoder identifier."""

    @abstractmethod
    def encode(self, frame: RawFrame, policy: EncodingPolicy) -> bytes:
        """Encode one raw frame and return compressed bytes."""


class CmafPackager(ABC):
    """Abstract CMAF packager contract."""

    @abstractmethod
    def package(self, encoded_frame: bytes, frame: RawFrame) -> CmafFragment:
        """Wrap encoded bytes into one CMAF-compatible fragment object."""
