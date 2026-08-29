#!/usr/bin/env bash
# Resilient kubectl port-forwards for the all-stacks demo. Each forward is kept
# alive in its own retry loop (port-forwards can drop under connection churn).
#   bash loadtest/pf_keeper.sh    # runs in foreground; Ctrl-C stops all
set -u
NS=pas-thesis
# local_port:service
MAP=(
  "9092:prometheus-demo:9090"
  "18001:go-user:8080"    "18002:go-product:8080"    "18003:go-order:8080"
  "18011:rust-user:8080"  "18012:rust-product:8080"  "18013:rust-order:8080"
  "18021:java-user:8080"  "18022:java-product:8080"  "18023:java-order:8080"
  "18031:node-user:8080"  "18032:node-product:8080"  "18033:node-order:8080"
)
pids=()
for m in "${MAP[@]}"; do
  lp="${m%%:*}"; rest="${m#*:}"; svc="${rest%%:*}"; rp="${rest##*:}"
  (
    while true; do
      kubectl -n "$NS" port-forward "svc/$svc" "$lp:$rp" >/dev/null 2>&1
      sleep 1
    done
  ) &
  pids+=($!)
done
echo "pf_keeper: ${#pids[@]} forwards up (pids: ${pids[*]})"
trap 'kill ${pids[*]} 2>/dev/null; pkill -P $$ 2>/dev/null' EXIT INT TERM
wait
