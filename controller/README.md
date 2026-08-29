# Predictive Auto-Scaling Controller

Custom Kubernetes controller for the thesis *"Machine Learning-Based Predictive
Auto-Scaling for Microservices Using Multi-Stack Backend Latency Time-Series
Data"* (Iko Afianando, 2602261970).

It is the **PREDICTIVE** arm of the experiment, compared head-to-head against a
standard **reactive HPA**. Instead of reacting to a P95 latency breach that has
*already happened*, it consumes a 30-second-ahead P95 forecast from the ML
service (`ml/serve.py`) and scales the affected Deployments **before** the
threshold is crossed.

```
                 ┌────────────────────┐   GET /predict?stack=go   ┌──────────────┐
                 │  ml/serve.py (ML)  │◀──────────────────────────│  controller  │
                 │  30s-ahead P95     │──────────  forecast ──────▶│  loop (Ns)   │
                 └────────────────────┘                            └──────┬───────┘
                                                                          │ patch scale
                                                    apps/v1 deployments/scale
                                                                          ▼
   go-user  go-product  go-order   rust-user … java-… node-…   (4 stacks × 3 services = 12)
```

---

## Files

| File | Purpose |
|---|---|
| `scaling_logic.py` | Pure, dependency-free decision logic (`decide()`). Shared by the live controller and the simulator so both prove the *same* code. |
| `predictive_controller.py` | The live control loop: fetch forecasts → decide → patch Deployment scale → log. |
| `metrics_exporter.py` | Optional Prometheus exporter (predicted P95, current replicas, scaling-events counter) for Grafana. |
| `sim.py` | Standalone simulator — feeds synthetic P95 series through `decide()`, computes reaction-time lead & false-positive rate. **No cluster / ML service needed.** |
| `requirements.txt` | `kubernetes`, `requests`, `prometheus-client`. |
| `Dockerfile` | Non-root, slim Python 3.12 image. |
| `k8s/` | `namespace.yaml`, `rbac.yaml` (SA + Role + RoleBinding: get/list/watch deployments, get/update/patch `deployments/scale`), `deployment.yaml` (+ metrics Service). |
| `logs/decisions.jsonl` | Live decision log (created at runtime). |
| `logs/sim_decisions.jsonl` | Simulator decision log (Bab IV dataset, same schema). |

---

## The decision logic (`decide()`)

For each managed Deployment, every tick:

- **Scale UP** — `predicted_p95 > SCALE_UP_THRESHOLD` (default 200 ms). Target is
  HPA-style proportional: `ceil(current × predicted / threshold)`, guaranteed to
  add at least 1 replica, capped at `UP_STEP_CAP` per tick and at `MAX_REPLICAS`.
  Up-scaling is **immediate** (no cooldown) — reacting fast is the whole point.
- **Scale DOWN** — only when `predicted_p95 < SCALE_DOWN_THRESHOLD` (default
  80 ms) has been *sustained* for `COOLDOWN_SECONDS`, then one replica at a time
  with a further `COOLDOWN_SECONDS` cooldown between steps. This dual guard is
  what prevents flapping.
- **Band / hold** — between the two thresholds, hold and reset the sustained-low
  clock.

Every decision is written as one structured-JSON line to **stdout** *and*
appended to `logs/decisions.jsonl`. That file is the raw data for the evaluation.

### Configuration (env vars)

| Var | Default | Meaning |
|---|---|---|
| `PREDICT_URL` | `http://ml-serve:8000/predict` | ML forecast endpoint. |
| `SCALE_UP_THRESHOLD` | `200` | ms; forecast above → scale up. |
| `SCALE_DOWN_THRESHOLD` | `80` | ms; forecast below (sustained) → scale down. |
| `MIN_REPLICAS` / `MAX_REPLICAS` | `1` / `10` | Replica bounds. |
| `INTERVAL_SECONDS` | `15` | Control-loop period. |
| `COOLDOWN_SECONDS` | `60` | Sustained-low window *and* down-scale cooldown. |
| `NAMESPACE` | `autoscale` | Namespace of the managed Deployments. |
| `DRY_RUN` | `false` | `true` → decide + log, never touch the K8s API. |
| `UP_STEP_CAP` | `4` | Max replicas added in one tick (anti-overshoot). |
| `METRICS_PORT` / `ENABLE_METRICS` | `9095` / `true` | Prometheus exporter. |

---

## DRY_RUN

`DRY_RUN=true` runs the **entire** loop — forecast fetch, decision, structured
logging — but skips both reading and patching the Kubernetes scale subresource.
The controller keeps its replica view in memory instead. This lets you:

- demonstrate the controller on a laptop with only the ML service reachable, and
- generate a `decisions.jsonl` for review without a live cluster.

