#!/usr/bin/env python3
"""Canonical, reproducible re-evaluation of every forecasting claim in the paper.

One script, one run, three experiments, all outputs written to data/:

  E1 aggregate   4 models x 4 stacks on the wave dataset. Recurrent models are
                 retrained under SEEDS initializations -> mean, std, and
                 Wilcoxon / Diebold-Mariano significance for GRU vs LSTM.
  E2 per-scenario 4 models x 4 load scenarios x {go, java}. Reports the
                 deep-learning-versus-baseline win tally AND how stable that
                 tally is across seeds, since these splits are small.
  E3 transfer    train on stack A, test on stack B, scored with sMAPE so the
                 comparison is scale free.

Everything the paper reports about forecasting comes from this file.
"""
from __future__ import annotations
import os, sys, csv, json, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

ROOT = "/Users/ikoafian/LEARN/RISET/predictive-autoscaling-thesis"
OUT = f"{ROOT}/2026-09-12_paper-revisi"
sys.path.insert(0, f"{ROOT}/ml")

import config, features                      # noqa: E402
from evaluate import regression_metrics      # noqa: E402

STACKS = ["go", "rust", "java", "node"]
SCENARIOS = ["spike", "soak", "stress", "load"]
SCEN_STACKS = ["go", "java"]
SEEDS = list(range(10))
EPOCHS, BATCH = 40, 32
DL = {"gru", "lstm"}


# ------------------------------------------------------------------ scaling
class _S:
    def fit(self, X):
        f = X.reshape(-1, X.shape[-1]); self.mu = f.mean(0); self.sd = f.std(0)
        self.sd[self.sd == 0] = 1.0; return self
    def tf(self, X): return (X - self.mu) / self.sd


class _T:
    def fit(self, y):
        self.mu = float(np.mean(y)); self.sd = float(np.std(y)) or 1.0; return self
    def tf(self, y): return (np.asarray(y, "float64") - self.mu) / self.sd
    def inv(self, y): return y * self.sd + self.mu


def load_df(path):
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = features.ensure_schema(df)
    return df.sort_values("timestamp").reset_index(drop=True)


# ------------------------------------------------------------------- models
def fit_recurrent(kind, eng, seed):
    import tensorflow as tf
    from tensorflow import keras
    keras.utils.set_random_seed(seed)
    sp = features.sequence_split(eng)
    if len(sp.y_test) < 3 or len(sp.y_train) < 10:
        return None
    xs, ys = _S().fit(sp.X_train), _T().fit(sp.y_train)
    L = keras.layers.GRU if kind == "gru" else keras.layers.LSTM
    m = keras.Sequential([
        keras.layers.Input(shape=(sp.X_train.shape[1], sp.X_train.shape[2])),
        L(64, return_sequences=True), L(64),
        keras.layers.Dense(32, activation="relu"), keras.layers.Dense(1)])
    m.compile(optimizer=keras.optimizers.Adam(1e-3), loss="mse")
    m.fit(xs.tf(sp.X_train), ys.tf(sp.y_train),
          validation_data=(xs.tf(sp.X_val), ys.tf(sp.y_val)),
          epochs=EPOCHS, batch_size=BATCH, verbose=0,
          callbacks=[keras.callbacks.EarlyStopping(patience=8, monitor="val_loss",
                                                   restore_best_weights=True)])
    p = np.clip(ys.inv(m.predict(xs.tf(sp.X_test), verbose=0).ravel()), 0, None)
    keras.backend.clear_session()
    return np.asarray(sp.y_test, "float64"), p.astype("float64")


def fit_xgboost(eng, seed=0, return_model=False):
    from xgboost import XGBRegressor
    sp = features.tabular_split(eng)
    if len(sp.y_test) < 3:
        return None
    m = XGBRegressor(n_estimators=400, max_depth=5, learning_rate=0.05,
                     subsample=0.9, colsample_bytree=0.9,
                     objective="reg:squarederror", random_state=seed, n_jobs=4)
    m.fit(sp.X_train, sp.y_train)
    p = np.clip(np.asarray(m.predict(sp.X_test), "float64"), 0, None)
    if return_model:
        return m, sp
    return np.asarray(sp.y_test, "float64"), p


