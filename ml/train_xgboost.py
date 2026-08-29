"""Train an XGBoost regressor per stack on the engineered lag features.

Config per SPEC/task: n_estimators=500, max_depth=6, learning_rate=0.1.
Predicts P95 latency HORIZON steps (30s) ahead.

If xgboost is not installed the script transparently falls back to
scikit-learn's HistGradientBoostingRegressor so the offline demo still runs;
a warning is printed and the model tag becomes "xgb_fallback".

Usage:
    python train_xgboost.py [--stack go] [--all]
"""
from __future__ import annotations

import argparse
import pickle

import numpy as np

import config
import features

try:
    from xgboost import XGBRegressor
    _HAVE_XGB = True
except Exception:
    _HAVE_XGB = False
    from sklearn.ensemble import HistGradientBoostingRegressor

MODEL_TAG = "xgboost" if _HAVE_XGB else "xgb_fallback"

def build_model():
    if _HAVE_XGB:
        return XGBRegressor(
            n_estimators=500, max_depth=6, learning_rate=0.1,
            subsample=0.9, colsample_bytree=0.9, objective="reg:squarederror",
            n_jobs=0, random_state=42,
        )

    return HistGradientBoostingRegressor(
        max_iter=500, max_depth=6, learning_rate=0.1, random_state=42,
    )

from evaluate import regression_metrics as _metrics

def train_stack(stack: str, save: bool = True) -> dict:
    """Train on one stack; return model + test predictions + metrics."""
    df = features.load_stack(stack)
    eng = features.engineer(df)
    sp = features.tabular_split(eng)

    model = build_model()
    fit_kwargs = {}
    if _HAVE_XGB:
        fit_kwargs = dict(eval_set=[(sp.X_val, sp.y_val)], verbose=False)
    model.fit(sp.X_train, sp.y_train, **fit_kwargs)

    y_pred = np.asarray(model.predict(sp.X_test), dtype="float64")
    y_test = np.asarray(sp.y_test, dtype="float64")
    m = _metrics(y_test, y_pred)

    if save:
        path = f"{config.MODELS_DIR}/{MODEL_TAG}_{stack}.pkl"
        with open(path, "wb") as fh:
            pickle.dump({"model": model, "features": sp.feature_names,
                         "tag": MODEL_TAG}, fh)

    return {"stack": stack, "model_tag": MODEL_TAG, "model": model,
            "y_test": y_test, "y_pred": y_pred, "metrics": m,
            "ts_test": sp.ts_test, "feature_names": sp.feature_names}

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stack", default=None)
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    if not _HAVE_XGB:
        print("WARNING: xgboost not installed — using sklearn "
              "HistGradientBoostingRegressor fallback.")

    stacks = config.STACKS if (args.all or not args.stack) else [args.stack]
    for stack in stacks:
        try:
            r = train_stack(stack)
        except FileNotFoundError:
            print(f"[{stack}] no data — run synthetic.py or collect.py")
            continue
        m = r["metrics"]
        print(f"[{stack}] {r['model_tag']}  "
              f"RMSE={m['rmse']:.5f}s  MAE={m['mae']:.5f}s  "
              f"sMAPE={m['mape_or_smape']:.2f}%")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
