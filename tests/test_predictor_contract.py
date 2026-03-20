"""Predictor scaffold tests."""

import pytest

from tigas.intelligence.predictor_kalman import KalmanPosePredictor
from tigas.intelligence.predictor_noop import NoOpPosePredictor
from tigas.shared.types import UplinkDatagram


def _sample_datagram() -> UplinkDatagram:
    return UplinkDatagram(
        seq_id=1,
        timestamp_ms=10.0,
        camera_matrix_4x4=[1.0] * 16,
        requested_lod="full",
        target_bitrate_kbps=3000,
    )


def test_noop_predictor_passthrough() -> None:
    predictor = NoOpPosePredictor()
    prediction = predictor.predict(_sample_datagram(), rtt_ms=25.0)

    assert prediction.predicted_matrix_4x4 == [1.0] * 16
    assert prediction.prediction_horizon_ms == 25.0
    assert prediction.confidence == 1.0


def test_kalman_predictor_is_placeholder() -> None:
    predictor = KalmanPosePredictor()
    with pytest.raises(NotImplementedError):
        predictor.predict(_sample_datagram(), rtt_ms=25.0)