def fit_prophet(df, eng):
    try:
        from prophet import Prophet
    except Exception:
        return None
    sp = features.tabular_split(eng)
    n = len(eng); i_tr = int(n * 0.85)
    tr = eng.iloc[:i_tr]; te = eng.iloc[i_tr:]
    if len(te) < 3:
        return None
    m = Prophet(daily_seasonality=False, weekly_seasonality=False, yearly_seasonality=False)
    m.fit(pd.DataFrame({"ds": tr["timestamp"].dt.tz_localize(None), "y": tr["y"]}))
    fc = m.predict(pd.DataFrame({"ds": te["timestamp"].dt.tz_localize(None)}))
    return (np.asarray(te["y"], "float64"),
            np.clip(np.asarray(fc["yhat"], "float64"), 0, None))


# --------------------------------------------------------------- statistics
def dm_test(e1, e2, h):
    from scipy import stats
    d = e1 ** 2 - e2 ** 2; T = len(d)
    if T < 5: return float("nan"), float("nan")
    db = float(np.mean(d)); dc = d - db
    lrv = float(np.dot(dc, dc) / T)
    for k in range(1, h):
        lrv += 2.0 * float(np.dot(dc[k:], dc[:-k]) / T)
    if lrv <= 0: return float("nan"), float("nan")
    dm = db / np.sqrt(lrv / T)
    hln = dm * np.sqrt((T + 1 - 2 * h + h * (h - 1) / T) / T)
    return float(hln), float(2 * (1 - stats.t.cdf(abs(hln), df=T - 1)))


def wilcox(a, b):
    from scipy import stats
    a, b = np.asarray(a, "float64"), np.asarray(b, "float64")
    if len(a) < 3 or np.allclose(a, b): return float("nan"), float("nan")
    r = stats.wilcoxon(a, b, alternative="two-sided")
    return float(r.statistic), float(r.pvalue)


def rmse(y, p): return float(np.sqrt(np.mean((p - y) ** 2)))


# ================================================================== E1
def experiment_1():
    print("\n### E1 aggregate (4 models x 4 stacks)", flush=True)
    rows, preds = [], {}
    for s in STACKS:
        eng = features.engineer(load_df(config.data_csv(s)))
        for kind in ("gru", "lstm"):
            runs = []
            for seed in SEEDS:
                r = fit_recurrent(kind, eng, seed)
                if r is None: continue
                y, p = r; m = regression_metrics(y, p)
                rows.append({"model": kind, "stack": s, "seed": seed,
                             "rmse": round(m["rmse"], 5), "mae": round(m["mae"], 5),
                             "smape": round(m["mape_or_smape"], 2)})
                runs.append(p)
            if runs:
                preds[(kind, s)] = (y, np.mean(np.vstack(runs), 0))
            print(f"  {kind}/{s} done ({len(runs)} seeds)", flush=True)
        r = fit_xgboost(eng)
        if r:
            y, p = r; m = regression_metrics(y, p)
            rows.append({"model": "xgboost", "stack": s, "seed": 0, "rmse": round(m["rmse"], 5),
                         "mae": round(m["mae"], 5), "smape": round(m["mape_or_smape"], 2)})
            preds[("xgboost", s)] = (y, p)
        r = fit_prophet(load_df(config.data_csv(s)), eng)
        if r:
            y, p = r; m = regression_metrics(y, p)
            rows.append({"model": "prophet", "stack": s, "seed": 0, "rmse": round(m["rmse"], 5),
                         "mae": round(m["mae"], 5), "smape": round(m["mape_or_smape"], 2)})
        print(f"  baselines/{s} done", flush=True)

    _write("e1_metrics_per_seed.csv", rows)
    summ = []
    for mdl in ("gru", "lstm", "xgboost", "prophet"):
        for s in STACKS:
            v = [r["rmse"] for r in rows if r["model"] == mdl and r["stack"] == s]
            if v:
                summ.append({"model": mdl, "stack": s, "n_runs": len(v),
                             "rmse_mean": round(float(np.mean(v)), 4),
                             "rmse_std": round(float(np.std(v, ddof=1)) if len(v) > 1 else 0.0, 4)})
    _write("e1_summary.csv", summ)

    sig = []
    for s in STACKS:
        g = [r["rmse"] for r in rows if r["model"] == "gru" and r["stack"] == s]
        l = [r["rmse"] for r in rows if r["model"] == "lstm" and r["stack"] == s]
        _, wp = wilcox(g, l)
        yg, pg = preds[("gru", s)]; yl, pl = preds[("lstm", s)]
        n = min(len(yg), len(yl))
        dm, dp = dm_test(pg[-n:] - yg[-n:], pl[-n:] - yl[-n:], config.HORIZON_STEPS)
        sig.append({"stack": s, "gru_rmse": round(float(np.mean(g)), 4),
                    "lstm_rmse": round(float(np.mean(l)), 4),
                    "seed_wilcoxon_p": round(wp, 4), "dm_stat": round(dm, 3),
                    "dm_p": round(dp, 4),
                    "sig_5pct": "yes" if wp == wp and wp < 0.05 else "no"})
    _write("e1_significance.csv", sig)
    return summ, sig


