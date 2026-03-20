"""Ablation runner scaffold smoke tests."""

from tigas.orchestration.ablation_runner import HeadlessAblationRunner
from tigas.shared.types import ExperimentConfig


class _StubRunner(HeadlessAblationRunner):
    def run_one(self, config: ExperimentConfig) -> dict:
        return {
            "trace": config.trace_path,
            "codec": config.codec,
            "predictor": config.predictor,
            "network_profile": config.network_profile,
            "lod": config.default_lod,
        }


def test_run_matrix_aggregates_results() -> None:
    runner = _StubRunner()
    configs = [
        ExperimentConfig(
            trace_path="trace_a.json",
            codec="libx264",
            predictor="noop",
            network_profile="wifi",
            default_lod="full",
        ),
        ExperimentConfig(
            trace_path="trace_b.json",
            codec="av1_nvenc",
            predictor="kalman",
            network_profile="lte",
            default_lod="sampled_50",
        ),
    ]

    results = runner.run_matrix(configs)

    assert len(results) == 2
    assert results[0]["codec"] == "libx264"
    assert results[1]["predictor"] == "kalman"
