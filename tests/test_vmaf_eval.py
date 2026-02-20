from __future__ import annotations

from evaluation.vmaf_eval import summarize


def test_summarize_vmaf() -> None:
    payload = {
        "pooled_metrics": {
            "vmaf": {"mean": 93.2, "min": 80.4, "max": 97.0},
            "integer_motion": {"mean": 4.1},
        }
    }

    summary = summarize(payload, min_vmaf=80.0)

    assert summary["vmaf_mean"] == 93.2
    assert summary["vmaf_min"] == 80.4
    assert summary["vmaf_max"] == 97.0
    assert summary["motion_mean"] == 4.1
    assert summary["good_quality"] is True
