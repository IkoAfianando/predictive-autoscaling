# Go (Gin) Backend Stack

Reference implementation of the three microservices (**User**, **Product**, **Order**)
for the thesis *"Machine Learning-Based Predictive Auto-Scaling for Microservices Using
Multi-Stack Backend Latency Time-Series Data"*.

This stack conforms to the shared contract in [`../../SPEC.md`](../../SPEC.md). Behavior,
configuration, and the metric bucket boundaries are identical to the Rust / Java / Node.js
stacks so the latency comparison stays apples-to-apples.

## Stack

- Go 1.22+
- [Gin](https://github.com/gin-gonic/gin) — HTTP
- `database/sql` + [pgx v5 stdlib](https://github.com/jackc/pgx) — Postgres (pool max 20)
- [go-redis v9](https://github.com/redis/go-redis) — Redis
- [x/crypto/bcrypt](https://pkg.go.dev/golang.org/x/crypto/bcrypt) — password hashing (cost 10)
- [prometheus/client_golang](https://github.com/prometheus/client_golang) — `/metrics`

## Layout

```
services/go/
├── go.mod / go.sum
├── Dockerfile               # multi-stage, non-root, parameterized by SERVICE_NAME
├── cmd/server/main.go       # reads SERVICE_NAME, wires the right service
└── internal/
    ├── config/config.go     # env parsing + SPEC defaults
    ├── metrics/metrics.go    # shared histogram with the EXACT 72 buckets (SPEC §4)
    ├── httpx/middleware.go   # records http_request_duration_seconds per request
    ├── db/db.go              # pgx pool (max 20), startup retry, migrations
    ├── cache/cache.go        # go-redis client, {stack}:product:{id} keys
    ├── hashpool/hashpool.go  # bounded bcrypt worker pool (never starves the runtime)
    ├── user/user.go          # User service (SPEC §1.1)
    ├── product/product.go    # Product service (SPEC §1.2)
    └── order/order.go        # Order service (SPEC §1.3)
```

## One binary, three services

A single binary becomes whichever service `SERVICE_NAME` selects (`user` | `product` |
`order`) — see SPEC §7. `main.go` registers only the routes for that service, plus the
shared `/health` and `/metrics` endpoints and the metrics middleware.

## Configuration (env vars — SPEC §5)

| Var | Default | Notes |
|---|---|---|
| `SERVICE_NAME` | `user` | `user` \| `product` \| `order` |
| `STACK_NAME` | `go` | metric label |
| `PORT` | `8080` | internal port |
| `DATABASE_URL` | `postgres://appuser:appsecret@localhost:5432/go_db` | |
| `REDIS_URL` | `redis://localhost:6379` | |
| `BCRYPT_COST` | `10` | SPEC §2 |
| `DB_POOL_MAX` | `20` | SPEC §2 |
| `CACHE_TTL_SECONDS` | `30` | SPEC §2 |
| `USER_SERVICE_URL` | `http://go-user:8080` | Order service fan-out |
| `PRODUCT_SERVICE_URL` | `http://go-product:8080` | Order service fan-out |

Parity constants baked in: bcrypt cost 10, DB pool max 20, Redis TTL 30s, fan-out timeout
5000 ms, and the exact 72 Prometheus histogram buckets from SPEC §4.

## Routes (SPEC §1)

**User** (`SERVICE_NAME=user`)
- `POST /users/register` — `{username, password}` → `{id, username}` (bcrypt cost 10)
- `POST /users/login` — `{username, password}` → `{token}` or 401
- `GET /users/:id` — `{id, username}` or 404

**Product** (`SERVICE_NAME=product`)
- `GET /products/:id` — read-through Redis (TTL 30s), Postgres on miss
- `POST /products` — `{name, price}` → created product
- `PUT /products/:id` — update + invalidate cache key

**Order** (`SERVICE_NAME=order`)
- `POST /orders` — `{user_id, product_id, qty}`; fan-out HTTP validates user + product
  (5s timeout) then inserts
- `GET /orders/:id` — order JSON or 404

**All services**
- `GET /health` — `{status:"ok"}` once DB + Redis are live (startup retry up to ~30s)
- `GET /metrics` — Prometheus exposition (`http_request_duration_seconds` + Go runtime metrics)

## Build & run locally

```bash
# Requires Go 1.22+, plus a reachable Postgres (go_db) and Redis.
go mod tidy
go build ./...

# Run the User service
SERVICE_NAME=user  PORT=8001 \
  DATABASE_URL=postgres://appuser:appsecret@localhost:5432/go_db \
  REDIS_URL=redis://localhost:6379 \
  go run ./cmd/server

# Product / Order likewise with SERVICE_NAME=product|order and PORT 8002/8003.
# The Order service also needs:
#   USER_SERVICE_URL=http://localhost:8001 PRODUCT_SERVICE_URL=http://localhost:8002
```

Tables (`users`, `products`, `orders`) are auto-created on startup (`db.Migrate`).

## Docker

One image, parameterized by `SERVICE_NAME` (SPEC §7). Multi-stage, non-root, `EXPOSE 8080`,
`HEALTHCHECK` on `/health`.

```bash
docker build -t thesis-go:latest .

# User service on host port 8001 (Go stack port map, SPEC §5)
docker run --rm -p 8001:8080 \
  -e SERVICE_NAME=user \
  -e DATABASE_URL=postgres://appuser:appsecret@postgres:5432/go_db \
  -e REDIS_URL=redis://redis:6379 \
  thesis-go:latest
```

Port map (SPEC §5): Go User `8001`, Product `8002`, Order `8003`.
Container limits (compose/k8s): CPU `1.0`, memory `512 MB` (SPEC §2).

## Notes

- **bcrypt offloading**: `internal/hashpool` bounds concurrent bcrypt operations to
  `GOMAXPROCS`, so a burst of register/login requests queues instead of spawning unbounded
  CPU-heavy goroutines that would starve the scheduler (SPEC §2).
- **Metrics parity**: the 72 bucket boundaries live in `internal/metrics/metrics.go` exactly
  as listed in SPEC §4 — do not edit without changing every stack.
- Verified with `go build ./...` and `go vet ./...` (both pass on Go 1.25).
