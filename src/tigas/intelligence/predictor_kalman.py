"""Kalman pose predictor placeholder.

Intended implementation:

1. Split pose into translation and orientation state vectors.
2. Maintain a Kalman state per stream id.
3. Predict forward by measured or estimated RTT horizon.
4. Emit confidence based on covariance growth.
"""

from __future__ import annotations

from tigas.intelligence.predictor_base import PosePredictor
from tigas.shared.types import PosePrediction, UplinkDatagram


class KalmanPosePredictor(PosePredictor):
    """Stateful predictor placeholder for low-latency camera extrapolation."""

    def predict(self, datagram: UplinkDatagram, rtt_ms: float) -> PosePrediction:
        raise NotImplementedError(
            "Implement Kalman state update and prediction for pose matrices."
        )
