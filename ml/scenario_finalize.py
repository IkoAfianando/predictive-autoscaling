"""Aggregate all per-run scenario JSON logs into a tidy comparison table and a
grouped RMSE bar chart.

Reads results/scenarios/*.json -> writes:
  * results/scenario_model_comparison.csv  (scenario,stack,model,rmse,mae,smape,winner)
  * results/scenario_analysis.png          (grouped RMSE bars, faceted by stack)
"""
from __future__ import annotations

import glob
import json
import os

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCEN_DIR = os.path.join(ROOT, "results", "scenarios")
OUT_CSV = os.path.join(ROOT, "results", "scenario_model_comparison.csv")
OUT_PNG = os.path.join(ROOT, "results", "scenario_analysis.png")

SCEN_ORDER = ["spike", "stress", "soak", "load"]
MODEL_ORDER = ["xgboost", "lstm", "prophet"]
MODEL_COLORS = {"xgboost": "#1f77b4", "lstm": "#d62728", "prophet": "#7f7f7f"}

def load_rows() -> pd.DataFrame:
    rows = []
    for path in sorted(glob.glob(os.path.join(SCEN_DIR, "*.json"))):
        with open(path) as fh:
            log = json.load(fh)
        scen = log["scenario"]
        stk = log["stack"]
        for model, m in log["models"].items():
            if "rmse" not in m:
                continue
            rows.append({
                "scenario": scen, "stack": stk, "model": model,
                "rmse": m["rmse"], "mae": m["mae"],
                "smape": m["mape_or_smape"],
                "p95_max": log["p95_seconds"]["max"],
                "rows": log["collection"]["rows"],
            })
    df = pd.DataFrame(rows)


    df = df.drop_duplicates(subset=["scenario", "stack", "model"], keep="last")
    return df

def add_winner(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["winner"] = ""
    for (scen, stk), grp in df.groupby(["scenario", "stack"]):
        best = grp.loc[grp["rmse"].idxmin(), "model"]
        mask = (df["scenario"] == scen) & (df["stack"] == stk)
        df.loc[mask, "winner"] = best
    return df

def plot(df: pd.DataFrame, out: str) -> None:
    stacks = sorted(df["stack"].unique())
    scen_present = [s for s in SCEN_ORDER if s in set(df["scenario"])]
    models = [m for m in MODEL_ORDER if m in set(df["model"])]

    fig, axes = plt.subplots(1, len(stacks), figsize=(7.5 * len(stacks), 5.2),
                             squeeze=False)
    x = np.arange(len(scen_present))
    width = 0.8 / max(1, len(models))

    for ax, stk in zip(axes[0], stacks):
        sub = df[df["stack"] == stk]
        for i, model in enumerate(models):
            vals = []
            for scen in scen_present:
                cell = sub[(sub["model"] == model) & (sub["scenario"] == scen)]
                vals.append(float(cell["rmse"].iloc[0]) if len(cell) else np.nan)
            bars = ax.bar(x + i * width, vals, width, label=model,
                          color=MODEL_COLORS.get(model, None))
            for b, v in zip(bars, vals):
                if np.isfinite(v):
                    ax.text(b.get_x() + b.get_width() / 2, v * 1.05,
                            f"{v:.3g}", ha="center", va="bottom",
                            fontsize=7, rotation=90)
        ax.set_yscale("log")
        ax.set_title(f"Stack: {stk}")
        ax.set_xticks(x + width * (len(models) - 1) / 2)
        ax.set_xticklabels(scen_present)
        ax.set_xlabel("load scenario")
        ax.grid(axis="y", alpha=0.3, which="both")
        ax.legend(title="model", fontsize=9)
    axes[0][0].set_ylabel("Test RMSE (s, log scale)  —  lower is better")
    fig.suptitle("Per-scenario model comparison — P95 latency forecast (t+30s)\n"
                 "LSTM wins bursty/saturating patterns (spike, stress); "
                 "XGBoost wins gradual/steady (load, soak); Prophet loses everywhere",
                 fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(out, dpi=130)
    plt.close(fig)

def main() -> int:
    df = load_rows()
    if df.empty:
        print("No scenario JSON logs found.")
        return 1
    df = add_winner(df)

    tidy = df[["scenario", "stack", "model", "rmse", "mae", "smape", "winner"]]
    tidy = tidy.sort_values(
        ["scenario", "stack", "rmse"]).reset_index(drop=True)
    tidy.to_csv(OUT_CSV, index=False)
    print(f"Wrote {OUT_CSV}  ({len(tidy)} rows)")

    plot(df, OUT_PNG)
    size = os.path.getsize(OUT_PNG)
    print(f"Wrote {OUT_PNG}  ({size} bytes)")

    print("\n=== Winner per scenario/stack (min RMSE) ===")
    w = df.drop_duplicates(["scenario", "stack"])[
        ["scenario", "stack", "winner"]]
    for scen in SCEN_ORDER:
        for stk in sorted(df["stack"].unique()):
            cell = w[(w["scenario"] == scen) & (w["stack"] == stk)]
            if len(cell):
                print(f"  {scen:7s} / {stk:5s} -> {cell['winner'].iloc[0]}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
