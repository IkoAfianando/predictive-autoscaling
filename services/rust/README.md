# Rust (Axum) Backend Stack

One of four backend stacks for the thesis *"ML-Based Predictive Auto-Scaling for
Microservices Using Multi-Stack Backend Latency Time-Series Data."* Implements the
three microservices defined in [`../../SPEC.md`](../../SPEC.md) — **User**, **Product**,
**Order** — as a single binary parameterized by the `SERVICE_NAME` env var.

## Stack

- Rust 1.78+ (built/tested on 1.90)
- [axum](https://docs.rs/axum) 0.7 on a multi-threaded [tokio](https://tokio.rs) runtime
- [sqlx](https://docs.rs/sqlx) 0.8 (Postgres, `runtime-tokio-rustls`), pool `max_connections = 20`
- [redis-rs](https://docs.rs/redis) 0.27 async multiplexed connection
- [bcrypt](https://docs.rs/bcrypt) 0.15, cost 10, offloaded via `tokio::task::spawn_blocking`
- [prometheus](https://docs.rs/prometheus) 0.13 — custom histogram with the exact 72 SPEC §4 buckets
- [reqwest](https://docs.rs/reqwest) 0.12 (rustls) for the Order fan-out, 5s timeout

## Layout

```
services/rust/
├── Cargo.toml         # deps; process metrics feature gated to Linux
├── Dockerfile         # multi-stage, non-root, EXPOSE 8080, HEALTHCHECK
├── schema.sql         # SPEC §3 tables (apply to rust_db)
├── src/
│   ├── main.rs        # reads SERVICE_NAME, mounts router, retries DB+Redis, /health, /metrics
│   ├── config.rs      # env-var configuration (SPEC §5)
│   ├── state.rs       # shared AppState (pool, cache, http client, config)
│   ├── db.rs          # Postgres pool (max 20) + startup retry + unique-violation helper
│   ├── cache.rs       # Redis wrapper, keys namespaced `{stack}:product:{id}`, TTL helper
│   ├── metrics.rs     # 72-bucket histogram + tower middleware + /metrics handler
│   ├── error.rs       # AppError -> HTTP status mapping
│   ├── user.rs        # User service (bcrypt)
│   ├── product.rs     # Product service (Redis read-through)
│   └── order.rs       # Order service (HTTP fan-out)
└── README.md
```

## Routes (per SPEC §1)

| Service | Routes |
|---|---|
| user | `POST /users/register`, `POST /users/login`, `GET /users/:id` |
| product | `GET /products/:id`, `POST /products`, `PUT /products/:id` |
| order | `POST /orders`, `GET /orders/:id` |
| all | `GET /health`, `GET /metrics` |

Every request is timed by an axum middleware that records
`http_request_duration_seconds{service,stack,method,route,status}` using the matched
route template (bounded cardinality).

## Configuration (env vars, SPEC §5)

| Var | Default | Notes |
|---|---|---|
| `SERVICE_NAME` | `user` | `user` \| `product` \| `order` — selects the router |
| `STACK_NAME` | `rust` | metric label + Redis key prefix |
| `PORT` | `8080` | internal listen port |
| `DATABASE_URL` | `postgres://appuser:appsecret@postgres:5432/rust_db` | |
| `REDIS_URL` | `redis://redis:6379` | |
| `BCRYPT_COST` | `10` | |
| `DB_POOL_MAX` | `20` | pool max connections |
| `CACHE_TTL_SECONDS` | `30` | product read-through TTL |
| `USER_SERVICE_URL` | `http://rust-user:8080` | order fan-out target |
| `PRODUCT_SERVICE_URL` | `http://rust-product:8080` | order fan-out target |

External port map (docker-compose, SPEC §5): user `8011`, product `8012`, order `8013`
— all internal `8080`.

## Build & run locally

```bash
# 1. Database schema (once, against rust_db)
psql "$DATABASE_URL" -f schema.sql

# 2. Compile
cargo build --release

# 3. Run each service (separate terminals / processes)
SERVICE_NAME=user    PORT=8011 ./target/release/server
SERVICE_NAME=product PORT=8012 ./target/release/server
SERVICE_NAME=order   PORT=8013 \
  USER_SERVICE_URL=http://localhost:8011 \
  PRODUCT_SERVICE_URL=http://localhost:8012 \
  ./target/release/server
```

`cargo check` / `cargo build` need no live database — all queries are runtime
(`sqlx::query_as`), not the compile-time-checked macros.

## Docker

One image, parameterized by `SERVICE_NAME`:

```bash
docker build -t rust-services services/rust

docker run -e SERVICE_NAME=user -e STACK_NAME=rust \
  -e DATABASE_URL=postgres://appuser:appsecret@postgres:5432/rust_db \
  -e REDIS_URL=redis://redis:6379 \
  -p 8011:8080 rust-services
```

The image is multi-stage (build with `cargo build --release`, run on
`debian:bookworm-slim`), runs as non-root user `appuser` (uid 10001), exposes 8080,
and defines a `HEALTHCHECK` hitting `/health`. Set the container CPU/memory limits
to 1.0 / 512 MB in compose/k8s per SPEC §2.

## Parity checklist (SPEC §2 / §8)

- bcrypt cost **10**, offloaded to the blocking pool (never blocks the async runtime).
- DB pool `max_connections = **20**`.
- Redis product cache TTL = **30s**, keys `rust:product:{id}`.
- `http_request_duration_seconds` histogram with the **exact 72** bucket boundaries.
- Process/runtime metrics (CPU, RSS) exported on Linux for the ML pipeline.
- Order fan-out → own stack's User + Product via env URLs, **5s** timeout.
- `/health` retries DB + Redis for ~30s on startup before exiting.
