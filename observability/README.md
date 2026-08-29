# Observability Stack

Prometheus + Grafana + OpenTelemetry Collector for the multi-stack
microservices thesis. Collects `http_request_duration_seconds` and
process/runtime metrics from all 12 backend services (Go / Rust / Java / Node
× user / product / order) and renders latency dashboards for the ML pipeline
and the comparison analysis.

## Layout

```
observability/
├── prometheus/
│   └── prometheus.yml                  # scrape jobs: 12 services + otel-collector + prometheus
├── otel/
│   └── otel-collector-config.yaml      # OTLP in (4317/4318) -> Prometheus (8889 + remote_write)
├── grafana/
│   ├── provisioning/
│   │   ├── datasources/prometheus.yml  # Prometheus datasource (uid: prometheus)
│   │   └── dashboards/dashboards.yml    # file-based dashboard provider
│   └── dashboards/
│       ├── latency.json                # P50/P95/P99, req rate, error rate, mem/CPU (var: $stack)
│       └── comparison.json             # P95 side-by-side across the 4 stacks
├── docker-compose.observability.yml    # prometheus + grafana + otel-collector
└── README.md
```

## Running

The observability stack attaches to a shared external docker network named
`thesis-net` so it can resolve the backend service DNS names
(`go-user`, `rust-order`, ...). The main services compose must also attach every
backend service to `thesis-net`.

```bash
# 1. Create the shared network (skip if the main compose already creates it)
docker network create thesis-net

# 2. Start the backend services (from wherever the main compose lives), attached
#    to thesis-net.

# 3. Start observability
cd observability
docker compose -f docker-compose.observability.yml up -d
```

Endpoints:

| Component        | URL                     | Notes                             |
|------------------|-------------------------|-----------------------------------|
| Prometheus       | http://localhost:9090   | Targets: `/targets`               |
| Grafana          | http://localhost:3000   | Login `admin` / `admin`           |
| OTLP gRPC        | localhost:4317          | `OTEL_EXPORTER_OTLP_ENDPOINT`     |
| OTLP HTTP        | localhost:4318          |                                   |
| OTel Prom export | http://localhost:8889   | Scraped by Prometheus             |

Stop: `docker compose -f docker-compose.observability.yml down`
(add `-v` to also drop the Prometheus/Grafana data volumes).

## Dashboards

Provisioned automatically from `grafana/dashboards/` into the
**Predictive Auto-Scaling** folder. Edit the JSON files and the file provider
reloads them within ~10s.

- **Latency Overview — $stack** (`thesis-latency`): P50 / P95 / P99 per service,
  request rate, error rate (5xx ratio), resident memory (RSS) and CPU cores.
  Template variables `$stack` (single) and `$service` (multi).
- **Stack Comparison — P95 latency** (`thesis-comparison`): P95 of every stack on
  one graph, a current-P95 bar gauge ranking, a P50/P95/P99 matrix table, and
  request rate by stack. Template variable `$service`.

## How P95 is computed (`histogram_quantile`)

Every service exports the histogram `http_request_duration_seconds` with the 72
explicit buckets from SPEC §4, split into `_bucket` (cumulative counts per `le`),
`_count`, and `_sum` series. Prometheus estimates a quantile by interpolating
inside the bucket where the target rank falls.

Per-stack P95 (used in the comparison dashboard):

```promql
histogram_quantile(
  0.95,
  sum(rate(http_request_duration_seconds_bucket{service=~"$service"}[$__rate_interval])) by (le, stack)
)
```

Per-service P95 within one stack (latency dashboard):

```promql
histogram_quantile(
  0.95,
  sum(rate(http_request_duration_seconds_bucket{stack="$stack", service=~"$service"}[$__rate_interval])) by (le, service)
)
```

Key points:

- `rate(..._bucket[$__rate_interval])` turns cumulative counters into a
  per-second rate over the dashboard's step, so the quantile reflects the
  *recent* window rather than all-time history.
- The `sum(...) by (le, ...)` **must** keep the `le` label — that is what
  `histogram_quantile` reads. Grouping additionally by `stack` (or `service`)
  yields one quantile line per stack (or service).
- Accuracy is bounded by bucket resolution. The 72 fine-grained buckets (1ms
  steps up to 10ms, then widening) give tight estimates in the sub-second range
  where the stack differences live.
- Swap the first argument for `0.50` or `0.99` for P50 / P99.

Error rate is derived from the same family via the `status` label:

```promql
sum(rate(http_request_duration_seconds_count{stack="$stack", status=~"5.."}[$__rate_interval])) by (service)
/
clamp_min(sum(rate(http_request_duration_seconds_count{stack="$stack"}[$__rate_interval])) by (service), 1)
```

## OpenTelemetry Collector

Stacks that push via OTLP (`OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317`,
SPEC §5) land in Prometheus two ways:

1. The collector re-exposes them in Prometheus format on `:8889`, which
   Prometheus scrapes (job `otel-collector`).
2. The collector also `prometheusremotewrite`s directly to Prometheus
   (`--web.enable-remote-write-receiver` is enabled on the Prometheus container).

`resource_to_telemetry_conversion` is on, so OTLP resource attributes (`stack`,
`service`) survive as metric labels and the same `histogram_quantile` queries
work for pushed metrics. Stacks that expose `/metrics` natively are scraped
directly and never touch the collector.

## Labels

Prometheus injects `stack` and `service` labels on every backend target (static
labels + relabeling in `prometheus.yml`), so those labels are always present for
templating even if a stack omits them from its own exposition.
