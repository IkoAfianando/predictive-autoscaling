"""Evaluate all models across all stacks and write comparison artifacts.

Produces:
  * results/metrics.csv     — RMSE / MAE / MAPE for each (model, stack) on test
  * results/comparison.png  — grouped bar chart (metric per model per stack)
  * results/transfer.csv    — cross-stack transfer (train on A, test on B)
  * results/transfer.png    — transfer RMSE heatmap

Models that are unavailable (missing TensorFlow / Prophet / XGBoost) are
skipped gracefully; whatever can run, runs.

Usage:
    python evaluate.py [--models xgboost lstm prophet] [--no-transfer]
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

import config
import features

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def regression_metrics(y_true, y_pred) -> dict:
    y_true = np.asarray(y_true, dtype="float64")
    y_pred = np.asarray(y_pred, dtype="float64")
    err = y_pred - y_true
    rmse = float(np.sqrt(np.mean(err ** 2)))
    mae = float(np.mean(np.abs(err)))


    denom = np.abs(y_true) + np.abs(y_pred)
    eps = 1e-6
    smape = float(np.mean(2.0 * np.abs(err) / np.maximum(denom, eps)) * 100.0)
    return {"rmse": rmse, "mae": mae, "mape_or_smape": smape}


def _run_xgboost(stack):
    import train_xgboost
    return train_xgboost.train_stack(stack, save=False)

def _run_lstm(stack):
    import train_lstm
    if not train_lstm._HAVE_TF:
        return None
    return train_lstm.train_stack(stack, save=False)

def _run_prophet(stack):
    import train_prophet
    if not train_prophet._HAVE_PROPHET:
        return None
    return train_prophet.train_stack(stack, save=False)

RUNNERS = {"xgboost": _run_xgboost, "lstm": _run_lstm, "prophet": _run_prophet}


def evaluate_all(models: list[str]) -> pd.DataFrame:
    rows = []
    for model in models:
        runner = RUNNERS[model]
        for stack in config.STACKS:
            try:
                res = runner(stack)
            except FileNotFoundError:
                print(f"[{model}/{stack}] no data — skipped")
                continue
            except Exception as exc:
                print(f"[{model}/{stack}] error: {exc}")
                continue
            if res is None:
                print(f"[{model}] backend not installed — skipped")
                break
            m = regression_metrics(res["y_test"], res["y_pred"])
            rows.append({"model": res["model_tag"], "stack": stack, **m})
            print(f"[{res['model_tag']}/{stack}]  RMSE={m['rmse']:.5f}s  "
                  f"MAE={m['mae']:.5f}s  sMAPE={m['mape_or_smape']:.2f}%")
    return pd.DataFrame(rows)

def transfer_test() -> pd.DataFrame:
    """Train XGBoost on stack A (train+val), test on stack B's test set."""
    import train_xgboost

    splits = {}
    for s in config.STACKS:
        try:
            eng = features.engineer(features.load_stack(s))
        except FileNotFoundError:
            continue
        splits[s] = features.tabular_split(eng)
    if not splits:
        return pd.DataFrame()

    rows = []
    for a, sp_a in splits.items():
        model = train_xgboost.build_model()
        X_fit = np.vstack([sp_a.X_train, sp_a.X_val])
        y_fit = np.concatenate([sp_a.y_train, sp_a.y_val])
        model.fit(X_fit, y_fit)
        for b, sp_b in splits.items():
            y_pred = model.predict(sp_b.X_test)
            m = regression_metrics(sp_b.y_test, y_pred)
            rows.append({"train_stack": a, "test_stack": b, **m})
            tag = "self" if a == b else "transfer"
            print(f"[transfer] train={a:5s} test={b:5s} "
                  f"RMSE={m['rmse']:.5f} ({tag})")
    return pd.DataFrame(rows)


def plot_comparison(df: pd.DataFrame, out: str) -> str:
    if df.empty:
        return ""
    metrics = ["rmse", "mae", "mape_or_smape"]
    titles = {"rmse": "RMSE (s)", "mae": "MAE (s)", "mape_or_smape": "sMAPE (%)"}
    fig, axes = plt.subplots(1, len(metrics), figsize=(14, 4.5))
    stacks = sorted(df["stack"].unique())
    modelset = sorted(df["model"].unique())
    x = np.arange(len(stacks))
    width = 0.8 / max(1, len(modelset))
    for ax, metric in zip(axes, metrics):
        for i, model in enumerate(modelset):
            vals = [df[(df.model == model) & (df.stack == s)][metric].mean()
                    for s in stacks]
            ax.bar(x + i * width, vals, width, label=model)
        ax.set_title(titles.get(metric, metric.upper()))
        ax.set_xticks(x + width * (len(modelset) - 1) / 2)
        ax.set_xticklabels(stacks)
        ax.grid(axis="y", alpha=0.3)
    axes[0].set_ylabel("error")
    axes[-1].legend(fontsize=8)
    fig.suptitle("Model comparison — P95 latency forecast (t+30s)")
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out

def plot_transfer(df: pd.DataFrame, out: str) -> str:
    if df.empty:
        return ""
    pivot = df.pivot(index="train_stack", columns="test_stack", values="rmse")
    fig, ax = plt.subplots(figsize=(6, 5))
    im = ax.imshow(pivot.values, cmap="viridis")
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels(pivot.columns)
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index)
    ax.set_xlabel("test stack")
    ax.set_ylabel("train stack")
    ax.set_title("Cross-stack transfer RMSE (XGBoost)")
    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            ax.text(j, i, f"{pivot.values[i, j]:.4f}", ha="center",
                    va="center", color="w", fontsize=8)
    fig.colorbar(im, ax=ax, label="RMSE")
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="*", default=["xgboost", "lstm", "prophet"])
    ap.add_argument("--no-transfer", action="store_true")
    args = ap.parse_args()

    print("=== Per-model evaluation ===")
    metrics_df = evaluate_all(args.models)
    if not metrics_df.empty:
        path = f"{config.RESULTS_DIR}/metrics.csv"
        metrics_df.to_csv(path, index=False)
        print(f"\nWrote {path}")
        p = plot_comparison(metrics_df, f"{config.RESULTS_DIR}/comparison.png")
        if p:
            print(f"Wrote {p}")
    else:
        print("No metrics produced (no data / no backends).")

    if not args.no_transfer:
        print("\n=== Cross-stack transfer (XGBoost) ===")
        tdf = transfer_test()
        if not tdf.empty:
            tpath = f"{config.RESULTS_DIR}/transfer.csv"
            tdf.to_csv(tpath, index=False)
            print(f"Wrote {tpath}")
            p = plot_transfer(tdf, f"{config.RESULTS_DIR}/transfer.png")
            if p:
                print(f"Wrote {p}")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
