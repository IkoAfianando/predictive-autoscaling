#!/usr/bin/env bash
# Wait until all backend services report /health ok
set -euo pipefail
declare -A PORTS=(
  [go-user]=8001 [go-product]=8002 [go-order]=8003
  [rust-user]=8011 [rust-product]=8012 [rust-order]=8013
  [java-user]=8021 [java-product]=8022 [java-order]=8023
  [node-user]=8031 [node-product]=8032 [node-order]=8033
)
for name in "${!PORTS[@]}"; do
  port=${PORTS[$name]}
  printf "waiting for %-14s (:%s) ... " "$name" "$port"
  for i in $(seq 1 60); do
    if curl -sf "http://localhost:$port/health" >/dev/null 2>&1; then echo "ok"; break; fi
    sleep 2
    [ "$i" -eq 60 ] && echo "TIMEOUT"
  done
done
echo "done."
