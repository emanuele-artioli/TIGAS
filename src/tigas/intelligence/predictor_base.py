"""Pose predictor interface.

All predictors consume current control state and return a projected pose for
the expected render horizon. This interface is intentionally minimal so novel
predictors can be dropped in for ablation without changing downstream modules.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from tigas.shared.types import PosePrediction, UplinkDatagram


class PosePredictor(ABC):
    """Abstract predictor contract for t + RTT pose extrapolation."""

    @abstractmethod
    def predict(self, datagram: UplinkDatagram, rtt_ms: float) -> PosePrediction:
        """Return predicted pose for the render horizon."""