# ================================================================== E2
def experiment_2():
    print("\n### E2 per-scenario (4 scenarios x 2 stacks)", flush=True)
    rows = []
    for scen in SCENARIOS:
        for s in SCEN_STACKS:
            path = f"{ROOT}/ml/data_scenarios/{scen}_{s}.csv"
            if not os.path.exists(path): continue
            eng = features.engineer(load_df(path))
            for kind in ("gru", "lstm"):
                for seed in SEEDS:
                    r = fit_recurrent(kind, eng, seed)
                    if r is None: continue
                    y, p = r
                    rows.append({"scenario": scen, "stack": s, "model": kind, "seed": seed,
                                 "rmse": round(rmse(y, p), 5), "n_test": len(y)})
            r = fit_xgboost(eng)
            if r:
                y, p = r
                rows.append({"scenario": scen, "stack": s, "model": "xgboost", "seed": 0,
                             "rmse": round(rmse(y, p), 5), "n_test": len(y)})
            r = fit_prophet(load_df(path), eng)
            if r:
                y, p = r
                rows.append({"scenario": scen, "stack": s, "model": "prophet", "seed": 0,
                             "rmse": round(rmse(y, p), 5), "n_test": len(y)})
            print(f"  {scen}/{s} done", flush=True)
    _write("e2_scenario_per_seed.csv", rows)

    # win tally: best deep-learning mean vs best baseline, per (scenario, stack)
    tally, per_seed_tally = [], []
    for scen in SCENARIOS:
        for s in SCEN_STACKS:
            sub = [r for r in rows if r["scenario"] == scen and r["stack"] == s]
            if not sub: continue
            def mean_of(m):
                v = [r["rmse"] for r in sub if r["model"] == m]
                return float(np.mean(v)) if v else float("inf")
            dl_best = min(mean_of("gru"), mean_of("lstm"))
            bl_best = min(mean_of("xgboost"), mean_of("prophet"))
            n_test = max([r["n_test"] for r in sub], default=0)
            tally.append({"scenario": scen, "stack": s, "n_test": n_test,
                          "dl_rmse": round(dl_best, 4), "baseline_rmse": round(bl_best, 4),
                          "winner": "deep_learning" if dl_best < bl_best else "baseline"})
            # stability: how many seeds would have given a DL win
            wins = 0
            for seed in SEEDS:
                dl = min([r["rmse"] for r in sub if r["model"] in DL and r["seed"] == seed] or [np.inf])
                if dl < bl_best: wins += 1
            per_seed_tally.append({"scenario": scen, "stack": s,
                                   "dl_wins_in_seeds": wins, "of_seeds": len(SEEDS)})
    _write("e2_win_tally.csv", tally)
    _write("e2_win_stability.csv", per_seed_tally)
    return tally, per_seed_tally


