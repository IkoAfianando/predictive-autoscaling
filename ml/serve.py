"""Prediction microservice consumed by the auto-scaling controller.

Exposes the best available per-stack model and serves the predicted P95 latency
30 seconds ahead:

    GET  /predict?stack=go            -> {"stack":"go","p95_pred":0.051,...}
    POST /predict  {"stacks":[...]}    -> batch predictions
    POST /predict  {"features": {...}} -> predict from an explicit feature row
    GET  /health                       -> {"status":"ok"}

The "best" model per stack is read from results/metrics.csv (lowest RMSE) when
present; otherwise it defaults to the tabular gradient-boosting model. LSTM /
Prophet are only used if their backends are installed and a saved model exists;
the portable tabular model (XGBoost or sklearn fallback) is always available and
is used as the safe default, so the controller always gets an answer.

Latest feature vectors are derived from data/{stack}.csv. In production, point
serve.py at a fresh CSV written by collect.py (e.g. via a sidecar cron) or
extend `_latest_features` to pull the live window from Prometheus.

Runs on FastAPI+uvicorn if available, else Flask.

Usage:
    python serve.py                 # http://0.0.0.0:8000
    uvicorn serve:asgi --port 8000  # if using the FastAPI app object
"""
from __future__ import annotations

import datetime as _dt
import os
import pickle
from functools import lru_cache

import numpy as np
import pandas as pd

import config
import features


PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "").strip()
LIVE_WINDOW_SECONDS = int(os.getenv("LIVE_WINDOW_SECONDS", "300"))
LIVE_STEP_SECONDS = int(os.getenv("LIVE_STEP_SECONDS", str(config.STEP_SECONDS)))
LIVE_MIN_ROWS = int(os.getenv("LIVE_MIN_ROWS", "6"))
LIVE = bool(PROMETHEUS_URL)


def _best_model_tag(stack: str) -> str:
    path = f"{config.RESULTS_DIR}/metrics.csv"
    if os.path.exists(path):
        df = pd.read_csv(path)
        sub = df[df["stack"] == stack]
        if not sub.empty:
            return str(sub.sort_values("rmse").iloc[0]["model"])
    return "xgboost"

@lru_cache(maxsize=None)
def _load_tabular(stack: str):
    """Return a fitted tabular model + its feature names for a stack.

    Loads a saved pickle if present, else trains one on the fly from the CSV.
    """
    for tag in ("xgboost", "xgb_fallback"):
        p = f"{config.MODELS_DIR}/{tag}_{stack}.pkl"
        if os.path.exists(p):
            with open(p, "rb") as fh:
                blob = pickle.load(fh)
            return blob["model"], blob["features"]

    import train_xgboost
    res = train_xgboost.train_stack(stack, save=True)
    return res["model"], res["feature_names"]

def _engineer_no_target(df: pd.DataFrame) -> pd.DataFrame:
    """Same feature construction as features.engineer() but WITHOUT building the
    supervised target `y` and WITHOUT the trailing dropna.

    features.engineer() drops the last HORIZON_STEPS rows (their future `y` is
    unknown) — but for *serving* those latest rows are exactly the ones we must
    predict FROM. So we reproduce the identical feature columns and keep the
    freshest row, filling warm-up NaNs with 0.0.
    """
    d = df.copy()
    d = features.add_time_features(d)
    d = features.add_lag_features(d, config.FEATURE_COLS, 8)
    d = features.add_rolling_features(d, config.TARGET_COL)
    return d

def _live_features(stack: str) -> tuple[np.ndarray, list[str], str, float]:
    """Build the freshest engineered feature row from LIVE Prometheus data.

    Reuses the exact same PromQL (ml/config.query_map) and tidy-frame assembly
    as collect.py, so the live features are apples-to-apples with the training
    features. Returns (x, feature_names, last_ts, live_p95_now_seconds).
    Raises on empty/insufficient data so callers can fall back to static.
    """
    import collect

    end = _dt.datetime.now(_dt.timezone.utc).timestamp()
    start = end - LIVE_WINDOW_SECONDS
    df = collect.collect_stack(PROMETHEUS_URL, stack, start, end, LIVE_STEP_SECONDS)
    if df.empty or len(df) < LIVE_MIN_ROWS:
        raise ValueError(f"live window too small for '{stack}' "
                         f"(rows={0 if df.empty else len(df)})")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = features.ensure_schema(df)
    df = df.sort_values("timestamp").reset_index(drop=True)

    eng = _engineer_no_target(df)
    feats = features.feature_columns(eng)
    row = eng[feats].iloc[[-1]].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    x = row.to_numpy(dtype="float32")
    last_ts = str(eng["timestamp"].iloc[-1])
    live_p95_now = float(df[config.TARGET_COL].iloc[-1])
    return x, feats, last_ts, live_p95_now

