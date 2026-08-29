# syntax=docker/dockerfile:1

# ---- Build stage ------------------------------------------------------------
FROM rust:1.90-slim AS builder
WORKDIR /app

# Cache dependencies: build a dummy binary against the manifests first.
COPY Cargo.toml Cargo.lock* ./
RUN mkdir src && echo 'fn main() {}' > src/main.rs \
    && cargo build --release \
    && rm -rf src

# Now build the real sources.
COPY src ./src
# Bust the cached dummy artifact so the real main.rs is recompiled.
RUN touch src/main.rs && cargo build --release

# ---- Runtime stage ----------------------------------------------------------
FROM debian:bookworm-slim AS runtime
WORKDIR /app

# ca-certificates for any TLS; curl for the healthcheck. Then a non-root user.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 appuser

COPY --from=builder /app/target/release/server /usr/local/bin/server

USER appuser
ENV PORT=8080
EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=5 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

# SERVICE_NAME (user|product|order) is provided at runtime via env.
ENTRYPOINT ["server"]
