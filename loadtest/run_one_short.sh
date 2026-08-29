#!/usr/bin/env bash
# Run one shortened scenario against one stack, record the exact k6 window,
# then collect + train via ml/scenario_run.py. Keeps stacks isolated (one k6
# process at a time) so there is no CPU contention between stacks.
set -euo pipefail
SCEN="$1"; STACK="$2"
ROOT="/Users/ikoafian/LEARN/RISET/predictive-autoscaling-thesis"
cd "$ROOT/loadtest"
START=$(python3 -c "import time;print(time.time())")
echo ">>> [$SCEN/$STACK] k6 start $(date -u +%H:%M:%S)"
k6 run -e STACK="$STACK" -e SCEN="$SCEN" scenarios/short.js \
  --quiet --no-summary >/dev/null 2>"$ROOT/loadtest/campaign_logs/k6_${SCEN}_${STACK}.err" || true
END=$(python3 -c "import time;print(time.time())")
echo ">>> [$SCEN/$STACK] k6 end   $(date -u +%H:%M:%S)  (dur $(python3 -c "print(round(($END-$START)/60,2))")min)"
echo ">>> waiting 15s for final Prometheus scrapes..."
sleep 15
"$ROOT/ml/.venv/bin/python" "$ROOT/ml/scenario_run.py" \
  --scenario "$SCEN" --stack "$STACK" --start "$START" --end "$END" --step 5
