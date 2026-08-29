#!/usr/bin/env bash
# =============================================================
# Orchestrated VISUAL predictive-scaling demo.
#
# Starts the predictive controller (go stack, live predictions), samples the
# go deployment replica counts every 10s into a timeline CSV, then drives a
# k6 load profile that ramps UP (pods scale up) and DOWN (pods scale down).
#
# Prereqs (already running for the demo):
#   * kubectl apply -k infra/k8s/demo   (go stack + in-cluster prometheus)
#   * kubectl -n pas-thesis port-forward svc/prometheus-demo 9092:9090
#   * PROMETHEUS_URL=http://localhost:9092 ml/.venv/bin/python ml/serve.py &
#   * kubectl -n pas-thesis port-forward svc/go-user    18001:8080 &
#     kubectl -n pas-thesis port-forward svc/go-product 18002:8080 &
#     kubectl -n pas-thesis port-forward svc/go-order   18003:8080 &
# =============================================================
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

TS="$(date +%Y%m%d_%H%M%S)"
NS=pas-thesis
DEPLOYS=(go-user go-product go-order)
TIMELINE="results/scaling/${TS}_replica_timeline.csv"
DECISIONS="results/scaling/${TS}_decisions.jsonl"
IDLE_TAIL="${IDLE_TAIL:-240}"   # seconds of idle sampling after k6 (scale-down)

mkdir -p results/scaling controller/logs
echo "ts,deploy,replicas" > "$TIMELINE"
echo "[demo] run id: $TS"
echo "[demo] timeline : $TIMELINE"
echo "[demo] decisions: $DECISIONS"

# --- replica sampler (every 10s) -------------------------------------------
sample_replicas() {
  while true; do
    now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    for d in "${DEPLOYS[@]}"; do
      r="$(kubectl -n "$NS" get deploy "$d" -o jsonpath='{.status.replicas}' 2>/dev/null || echo)"
      [ -z "$r" ] && r=0
      echo "${now},${d},${r}" >> "$TIMELINE"
    done
    sleep 10
  done
}
sample_replicas &
SAMPLER_PID=$!
echo "[demo] sampler pid $SAMPLER_PID"

# --- predictive controller --------------------------------------------------
DRY_RUN=false \
NAMESPACE="$NS" \
MANAGED_STACKS=go \
PREDICT_URL=http://localhost:8000/predict \
INTERVAL_SECONDS=10 \
MIN_REPLICAS=1 MAX_REPLICAS=8 \
SCALE_UP_THRESHOLD=500 SCALE_DOWN_THRESHOLD=250 \
COOLDOWN_SECONDS=15 UP_STEP_CAP=2 \
ENABLE_METRICS=false \
RESULTS_LOG_PATH="$DECISIONS" \
controller/../ml/.venv/bin/python controller/predictive_controller.py \
  > "results/scaling/${TS}_controller.log" 2>&1 &
CTRL_PID=$!
echo "[demo] controller pid $CTRL_PID"

cleanup() {
  echo "[demo] stopping controller + sampler"
  kill "$CTRL_PID" 2>/dev/null || true
  sleep 2
  kill "$SAMPLER_PID" 2>/dev/null || true
}
trap cleanup EXIT

sleep 5   # let the controller take one baseline tick at 1 replica

# --- k6 load profile: ramp UP -> hold -> ramp DOWN --------------------------
echo "[demo] starting k6 load profile"
TARGET="${TARGET:-80}" RAMP_UP="${RAMP_UP:-90s}" HOLD="${HOLD:-60s}" RAMP_DOWN="${RAMP_DOWN:-60s}" \
  k6 run loadtest/scenarios/visual-demo.js \
  > "results/scaling/${TS}_k6.log" 2>&1 || true
echo "[demo] k6 finished; idle tail ${IDLE_TAIL}s (watch scale-down)"

# --- idle tail: no load -> prediction falls -> controller scales DOWN --------
sleep "$IDLE_TAIL"

cleanup
trap - EXIT
echo "[demo] DONE. run id: $TS"
echo "TS=$TS"
