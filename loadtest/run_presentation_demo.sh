#!/usr/bin/env bash
# =============================================================================
# ONE-SHOT PRESENTATION DEMO — predictive auto-scaling (go stack, 1 -> up -> 1)
#
# Satu perintah buat presentasi. Dia:
#   1. Nyalain semua port-forward yang diperlukan (prometheus + go services)
#   2. Start ML serve endpoint (live P95 forecast dari Prometheus in-cluster)
#   3. Tunggu go pods READY
#   4. Jalanin demo scaling (k6 ramp UP -> HOLD -> DOWN) + predictive controller
#   5. Bersih-bersih port-forward pas selesai
#
# CARA PAKAI (share screen: buka `k9s` di window lain, filter /go):
#   bash loadtest/run_presentation_demo.sh
#
# Yang lu lihat: replica go-user 1 -> naik (pas beban datang, SEBELUM CPU tinggi)
#                -> turun balik ke 1 pas idle. Itu inti kontribusi thesis.
# =============================================================================
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

NS=pas-thesis
PY="ml/.venv/bin/python"
PF_PIDS=()

log() { printf "\033[1;36m[demo]\033[0m %s\n" "$*"; }
ok()  { printf "\033[1;32m  ✓\033[0m %s\n" "$*"; }

cleanup() {
  log "cleanup: matiin serve + port-forwards"
  [ -n "${SERVE_PID:-}" ] && kill "$SERVE_PID" 2>/dev/null || true
  for p in "${PF_PIDS[@]:-}"; do kill "$p" 2>/dev/null || true; done
  pkill -f "kubectl.*port-forward.*pas-thesis" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# --- 0. sanity: cluster + pods ----------------------------------------------
log "cek cluster + go pods..."
kubectl get ns "$NS" >/dev/null 2>&1 || { echo "ERROR: namespace $NS gak ada. Jalanin: kubectl apply -k infra/k8s/demo"; exit 1; }

log "nunggu go pods READY (max 90s)..."
kubectl wait -n "$NS" --for=condition=ready pod -l 'app in (go-user,go-product,go-order)' --timeout=90s >/dev/null 2>&1 \
  && ok "go pods ready" || log "WARNING: sebagian go pods belum ready, lanjut aja"

# --- 1. pastikan mulai dari 1 replica ---------------------------------------
for d in go-user go-product go-order; do kubectl -n "$NS" scale deploy "$d" --replicas=1 >/dev/null 2>&1 || true; done
ok "reset ke 1 replica (baseline)"

# --- 2. port-forwards -------------------------------------------------------
log "buka port-forwards..."
kubectl -n "$NS" port-forward svc/prometheus-demo 9092:9090 >/dev/null 2>&1 & PF_PIDS+=($!)
kubectl -n "$NS" port-forward svc/go-user    18001:8080 >/dev/null 2>&1 & PF_PIDS+=($!)
kubectl -n "$NS" port-forward svc/go-product 18002:8080 >/dev/null 2>&1 & PF_PIDS+=($!)
kubectl -n "$NS" port-forward svc/go-order   18003:8080 >/dev/null 2>&1 & PF_PIDS+=($!)
sleep 4
curl -sf http://localhost:9092/-/ready >/dev/null 2>&1 && ok "prometheus reachable :9092" || log "WARN prometheus belum ready"
curl -sf http://localhost:18001/health  >/dev/null 2>&1 && ok "go-user reachable :18001"     || log "WARN go-user belum ready"

# --- 3. ML serve (live forecast) --------------------------------------------
log "start ML serve endpoint (live P95 forecast)..."
PROMETHEUS_URL=http://localhost:9092 "$PY" ml/serve.py > results/scaling/presentation_serve.log 2>&1 & SERVE_PID=$!
sleep 6
if curl -sf "http://localhost:8000/predict?stack=go" >/dev/null 2>&1; then
  P=$(curl -s "http://localhost:8000/predict?stack=go")
  ok "serve up — sample: $P"
else
  log "WARN serve belum jawab, tunggu 4s lagi..."; sleep 4
fi

# --- 4. jalanin demo scaling (go 1 -> up -> 1) ------------------------------
echo ""
log "=============================================="
log " MULAI DEMO — tonton di k9s (filter /go)"
log " replica bakal NAIK pas beban datang, TURUN pas idle"
log "=============================================="
echo ""
# profil beban lebih pendek biar muat presentasi ~5-6 menit total
TARGET="${TARGET:-80}" RAMP_UP="${RAMP_UP:-75s}" HOLD="${HOLD:-45s}" RAMP_DOWN="${RAMP_DOWN:-30s}" \
IDLE_TAIL="${IDLE_TAIL:-150}" \
  bash loadtest/run_visual_demo.sh

echo ""
log "DEMO SELESAI. Timeline + chart di results/scaling/ & results/charts/"
