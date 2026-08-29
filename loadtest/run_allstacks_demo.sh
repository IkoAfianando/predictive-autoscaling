#!/usr/bin/env bash
# =============================================================
# Orchestrated ALL-FOUR-STACKS predictive-scaling demo.
#
# Starts the predictive controller (managing go+rust+java+node), samples every
# stack's deployment replica counts into a timeline CSV, drives a STAGGERED k6
# ramp (one stack after another), then idles so every stack scales back down.
#
# Prereqs (see docs/ARGOCD-AND-ALLSTACKS-DEMO.md):
#   * kubectl apply -k infra/k8s/demo-allstacks   (all 4 stacks + prometheus)
#   * bash loadtest/pf_keeper.sh &                 (13 resilient port-forwards)
#   * PROMETHEUS_URL=http://localhost:9092 LIVE_WINDOW_SECONDS=300 \
#       ml/.venv/bin/python ml/serve.py --port 8000 &   (LIVE prediction)
#
# Per-stack thresholds are passed below (the four stacks' models have very
# different idle/loaded forecast baselines — see the doc).
# =============================================================
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

TS="$(date +%Y%m%d_%H%M%S)"
NS=pas-thesis
STACKS=(go rust java node)
SERVICES=(user product order)
TIMELINE="results/scaling/allstacks_${TS}_replica_timeline.csv"
DECISIONS="results/scaling/allstacks_${TS}_decisions.jsonl"
IDLE_TAIL="${IDLE_TAIL:-200}"

mkdir -p results/scaling controller/logs
echo "ts,elapsed,stack,service,deploy,replicas" > "$TIMELINE"
echo "[demo] run id: $TS"
echo "[demo] timeline : $TIMELINE"
echo "[demo] decisions: $DECISIONS"

T0=$(date +%s)
sample_replicas() {
  while true; do
    now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"; el=$(( $(date +%s) - T0 ))
    for s in "${STACKS[@]}"; do for svc in "${SERVICES[@]}"; do
      d="${s}-${svc}"
      r="$(kubectl -n "$NS" get deploy "$d" -o jsonpath='{.status.replicas}' 2>/dev/null || echo)"
      [ -z "$r" ] && r=0
      echo "${now},${el},${s},${svc},${d},${r}" >> "$TIMELINE"
    done; done
    sleep 5
  done
}
sample_replicas & SAMPLER_PID=$!
echo "[demo] sampler pid $SAMPLER_PID"

# --- light baseline trickle (keeps the live P95 window FRESH) ---------------
# Without a steady low trickle, a stack that goes fully silent produces sparse
# Prometheus samples and the derived rolling features spike (esp. node, which
# otherwise sticks ~1400 ms with zero load) — so the forecast never falls and
# the stack never scales DOWN. A gentle ~2 req/s/stack keeps p95 genuinely low
# and stable, so idle forecasts return to their true floor and scale-down works.
PORTS=(18001:18002:18003 18011:18012:18013 18021:18022:18023 18031:18032:18033)
trickle() {
  while true; do
    for b in "${PORTS[@]}"; do
      u="${b%%:*}"; rest="${b#*:}"; p="${rest%%:*}"
      curl -s -o /dev/null -X POST "http://localhost:$u/users/register" \
        -H 'content-type: application/json' -d "{\"username\":\"trk_${RANDOM}\",\"password\":\"pw123\"}" &
      curl -s -o /dev/null "http://localhost:$p/products/1" &
    done
    sleep 1
  done
}
trickle & TRICKLE_PID=$!
echo "[demo] trickle pid $TRICKLE_PID"

# --- warm-up: let the trickle bring every stack's forecast down to its idle
#     floor BEFORE the controller starts, otherwise sparse-data spikes at t=0
#     would scale everything up spuriously. ---------------------------------
WARMUP="${WARMUP:-45}"
echo "[demo] warm-up ${WARMUP}s (settle forecasts to idle floor before scaling)"
sleep "$WARMUP"

# --- predictive controller (all 4 stacks, per-stack thresholds) -------------
# Per-stack thresholds — the four models have very different forecast bands
# (calibrated live idle -> loaded-peak, ms: go 4->4750, rust 2->3645,
#  java 370->3400, node 309->2977). Each stack gets its own up/down band.
# NOTE: keep this a single unbroken backslash-continued command — do NOT insert
# comment lines between the continuations or the env stops reaching python.
DRY_RUN=false \
NAMESPACE="$NS" \
MANAGED_STACKS="${MANAGED_STACKS:-go,rust,java,node}" \
PREDICT_URL=http://localhost:8000/predict \
PREDICT_TIMEOUT_SECONDS="${PREDICT_TIMEOUT_SECONDS:-15}" \
INTERVAL_SECONDS="${INTERVAL_SECONDS:-10}" \
MIN_REPLICAS=1 MAX_REPLICAS="${MAX_REPLICAS:-4}" \
UP_STEP_CAP="${UP_STEP_CAP:-2}" COOLDOWN_SECONDS="${COOLDOWN_SECONDS:-15}" \
SCALE_UP_THRESHOLD="${SCALE_UP_THRESHOLD:-300}" SCALE_DOWN_THRESHOLD="${SCALE_DOWN_THRESHOLD:-150}" \
SCALE_UP_THRESHOLD_GO="${SCALE_UP_THRESHOLD_GO:-250}"     SCALE_DOWN_THRESHOLD_GO="${SCALE_DOWN_THRESHOLD_GO:-100}" \
SCALE_UP_THRESHOLD_RUST="${SCALE_UP_THRESHOLD_RUST:-250}"  SCALE_DOWN_THRESHOLD_RUST="${SCALE_DOWN_THRESHOLD_RUST:-100}" \
SCALE_UP_THRESHOLD_JAVA="${SCALE_UP_THRESHOLD_JAVA:-750}"  SCALE_DOWN_THRESHOLD_JAVA="${SCALE_DOWN_THRESHOLD_JAVA:-500}" \
SCALE_UP_THRESHOLD_NODE="${SCALE_UP_THRESHOLD_NODE:-550}"  SCALE_DOWN_THRESHOLD_NODE="${SCALE_DOWN_THRESHOLD_NODE:-380}" \
ENABLE_METRICS=false \
RESULTS_LOG_PATH="$DECISIONS" \
ml/.venv/bin/python controller/predictive_controller.py \
  > "results/scaling/allstacks_${TS}_controller.log" 2>&1 &
CTRL_PID=$!
echo "[demo] controller pid $CTRL_PID"

cleanup() {
  echo "[demo] stopping controller + sampler + trickle"
  kill "$CTRL_PID" 2>/dev/null || true; sleep 2
  kill "$SAMPLER_PID" 2>/dev/null || true
  kill "$TRICKLE_PID" 2>/dev/null || true
  pkill -P "$TRICKLE_PID" 2>/dev/null || true
}
trap cleanup EXIT
sleep 5   # baseline tick at 1 replica

echo "[demo] starting staggered k6 ramp (go -> rust -> java -> node)"
TARGET="${TARGET:-70}" k6 run loadtest/scenarios/allstacks-demo.js \
  > "results/scaling/allstacks_${TS}_k6.log" 2>&1 || true
echo "[demo] k6 done; idle tail ${IDLE_TAIL}s (watch every stack scale DOWN)"
sleep "$IDLE_TAIL"

cleanup
trap - EXIT
echo "[demo] DONE. run id: $TS"
echo "TS=$TS"
