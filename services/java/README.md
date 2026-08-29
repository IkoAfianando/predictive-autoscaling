# Java (Spring Boot 3) Backend Stack

One of four backend stacks (Go, Rust, **Java**, Node.js) for the thesis
_"Machine Learning-Based Predictive Auto-Scaling for Microservices Using
Multi-Stack Backend Latency Time-Series Data."_ All stacks implement the
**identical** contract in [`../../SPEC.md`](../../SPEC.md) so the latency
comparison is apples-to-apples.

This stack is **one Spring Boot 3 application** (Java 25) that becomes the
**User**, **Product**, or **Order** service depending on the `SERVICE_NAME`
environment variable. Controllers are switched on with
`@ConditionalOnProperty(app.service-name)`, so exactly one service's routes are
exposed per container while all three share identical infrastructure (metrics,
DB pool, Redis, health, bcrypt offload).

## Stack

| Concern | Choice |
|---|---|
| Framework | Spring Boot 3.3.5, embedded Tomcat, Spring MVC |
| Language | Java 25 (`--release 25`) |
| DB access | `spring-boot-starter-jdbc` + `JdbcTemplate`, **HikariCP pool max 20** |
| Cache | `spring-boot-starter-data-redis` (Lettuce), **TTL 30s** |
| Hashing | `spring-security-crypto` `BCryptPasswordEncoder(10)`, offloaded to a bounded executor |
| Metrics | Micrometer + `micrometer-registry-prometheus` (native Prometheus client) |
| Fan-out HTTP | Spring `RestClient`, 5s connect + read timeout |

## Services, ports & routes (SPEC §1, §5)

| Service | `SERVICE_NAME` | Local port | Routes |
|---|---|---|---|
| User (CPU/bcrypt) | `user` | 8021 | `POST /users/register`, `POST /users/login`, `GET /users/:id` |
| Product (Redis) | `product` | 8022 | `GET /products/:id`, `POST /products`, `PUT /products/:id` |
| Order (fan-out) | `order` | 8023 | `POST /orders`, `GET /orders/:id` |

Every service also exposes `GET /health` and `GET /metrics`.

## Configuration parity (SPEC §2)

| Parameter | Value | Where |
|---|---|---|
| bcrypt cost | 10 | `BeansConfig.passwordEncoder` (from `BCRYPT_COST`) |
| DB pool max | 20 | `DataSourceConfig` (from `DB_POOL_MAX`) |
| Redis TTL | 30s | `ProductCache` (from `CACHE_TTL_SECONDS`) |
| bcrypt offload | bounded pool | `BeansConfig.bcryptExecutor` + `BcryptService` |
| Fan-out timeout | 5000 ms | `BeansConfig.restClient` |
| Histogram buckets | exact 72 | `metrics/HistogramBuckets.java` |

## Metrics (SPEC §4)

`GET /metrics` returns Prometheus text exposition from a single registry that
holds both:

- **`http_request_duration_seconds`** — a **native Prometheus classic
  histogram** with the **exact 72 bucket boundaries** from SPEC §4 and labels
  `service`, `stack`, `method`, `route`, `status`. It is registered directly on
  the Micrometer Prometheus registry (`MetricsConfig`) so there is no metric
  renaming or extra percentile buckets. A servlet filter (`MetricsFilter`)
  records every request; the `route` label uses the matched template
  (`/users/:id`) — braces normalised to the `:param` form for parity with the
  Go/Rust stacks; unmatched requests use `unmatched`.
- **Default JVM / process metrics** (CPU, memory, GC) from Micrometer, for the
  ML feature set.

`GET /metrics` is served by `MetricsController` (a plain controller path, as the
SPEC requires); the same data is also available at `/actuator/prometheus`.

## Environment variables (SPEC §5)

