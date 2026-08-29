"""
Pure, dependency-free scaling decision logic for the predictive auto-scaler.

This module intentionally imports NOTHING external (no kubernetes, no requests)
so it can be exercised by sim.py on any machine and unit-tested in isolation.
Both predictive_controller.py and sim.py drive their decisions through decide().

Predictive philosophy
----------------------
The ML service forecasts the P95 latency 30s into the FUTURE. We scale UP the
moment the *forecast* crosses SCALE_UP_THRESHOLD, i.e. BEFORE the real P95 ever
breaches it. A reactive HPA can only respond after the breach has already
happened (and after its own metric-averaging window). The gap between those two
moments is the "reaction-time lead" this project measures.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class ScalingConfig:
    scale_up_threshold_ms: float = 200.0
    scale_down_threshold_ms: float = 80.0
    min_replicas: int = 1
    max_replicas: int = 10
    cooldown_seconds: float = 60.0
    up_step_cap: int = 4
    up_sustain_seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.scale_down_threshold_ms >= self.scale_up_threshold_ms:
            raise ValueError("scale_down_threshold must be < scale_up_threshold")
        if self.min_replicas < 1:
            raise ValueError("min_replicas must be >= 1")
        if self.max_replicas < self.min_replicas:
            raise ValueError("max_replicas must be >= min_replicas")


@dataclass
class DeploymentState:
    name: str
    stack: str
    current_replicas: int
    low_since: Optional[float] = None
    high_since: Optional[float] = None
    last_scale_down_ts: Optional[float] = None
    last_scale_up_ts: Optional[float] = None


@dataclass
class Decision:
    ts: str
    epoch: float
    service: str
    stack: str
    predicted_p95_ms: float
    current_replicas: int
    new_replicas: int
    action: str
    reason: str
    threshold_up_ms: float
    threshold_down_ms: float
    dry_run: bool = False
    extra: dict = field(default_factory=dict)

    def to_json_dict(self) -> dict:
        return asdict(self)


def compute_desired_replicas(predicted_p95_ms: float, current_replicas: int,
                             cfg: ScalingConfig) -> int:
    """
    HPA-style proportional target for the UP direction.

        desired = ceil(current * predicted / up_threshold)

    Scaling is proportional to how far the forecast overshoots the threshold,
    then clamped so we never add more than up_step_cap in one tick and never
    exceed max_replicas.
    """
    ratio = predicted_p95_ms / cfg.scale_up_threshold_ms
    desired = math.ceil(current_replicas * ratio)
    desired = max(desired, current_replicas + 1)
    desired = min(desired, current_replicas + cfg.up_step_cap)
    desired = min(desired, cfg.max_replicas)
    return desired

def decide(state: DeploymentState, predicted_p95_ms: float, cfg: ScalingConfig,
           now: float, measured_p95_ms: Optional[float] = None) -> tuple[int, str, str]:
    """
    Return (new_replicas, action, reason) given the current state and forecast.

    Hybrid signals (asymmetric, standard production practice):
      * SCALE UP uses the 30s-ahead FORECAST (predicted_p95_ms) so capacity is
        added proactively before the load actually arrives.
      * SCALE DOWN uses the MEASURED live P95 (measured_p95_ms) when provided, so
        removal of capacity is conservative and immune to the forecaster's known
        over-prediction during near-idle traffic. Falls back to the forecast when
        no measured value is supplied (backward compatible).

    Does NOT mutate `state` except for the sustained-low bookkeeping timestamps.
    """
    current = state.current_replicas
    down_signal = measured_p95_ms if measured_p95_ms is not None else predicted_p95_ms


    if down_signal < cfg.scale_down_threshold_ms:
        state.high_since = None
        if state.low_since is None:
            state.low_since = now
        low_duration = now - state.low_since
        cooldown_ok = (state.last_scale_down_ts is None
                       or (now - state.last_scale_down_ts) >= cfg.cooldown_seconds)

        if current <= cfg.min_replicas:
            return current, "no_change", "at_min_replicas"
        if low_duration < cfg.cooldown_seconds:
            return current, "no_change", (
                f"low_not_sustained({low_duration:.0f}s/"
                f"{cfg.cooldown_seconds:.0f}s)")
        if not cooldown_ok:
            return current, "no_change", "down_cooldown_active"

        return current - 1, "scale_down", "sustained_low_measured"

    if predicted_p95_ms > cfg.scale_up_threshold_ms:
        state.low_since = None
        if state.high_since is None:
            state.high_since = now
        high_duration = now - state.high_since
        if current >= cfg.max_replicas:
            return current, "no_change", "at_max_replicas"


        if high_duration < cfg.up_sustain_seconds:
            return current, "no_change", (
                f"high_not_sustained({high_duration:.0f}s/"
                f"{cfg.up_sustain_seconds:.0f}s)")
        desired = compute_desired_replicas(predicted_p95_ms, current, cfg)
        if desired > current:
            return desired, "scale_up", "predicted_breach"
        return current, "no_change", "at_max_replicas"

    state.low_since = None
    state.high_since = None
    return current, "no_change", "within_band"
