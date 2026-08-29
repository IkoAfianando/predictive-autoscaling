"""Train a Keras LSTM per stack to forecast P95 latency 30s ahead.

Architecture (per task): 2 stacked LSTM layers x 64 units, lookback 60s
(= LOOKBACK_STEPS samples at 15s), dense head -> 1 output.
Saves the model (models/lstm_{stack}.keras) and a train/val loss curve PNG
(results/lstm_loss_{stack}.png).

TensorFlow/Keras is optional. If it is not installed the script prints an
install hint and exits cleanly (return code 3) so partial pipeline runs work.

Usage:
    python train_lstm.py [--stack go] [--all] [--epochs 40]
"""
from __future__ import annotations

import argparse

import numpy as np

import config
import features

try:
    import tensorflow as tf
    from tensorflow.keras import layers, models
    _HAVE_TF = True
except Exception:
    _HAVE_TF = False

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from evaluate import regression_metrics as _metrics

def build_model(n_timesteps: int, n_features: int):
    model = models.Sequential([
        layers.Input(shape=(n_timesteps, n_features)),
        layers.LSTM(64, return_sequences=True),
        layers.LSTM(64),
        layers.Dense(32, activation="relu"),
        layers.Dense(1),
    ])


    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=5e-4, clipnorm=1.0),
        loss="mse", metrics=["mae"])
    return model

class _Scaler:
    """Per-feature standardization fit on the training window only (X: n,t,f)."""
    def fit(self, X):
        flat = X.reshape(-1, X.shape[-1])
        self.mu = flat.mean(axis=0)
        self.sd = flat.std(axis=0) + 1e-8
        return self

    def transform(self, X):
        return (X - self.mu) / self.sd

class _TargetScaler:
    """Standardize the 1-D target on TRAIN only; inverse for metrics.

    The p95 target has a huge dynamic range (idle ~0.002s to saturated ~10s).
    Feeding it raw makes the MSE gradient enormous and the LSTM diverges to
    NaN. Scaling the target to ~unit variance (and inverse-transforming the
    predictions before computing errors) is the key fix.
    """
    def fit(self, y):
        y = np.asarray(y, dtype="float64")
        self.mu = float(y.mean())
        self.sd = float(y.std()) + 1e-8
        return self

    def transform(self, y):
        return (np.asarray(y, dtype="float64") - self.mu) / self.sd

    def inverse(self, y):
        return np.asarray(y, dtype="float64") * self.sd + self.mu

def train_stack(stack: str, epochs: int = 40, batch_size: int = 32,
                save: bool = True) -> dict:
    if not _HAVE_TF:
        raise RuntimeError("tensorflow not available")

    df = features.load_stack(stack)
    sp = features.sequence_split(df)

    scaler = _Scaler().fit(sp.X_train)
    Xtr, Xva, Xte = (scaler.transform(x)
                     for x in (sp.X_train, sp.X_val, sp.X_test))

    yscaler = _TargetScaler().fit(sp.y_train)
    ytr_s = yscaler.transform(sp.y_train)
    yva_s = yscaler.transform(sp.y_val)

    model = build_model(Xtr.shape[1], Xtr.shape[2])
    es = tf.keras.callbacks.EarlyStopping(
        patience=8, restore_best_weights=True, monitor="val_loss")
    hist = model.fit(Xtr, ytr_s, validation_data=(Xva, yva_s),
                     epochs=epochs, batch_size=batch_size, verbose=0,
                     callbacks=[es])


    y_pred_s = model.predict(Xte, verbose=0).ravel()
    y_pred = np.clip(yscaler.inverse(y_pred_s), 0.0, None).astype("float64")
    y_test = np.asarray(sp.y_test, dtype="float64")
    m = _metrics(y_test, y_pred)

    if save:
        model.save(f"{config.MODELS_DIR}/lstm_{stack}.keras")
        _plot_loss(stack, hist.history)

    return {"stack": stack, "model_tag": "lstm", "model": model,
            "scaler": scaler, "yscaler": yscaler,
            "y_test": y_test, "y_pred": y_pred,
            "metrics": m, "ts_test": sp.ts_test}

def _plot_loss(stack: str, history: dict) -> str:
    plt.figure(figsize=(7, 4))
    plt.plot(history.get("loss", []), label="train loss")
    plt.plot(history.get("val_loss", []), label="val loss")
    plt.title(f"LSTM training — {stack}")
    plt.xlabel("epoch")
    plt.ylabel("MSE loss")
    plt.legend()
    plt.tight_layout()
    out = f"{config.RESULTS_DIR}/lstm_loss_{stack}.png"
    plt.savefig(out, dpi=120)
    plt.close()
    return out

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stack", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--epochs", type=int, default=40)
    args = ap.parse_args()

    if not _HAVE_TF:
        print("tensorflow/keras not installed — skipping LSTM training.")
        print("Install with:  pip install tensorflow   "
              "(tensorflow-macos on Apple Silicon)")
        return 3

    stacks = config.STACKS if (args.all or not args.stack) else [args.stack]
    for stack in stacks:
        try:
            r = train_stack(stack, epochs=args.epochs)
        except FileNotFoundError:
            print(f"[{stack}] no data — run synthetic.py or collect.py")
            continue
        m = r["metrics"]
        print(f"[{stack}] lstm  RMSE={m['rmse']:.5f}s  "
              f"MAE={m['mae']:.5f}s  sMAPE={m['mape_or_smape']:.2f}%")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
