#!/usr/bin/env bash
# =============================================================================
# ABLATION STUDY RUNNER — 4 scenarios x 4 sub-scenarios = 16 k6 runs for ONE
# stack, against the LIVE predictive-autoscaling cluster.
#
# For every combination it captures, into
#   2026-08-28_e2e-ablation-training/logs/ :
#     <name>.log          full k6 stdout+stderr (the human-readable run report)
#     <name>.summary.json k6 --summary-export machine-readable metrics summary
#     <name>.meta.json    run metadata (timestamps, scenario, sub, stack, params)
# where <name> = s<N>_<scenario>_sub<S>_<stack>_<timestamp>.
#
# It DRIVES LOAD (k6 run). Do NOT start it while the cluster is in use by another
# process. PREREQUISITES (all must already be running — this script does NOT
# start them, mirroring loadtest/run_visual_demo.sh / run_allstacks_demo.sh):
#
#   1. K8s cluster up, namespace pas-thesis, the target stack deployed:
#        kubectl apply -k infra/k8s/demo-allstacks    (or .../demo for go only)
#   2. Port-forwards for the target stack's user/product/order (+ prometheus):
#        bash loadtest/pf_keeper.sh &                  (all 13 forwards)
#   3. ML serve endpoint (live P95 forecast from in-cluster prometheus):
#        PROMETHEUS_URL=http://localhost:9092 ml/.venv/bin/python ml/serve.py &
#   4. Predictive controller managing the target stack (see run_allstacks_demo.sh
#        for the full env block, e.g. MANAGED_STACKS, per-stack thresholds):
#        ... controller/predictive_controller.py &
#
# USAGE:
#   bash loadtest/ablation/run_ablation.sh                 # STACK=go, full run
#   STACK=rust bash loadtest/ablation/run_ablation.sh      # a different stack
#   ONLY=s1,s3 bash loadtest/ablation/run_ablation.sh      # subset of scenarios
#   SUBS=1,2   bash loadtest/ablation/run_ablation.sh      # subset of sub-scenarios
#   IDLE_TAIL=180 bash loadtest/ablation/run_ablation.sh   # idle gap between runs
#   SOAK_HOLD=5m bash loadtest/ablation/run_ablation.sh    # shorten the soaks
#   DRY_RUN=1 bash loadtest/ablation/run_ablation.sh       # print plan, run nothing
#
# Any per-scenario override env (BASE, PEAK, LEVEL, CEIL, SOAK_HOLD, RAMP, ...)
# is passed straight through to k6, so the campaign is fully tunable.
# =============================================================================
set -uo pipefail

# --- locate repo root (this script lives in loadtest/ablation/) --------------
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

ABL_DIR="loadtest/ablation"
LOG_DIR="2026-08-28_e2e-ablation-training/logs"
mkdir -p "$LOG_DIR"

# --- config ------------------------------------------------------------------
STACK="${STACK:-go}"
IDLE_TAIL="${IDLE_TAIL:-120}"   # seconds of idle between runs (let controller scale DOWN)
DRY_RUN="${DRY_RUN:-0}"

# Scenario registry (bash 3.2 compatible — no associative arrays).
# Each entry: "key:script.js:human_name"
SCENARIOS=(
  "s1:s1_flash_sale.js:flash_sale"
  "s2:s2_daily_peak.js:daily_peak"
  "s3:s3_payday_soak.js:payday_soak"
  "s4:s4_viral_stress.js:viral_stress"
)

# Optional filters: ONLY=s1,s3  and  SUBS=1,2
ONLY="${ONLY:-}"
SUBS="${SUBS:-1 2 3 4}"
SUBS="${SUBS//,/ }"

want_scenario() {
  [ -z "$ONLY" ] && return 0
  case ",${ONLY//[[:space:]]/}," in *",$1,"*) return 0;; *) return 1;; esac
}

# --- validate stack early ----------------------------------------------------
case "$STACK" in go|rust|java|node) ;; *)
  echo "ERROR: STACK must be one of go|rust|java|node (got '$STACK')"; exit 1;; esac

# --- port-forward reachability warning (non-fatal) ---------------------------
case "$STACK" in
  go)   UP=18001;; rust) UP=18011;; java) UP=18021;; node) UP=18031;;
esac
if ! curl -sf "http://localhost:${UP}/health" >/dev/null 2>&1; then
  echo "WARNING: http://localhost:${UP}/health not reachable."
  echo "         Is pf_keeper.sh running and the $STACK stack deployed? Continuing anyway."
fi

RUN_ID="$(date +%Y%m%d_%H%M%S)"
echo "==================================================================="
echo " ABLATION STUDY — stack=$STACK  run_id=$RUN_ID"
echo " scenarios : ${ONLY:-all(s1..s4)}   subs: $SUBS"
echo " idle tail : ${IDLE_TAIL}s between runs"
echo " log dir   : $LOG_DIR"
echo " dry run   : $DRY_RUN"
echo "==================================================================="