The `kubernetes` and `requests` imports are guarded, so the module imports even
when those packages are missing; you only need them for a *real* (non-dry) run.

---

## Run the simulator (proves the logic today — no cluster, no ML service)

```bash
cd controller
python3 sim.py
```

It drives four synthetic traffic personalities (one per stack) through the real
`decide()`:

| Stack | Pattern | What it exercises |
|---|---|---|
| `go` | idle → sharp spike → decay | clean up-scale + graceful, flap-free down-scale |
| `rust` | noisy around the threshold | false positives from forecast noise |
| `java` | heavy sustained load | `MAX_REPLICAS` clamp + `UP_STEP_CAP` |
| `node` | mostly idle w/ a brief blip | stays at `MIN_REPLICAS`, does **not** flap |

It prints a per-stack scaling timeline and an aggregate summary, and writes
`logs/sim_decisions.jsonl`.

### Latest run (seed 42)

| stack | reaction-time lead vs reactive | scale-ups | false positives | peak replicas |
|---|---|---|---|---|
| go | **+60 s** | 5 | 0 | 10 |
| rust | **+30 s** | 6 | 1 (16.7%) | 10 |
| java | **+60 s** | 5 | 0 | 10 |
| node | — (stayed at min) | 0 | 0 | 1 |
| **aggregate** | **+50 s mean** | 16 | **6.2%** | — |

Positive lead = the predictive controller scaled up *earlier* than a reactive
HPA would have.

---

## How the reaction-time & false-positive metrics are computed

The simulator models the two approaches on the *same* latency series:

- **Reactive HPA baseline** — can only act *after* the real P95 crosses the
  threshold, plus its stabilisation delay (`REACTIVE_DELAY_TICKS`, ~1 sync period
  + metric window). `reactive_scale_tick = first_breach_tick + delay`.
- **Predictive controller** — acts when the *forecast* (which leads reality by
  `HORIZON_SECONDS = 30 s`) crosses the threshold, i.e. before the breach.
- **Reaction-time lead** = `(reactive_scale_tick − predictive_scale_tick) × tick`.
- **False positive** = a scale-up whose forecast breach the *actual* latency at
  the forecast horizon never confirms (`actual[t+lead] ≤ threshold`). Forecast
  noise + occasional phantom spikes make this non-zero and realistic.

---

## How the decision log feeds Bab IV evaluation

Both `decisions.jsonl` (live) and `sim_decisions.jsonl` (synthetic) share one
schema, one line per decision:

```json
{"ts":"…","epoch":…,"service":"go-order","stack":"go","predicted_p95_ms":221.7,
 "current_replicas":1,"new_replicas":2,"action":"scale_up","reason":"predicted_breach",
 "threshold_up_ms":200.0,"threshold_down_ms":80.0,"dry_run":false,
 "extra":{"tick":25,"actual_p95_ms":170.0,"horizon_actual_p95_ms":300.0}}
```

The Bab IV notebook joins these decisions against the observed `/metrics` P95 to
report, per stack and aggregate:

1. **Reaction-time lead** — seconds the predictive controller scaled before the
   reactive HPA / before the real breach.
2. **False-positive rate** — fraction of scale-ups the ground truth didn't justify.
3. **SLO adherence** — time spent above the P95 threshold under each approach.
4. **Resource cost** — replica-seconds (over-provisioning trade-off).

---

## Deploy to a cluster

```bash
# 1. build & push the image (pin a real tag/registry)
docker build -t <registry>/predictive-controller:v1 controller/
docker push <registry>/predictive-controller:v1

# 2. apply manifests (edit the image ref in k8s/deployment.yaml first)
kubectl apply -f controller/k8s/namespace.yaml
kubectl apply -f controller/k8s/rbac.yaml
kubectl apply -f controller/k8s/deployment.yaml

# 3. watch the decisions stream
kubectl -n autoscale logs deploy/predictive-controller -f
```

The controller Deployment mounts `logs/` as an `emptyDir`; swap it for a PVC to
persist the evaluation dataset across restarts.

---

## Predictive vs reactive HPA — the difference

| | Reactive HPA | Predictive controller (this) |
|---|---|---|
| Trigger | Current metric already over target | 30 s-ahead **forecast** over threshold |
| Timing | After breach + stabilisation window | **Before** the breach |
| Input | Instantaneous CPU / custom metric | ML latency time-series forecast |
| Down-scale | Stabilisation window | Sustained-low window + cooldown (flap-safe) |
| Risk | SLO violated during the reaction gap | Occasional false-positive over-provisioning |

The experiment quantifies exactly that trade-off: the predictive controller buys
a reaction-time lead (fewer/shorter SLO violations) at the cost of a measurable
false-positive rate — both computed directly from the decision logs above.
