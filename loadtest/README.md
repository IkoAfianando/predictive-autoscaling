# Load-testing suite (k6)

k6 load generators for the thesis *Machine Learning-Based Predictive Auto-Scaling
for Microservices Using Multi-Stack Backend Latency Time-Series Data*.

These scripts drive the four backend stacks (Go, Rust, Java, Node.js) with an
identical, realistic workload so the collected latency time-series are
apples-to-apples across stacks (see `../SPEC.md`).

## Prerequisites

- **k6** must be installed. Verify:

  ```bash
  k6 version
  ```

  Install: https://k6.io/docs/get-started/installation/

- The target stack's services must be running and reachable on the host ports
  from `SPEC.md` §5 (docker-compose publishes them to `localhost`):

  | Stack | User | Product | Order |
  |-------|------|---------|-------|
  | go    | 8001 | 8002    | 8003  |
  | rust  | 8011 | 8012    | 8013  |
  | java  | 8021 | 8022    | 8023  |
  | node  | 8031 | 8032    | 8033  |

## Layout

```
loadtest/
├── lib/
│   └── workload.js        # shared workload: register→login→product→get→order
├── scenarios/
│   ├── load.js            # 0 → 100 VU ramp, ~10 min
│   ├── stress.js          # 50 → 1000 VU, ~13 min
│   ├── spike.js           # 20 → 200 VU sudden, ~5.5 min
│   └── soak.js            # 30 VU sustained, ~40 min
├── results/               # k6 output (created on first run)
├── run-all.sh             # run every scenario against every stack
└── README.md
```

## The workload

`lib/workload.js` exports `runWorkload(baseUrls)`, which performs one realistic
end-to-end iteration exercising every latency path in the SPEC:

1. **register** a user — `POST /users/register` (bcrypt **CPU** path)
2. **login** — `POST /users/login` (bcrypt verify, **CPU** path)
3. **create product** — `POST /products` (Postgres write + cache invalidate)
4. **get product** ×2 — `GET /products/:id` (Redis read-through: **cache** miss then hit)
5. **create order** — `POST /orders` (HTTP **fan-out** to User + Product)

It records a custom `workload_duration` Trend plus per-step Trends
(`step_register_duration`, `step_login_duration`, `step_product_post_duration`,
`step_product_get_duration`, `step_order_duration`) and a `workload_errors`
Counter, all tagged with `stack`, so latency can be attributed to the CPU /
cache / fan-out paths independently.

### Selecting the target stack

The target stack is chosen with the `STACK` env var (`go|rust|java|node`),
which `resolveBaseUrls()` maps to the correct host ports via `PORT_MAP`.
Override the host with `HOST` (default `localhost`).

## Running a single scenario

```bash
cd loadtest
k6 run -e STACK=go   scenarios/stress.js
k6 run -e STACK=rust scenarios/load.js
k6 run -e STACK=node -e HOST=127.0.0.1 scenarios/spike.js
```

Export results manually if you want the ML-pipeline inputs:

```bash
k6 run -e STACK=go \
  --summary-export results/go-load.json \
  --out json=results/go-load.ndjson \
  scenarios/load.js
```

Quick syntax / structure check without any services running:

```bash
k6 inspect scenarios/load.js
```

## Running everything

```bash
cd loadtest
./run-all.sh
```

Runs each scenario against each stack **sequentially** and writes, per pair:

- `results/{stack}-{scenario}.json` — end-of-test summary (aggregated metrics)
- `results/{stack}-{scenario}.ndjson` — full per-sample stream (the raw time-series)

Subset the matrix with env vars:

```bash
STACKS="go rust" SCENARIOS="load spike" ./run-all.sh
```

> Note: run stacks one at a time so they don't contend for host CPU/memory and
> bias the latency comparison. `run-all.sh` is sequential for exactly this reason.

## How the output feeds the ML pipeline

The ML stage (`../ml/`) forecasts load/latency to drive **predictive**
autoscaling. It consumes two aligned sources:

1. **k6 latency time-series** — the `results/{stack}-{scenario}.ndjson` streams.
   Each line is a JSON sample (`http_req_duration`, `workload_duration`, the
   per-step Trends, etc.) with a timestamp and the `stack`/`scenario`/`step`
   tags. These give the *ground-truth request latency* and *offered load* over
   time, per stack and per code path.
2. **Prometheus metrics** — the `http_request_duration_seconds` histogram and
   process/runtime metrics each service exposes at `/metrics` (SPEC §4),
   scraped over the same window.

Pipeline flow:

```
k6 (this suite) ──ndjson──┐
                          ├─► align on timestamp ─► feature matrix ─► ML model
services /metrics ─prom───┘        (per stack)      (latency + CPU/mem)   (forecast → scale)
```

Because every stack is driven by the **identical** workload and scenarios, the
resulting time-series differ only by stack behavior, which is the whole point of
the comparison. The `{stack}` and `{scenario}` tags let the pipeline slice the
data per experiment; the sudden `spike` and ramping `stress` scenarios provide
the non-stationary load the forecaster must learn to anticipate.
