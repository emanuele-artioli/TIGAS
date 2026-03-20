"""No-op pose predictor baseline.

This baseline returns the latest observed pose unchanged and is useful as a
 control group for measuring the incremental impact of prediction logic.
"""

from __future__ import annotations

from tigas.intelligence.predictor_base import PosePredictor
from tigas.shared.types import PosePrediction, UplinkDatagram


class NoOpPosePredictor(PosePredictor):
    """Passthrough predictor that performs no extrapolation."""

    def predict(self, datagram: UplinkDatagram, rtt_ms: float) -> PosePrediction:
        return PosePrediction(
            predicted_matrix_4x4=list(datagram.camera_matrix_4x4),
            prediction_horizon_ms=float(rtt_ms),
            confidence=1.0,
        )
