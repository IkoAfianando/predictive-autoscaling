"""Train a Prophet forecaster per stack on the P95 latency series.

Config per task: daily + weekly seasonality, changepoint_prior_scale=0.05.
Prophet is a pure time model (no exogenous lags): it is fit on the training
portion of the P95 series and back-tested on the held-out test timestamps,
which are >=30s in the future relative to training — matching the forecast
objective. Saves a forecast plot (results/prophet_{stack}.png).

Prophet is optional. If it is not installed the script prints an install hint
and exits cleanly (return code 3).

Usage:
    python train_prophet.py [--stack go] [--all]
"""
from __future__ import annotations

import argparse
import warnings

import numpy as np
import pandas as pd

import config
import features

warnings.filterwarnings("ignore")

try:
    from prophet import Prophet
    _HAVE_PROPHET = True
except Exception:
    _HAVE_PROPHET = False

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from evaluate import regression_metrics as _metrics

def train_stack(stack: str, save: bool = True) -> dict:
    if not _HAVE_PROPHET:
        raise RuntimeError("prophet not available")

    df = features.load_stack(stack)

    pdf = pd.DataFrame({
        "ds": df["timestamp"].dt.tz_convert("UTC").dt.tz_localize(None),
        "y": df[config.TARGET_COL].astype("float64"),
    })

    n = len(pdf)
    i_tr = int(n * 0.70)
    i_va = int(n * 0.85)
    train_df = pdf.iloc[:i_tr]
    test_df = pdf.iloc[i_va:]


    m = Prophet(
        changepoint_prior_scale=0.05,
        daily_seasonality=False,
        weekly_seasonality=False,
        yearly_seasonality=False,
    )
    m.add_seasonality(name="minutely", period=5.0 / (24 * 60), fourier_order=3)
    m.fit(train_df)

    forecast = m.predict(pdf[["ds"]])
    pred = forecast["yhat"].to_numpy()

    y_test = test_df["y"].to_numpy(dtype="float64")
    y_pred = np.clip(pred[i_va:], 0.0, None).astype("float64")
    metrics = _metrics(y_test, y_pred)

    if save:
        _plot(stack, m, forecast, pdf, i_va)

    return {"stack": stack, "model_tag": "prophet", "model": m,
            "y_test": y_test, "y_pred": y_pred, "metrics": metrics,
            "ts_test": test_df["ds"]}

def _plot(stack, model, forecast, pdf, i_va) -> str:
    plt.figure(figsize=(10, 4))
    plt.plot(pdf["ds"], pdf["y"], color="#555", lw=0.8, label="actual p95")
    plt.plot(forecast["ds"], forecast["yhat"], color="C0", lw=1.2,
             label="prophet yhat")
    plt.fill_between(forecast["ds"], forecast["yhat_lower"],
                     forecast["yhat_upper"], color="C0", alpha=0.2)
    plt.axvline(pdf["ds"].iloc[i_va], color="red", ls="--", lw=1,
                label="test split")
    plt.title(f"Prophet forecast — {stack}")
    plt.xlabel("time")
    plt.ylabel("p95 (s)")
    plt.legend(fontsize=8)
    plt.tight_layout()
    out = f"{config.RESULTS_DIR}/prophet_{stack}.png"
    plt.savefig(out, dpi=120)
    plt.close()
    return out

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stack", default=None)
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    if not _HAVE_PROPHET:
        print("prophet not installed — skipping Prophet training.")
        print("Install with:  pip install prophet")
        return 3

    stacks = config.STACKS if (args.all or not args.stack) else [args.stack]
    for stack in stacks:
        try:
            r = train_stack(stack)
        except FileNotFoundError:
            print(f"[{stack}] no data — run synthetic.py or collect.py")
            continue
        mm = r["metrics"]
        print(f"[{stack}] prophet  RMSE={mm['rmse']:.5f}s  "
              f"MAE={mm['mae']:.5f}s  sMAPE={mm['mape_or_smape']:.2f}%")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
