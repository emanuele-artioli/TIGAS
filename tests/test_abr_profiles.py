"""ABR profile loading and policy selection tests."""

from pathlib import Path

from tigas.intelligence.abr_client import (
    build_client_abr_controller,
    load_abr_profile,
    resolve_abr_profile,
)


def test_resolve_abr_profile_by_name() -> None:
    resolved = resolve_abr_profile("throughput")
    assert resolved is not None
    assert resolved.name == "throughput.json"


def test_load_and_build_controllers_for_all_profiles() -> None:
    root = Path(__file__).resolve().parents[1]
    profile_paths = [
        root / "abr_profiles" / "throughput.json",
        root / "abr_profiles" / "bola.json",
        root / "abr_profiles" / "robustmpc.json",
    ]

    for profile_path in profile_paths:
        profile = load_abr_profile(profile_path)
        controller = build_client_abr_controller(profile)
        decision = controller.decide(
            throughput_kbps=2800.0,
            decode_latency_ms=12.0,
            buffer_level_ms=1800.0,
        )
        assert decision.target_bitrate_kbps > 0
        assert decision.requested_lod in {"full", "sampled_50", "quant_8bit", "adaptive"}
