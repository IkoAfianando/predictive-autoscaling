# Predictive Auto-Scaling of Multi-Stack Microservices with Deep Learning

Reference implementation for the study *Predictive Auto-Scaling of Multi-Stack Microservices
with Deep Learning on Backend Latency Time-Series*. It forecasts the 95th-percentile request
latency thirty seconds ahead and scales a Kubernetes deployment **before** a load peak arrives,
instead of reacting after CPU has already crossed a threshold.

Four backend stacks — **Go, Rust, Java, and Node.js** — each implement the same three
microservices under identical configuration, so any difference in behavior is attributable to the
runtime rather than to the application. A hybrid controller scales **up on the forecast** and
**down on the measured latency**, which keeps it proactive while staying immune to the forecaster's
near-idle over-prediction.

## What is inside

| Path | Contents |
|------|----------|
| `services/{go,rust,java,node}/` | Four functionally identical stacks: `user` (bcrypt-heavy), `product` (Redis-cached), `order` (HTTP fan-out) |
| `controller/` | Hybrid predictive controller, decision logic (`scaling_logic.py`), unit tests, metrics exporter |
| `ml/` | Forecasting pipeline: feature engineering, training of LSTM / GRU / XGBoost / Prophet, evaluation |
| `ml/data_sample/` | A ready-to-use latency time-series sample (one series per stack) so the pipeline runs out of the box |
| `infra/` | Kubernetes manifests, Postgres init, HPA baseline |
| `observability/` | Prometheus, Grafana, and OpenTelemetry configuration |
| `loadtest/` | k6 workloads and the four ablation scenarios (Flash-Sale, Daily-Peak, Payday-Soak, Viral-Stress) |
| `scripts/` | Smoke test, health wait, port helpers |

## Architecture

![architecture](docs/figures/diagrams/02_system_architecture.png)

## Results

Full figures and tables are in **[RESULTS.md](RESULTS.md)**. In short: GRU is the strongest deep
forecaster on the burst and saturation regimes that scaling depends on; the controller scales one to
eight replicas while CPU is still idle and back with no flapping; the idle false-positive rate is
6.2%; and models do not transfer cleanly between runtimes.

![ablation](docs/figures/charts/07_ablation_4stack.png)

![scaling 1-8-1](docs/figures/charts/04_scaling_1_8_1.png)

## Hardware and environment used

All measurements in the paper were collected on a single host:

- **Apple M4 MacBook**, 10 CPU cores, **16 GB** RAM
- macOS with **Docker Desktop** and its built-in single-node **Kubernetes**
- Per-service limits of **1.0 CPU / 512 MB**, so every stack competes under the same budget
- Prometheus scraping at 15-second resolution

The workloads are CPU-bound (bcrypt cost 10) and the results are meant to be read as the behavior
of these stacks under one identical application configuration, not as a raw language-speed ranking.

## Prerequisites

- Docker Desktop with Kubernetes enabled (or any single-node cluster + `kubectl`)
- [k6](https://k6.io/) for load generation
- Python 3.11+ for the ML pipeline and the controller
- Go 1.22+, Rust 1.75+, JDK 17+, Node 20+ only if you want to rebuild the service images

## Quick start (Docker Compose)

Bring the whole stack up locally:

```bash
docker compose up --build
```

This starts the four backends, one Postgres, one Redis, and the observability stack. Then run a
smoke test:

```bash
./scripts/smoke-test.sh
```

## Run on Kubernetes

```bash
kubectl apply -k infra/k8s          # namespace, Postgres, Redis, the four stacks
./scripts/wait-for-healthy.sh       # block until every pod is Ready
```

The reactive baseline (Kubernetes HPA at a 60% CPU target) is in `infra/k8s/hpa.yaml`.

## Load testing

Every scenario is a k6 script. Run one directly:

```bash
k6 run loadtest/scenarios/wave.js               # the oscillating wave used to train the models
k6 run loadtest/ablation/s1_flash_sale.js       # a 50x flash-sale spike
```

Or drive the full four-scenario ablation across the stacks:

```bash
./loadtest/ablation/run_ablation.sh
```

## Train the forecasters

```bash
cd ml
pip install -r requirements.txt
python features.py            # build lag / rolling / rate features from the latency series
python evaluate.py            # train LSTM, GRU, XGBoost, Prophet and report RMSE / MAE / sMAPE
```

`ml/data_sample/` is used by default so this runs without collecting new data. To gather a fresh
series from a running cluster, use `python collect.py`.

## Run the predictive controller

```bash
cd controller
pip install -r requirements.txt
python -m pytest test_scaling_logic.py          # decision-logic unit tests
python predictive_controller.py                 # scale a live deployment from the forecast
```

The decision rule lives in `scaling_logic.py`: scale-up follows the forecast and requires a
sustained-high breach; scale-down is checked first and keyed to the measured P95, so shrinking
capacity is always governed by ground truth.

## Reproducing the headline results

1. Deploy the stacks on Kubernetes and confirm parity (bcrypt cost 10, pool 20, TTL 30 s, 1.0 CPU / 512 MB).
2. Run the wave workload and collect the latency series.
3. Train the four forecasters; GRU is the strongest deep model, and deep learning wins on the
   spike, soak, and saturating regimes that scaling depends on.
4. Run the controller: it scales one to eight replicas while CPU is still idle and returns to one
   without flapping.
5. Run the ablation for the per-stack, per-intensity tail-latency response.

## Citation

If you use this code, please cite the accompanying paper (Iko Afianando, BINUS, 2026). A BibTeX
entry will be added here once the paper has a DOI.

## License

MIT — see [LICENSE](LICENSE).
