"""
Standalone simulator for the predictive auto-scaling decision logic.

NO cluster, NO ML service, NO kubernetes/requests packages required. It feeds a
synthetic P95 latency time-series through the SAME scaling_logic.decide() that
the live controller uses, then quantifies the two headline thesis metrics:

  1. REACTION-TIME LEAD vs a reactive HPA baseline
     The ML forecast looks HORIZON_SECONDS (30s) ahead, so the predictive
     controller can scale up BEFORE the real P95 breaches the threshold. A
     reactive HPA only reacts AFTER the breach, plus its own stabilisation
     delay. The lead is the seconds saved.

  2. FALSE-POSITIVE RATE
     A scale-up is a false positive when the forecast said "breach coming" but
     the actual latency at the forecast horizon never crossed the threshold.
     Forecast noise makes this non-zero and realistic.

Outputs a per-stack timeline + an aggregate summary, and writes every synthetic
decision to logs/sim_decisions.jsonl (same schema as the live decision log, so
the Bab IV evaluation notebook can consume both identically).

Run:  python3 sim.py
"""

from __future__ import annotations

import json
import math
import os
import random
from dataclasses import asdict
from datetime import datetime, timezone

from scaling_logic import ScalingConfig, DeploymentState, Decision, decide


DT_SECONDS = 15.0
HORIZON_SECONDS = 30.0
LEAD_TICKS = int(round(HORIZON_SECONDS / DT_SECONDS))
REACTIVE_DELAY_TICKS = 2
N_TICKS = 120
BASE_EPOCH = 1_700_000_000.0
SEED = 42

CFG = ScalingConfig(
    scale_up_threshold_ms=200.0,
    scale_down_threshold_ms=80.0,
    min_replicas=1,
    max_replicas=10,
    cooldown_seconds=60.0,
    up_step_cap=4,
)

FORECAST_NOISE_STD = 0.06
FALSE_SPIKE_PROB = 0.03


def series_clean_spike(n: int) -> list[float]:
    """Idle -> sharp traffic spike -> plateau -> decay back to idle."""
    out = []
    for t in range(n):
        if t < 20:
            v = 60
        elif t < 30:
            v = 60 + (t - 20) * 22
        elif t < 55:
            v = 300
        elif t < 70:
            v = 300 - (t - 55) * 18
        else:
            v = 55
        out.append(float(max(30, v)))
    return out

def series_noisy_band(n: int) -> list[float]:
    """Latency hovers right around the up-threshold -> tests false positives."""
    rng = random.Random(SEED + 1)
    return [float(max(30, 190 + rng.gauss(0, 35))) for _ in range(n)]

def series_sustained_high(n: int) -> list[float]:
    """Heavy sustained load -> tests MAX_REPLICAS clamp & up_step_cap."""
    out = []
    for t in range(n):
        if t < 10:
            v = 70
        elif t < 20:
            v = 70 + (t - 10) * 45
        else:
            v = 520
        out.append(float(v))
    return out

def series_mostly_idle(n: int) -> list[float]:
    """Consistently low -> tests sustained-low scale-down to MIN with cooldown."""
    rng = random.Random(SEED + 3)
    out = []
    for t in range(n):
        v = 50 + rng.gauss(0, 8)
        if 40 <= t < 46:
            v = 120
        out.append(float(max(20, v)))
    return out

SCENARIOS = {
    "go":   series_clean_spike,
    "rust": series_noisy_band,
    "java": series_sustained_high,
    "node": series_mostly_idle,
}


def build_forecast(actual: list[float], rng: random.Random) -> list[float]:
    n = len(actual)
    fc = []
    for t in range(n):
        horizon = min(t + LEAD_TICKS, n - 1)
        v = actual[horizon] * (1 + rng.gauss(0, FORECAST_NOISE_STD))
        if rng.random() < FALSE_SPIKE_PROB:
            v *= 1.8
        fc.append(max(10.0, v))
    return fc

def horizon_actual(actual: list[float], t: int) -> float:
    return actual[min(t + LEAD_TICKS, len(actual) - 1)]


def reactive_first_scale_tick(actual: list[float]) -> int | None:
    """First tick a reactive HPA would have SCALED, i.e. breach + its delay."""
    for t in range(len(actual)):
        if actual[t] > CFG.scale_up_threshold_ms:
            return t + REACTIVE_DELAY_TICKS
    return None

def actual_first_breach_tick(actual: list[float]) -> int | None:
    for t in range(len(actual)):
        if actual[t] > CFG.scale_up_threshold_ms:
            return t
    return None


def now_iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()

