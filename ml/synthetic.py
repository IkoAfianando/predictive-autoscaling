"""Generate realistic synthetic per-stack latency time-series.

Real cluster data does not exist yet, so this module fabricates plausible P95
latency series (daily seasonality + diurnal load + noise + occasional spikes)
together with correlated feature series (request rate, error rate, CPU, memory)
for each stack. This lets the whole pipeline run end-to-end today.

The CSV schema matches collect.py exactly:
    timestamp, request_rate, error_rate, cpu, memory, p95

Usage:
    python synthetic.py --hours 24 --step 15        # write data/{stack}.csv
"""
from __future__ import annotations

import argparse
import datetime as dt

import numpy as np
import pandas as pd

import config


STACK_PROFILE = {
    "go":   dict(base=0.045, sens=0.030, jitter=0.006, rps=90),
    "rust": dict(base=0.035, sens=0.022, jitter=0.005, rps=95),
    "java": dict(base=0.080, sens=0.060, jitter=0.012, rps=70),
    "node": dict(base=0.070, sens=0.055, jitter=0.011, rps=65),
}

def _diurnal(t_hours: np.ndarray) -> np.ndarray:
    """Load multiplier in [~0.3, ~1.0] peaking mid-afternoon, dip overnight."""

    daily = 0.5 * (1 + np.sin((t_hours - 9) / 24 * 2 * np.pi))
    harm = 0.15 * np.sin((t_hours - 3) / 12 * 2 * np.pi)
    return np.clip(0.35 + 0.65 * daily + harm, 0.2, 1.15)

def generate_stack(stack: str, hours: float, step: int,
                   end: dt.datetime | None = None,
                   seed: int | None = None) -> pd.DataFrame:
    prof = STACK_PROFILE.get(stack, STACK_PROFILE["go"])
    rng = np.random.default_rng(
        seed if seed is not None else abs(hash(stack)) % (2**31))

    end = end or dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    n = int(hours * 3600 / step)
    ts = pd.date_range(end=end, periods=n, freq=f"{step}s", tz="utc")

    hod = ts.hour + ts.minute / 60 + ts.second / 3600
    load = _diurnal(hod.to_numpy())

    request_rate = prof["rps"] * load * rng.normal(1.0, 0.05, n)
    request_rate = np.clip(request_rate, 1.0, None)

    cpu = np.clip(0.15 + 0.65 * load + rng.normal(0, 0.03, n), 0.02, 0.99)
    mem_drift = np.linspace(0, 40, n)
    memory = np.clip(180 + 220 * load + mem_drift + rng.normal(0, 8, n), 80, 500)

    p95 = prof["base"] + prof["sens"] * (load ** 1.6)
    noise = np.zeros(n)
    e = rng.normal(0, prof["jitter"], n)
    for i in range(1, n):
        noise[i] = 0.7 * noise[i - 1] + e[i]
    p95 = p95 + noise

    n_spikes = max(1, int(hours / 4))
    for _ in range(n_spikes):
        start = rng.integers(0, n)
        width = int(rng.integers(2, 8))
        mag = rng.uniform(2.0, 6.0) * prof["base"]
        end_i = min(n, start + width)
        decay = np.linspace(1.0, 0.2, end_i - start)
        p95[start:end_i] += mag * decay

    p95 = np.clip(p95, 0.001, None)

    hi = (p95 > np.quantile(p95, 0.9)).astype(float)
    error_rate = np.clip(
        0.002 + 0.05 * hi + rng.normal(0, 0.003, n), 0.0, 0.5)

    df = pd.DataFrame({
        "timestamp": ts,
        "request_rate": np.round(request_rate, 4),
        "error_rate": np.round(error_rate, 5),
        "cpu": np.round(cpu, 4),
        "memory": np.round(memory, 2),
        "p95": np.round(p95, 6),
    })
    return df

def generate_all(hours: float = 24, step: int = config.STEP_SECONDS,
                 write: bool = True, seed: int | None = None) -> dict[str, pd.DataFrame]:
    out = {}
    end = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    for i, stack in enumerate(config.STACKS):
        df = generate_stack(stack, hours, step, end=end,
                            seed=None if seed is None else seed + i)
        out[stack] = df
        if write:
            path = config.data_csv(stack)
            df.to_csv(path, index=False)
            print(f"  [{stack}] {len(df)} rows → {path}")
    return out

def main() -> int:
    ap = argparse.ArgumentParser(description="Generate synthetic latency data.")
    ap.add_argument("--hours", type=float, default=24)
    ap.add_argument("--step", type=int, default=config.STEP_SECONDS)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    print(f"Generating synthetic data: hours={args.hours} step={args.step}s")
    generate_all(hours=args.hours, step=args.step, seed=args.seed)
    print(f"Done → {config.DATA_DIR}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