INDEX="$LOG_DIR/ablation_index_${STACK}_${RUN_ID}.csv"
echo "scenario,sub,stack,timestamp,log,summary,meta,exit_code,started_at,ended_at" > "$INDEX"

total=0; done=0; failed=0

for entry in "${SCENARIOS[@]}"; do
  key="${entry%%:*}"
  rest="${entry#*:}"
  scriptfile="${rest%%:*}"
  sname="${rest##*:}"
  want_scenario "$key" || continue
  script="$ABL_DIR/${scriptfile}"
  for sub in $SUBS; do
    total=$((total+1))
    TS="$(date +%Y%m%d_%H%M%S)"
    base="${key}_${sname}_sub${sub}_${STACK}_${TS}"
    LOG="$LOG_DIR/${base}.log"
    SUMMARY="$LOG_DIR/${base}.summary.json"
    META="$LOG_DIR/${base}.meta.json"

    echo ""
    echo "-------------------------------------------------------------------"
    echo "[$total] ${key} (${sname})  sub=${sub}  stack=${STACK}"
    echo "    log     : $LOG"
    echo "    summary : $SUMMARY"

    if [ "$DRY_RUN" = "1" ]; then
      echo "    DRY_RUN: would run -> k6 run -e STACK=$STACK -e SUB=$sub --summary-export=$SUMMARY $script"
      continue
    fi

    started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

    # --- metadata sidecar (written BEFORE the run so a crash still leaves it) --
    cat > "$META" <<JSON
{
  "run_id": "$RUN_ID",
  "scenario_key": "$key",
  "scenario_name": "$sname",
  "sub": $sub,
  "stack": "$STACK",
  "script": "$script",
  "timestamp": "$TS",
  "started_at": "$started_at",
  "log_file": "${base}.log",
  "summary_file": "${base}.summary.json",
  "idle_tail_seconds": $IDLE_TAIL,
  "k6_version": "$(k6 version 2>/dev/null | head -1)",
  "env_overrides": {
    "BASE": "${BASE:-}", "PEAK": "${PEAK:-}", "LEVEL": "${LEVEL:-}",
    "CEIL": "${CEIL:-}", "RAMP": "${RAMP:-}", "HOLD": "${HOLD:-}",
    "SOAK_HOLD": "${SOAK_HOLD:-}", "THINK": "${THINK:-}"
  }
}
JSON

    # --- the run: full stdout+stderr -> LOG, machine summary -> SUMMARY -------
    # k6's exit code is captured; threshold breaches (exit 99) are recorded, not
    # treated as a hard failure — ablation runs are observational.
    k6 run \
      -e STACK="$STACK" \
      -e SUB="$sub" \
      --summary-export="$SUMMARY" \
      "$script" \
      >"$LOG" 2>&1
    rc=$?
    ended_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

    if [ $rc -eq 0 ]; then
      echo "    -> OK (exit 0)"; done=$((done+1))
    elif [ $rc -eq 99 ]; then
      echo "    -> completed with threshold breach (exit 99) — recorded"; done=$((done+1))
    else
      echo "    -> k6 exited $rc (see $LOG)"; failed=$((failed+1))
    fi

    # --- rewrite meta with the completed-run fields (portable, no sed) --------
    cat > "$META" <<JSON
{
  "run_id": "$RUN_ID",
  "scenario_key": "$key",
  "scenario_name": "$sname",
  "sub": $sub,
  "stack": "$STACK",
  "script": "$script",
  "timestamp": "$TS",
  "started_at": "$started_at",
  "ended_at": "$ended_at",
  "exit_code": $rc,
  "log_file": "${base}.log",
  "summary_file": "${base}.summary.json",
  "idle_tail_seconds": $IDLE_TAIL,
  "k6_version": "$(k6 version 2>/dev/null | head -1)",
  "env_overrides": {
    "BASE": "${BASE:-}", "PEAK": "${PEAK:-}", "LEVEL": "${LEVEL:-}",
    "CEIL": "${CEIL:-}", "RAMP": "${RAMP:-}", "HOLD": "${HOLD:-}",
    "SOAK_HOLD": "${SOAK_HOLD:-}", "THINK": "${THINK:-}"
  }
}
JSON

    echo "$key,$sub,$STACK,$TS,${base}.log,${base}.summary.json,${base}.meta.json,$rc,$started_at,$ended_at" >> "$INDEX"

    # --- idle gap: let load fall so the predictive controller scales DOWN -----
    if [ "$IDLE_TAIL" -gt 0 ]; then
      echo "    idle ${IDLE_TAIL}s (controller scales back to baseline)..."
      sleep "$IDLE_TAIL"
    fi
  done
done

echo ""
echo "==================================================================="
echo " ABLATION DONE — stack=$STACK  planned=$total  ok=$done  failed=$failed"
echo " index: $INDEX"
echo " logs : $LOG_DIR"
echo "==================================================================="
