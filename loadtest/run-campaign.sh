#!/usr/bin/env bash
cd "$(dirname "$0")/.."
ROUNDS=${1:-6}
for round in $(seq 1 $ROUNDS); do
  for s in go rust java node; do
    echo "$(date '+%H:%M:%S') round=$round stack=$s START" >> loadtest/campaign_logs/progress.log
    k6 run -e STACK=$s --quiet loadtest/scenarios/wave.js >> loadtest/campaign_logs/${s}.log 2>&1
    echo "$(date '+%H:%M:%S') round=$round stack=$s DONE" >> loadtest/campaign_logs/progress.log
  done
done
echo "$(date '+%H:%M:%S') CAMPAIGN COMPLETE ($ROUNDS rounds)" >> loadtest/campaign_logs/progress.log
