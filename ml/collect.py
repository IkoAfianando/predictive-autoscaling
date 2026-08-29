"""Collect per-stack latency time-series from Prometheus.

For each stack it queries the P95 latency target plus four feature series
(request rate, error rate, CPU, memory) over a time range via the Prometheus
`/api/v1/query_range` HTTP API, aligns them on a common time index, and writes
`data/{stack}.csv` with columns: timestamp + features + target (p95).

Usage:
    python collect.py --url http://localhost:9090 --minutes 120 --step 15
    python collect.py --start 2026-07-13T00:00:00Z --end 2026-07-13T02:00:00Z

If Prometheus is unreachable, this script exits with a hint to run the offline
synthetic demo instead (see synthetic.py / README.md).
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys

import pandas as pd
import requests

import config

def _to_epoch(value: str | float | dt.datetime) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dt.datetime):
        return value.timestamp()

    return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()

def query_range(base_url: str, promql: str, start: float, end: float,
                step: int, timeout: int = 30) -> pd.Series:
    """Run one range query, return a float Series indexed by UTC timestamp."""
    resp = requests.get(
        base_url.rstrip("/") + "/api/v1/query_range",
        params={"query": promql, "start": start, "end": end, "step": f"{step}s"},
        timeout=timeout,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("status") != "success":
        raise RuntimeError(f"Prometheus error: {payload}")

    result = payload["data"]["result"]
    if not result:
        return pd.Series(dtype="float64")

    pairs = result[0]["values"]
    idx = pd.to_datetime([float(ts) for ts, _ in pairs], unit="s", utc=True)
    vals = pd.to_numeric([v for _, v in pairs], errors="coerce")
    return pd.Series(vals, index=idx, name="value")

def collect_stack(base_url: str, stack: str, start: float, end: float,
                  step: int) -> pd.DataFrame:
    """Collect all feature/target series for one stack into a tidy DataFrame."""
    frames = {}
    for col, promql in config.query_map(stack).items():
        try:
            frames[col] = query_range(base_url, promql, start, end, step)
        except Exception as exc:
            print(f"  [{stack}] '{col}' query failed: {exc}", file=sys.stderr)
            frames[col] = pd.Series(dtype="float64")


    frames = {k: v for k, v in frames.items() if not v.empty}
    df = pd.DataFrame(frames)
    if df.empty:
        return df

    df.index = pd.to_datetime(df.index, utc=True, errors="coerce")
    df = df[df.index.notna()]

    df = df.sort_index()
    df = df.resample(f"{step}s").mean()
    df = df.ffill(limit=4).bfill(limit=4)
    df = df.dropna(subset=[config.TARGET_COL])


    for col in config.FEATURE_COLS:
        if col not in df.columns:
            df[col] = 0.0
    df[config.FEATURE_COLS] = df[config.FEATURE_COLS].fillna(0.0)

    df = df[config.FEATURE_COLS]

    df.index.name = "timestamp"
    return df.reset_index()

def main() -> int:
    ap = argparse.ArgumentParser(description="Collect Prometheus latency series.")
    ap.add_argument("--url", default="http://localhost:9090",
                    help="Prometheus base URL (default: %(default)s)")
    ap.add_argument("--minutes", type=int, default=120,
                    help="Look back this many minutes from now (default 120).")
    ap.add_argument("--start", default=None, help="ISO8601 or epoch start.")
    ap.add_argument("--end", default=None, help="ISO8601 or epoch end.")
    ap.add_argument("--step", type=int, default=config.STEP_SECONDS,
                    help="Sample resolution in seconds (default 15).")
    ap.add_argument("--stacks", nargs="*", default=config.STACKS)
    args = ap.parse_args()

    if args.start and args.end:
        start, end = _to_epoch(args.start), _to_epoch(args.end)
    else:
        end = dt.datetime.now(dt.timezone.utc).timestamp()
        start = end - args.minutes * 60

    print(f"Collecting from {args.url}  step={args.step}s  "
          f"range={(end - start) / 60:.0f}min  stacks={args.stacks}")

    written = 0
    for stack in args.stacks:
        try:
            df = collect_stack(args.url, stack, start, end, args.step)
        except requests.exceptions.RequestException as exc:
            print(f"\nERROR: could not reach Prometheus at {args.url}: {exc}",
                  file=sys.stderr)
            print("Tip: run the offline demo instead → python synthetic.py",
                  file=sys.stderr)
            return 2
        if df.empty:
            print(f"  [{stack}] no data returned — skipping.")
            continue
        out = config.data_csv(stack)
        df.to_csv(out, index=False)
        written += 1
        print(f"  [{stack}] wrote {len(df)} rows → {out}")

    print(f"Done. {written}/{len(args.stacks)} stacks written to {config.DATA_DIR}")
    return 0 if written else 1

if __name__ == "__main__":
    raise SystemExit(main())
