# In-cluster k6 load harness

Runs the k6 scaling load **inside** the Kubernetes cluster as a `batch/v1` Job,
instead of driving it from a laptop through `kubectl port-forward`. This exists
to make auto-scaling experiments robust.

## Why in-cluster (vs port-forward)

`kubectl port-forward svc/... ` looks like it targets a Service, but it actually
pins a tunnel to **one specific pod**. The moment the autoscaler / predictive
controller does its job — scaling a Deployment up or down, rolling pods, or
evicting the pod the forward happened to pick — that tunnel breaks:

- forwards drop mid-run (`lost connection to pod`), corrupting the load profile;
- reconnect races leave gaps exactly when the system is scaling (the interesting
  part of the test);
- you need one forward per service per stack (see `../pf_keeper.sh`, 13 of them)
  kept alive by a retry loop.

An in-cluster Job instead talks to the **ClusterIP Service DNS**
(`http://<stack>-user.pas-thesis.svc.cluster.local:8080`). ClusterIP load-balances
across whatever pods currently back the Service, so pod churn during scaling is
invisible to the load generator. No port-forward, no `pf_keeper.sh`, nothing local
to keep alive.

## Files

| File | What it is |
|------|-----------|
| `k6-load-configmap.yaml` | ConfigMap holding the k6 script (`scale_incluster.js`). Same 5-step e-commerce workload and the same ramp-up → spike → hold → down-to-light(5 VU) → sustain profile as `../scenarios/scale_clean.js`. Targets are taken from `BASE_USER` / `BASE_PRODUCT` / `BASE_ORDER`. |
| `k6-job.yaml` | The Job. Uses `grafana/k6:0.49.0`, mounts the ConfigMap at `/scripts`, sets the `BASE_*` env to the stack's ClusterIP DNS. `__STACK__` is a placeholder the runner substitutes. `restartPolicy: Never`, small resources, k6 logs → stdout. |
| `run_incluster_scaling.sh` | Runner: renders the Job for a stack, applies ConfigMap + Job, waits for completion, saves `kubectl logs` under `results/`. |
| `results/` | Captured k6 run logs + rendered manifests (git-ignore as you like). |

## Usage

Prerequisites (the runner does **not** start these):

- cluster up, namespace `pas-thesis`, target stack deployed with its three
  ClusterIP services (`<stack>-user|product|order`, port 8080);
- the predictive/hybrid controller managing that stack, if you want to watch it
  react to the load.

```bash
# default stack = go
bash loadtest/incluster/run_incluster_scaling.sh

# another stack
STACK=rust bash loadtest/incluster/run_incluster_scaling.sh

# longer completion wait (seconds)
TIMEOUT=1500 STACK=java bash loadtest/incluster/run_incluster_scaling.sh

# keep the Job object after the run (default: delete; it also self-GCs after 1h)
KEEP=1 STACK=node bash loadtest/incluster/run_incluster_scaling.sh

# validate manifests only — applies nothing
DRY_RUN=1 STACK=go bash loadtest/incluster/run_incluster_scaling.sh
```

The k6 run report is streamed live and saved to
`results/k6-load-<stack>_<timestamp>.log`. You can also watch it directly:

```bash
kubectl -n pas-thesis logs -f job/k6-load-go
```

## Tuning the profile

The script reads optional env (defaults in parentheses), all wired as Job env in
`k6-job.yaml` so you can edit them there without touching the ConfigMap:

- `SPIKE` (130) — peak VUs at the spike stage
- `HOLD_VU` (100) — VUs during the high hold
- `LIGHT` (5) — off-peak floor VUs (kept > 0 so P95 stays measurable → clean
  scale-down)
- `SUSTAIN` (150s) — duration of the light-floor tail
- `THINK` (0.3) — per-iteration sleep, seconds

## Validation (no load sent)

```bash
kubectl apply --dry-run=client -f loadtest/incluster/k6-load-configmap.yaml
# render then validate the Job (has a __STACK__ placeholder):
sed 's/__STACK__/go/g' loadtest/incluster/k6-job.yaml | kubectl apply --dry-run=client -f -
```
