# syntax=docker/dockerfile:1

# ---- Build stage ----
FROM golang:1.22-alpine AS build
WORKDIR /src

# Cache module downloads.
COPY go.mod go.sum ./
RUN go mod download

# Build a static binary.
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/server ./cmd/server

# ---- Runtime stage ----
FROM alpine:3.20
# wget (for HEALTHCHECK) + CA certs (for the Order service fan-out over HTTP/S).
RUN apk add --no-cache ca-certificates wget \
    && addgroup -S app && adduser -S -G app app

COPY --from=build /out/server /usr/local/bin/server

USER app
EXPOSE 8080

# One image parameterized by SERVICE_NAME (SPEC §7). Override at runtime:
#   docker run -e SERVICE_NAME=user|product|order ...
ENV SERVICE_NAME=user \
    STACK_NAME=go \
    PORT=8080

HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=5 \
    CMD wget -qO- http://127.0.0.1:8080/health || exit 1

ENTRYPOINT ["/usr/local/bin/server"]
