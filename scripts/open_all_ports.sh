#!/usr/bin/env bash
# =============================================================================
# Buka SEMUA port-forward buat presentasi, sekali jalan.
# Biarin jalan di satu terminal (jangan ditutup). Ctrl-C = matiin semua.
#
#   bash scripts/open_all_ports.sh
#
# Setelah ini, tinggal buka di browser:
#   ArgoCD    https://localhost:8090   (admin / <password di bawah>)
#   Portainer http://localhost:9000    (admin / portainerthesis1)
#   Grafana   http://localhost:3001    (admin / admin)      [docker, bukan port-forward]
#   Jaeger    http://localhost:16687                        [docker]
#   Prom(K8s) http://localhost:9092
#   ML serve  http://localhost:8000/predict?stack=go
# =============================================================================
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
NS=pas-thesis
PIDS=()

cleanup() { echo; echo "[ports] matiin semua port-forward..."; for p in "${PIDS[@]:-}"; do kill "$p" 2>/dev/null || true; done; pkill -f "kubectl.*port-forward" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

pf() { kubectl -n "$2" port-forward "$3" "$4" >/dev/null 2>&1 & PIDS+=($!); printf "  ✓ %-12s %s\n" "$1" "$4"; }

echo "[ports] buka port-forward K8s..."
pf "ArgoCD"     argocd    svc/argocd-server    8090:443
pf "Portainer"  portainer svc/portainer        9000:9000
pf "Prometheus" "$NS"     svc/prometheus-demo  9092:9090
pf "go-user"    "$NS"     svc/go-user          18001:8080
pf "rust-user"  "$NS"     svc/rust-user        18011:8080
pf "java-user"  "$NS"     svc/java-user        18021:8080
pf "node-user"  "$NS"     svc/node-user        18031:8080

sleep 4
echo ""
echo "[ports] ✅ semua kebuka. Password ArgoCD:"
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" 2>/dev/null | base64 -d; echo
echo ""
echo "  ArgoCD    https://localhost:8090   (admin / ^ di atas)"
echo "  Portainer http://localhost:9000    (admin / portainerthesis1)"
echo "  Grafana   http://localhost:3001    (admin / admin)"
echo "  Jaeger    http://localhost:16687"
echo "  Prom K8s  http://localhost:9092"
echo ""
echo "[ports] biarin terminal ini jalan. Ctrl-C buat matiin semua."
wait
