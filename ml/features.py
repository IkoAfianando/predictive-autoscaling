"""Feature engineering shared by every model.

Given a per-stack CSV (timestamp + features + p95) this builds:
  * lag features       t-1 .. t-k of the target and driver features
  * rolling statistics rolling mean/std of the target
  * time-of-day        hour + cyclical sin/cos encoding
  * the supervised target: p95 at t + HORIZON (default 30s ahead)

It then produces a time-ordered 70/15/15 train/val/test split (NO shuffle),
usable both as flat tabular matrices (XGBoost) and as 3-D sequence windows
(LSTM lookback).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

import config


def ensure_schema(df: pd.DataFrame) -> pd.DataFrame:
    """Guarantee a consistent, apple-to-apple feature schema across stacks.

    collect.py may omit a feature column when its PromQL returned no series
    (e.g. `error_rate` when there were zero requests / zero 5xx). Downstream
    feature engineering requires every column in ``config.FEATURE_COLS`` to be
    present and identical across all four stacks. Any missing feature is
    created filled with 0.0 so the models train on the same feature set.
    """
    for col in config.FEATURE_COLS:
        if col not in df.columns:
            df[col] = 0.0


    for col in config.FEATURE_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df[config.FEATURE_COLS] = (
        df[config.FEATURE_COLS]
        .replace([np.inf, -np.inf], np.nan)
        .fillna(0.0)
    )
    return df

def load_stack(stack: str) -> pd.DataFrame:
    """Load one stack's CSV with a parsed, sorted timestamp index."""
    df = pd.read_csv(config.data_csv(stack))
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = ensure_schema(df)
    return df.sort_values("timestamp").reset_index(drop=True)

def has_data() -> bool:
    """True if at least one stack CSV exists in data/."""
    return any(__import__("os").path.exists(config.data_csv(s))
               for s in config.STACKS)


def add_time_features(df: pd.DataFrame) -> pd.DataFrame:
    ts = df["timestamp"]
    hour = ts.dt.hour + ts.dt.minute / 60.0
    df["tod_hour"] = hour
    df["tod_sin"] = np.sin(2 * np.pi * hour / 24.0)
    df["tod_cos"] = np.cos(2 * np.pi * hour / 24.0)
    df["dow"] = ts.dt.dayofweek
    return df

def add_lag_features(df: pd.DataFrame, cols: list[str], k: int) -> pd.DataFrame:
    for col in cols:
        for lag in range(1, k + 1):
            df[f"{col}_lag{lag}"] = df[col].shift(lag)
    return df

def add_rolling_features(df: pd.DataFrame, col: str,
                         windows=(4, 8, 16)) -> pd.DataFrame:
    for w in windows:
        df[f"{col}_rmean{w}"] = df[col].shift(1).rolling(w).mean()
        df[f"{col}_rstd{w}"] = df[col].shift(1).rolling(w).std()
    return df

def engineer(df: pd.DataFrame, lags: int = 8,
             horizon_steps: int = config.HORIZON_STEPS) -> pd.DataFrame:
    """Full feature engineering + supervised target column `y`.

    `y` = target (p95) shifted HORIZON steps into the future.
    Rows with NaNs (warm-up lags / trailing horizon) are dropped.
    """
    df = df.copy()
    df = add_time_features(df)
    df = add_lag_features(df, config.FEATURE_COLS, lags)
    df = add_rolling_features(df, config.TARGET_COL)

    df["y"] = df[config.TARGET_COL].shift(-horizon_steps)

    df = df.dropna().reset_index(drop=True)
    return df

def feature_columns(df: pd.DataFrame) -> list[str]:
    """Every engineered column except identifiers and the target."""
    drop = {"timestamp", "y"}
    return [c for c in df.columns if c not in drop]


@dataclass
class Split:
    X_train: np.ndarray
    y_train: np.ndarray
    X_val: np.ndarray
    y_val: np.ndarray
    X_test: np.ndarray
    y_test: np.ndarray
    feature_names: list[str]

    ts_train: pd.Series | None = None
    ts_val: pd.Series | None = None
    ts_test: pd.Series | None = None

def _bounds(n: int, train=0.70, val=0.15) -> tuple[int, int]:
    i_tr = int(n * train)
    i_va = int(n * (train + val))
    return i_tr, i_va

def tabular_split(df: pd.DataFrame, train=0.70, val=0.15) -> Split:
    """Time-ordered 70/15/15 split of the engineered tabular frame."""
    feats = feature_columns(df)
    X = df[feats].to_numpy(dtype="float32")
    y = df["y"].to_numpy(dtype="float32")
    ts = df["timestamp"]
    i_tr, i_va = _bounds(len(df), train, val)
    return Split(
        X_train=X[:i_tr], y_train=y[:i_tr],
        X_val=X[i_tr:i_va], y_val=y[i_tr:i_va],
        X_test=X[i_va:], y_test=y[i_va:],
        feature_names=feats,
        ts_train=ts[:i_tr], ts_val=ts[i_tr:i_va], ts_test=ts[i_va:],
    )

def make_sequences(df: pd.DataFrame, lookback: int = config.LOOKBACK_STEPS,
                   horizon_steps: int = config.HORIZON_STEPS,
                   feature_cols: list[str] | None = None):
    """Build 3-D sequence windows for the LSTM.

    Returns (X, y, ts_target) where
        X          shape (samples, lookback, n_features)
        y          p95 `horizon_steps` after the end of each window
        ts_target  timestamp of each y
    Operates on RAW feature columns (before lag/rolling engineering) so the
    LSTM learns its own temporal structure.
    """
    d = add_time_features(df.copy())
    feature_cols = feature_cols or (config.FEATURE_COLS + ["tod_sin", "tod_cos"])
    values = d[feature_cols].to_numpy(dtype="float32")
    target = d[config.TARGET_COL].to_numpy(dtype="float32")
    ts = d["timestamp"].to_numpy()

    X, y, tt = [], [], []
    last = len(d) - horizon_steps
    for i in range(lookback, last):
        X.append(values[i - lookback:i])
        y.append(target[i + horizon_steps - 1])
        tt.append(ts[i + horizon_steps - 1])
    return (np.asarray(X, dtype="float32"),
            np.asarray(y, dtype="float32"),
            np.asarray(tt))

def sequence_split(df: pd.DataFrame, lookback: int = config.LOOKBACK_STEPS,
                   horizon_steps: int = config.HORIZON_STEPS,
                   train=0.70, val=0.15) -> Split:
    """Time-ordered 70/15/15 split of LSTM sequence windows."""
    X, y, tt = make_sequences(df, lookback, horizon_steps)
    i_tr, i_va = _bounds(len(X), train, val)
    return Split(
        X_train=X[:i_tr], y_train=y[:i_tr],
        X_val=X[i_tr:i_va], y_val=y[i_tr:i_va],
        X_test=X[i_va:], y_test=y[i_va:],
        feature_names=[f"seq[{lookback}]"],
        ts_train=pd.Series(tt[:i_tr]),
        ts_val=pd.Series(tt[i_tr:i_va]),
        ts_test=pd.Series(tt[i_va:]),
    )

if __name__ == "__main__":

    for s in config.STACKS:
        try:
            df = load_stack(s)
        except FileNotFoundError:
            print(f"[{s}] no CSV — run synthetic.py or collect.py")
            continue
        eng = engineer(df)
        sp = tabular_split(eng)
        print(f"[{s}] rows={len(df)} engineered={len(eng)} "
              f"feats={len(sp.feature_names)} "
              f"train/val/test={len(sp.y_train)}/{len(sp.y_val)}/{len(sp.y_test)}")