def _latest_features(stack: str) -> tuple[np.ndarray, list[str], str]:
    """Build the most recent engineered feature row for a stack (static CSV)."""
    df = features.load_stack(stack)
    eng = features.engineer(df)
    feats = features.feature_columns(eng)
    x = eng[feats].iloc[[-1]].to_numpy(dtype="float32")
    last_ts = str(eng["timestamp"].iloc[-1])
    return x, feats, last_ts

def predict_stack(stack: str) -> dict:
    if stack not in config.STACKS:
        raise ValueError(f"unknown stack '{stack}' (expected {config.STACKS})")
    model, feat_names = _load_tabular(stack)

    source = "static"
    live_p95_now = None
    live_error = None
    if LIVE:
        try:
            x, latest_feats, last_ts, live_p95_now = _live_features(stack)
            source = "live"
        except Exception as exc:
            live_error = str(exc)
            x, latest_feats, last_ts = _latest_features(stack)
    else:
        x, latest_feats, last_ts = _latest_features(stack)

    if feat_names and latest_feats != feat_names:
        row = pd.DataFrame(x, columns=latest_feats)
        x = row.reindex(columns=feat_names, fill_value=0.0).to_numpy("float32")
    pred = float(np.asarray(model.predict(x)).ravel()[0])
    out = {
        "stack": stack,
        "p95_pred": round(max(pred, 0.0), 6),
        "horizon_seconds": config.HORIZON_SECONDS,
        "model": _best_model_tag(stack),
        "as_of": last_ts,
        "source": source,
    }
    if live_p95_now is not None:
        out["live_p95_now"] = round(live_p95_now, 6)
    if live_error is not None:
        out["live_error"] = live_error
    return out

def predict_from_features(stack: str, feat: dict) -> dict:
    model, feat_names = _load_tabular(stack)
    row = pd.DataFrame([feat])
    x = row.reindex(columns=feat_names, fill_value=0.0).to_numpy("float32")
    pred = float(np.asarray(model.predict(x)).ravel()[0])
    return {"stack": stack, "p95_pred": round(max(pred, 0.0), 6),
            "horizon_seconds": config.HORIZON_SECONDS}


def _build_fastapi():
    from fastapi import FastAPI, HTTPException, Query
    from pydantic import BaseModel

    app = FastAPI(title="Predictive Auto-Scaling — P95 Forecast")

    class BatchReq(BaseModel):
        stacks: list[str] | None = None
        stack: str | None = None
        features: dict | None = None

    @app.get("/health")
    def health():
        return {"status": "ok", "stacks": config.STACKS}

    @app.get("/predict")
    def predict(stack: str = Query(...)):
        try:
            return predict_stack(stack)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except FileNotFoundError:
            raise HTTPException(status_code=503,
                                detail=f"no data for stack '{stack}'")

    @app.post("/predict")
    def predict_batch(req: BatchReq):
        if req.features is not None and req.stack:
            return predict_from_features(req.stack, req.features)
        stacks = req.stacks or config.STACKS
        return {"predictions": [predict_stack(s) for s in stacks]}

    return app

def _build_flask():
    from flask import Flask, jsonify, request

    app = Flask(__name__)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "stacks": config.STACKS})

    @app.get("/predict")
    def predict():
        stack = request.args.get("stack", "")
        try:
            return jsonify(predict_stack(stack))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.post("/predict")
    def predict_batch():
        body = request.get_json(silent=True) or {}
        if body.get("features") and body.get("stack"):
            return jsonify(predict_from_features(body["stack"], body["features"]))
        stacks = body.get("stacks") or config.STACKS
        return jsonify({"predictions": [predict_stack(s) for s in stacks]})

    return app

try:
    asgi = _build_fastapi()
except Exception:
    asgi = None

def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    if asgi is not None:
        import uvicorn
        print(f"Serving (FastAPI) on http://{args.host}:{args.port}")
        uvicorn.run(asgi, host=args.host, port=args.port)
    else:
        app = _build_flask()
        print(f"Serving (Flask) on http://{args.host}:{args.port}")
        app.run(host=args.host, port=args.port)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