# ================================================================== E3
def experiment_3():
    print("\n### E3 cross-stack transfer", flush=True)
    engs = {s: features.engineer(load_df(config.data_csv(s))) for s in STACKS}
    models = {}
    for s in STACKS:
        models[s] = fit_xgboost(engs[s], return_model=True)
    rows = []
    for a in STACKS:
        m, _ = models[a]
        for b in STACKS:
            sp = features.tabular_split(engs[b])
            p = np.clip(np.asarray(m.predict(sp.X_test), "float64"), 0, None)
            y = np.asarray(sp.y_test, "float64")
            mm = regression_metrics(y, p)
            rows.append({"train_stack": a, "test_stack": b,
                         "rmse": round(mm["rmse"], 4), "smape": round(mm["mape_or_smape"], 2)})
    _write("e3_transfer.csv", rows)
    ratios = []
    for b in STACKS:
        self_s = next(r["smape"] for r in rows if r["train_stack"] == b and r["test_stack"] == b)
        cross = [r["smape"] for r in rows if r["test_stack"] == b and r["train_stack"] != b]
        ratios.append({"test_stack": b, "self_smape": self_s,
                       "cross_smape_mean": round(float(np.mean(cross)), 2),
                       "degradation_ratio": round(float(np.mean(cross)) / self_s, 3)})
    _write("e3_transfer_ratio.csv", ratios)
    return rows, ratios


def _write(name, rows):
    os.makedirs(f"{OUT}/data", exist_ok=True)
    with open(f"{OUT}/data/{name}", "w", newline="") as fo:
        w = csv.DictWriter(fo, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    print(f"    -> data/{name} ({len(rows)} rows)", flush=True)


def main():
    summ, sig = experiment_1()
    tally, stab = experiment_2()
    tr, ratios = experiment_3()

    print("\n================ CANONICAL RESULTS ================")
    print("\nE1 RMSE (mean +/- std):")
    for r in summ:
        print(f"  {r['model']:8s} {r['stack']:5s} {r['rmse_mean']:.4f} +/- {r['rmse_std']:.4f} (n={r['n_runs']})")
    print("\nE1 GRU vs LSTM:")
    for r in sig:
        print(f"  {r['stack']:5s} GRU={r['gru_rmse']:.4f} LSTM={r['lstm_rmse']:.4f} "
              f"seedWilcoxon p={r['seed_wilcoxon_p']:.4f} DM p={r['dm_p']:.4f} sig={r['sig_5pct']}")
    print("\nE2 per-scenario winners:")
    dl = sum(1 for t in tally if t["winner"] == "deep_learning")
    for t in tally:
        st = next(x for x in stab if x["scenario"] == t["scenario"] and x["stack"] == t["stack"])
        print(f"  {t['scenario']:7s}/{t['stack']:5s} n_test={t['n_test']:2d} "
              f"DL={t['dl_rmse']:.4f} base={t['baseline_rmse']:.4f} -> {t['winner']:13s} "
              f"(DL wins in {st['dl_wins_in_seeds']}/{st['of_seeds']} seeds)")
    print(f"  TALLY: deep learning wins {dl} of {len(tally)}")
    print("\nE3 transfer degradation (cross / self sMAPE):")
    for r in ratios:
        print(f"  test={r['test_stack']:5s} self={r['self_smape']:.1f} cross={r['cross_smape_mean']:.1f} "
              f"ratio={r['degradation_ratio']:.3f}")
    print(f"  mean degradation ratio = {np.mean([r['degradation_ratio'] for r in ratios]):.3f}")
    print("\nDONE")


if __name__ == "__main__":
    sys.exit(main() or 0)
