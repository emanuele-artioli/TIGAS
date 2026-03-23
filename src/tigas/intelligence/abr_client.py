"""Client-side ABR controllers.

Client ABR estimates available throughput and chooses request-level knobs such
as target bitrate and preferred LOD. Policies are loaded from repository
profiles to keep experiments reproducible.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(slots=True)
class ClientAbrDecision:
    """ABR decision fields to include in outgoing control datagram."""

    target_bitrate_kbps: int
    requested_lod: str


class ClientAbrController(Protocol):
    """Policy interface implemented by concrete ABR algorithms."""

    def decide(
        self,
        throughput_kbps: float,
        decode_latency_ms: float,
        buffer_level_ms: float,
    ) -> ClientAbrDecision:
        """Return bitrate and LOD request based on client conditions."""


@dataclass(slots=True)
class AbrProfile:
    """Serializable ABR profile loaded from abr_profiles/*.json."""

    name: str
    algorithm: str
    bitrates_kbps: list[int]
    lods: list[str]
    safety_factor: float = 0.9
    ewma_alpha: float = 0.3
    min_bitrate_kbps: int = 300
    max_bitrate_kbps: int = 10000
    bola_v: float = 5.0
    bola_gamma: float = 5.0
    robustmpc_horizon: int = 3
    robustmpc_rebuffer_penalty: float = 4.3
    robustmpc_switch_penalty: float = 0.15

    @classmethod
    def from_dict(cls, payload: dict) -> "AbrProfile":
        bitrates = [int(max(1, value)) for value in payload.get("bitrates_kbps", [])]
        if not bitrates:
            raise ValueError("ABR profile requires non-empty bitrates_kbps.")

        lods = [str(value) for value in payload.get("lods", [])]
        if not lods:
            lods = ["full"] * len(bitrates)
        if len(lods) != len(bitrates):
            raise ValueError("ABR profile lods length must match bitrates_kbps length.")

        return cls(
            name=str(payload.get("name", "unnamed_abr")),
            algorithm=str(payload.get("algorithm", "throughput")).lower(),
            bitrates_kbps=sorted(bitrates),
            lods=lods,
            safety_factor=float(payload.get("safety_factor", 0.9)),
            ewma_alpha=float(payload.get("ewma_alpha", 0.3)),
            min_bitrate_kbps=int(payload.get("min_bitrate_kbps", 300)),
            max_bitrate_kbps=int(payload.get("max_bitrate_kbps", 10000)),
            bola_v=float(payload.get("bola_v", 5.0)),
            bola_gamma=float(payload.get("bola_gamma", 5.0)),
            robustmpc_horizon=int(payload.get("robustmpc_horizon", 3)),
            robustmpc_rebuffer_penalty=float(payload.get("robustmpc_rebuffer_penalty", 4.3)),
            robustmpc_switch_penalty=float(payload.get("robustmpc_switch_penalty", 0.15)),
        )


@dataclass(slots=True)
class ThroughputEstimator:
    """EWMA-smoothed throughput estimator based on observed delivered payload."""

    ewma_alpha: float = 0.3
    _estimate_kbps: float | None = None

    def observe(self, delivered_bytes: int, elapsed_s: float) -> float:
        safe_seconds = max(1e-6, elapsed_s)
        instantaneous_kbps = (max(0, delivered_bytes) * 8.0) / (safe_seconds * 1000.0)
        if self._estimate_kbps is None:
            self._estimate_kbps = instantaneous_kbps
        else:
            alpha = min(1.0, max(0.0, self.ewma_alpha))
            self._estimate_kbps = alpha * instantaneous_kbps + (1.0 - alpha) * self._estimate_kbps
        return self._estimate_kbps

    def current(self, fallback_kbps: float) -> float:
        if self._estimate_kbps is None:
            return max(1.0, fallback_kbps)
        return max(1.0, self._estimate_kbps)


class _BaseProfiledClientAbr:
    """Shared helpers for profile-driven ABR controllers."""

    def __init__(self, profile: AbrProfile) -> None:
        self.profile = profile
        self.bitrates = sorted(profile.bitrates_kbps)
        self.lods = profile.lods

    def _clamp(self, bitrate_kbps: float) -> int:
        bounded = min(self.profile.max_bitrate_kbps, max(self.profile.min_bitrate_kbps, bitrate_kbps))
        return int(round(bounded))

    def _select_nearest_lte(self, target_kbps: float) -> int:
        selected = self.bitrates[0]
        for bitrate in self.bitrates:
            if bitrate <= target_kbps:
                selected = bitrate
            else:
                break
        return selected

    def _lod_for(self, bitrate_kbps: int) -> str:
        index = self.bitrates.index(bitrate_kbps)
        return self.lods[index]


class ThroughputClientAbr(_BaseProfiledClientAbr):
    """Classic rate-based ABR with safety margin."""

    def decide(
        self,
        throughput_kbps: float,
        decode_latency_ms: float,
        buffer_level_ms: float,
    ) -> ClientAbrDecision:
        del decode_latency_ms
        del buffer_level_ms
        target = self._clamp(throughput_kbps * self.profile.safety_factor)
        selected = self._select_nearest_lte(target)
        return ClientAbrDecision(target_bitrate_kbps=selected, requested_lod=self._lod_for(selected))


class BolaClientAbr(_BaseProfiledClientAbr):
    """Buffer-based adaptation approximating BOLA objective ranking."""

    def decide(
        self,
        throughput_kbps: float,
        decode_latency_ms: float,
        buffer_level_ms: float,
    ) -> ClientAbrDecision:
        del decode_latency_ms
        safe_buffer_s = max(0.0, buffer_level_ms / 1000.0)
        best_bitrate = self.bitrates[0]
        best_score = -1e18

        for bitrate in self.bitrates:
            utility = self.profile.bola_v * (float(bitrate) / float(self.bitrates[0]))
            score = (safe_buffer_s * utility + self.profile.bola_gamma) / max(1.0, bitrate)
            if score > best_score:
                best_score = score
                best_bitrate = bitrate

        capped = min(best_bitrate, self._select_nearest_lte(throughput_kbps * 1.05))
        return ClientAbrDecision(target_bitrate_kbps=capped, requested_lod=self._lod_for(capped))


class RobustMpcClientAbr(_BaseProfiledClientAbr):
    """Short-horizon MPC-style selection using throughput history."""

    def __init__(self, profile: AbrProfile) -> None:
        super().__init__(profile)
        self._history = deque(maxlen=max(2, profile.robustmpc_horizon * 2))
        self._last_choice = self.bitrates[0]

    def _predict_throughput(self, fallback_kbps: float) -> float:
        if not self._history:
            return max(1.0, fallback_kbps)
        values = sorted(self._history)
        harmonic = len(values) / sum(1.0 / max(1.0, value) for value in values)
        return max(1.0, harmonic)

    def decide(
        self,
        throughput_kbps: float,
        decode_latency_ms: float,
        buffer_level_ms: float,
    ) -> ClientAbrDecision:
        del decode_latency_ms
        self._history.append(max(1.0, throughput_kbps))
        predicted = self._predict_throughput(throughput_kbps)

        best_bitrate = self.bitrates[0]
        best_value = -1e18
        buffer_s = max(0.0, buffer_level_ms / 1000.0)
        horizon = max(1, self.profile.robustmpc_horizon)

        for bitrate in self.bitrates:
            projected_download_s = (bitrate * horizon) / max(1.0, predicted)
            projected_rebuffer_s = max(0.0, projected_download_s - buffer_s)
            quality_term = float(bitrate) / float(self.bitrates[-1])
            switch_term = abs(float(bitrate - self._last_choice)) / float(self.bitrates[-1])
            objective = (
                quality_term
                - self.profile.robustmpc_rebuffer_penalty * projected_rebuffer_s
                - self.profile.robustmpc_switch_penalty * switch_term
            )
            if objective > best_value:
                best_value = objective
                best_bitrate = bitrate

        self._last_choice = best_bitrate
        return ClientAbrDecision(
            target_bitrate_kbps=best_bitrate,
            requested_lod=self._lod_for(best_bitrate),
        )


def resolve_abr_profile(profile_arg: str | None) -> Path | None:
    """Resolve ABR profile by absolute path, relative path, or profile name."""
    if not profile_arg:
        return None

    candidate = Path(profile_arg)
    if candidate.exists():
        return candidate

    project_root = Path(__file__).resolve().parents[3]
    by_name = project_root / "abr_profiles" / f"{profile_arg}.json"
    if by_name.exists():
        return by_name

    raise FileNotFoundError(
        f"Could not resolve ABR profile '{profile_arg}'. Checked path and {by_name}."
    )


def load_abr_profile(profile_path: Path) -> AbrProfile:
    """Load ABR profile JSON from disk."""
    with profile_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return AbrProfile.from_dict(payload)


def build_client_abr_controller(profile: AbrProfile) -> ClientAbrController:
    """Build concrete ABR controller from profile algorithm id."""
    algorithm = profile.algorithm.lower()
    if algorithm == "throughput":
        return ThroughputClientAbr(profile)
    if algorithm == "bola":
        return BolaClientAbr(profile)
    if algorithm == "robustmpc":
        return RobustMpcClientAbr(profile)
    raise ValueError(f"Unsupported ABR algorithm '{profile.algorithm}'.")
