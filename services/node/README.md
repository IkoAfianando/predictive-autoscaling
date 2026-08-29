# Node.js Stack — Fastify + TypeScript

Node.js (Node 20 LTS) implementation of the three microservices for the
predictive auto-scaling thesis. It is one of four parity stacks (Go, Rust, Java,
Node.js) and follows the shared contract in [`../../SPEC.md`](../../SPEC.md)
exactly.

- **HTTP:** Fastify 4
- **Language:** TypeScript 5 (compiled to CommonJS, run on plain Node)
- **Postgres:** `pg` (node-postgres) `Pool` with `max: 20`
- **Redis:** `ioredis`, product read-through cache, TTL 30s (`SET key val EX 30`)
- **Passwords:** `bcrypt` (native) with cost 10 — hashing runs on the libuv
  threadpool, so it never blocks the event loop
- **Metrics:** `prom-client` custom `http_request_duration_seconds` histogram
  with the exact 72 SPEC §4 buckets, plus default process/runtime metrics

## Services

One image, parameterized by `SERVICE_NAME` (`user` | `product` | `order`). The
entrypoint (`src/index.ts`) registers only the routes for the selected service.

| SERVICE_NAME | Kind | Routes |
|---|---|---|
| `user` | CPU-bound (bcrypt) | `POST /users/register`, `POST /users/login`, `GET /users/:id` |
| `product` | cache-bound (Redis) | `GET /products/:id`, `POST /products`, `PUT /products/:id` |
| `order` | I/O fan-out (HTTP) | `POST /orders`, `GET /orders/:id` |

Every service also exposes `GET /health` and `GET /metrics`.

## Layout

```
services/node/
├── package.json
├── tsconfig.json
├── Dockerfile            # multi-stage, non-root, EXPOSE 8080, HEALTHCHECK
├── src/index.ts          # reads SERVICE_NAME, registers the matching routes
├── src/config.ts         # env vars + SPEC defaults
├── src/metrics.ts        # 72-bucket histogram + onRequest/onResponse hooks
├── src/db.ts             # pg Pool (max 20) + startup retry
├── src/cache.ts          # ioredis client + startup retry + product key helper
└── src/services/{user,product,order}.ts
```

## Configuration

All settings come from the environment (SPEC §5). Defaults match parity (SPEC §2).

| Env var | Default | Notes |
|---|---|---|
| `SERVICE_NAME` | `user` | `user` \| `product` \| `order` |
| `STACK_NAME` | `node` | used for metric label + Redis key namespace |
| `PORT` | `8080` | internal port |
| `DATABASE_URL` | `postgres://appuser:appsecret@localhost:5432/node_db` | |
| `REDIS_URL` | `redis://localhost:6379` | |
| `BCRYPT_COST` | `10` | |
| `DB_POOL_MAX` | `20` | |
| `CACHE_TTL_SECONDS` | `30` | |
| `USER_SERVICE_URL` | `http://node-user:8080` | order service only |
| `PRODUCT_SERVICE_URL` | `http://node-product:8080` | order service only |
| `FANOUT_TIMEOUT_MS` | `5000` | order fan-out timeout |

Local docker-compose port map (SPEC §5): user `8031`, product `8032`, order `8033`.

## Build & run (local)

```bash
npm install
npm run build          # tsc -> dist/
SERVICE_NAME=user npm start
```

Typecheck only:

```bash
npm run typecheck      # tsc --noEmit
```

## Build & run (Docker)

The image is parameterized by `SERVICE_NAME`. Build once, run three times:

```bash
docker build -t node-stack ./services/node

docker run --rm -p 8031:8080 \
  -e SERVICE_NAME=user -e STACK_NAME=node \
  -e DATABASE_URL=postgres://appuser:appsecret@postgres:5432/node_db \
  -e REDIS_URL=redis://redis:6379 \
  node-stack

docker run --rm -p 8032:8080 -e SERVICE_NAME=product ... node-stack

docker run --rm -p 8033:8080 \
  -e SERVICE_NAME=order \
  -e USER_SERVICE_URL=http://node-user:8080 \
  -e PRODUCT_SERVICE_URL=http://node-product:8080 \
  ... node-stack
```

The container runs as the non-root `node` user, exposes `8080`, and has a
`HEALTHCHECK` that hits `/health`.

## Health & metrics

- `GET /health` returns `200 {"status":"ok"}` once DB **and** Redis are live;
  on startup the service retries both connections for up to ~30s before exiting
  (SPEC §6).
- `GET /metrics` returns Prometheus text: `http_request_duration_seconds`
  (labels `service`, `stack`, `method`, `route`, `status`) with the exact 72
  SPEC §4 buckets, plus default Node process/runtime metrics.
