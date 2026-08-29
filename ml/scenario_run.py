"""Per-scenario collect + train + log driver.

Given a scenario name, stack, and a [start,end] epoch window (the k6 run window),
this:
  1. Collects that Prometheus window into ml/data_scenarios/{scenario}_{stack}.csv
     (consistent schema: timestamp + request_rate,error_rate,cpu,memory,p95).
  2. Trains XGBoost, LSTM and Prophet on that per-scenario dataset by
     monkeypatching features.load_stack to read the scenario CSV.
  3. Writes a timestamped per-run JSON log to
     results/scenarios/{ts}_{scenario}_{stack}.json with row count,
     P95 min/max/mean, and every model's RMSE/MAE/sMAPE.

Usage:
    python scenario_run.py --scenario spike --stack go \
        --start <epoch> --end <epoch> [--step 5] [--url http://localhost:9091]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os

import numpy as np
import pandas as pd

import config
import collect
import features
from evaluate import regression_metrics

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA_SCEN_DIR = os.path.join(HERE, "data_scenarios")
RESULTS_SCEN_DIR = os.path.join(ROOT, "results", "scenarios")
os.makedirs(DATA_SCEN_DIR, exist_ok=True)
os.makedirs(RESULTS_SCEN_DIR, exist_ok=True)

def _iso(epoch: float) -> str:
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).isoformat()

def run(scenario: str, stack: str, start: float, end: float,
        step: int, url: str) -> dict:

    df = collect.collect_stack(url, stack, start - 15, end + 10, step)
    if df.empty:
        raise SystemExit(f"[{scenario}/{stack}] Prometheus returned no rows")

    csv_path = os.path.join(DATA_SCEN_DIR, f"{scenario}_{stack}.csv")
    df.to_csv(csv_path, index=False)
    n_rows = len(df)
    p95 = df[config.TARGET_COL].astype(float)
    print(f"[{scenario}/{stack}] wrote {n_rows} rows -> {csv_path}  "
          f"p95 min/mean/max = {p95.min():.4f}/{p95.mean():.4f}/{p95.max():.4f}s")

    def _load_scenario(_stack: str) -> pd.DataFrame:
        d = pd.read_csv(csv_path)
        d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True)
        d = features.ensure_schema(d)
        return d.sort_values("timestamp").reset_index(drop=True)

    features.load_stack = _load_scenario

    import train_xgboost
    import train_lstm
    import train_prophet

    model_metrics: dict[str, dict] = {}

    try:
        r = train_xgboost.train_stack(stack, save=False)
        model_metrics["xgboost"] = {**r["metrics"],
                                    "n_test": int(len(r["y_test"]))}
        m = r["metrics"]
        print(f"  xgboost  RMSE={m['rmse']:.5f}  MAE={m['mae']:.5f}  "
              f"sMAPE={m['mape_or_smape']:.2f}%")
    except Exception as exc:
        model_metrics["xgboost"] = {"error": str(exc)}
        print(f"  xgboost FAILED: {exc}")

    try:
        r = train_lstm.train_stack(stack, epochs=80, batch_size=16, save=False)
        model_metrics["lstm"] = {**r["metrics"],
                                 "n_test": int(len(r["y_test"]))}
        m = r["metrics"]
        print(f"  lstm     RMSE={m['rmse']:.5f}  MAE={m['mae']:.5f}  "
              f"sMAPE={m['mape_or_smape']:.2f}%")
    except Exception as exc:
        model_metrics["lstm"] = {"error": str(exc)}
        print(f"  lstm FAILED: {exc}")

    try:
        r = train_prophet.train_stack(stack, save=False)
        model_metrics["prophet"] = {**r["metrics"],
                                    "n_test": int(len(r["y_test"]))}
        m = r["metrics"]
        print(f"  prophet  RMSE={m['rmse']:.5f}  MAE={m['mae']:.5f}  "
              f"sMAPE={m['mape_or_smape']:.2f}%")
    except Exception as exc:
        model_metrics["prophet"] = {"error": str(exc)}
        print(f"  prophet FAILED: {exc}")

    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log = {
        "timestamp": ts,
        "scenario": scenario,
        "stack": stack,
        "window": {"start": _iso(start), "end": _iso(end),
                   "start_epoch": start, "end_epoch": end,
                   "duration_min": round((end - start) / 60.0, 2)},
        "collection": {"step_seconds": step, "url": url, "rows": n_rows},
        "p95_seconds": {"min": float(p95.min()), "mean": float(p95.mean()),
                        "max": float(p95.max()), "std": float(p95.std())},
        "request_rate": {"min": float(df["request_rate"].min()),
                         "mean": float(df["request_rate"].mean()),
                         "max": float(df["request_rate"].max())},
        "models": model_metrics,
        "csv": os.path.relpath(csv_path, ROOT),
    }
    out = os.path.join(RESULTS_SCEN_DIR, f"{ts}_{scenario}_{stack}.json")
    with open(out, "w") as fh:
        json.dump(log, fh, indent=2)
    print(f"[{scenario}/{stack}] log -> {out}")
    return log

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--stack", required=True)
    ap.add_argument("--start", type=float, required=True)
    ap.add_argument("--end", type=float, required=True)
    ap.add_argument("--step", type=int, default=5)
    ap.add_argument("--url", default="http://localhost:9091")
    args = ap.parse_args()
    run(args.scenario, args.stack, args.start, args.end, args.step, args.url)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
