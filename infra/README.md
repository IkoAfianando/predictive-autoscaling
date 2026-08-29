# Infrastructure — predictive-autoscaling-thesis

Docker Compose (local, single host) and Kubernetes (reactive-HPA baseline)
infrastructure for the multi-stack microservices benchmark. Everything here is
driven by the parity contract in [`../SPEC.md`](../SPEC.md).

The system is **4 backend stacks** (Go, Rust, Java, Node.js) × **3 services**
(user, product, order) = **12 services**, sharing one PostgreSQL 15 and one
Redis 7 instance.

```
infra/
├── README.md                 # this file
├── postgres/
│   └── init.sql              # creates go_db/rust_db/java_db/node_db + tables (SPEC §3)
└── k8s/
    ├── namespace.yaml        # pas-thesis namespace
    ├── config.yaml           # app-common-config ConfigMap + db-credentials Secret
    ├── postgres.yaml         # Postgres Deployment + Service + PVC
    ├── redis.yaml            # Redis Deployment + Service
    ├── go.yaml               # go-user/product/order Deployments + Services
    ├── rust.yaml             # rust-* Deployments + Services
    ├── java.yaml             # java-* Deployments + Services
    ├── node.yaml             # node-* Deployments + Services
    ├── hpa.yaml              # 12 reactive CPU HPAs (baseline autoscaler)
    ├── init.sql              # verbatim copy of postgres/init.sql (see note below)
    └── kustomization.yaml    # ties it together (+ mounts init.sql as ConfigMap)

# at repo root:
../docker-compose.yml         # full local system
../.env.example               # copy to ../.env
```

---

## Port map (SPEC §5)

Host ports published by Docker Compose. In Kubernetes every service listens on
ClusterIP port **8080** and is reached by name (e.g. `http://go-user:8080`).

| Stack   | User | Product | Order | DB        |
|---------|------|---------|-------|-----------|
| Go      | 8001 | 8002    | 8003  | `go_db`   |
| Rust    | 8011 | 8012    | 8013  | `rust_db` |
| Java    | 8021 | 8022    | 8023  | `java_db` |
| Node.js | 8031 | 8032    | 8033  | `node_db` |

Infra ports: PostgreSQL `5432`, Redis `6379`.

Every service also exposes `GET /health` and `GET /metrics` on its port.

---

## Docker Compose (local)

```bash
# from the repo root
cp .env.example .env

# validate compose syntax without building
docker compose config

# build all four stack images and start the full system
docker compose up -d --build

# check status / logs
docker compose ps
docker compose logs -f go-order

# tear down (add -v to also drop the postgres volume)
docker compose down
```

Each stack ships **one image parameterized by `SERVICE_NAME`** (SPEC §7), so the
three services of a stack share a single build and differ only by env. Resource
limits are pinned per SPEC §2: `cpus: "1.0"`, `mem_limit: 512m`. Backends wait
for `postgres` and `redis` to be **healthy** (`depends_on` conditions); order
services additionally wait for their own stack's user/product to start.

`init.sql` runs automatically on first Postgres start (empty volume). To re-run
it, drop the volume: `docker compose down -v`.

### Smoke test

```bash
curl localhost:8001/health          # go-user
curl -X POST localhost:8001/users/register \
     -H 'content-type: application/json' \
     -d '{"username":"a","password":"b"}'
```

---

## Kubernetes (reactive baseline)

The Kubernetes manifests deploy the same system with a **reactive CPU HPA per
service** — this is the baseline the ML-based predictive controller (in
[`../controller`](../controller)) is compared against.

```bash
# build images locally first (compose is the easiest way)
docker compose build

# load images into your local cluster (kind example)
for s in go rust java node; do kind load docker-image pas/$s:latest; done
# (for minikube: eval $(minikube docker-env) before `docker compose build`)

# apply everything
kubectl apply -k infra/k8s

# watch it come up
kubectl -n pas-thesis get pods,svc,hpa
```

> **Note:** `k8s/init.sql` is a verbatim copy of the canonical
> `postgres/init.sql`. kustomize forbids `configMapGenerator` file sources
> outside its own directory, so the copy lives beside the kustomization. If you
> edit the schema, update both (`cp postgres/init.sql k8s/init.sql`).

The HPAs require a metrics source:

```bash
# metrics-server must be installed for CPU-based HPA to work
kubectl top pods -n pas-thesis
```

### HPA policy (baseline)

| Setting            | Value            |
|--------------------|------------------|
| Metric             | CPU utilization  |
| Target             | 60% average      |
| Min / Max replicas | 1 / 10           |
| Scale-up window    | 0s (react fast)  |
| Scale-down window  | 300s (stabilize) |

Tune in `k8s/hpa.yaml` if the experiment needs a different reactive baseline.

---

## Observability

Prometheus, Grafana and the OpenTelemetry Collector are **authored by the
observability agent** under [`../observability`](../observability) — not here.
Services already export to `OTEL_EXPORTER_OTLP_ENDPOINT`
(`http://otel-collector:4317`, optional) and expose `/metrics`.

To run the observability stack alongside this one (once that agent provides
`observability/docker-compose.observability.yml`):

```bash
docker compose \
  -f docker-compose.yml \
  -f observability/docker-compose.observability.yml \
  up -d
```

On Kubernetes, apply the observability agent's manifests into the same
`pas-thesis` namespace after `kubectl apply -k infra/k8s`.