```
SERVICE_NAME        = user | product | order
STACK_NAME          = java
PORT                = 8080
DATABASE_URL        = postgres://appuser:appsecret@postgres:5432/java_db
REDIS_URL           = redis://redis:6379
BCRYPT_COST         = 10
DB_POOL_MAX         = 20
CACHE_TTL_SECONDS   = 30
USER_SERVICE_URL    = http://java-user:8080      (order service only)
PRODUCT_SERVICE_URL = http://java-product:8080   (order service only)
```

`DATABASE_URL` uses the SPEC `postgres://user:pass@host:port/db` form and is
parsed into a JDBC URL by `DataSourceConfig` (Spring Boot cannot consume that
URI directly).

## Health & readiness (SPEC §6)

On startup, `StartupRunner` retries DB (`SELECT 1`) and Redis (`PING`) for up to
~30s, creates the schema idempotently (`CREATE TABLE IF NOT EXISTS`), then flips
the readiness flag. `GET /health` returns `200 {"status":"ok"}` once ready,
`503` while starting. If neither dependency comes up within the window the
process exits so the orchestrator can restart it.

## Build & run

> **Java 25 is required.** The `pom.xml` targets `--release 25`. If your host
> only has Java 11 (`java -version`), install a 25+ JDK first, e.g.
> `sdk install java 25-tem` (SDKMAN), or build inside Docker (below), which
> pins Java 25. This repo was compiled and packaged successfully with a
> JDK 25 compiler using `--release 25`.

### Local (Maven)

```bash
# Needs a JDK 25+ on PATH and a reachable Postgres + Redis.
mvn -q -DskipTests package

SERVICE_NAME=user STACK_NAME=java PORT=8021 \
DATABASE_URL=postgres://appuser:appsecret@localhost:5432/java_db \
REDIS_URL=redis://localhost:6379 \
java -jar target/app.jar
```

Swap `SERVICE_NAME`/`PORT` for `product` (8022) or `order` (8023). The Order
service also needs `USER_SERVICE_URL` and `PRODUCT_SERVICE_URL`.

### Docker (single image, three services)

```bash
docker build -t thesis/java-stack:latest .

# User service
docker run --rm -p 8021:8080 \
  -e SERVICE_NAME=user \
  -e DATABASE_URL=postgres://appuser:appsecret@postgres:5432/java_db \
  -e REDIS_URL=redis://redis:6379 \
  thesis/java-stack:latest
```

The image is multi-stage (Maven+JDK25 build → JRE25 runtime), runs as a
non-root user, `EXPOSE`s 8080, and has a `HEALTHCHECK` hitting `/health`. Set
the container CPU limit to `1.0` and memory to `512Mi` (SPEC §2) in
compose/k8s.

## Quick smoke test

```bash
# User service on 8021
curl -s localhost:8021/health
curl -s -XPOST localhost:8021/users/register -H 'content-type: application/json' \
  -d '{"username":"alice","password":"secret"}'
curl -s -XPOST localhost:8021/users/login -H 'content-type: application/json' \
  -d '{"username":"alice","password":"secret"}'
curl -s localhost:8021/metrics | grep http_request_duration_seconds | head
```

## Layout

```
services/java/
├── pom.xml
├── Dockerfile
├── README.md
└── src/main/
    ├── java/com/thesis/app/
    │   ├── Application.java              # SERVICE_NAME-driven single app
    │   ├── config/                       # AppProperties, DataSource(Hikari 20), RestClient, bcrypt executor
    │   ├── bcrypt/BcryptService.java     # bcrypt(10) offloaded to bounded pool
    │   ├── metrics/                      # 72-bucket histogram, servlet filter, /metrics controller
    │   ├── health/                       # readiness retry (DB+Redis, ~30s) + /health
    │   ├── user/  product/  order/       # the three services (conditional controllers)
    │   └── common/GlobalExceptionHandler.java
    └── resources/
        ├── application.yml
        └── schema.sql                    # reference DDL (also ensured at startup)
```

## Compile status

`mvn -DskipTests compile` and `mvn -DskipTests package` both **BUILD SUCCESS**
(compiled with a JDK 25 toolchain targeting `--release 25`; runtime target is
Java 25). The fat jar is produced at `target/app.jar`.