def run_stack(stack: str, actual: list[float], forecast: list[float]) -> dict:
    state = DeploymentState(name=f"{stack}-order", stack=stack,
                            current_replicas=CFG.min_replicas)
    decisions: list[Decision] = []
    predictive_first_up_tick: int | None = None
    scale_ups = 0
    false_positives = 0

    for t in range(len(actual)):
        now = BASE_EPOCH + t * DT_SECONDS
        before = state.current_replicas
        predicted = forecast[t]
        new_replicas, action, reason = decide(state, predicted, CFG, now)
        if action != "no_change":
            state.current_replicas = new_replicas
            if action == "scale_up":
                state.last_scale_up_ts = now
                if predictive_first_up_tick is None:
                    predictive_first_up_tick = t
            elif action == "scale_down":
                state.last_scale_down_ts = now

        if action == "scale_up":
            scale_ups += 1

            if horizon_actual(actual, t) <= CFG.scale_up_threshold_ms:
                false_positives += 1

        d = Decision(
            ts=now_iso(now), epoch=now, service=state.name, stack=stack,
            predicted_p95_ms=round(predicted, 2), current_replicas=before,
            new_replicas=new_replicas, action=action, reason=reason,
            threshold_up_ms=CFG.scale_up_threshold_ms,
            threshold_down_ms=CFG.scale_down_threshold_ms, dry_run=True,
            extra={"tick": t, "actual_p95_ms": round(actual[t], 2),
                   "horizon_actual_p95_ms": round(horizon_actual(actual, t), 2)},
        )
        decisions.append(d)

    breach_tick = actual_first_breach_tick(actual)
    reactive_tick = reactive_first_scale_tick(actual)
    lead_seconds = None
    if predictive_first_up_tick is not None and reactive_tick is not None:
        lead_seconds = (reactive_tick - predictive_first_up_tick) * DT_SECONDS
    fp_rate = (false_positives / scale_ups) if scale_ups else 0.0

    return {
        "stack": stack,
        "decisions": decisions,
        "actual": actual,
        "forecast": forecast,
        "breach_tick": breach_tick,
        "predictive_first_up_tick": predictive_first_up_tick,
        "reactive_first_up_tick": reactive_tick,
        "lead_seconds": lead_seconds,
        "scale_ups": scale_ups,
        "false_positives": false_positives,
        "fp_rate": fp_rate,
        "final_replicas": state.current_replicas,
        "peak_replicas": max(d.new_replicas for d in decisions),
    }


def print_timeline(result: dict) -> None:
    stack = result["stack"]
    decisions = result["decisions"]
    print(f"\n=== stack={stack}  ({decisions[0].service}) "
          f"=================================================")
    print(f"  {'tick':>4} {'t(s)':>6} {'actual':>8} {'pred':>8} "
          f"{'repl':>5} {'->':>2} {'new':>4}  action/reason")
    prev_action = None
    shown = 0
    for d in decisions:

        interesting = d.action != "no_change" or d.reason not in ("within_band",)
        if d.action == "no_change" and d.reason == "within_band":
            continue
        if not interesting:
            continue
        t = d.extra["tick"]
        print(f"  {t:>4} {int(t*DT_SECONDS):>6} {d.extra['actual_p95_ms']:>8.1f} "
              f"{d.predicted_p95_ms:>8.1f} {d.current_replicas:>5} {'->':>2} "
              f"{d.new_replicas:>4}  {d.action}/{d.reason}")
        shown += 1
        prev_action = d.action
    if shown == 0:
        print("  (no notable transitions)")

def print_summary(results: list[dict]) -> None:
    print("\n" + "=" * 78)
    print("SUMMARY — predictive vs reactive")
    print("=" * 78)
    hdr = (f"{'stack':>6} {'breach@s':>9} {'predUp@s':>9} {'reactUp@s':>10} "
           f"{'lead(s)':>8} {'ups':>4} {'FP':>3} {'FPrate':>7} {'peak':>5}")
    print(hdr)
    print("-" * len(hdr))
    leads = []
    total_ups = 0
    total_fp = 0
    for r in results:
        breach_s = "-" if r["breach_tick"] is None else int(r["breach_tick"] * DT_SECONDS)
        pred_s = "-" if r["predictive_first_up_tick"] is None else int(r["predictive_first_up_tick"] * DT_SECONDS)
        react_s = "-" if r["reactive_first_up_tick"] is None else int(r["reactive_first_up_tick"] * DT_SECONDS)
        lead = r["lead_seconds"]
        if lead is not None:
            leads.append(lead)
        total_ups += r["scale_ups"]
        total_fp += r["false_positives"]
        print(f"{r['stack']:>6} {str(breach_s):>9} {str(pred_s):>9} {str(react_s):>10} "
              f"{('-' if lead is None else f'{lead:+.0f}'):>8} "
              f"{r['scale_ups']:>4} {r['false_positives']:>3} "
              f"{r['fp_rate']*100:>6.1f}% {r['peak_replicas']:>5}")
    print("-" * len(hdr))
    mean_lead = sum(leads) / len(leads) if leads else 0.0
    agg_fp = (total_fp / total_ups) if total_ups else 0.0
    print(f"\n  Mean reaction-time lead vs reactive : {mean_lead:+.1f} s "
          f"(positive = predictive scaled EARLIER)")
    print(f"  Aggregate false-positive rate       : {agg_fp*100:.1f}% "
          f"({total_fp}/{total_ups} scale-ups)")
    print(f"  Forecast horizon                    : {HORIZON_SECONDS:.0f} s "
          f"({LEAD_TICKS} ticks) | tick={DT_SECONDS:.0f}s | reactive delay="
          f"{REACTIVE_DELAY_TICKS} ticks")


def main() -> int:
    rng = random.Random(SEED)
    log_path = os.path.join(os.path.dirname(__file__), "logs", "sim_decisions.jsonl")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    results = []
    with open(log_path, "w") as fh:
        for stack, gen in SCENARIOS.items():
            actual = gen(N_TICKS)
            forecast = build_forecast(actual, random.Random(rng.randint(0, 1 << 30)))
            r = run_stack(stack, actual, forecast)
            results.append(r)
            for d in r["decisions"]:
                fh.write(json.dumps(asdict(d), separators=(",", ":")) + "\n")

    for r in results:
        print_timeline(r)
    print_summary(results)
    print(f"\nWrote {sum(len(r['decisions']) for r in results)} decisions to {log_path}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
