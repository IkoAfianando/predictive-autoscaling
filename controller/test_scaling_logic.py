"""
Deterministic unit tests for the HYBRID auto-scaling controller logic in
scaling_logic.decide().

No infrastructure, no Docker/K8s, no clock: `now` is passed explicitly so every
scenario is fully reproducible on CPU.

Signal model under test (asymmetric / hybrid):
  * SCALE DOWN is checked FIRST and uses the MEASURED live P95 when provided
    (falls back to forecast when measured is None). Needs a sustained-low window
    AND a down cooldown. Steps down 1 replica at a time.
  * SCALE UP uses the FORECAST and requires a sustained-high window
    (up_sustain_seconds) before it fires (anti-flap hysteresis).
  * Otherwise -> no_change (within_band), streaks reset.

NOTE: decide() only mutates state.low_since / state.high_since. It does NOT set
last_scale_down_ts / current_replicas — the real controller does that. The tests
that simulate multiple ticks mimic the controller via `apply()`.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scaling_logic import ScalingConfig, DeploymentState, decide


def make_cfg(**kw) -> ScalingConfig:
    base = dict(
        scale_up_threshold_ms=200.0,
        scale_down_threshold_ms=80.0,
        min_replicas=1,
        max_replicas=10,
        cooldown_seconds=60.0,
        up_step_cap=4,
        up_sustain_seconds=0.0,
    )
    base.update(kw)
    return ScalingConfig(**base)

def make_state(current=3, **kw) -> DeploymentState:
    return DeploymentState(name="svc", stack="test", current_replicas=current, **kw)

def apply(state: DeploymentState, result, now: float):
    """Mimic what the real controller does after decide() returns."""
    new_replicas, action, _reason = result
    state.current_replicas = new_replicas
    if action == "scale_down":
        state.last_scale_down_ts = now
    elif action == "scale_up":
        state.last_scale_up_ts = now
    return action


def test_scale_up_requires_sustained_breach():
    cfg = make_cfg(up_sustain_seconds=30.0)
    state = make_state(current=3)

    new, action, reason = decide(state, predicted_p95_ms=250.0, cfg=cfg, now=0.0)
    assert action == "no_change"
    assert reason.startswith("high_not_sustained")
    assert new == 3
    assert state.high_since == 0.0

    new, action, reason = decide(state, predicted_p95_ms=250.0, cfg=cfg, now=15.0)
    assert action == "no_change"
    assert reason.startswith("high_not_sustained")

    new, action, reason = decide(state, predicted_p95_ms=250.0, cfg=cfg, now=30.0)
    assert action == "scale_up"
    assert reason == "predicted_breach"
    assert new > 3

def test_transient_breach_never_scales_up():
    """A momentary breach that falls back into the band must not accumulate."""
    cfg = make_cfg(up_sustain_seconds=30.0)
    state = make_state(current=3)

    _, action, _ = decide(state, predicted_p95_ms=250.0, cfg=cfg, now=0.0)
    assert action == "no_change"
    assert state.high_since == 0.0

    _, action, _ = decide(state, predicted_p95_ms=100.0, cfg=cfg, now=10.0)
    assert action == "no_change"
    assert state.high_since is None

    _, action, reason = decide(state, predicted_p95_ms=250.0, cfg=cfg, now=20.0)
    assert action == "no_change"
    assert reason.startswith("high_not_sustained")
    assert state.high_since == 20.0
    assert state.current_replicas == 3


def test_scale_down_uses_measured_over_high_forecast():
    """Core fix: forecast over-predicts (800ms) but measured is idle (10ms)
    -> the system is genuinely idle, so scale DOWN despite the high forecast."""
    cfg = make_cfg()

    state = make_state(current=3, low_since=940.0)
    new, action, reason = decide(
        state, predicted_p95_ms=800.0, cfg=cfg, now=1000.0, measured_p95_ms=10.0
    )
    assert action == "scale_down"
    assert reason == "sustained_low_measured"
    assert new == 2

    assert state.high_since is None

def test_high_measured_blocks_scale_down_even_if_forecast_low():
    """Reverse: measured is high (300ms) but forecast is low (10ms) -> we must
    NOT scale down; measured latency shows real load."""
    cfg = make_cfg()
    state = make_state(current=3, low_since=940.0)
    new, action, reason = decide(
        state, predicted_p95_ms=10.0, cfg=cfg, now=1000.0, measured_p95_ms=300.0
    )
    assert action == "no_change"
    assert reason == "within_band"
    assert new == 3


def test_low_not_sustained_then_scale_down():
    cfg = make_cfg()
    state = make_state(current=3)

    new, action, reason = decide(
        state, predicted_p95_ms=800.0, cfg=cfg, now=1000.0, measured_p95_ms=10.0
    )
    assert action == "no_change"
    assert reason.startswith("low_not_sustained")
    assert state.low_since == 1000.0
    assert new == 3

    new, action, reason = decide(
        state, predicted_p95_ms=800.0, cfg=cfg, now=1030.0, measured_p95_ms=10.0
    )
    assert action == "no_change"
    assert reason.startswith("low_not_sustained")

    new, action, reason = decide(
        state, predicted_p95_ms=800.0, cfg=cfg, now=1060.0, measured_p95_ms=10.0
    )
    assert action == "scale_down"
    assert reason == "sustained_low_measured"
    assert new == 2


def test_down_cooldown_blocks_second_scale_down():
    cfg = make_cfg()

    state = make_state(current=3, low_since=800.0, last_scale_down_ts=990.0)
    new, action, reason = decide(
        state, predicted_p95_ms=800.0, cfg=cfg, now=1000.0, measured_p95_ms=10.0
    )
    assert action == "no_change"
    assert reason == "down_cooldown_active"
    assert new == 3

    new, action, reason = decide(
        state, predicted_p95_ms=800.0, cfg=cfg, now=1050.0, measured_p95_ms=10.0
    )
    assert action == "scale_down"
    assert new == 2


def test_at_min_replicas_no_further_scale_down():
    cfg = make_cfg(min_replicas=1)
    state = make_state(current=1, low_since=800.0)
    new, action, reason = decide(
        state, predicted_p95_ms=800.0, cfg=cfg, now=1000.0, measured_p95_ms=10.0
    )
    assert action == "no_change"
    assert reason == "at_min_replicas"
    assert new == 1

def test_at_max_replicas_no_further_scale_up():
    cfg = make_cfg(max_replicas=10, up_sustain_seconds=0.0)
    state = make_state(current=10)
    new, action, reason = decide(state, predicted_p95_ms=800.0, cfg=cfg, now=1000.0)
    assert action == "no_change"
    assert reason == "at_max_replicas"
    assert new == 10


def test_end_to_end_no_false_scale_up_monotonic_down():
    """
    Idle-workload replay. The forecaster oscillates wildly (800 <-> 10) due to
    its known near-idle over-prediction, but the MEASURED P95 stays low the whole
    time. Expected: never a scale_up, replicas fall monotonically toward min.
    """
    cfg = make_cfg(up_sustain_seconds=30.0)
    state = make_state(current=5)

    actions = []
    replicas_trace = [state.current_replicas]
    forecast_cycle = [800.0, 10.0]

    now = 0.0
    for i in range(30):
        forecast = forecast_cycle[i % 2]
        result = decide(
            state, predicted_p95_ms=forecast, cfg=cfg, now=now, measured_p95_ms=10.0
        )
        action = apply(state, result, now)
        actions.append(action)
        replicas_trace.append(state.current_replicas)
        now += 30.0

    assert "scale_up" not in actions, f"unexpected scale_up in {actions}"

    for a, b in zip(replicas_trace, replicas_trace[1:]):
        assert b <= a, f"replicas went up: {replicas_trace}"

    assert state.current_replicas == cfg.min_replicas
    assert replicas_trace[0] == 5

    for a, b in zip(replicas_trace, replicas_trace[1:]):
        assert b in (a, a - 1)


def test_backward_compat_down_uses_forecast_when_no_measured():
    cfg = make_cfg()
    state = make_state(current=3, low_since=940.0)
    new, action, reason = decide(
        state, predicted_p95_ms=10.0, cfg=cfg, now=1000.0
    )
    assert action == "scale_down"
    assert reason == "sustained_low_measured"
    assert new == 2

def test_backward_compat_up_still_works_without_measured():
    cfg = make_cfg(up_sustain_seconds=0.0)
    state = make_state(current=2)
    new, action, reason = decide(state, predicted_p95_ms=800.0, cfg=cfg, now=1000.0)
    assert action == "scale_up"
    assert reason == "predicted_breach"
    assert new > 2


def test_config_rejects_inverted_thresholds():
    with pytest.raises(ValueError):
        make_cfg(scale_down_threshold_ms=200.0, scale_up_threshold_ms=200.0)

def test_config_rejects_bad_replica_bounds():
    with pytest.raises(ValueError):
        make_cfg(min_replicas=0)
    with pytest.raises(ValueError):
        make_cfg(min_replicas=5, max_replicas=3)
