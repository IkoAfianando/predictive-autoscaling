# ML Pipeline — Predictive Auto-Scaling

Forecasts **P95 HTTP request latency 30 seconds ahead**, per backend stack
(`go` / `rust` / `java` / `node`), and compares three algorithms — **LSTM**,
**Prophet**, **XGBoost** — on **RMSE / MAE / MAPE**. The best model is served to
the auto-scaling controller over HTTP.

Metric source (see `../SPEC.md` §4): `http_request_duration_seconds` histogram,
label `stack`. P95 is computed with:

```promql
histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{stack="$s"}[1m])) by (le))
```

## Files

| File | Purpose |
|---|---|
| `config.py` | Shared constants: stacks, metric, paths, horizon/step, PromQL builders. |
| `collect.py` | Pull per-stack time-series from Prometheus `/api/v1/query_range` → `data/{stack}.csv`. |
| `synthetic.py` | Generate realistic synthetic P95 series (daily seasonality + noise + spikes) so the pipeline runs with no cluster. |
| `features.py` | Feature engineering: lags, rolling mean/std, time-of-day; supervised windows for t+30s; 70/15/15 time-ordered split (no shuffle). Also LSTM sequence windows. |
| `train_lstm.py` | Keras LSTM (2×64 units, 60s lookback). Saves model + loss-curve PNG. |
| `train_prophet.py` | Prophet per stack (daily+weekly seasonality, `changepoint_prior_scale=0.05`). Saves forecast plot. |
| `train_xgboost.py` | XGBoost regressor (500 trees, depth 6, lr 0.1) on lag features. Falls back to sklearn `HistGradientBoostingRegressor` if xgboost is missing. |
| `evaluate.py` | RMSE/MAE/MAPE for each model×stack → `results/metrics.csv` + comparison chart; cross-stack transfer → `results/transfer.csv` + heatmap. |
| `serve.py` | FastAPI (or Flask) service exposing `GET /predict?stack=go` and batch `POST /predict` for the controller. |
| `notebook.ipynb` | End-to-end walkthrough (load → features → 3 models → evaluate → plots). |

Outputs land in `data/` (CSVs), `models/` (saved models), `results/` (metrics + plots).

## Data schema (`data/{stack}.csv`)

```
timestamp, request_rate, error_rate, cpu, memory, p95
```

`p95` is the forecast target; the others are driver features. `collect.py` and
`synthetic.py` write the **same** schema, so downstream code is identical for
real and synthetic data.

## Quick start — offline demo (no cluster, runs today)

```bash
cd ml
pip install -r requirements.txt          # or just: pandas numpy scikit-learn matplotlib

python synthetic.py --hours 24           # → data/{stack}.csv
python train_xgboost.py --all            # train + report metrics
python evaluate.py                       # metrics.csv, comparison.png, transfer.csv, transfer.png
python serve.py                          # http://0.0.0.0:8000/predict?stack=go
```

Or run the whole thing in the notebook:

```bash
jupyter notebook notebook.ipynb
```

The notebook auto-generates synthetic data if `data/` is empty.

### Minimum vs. full install

* **Minimum** (demo works): `pandas numpy scikit-learn matplotlib`. XGBoost is
  substituted by a scikit-learn gradient-boosting fallback (model tag
  `xgb_fallback`); LSTM and Prophet are skipped with a printed hint.
* **Full comparison**: also `pip install xgboost tensorflow prophet`
  (`tensorflow-macos` on Apple Silicon). All scripts guard these imports, so a
  partial install still runs whatever is available.

## Running on real Prometheus data

```bash
python collect.py --url http://<prometheus-host>:9090 --minutes 180 --step 15
# or an explicit window:
python collect.py --url http://<prometheus-host>:9090 \
    --start 2026-07-13T00:00:00Z --end 2026-07-13T03:00:00Z
```

Then run the same `train_*.py` / `evaluate.py` / `serve.py` commands — they read
whatever CSVs are in `data/`. Collect over a multi-day window for Prophet's
daily/weekly seasonality to be meaningful.

## Serving to the controller

```bash
python serve.py --port 8000
# GET  /predict?stack=go            -> {"stack":"go","p95_pred":0.051,"horizon_seconds":30,...}
# POST /predict {"stacks":["go","rust"]}          -> batch
# POST /predict {"stack":"go","features":{...}}   -> predict from an explicit row
# GET  /health
```

`serve.py` picks the best model per stack from `results/metrics.csv` (lowest
RMSE) when present, and always keeps the portable tabular model as a safe
default so the controller never gets an empty answer. It builds the latest
feature row from `data/{stack}.csv`; in production, refresh that CSV with
`collect.py` on a schedule (or extend `_latest_features` to pull the live window
straight from Prometheus).

## Config knobs (`config.py`)

`STEP_SECONDS=15`, `HORIZON_SECONDS=30`, `LOOKBACK_SECONDS=60`,
`FEATURE_COLS`, `TARGET_COL`, and the `promql_*` builders. Change these in one
place and every script follows.
