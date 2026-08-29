#!/usr/bin/env bash
# =============================================================================
# IN-CLUSTER k6 scaling load runner.
#
# Runs the k6 load Job (k6-job.yaml) INSIDE the cluster for one stack, so the
# load generator talks to services over ClusterIP DNS and survives pod churn —
# no `kubectl port-forward`, which is pinned to a single pod and dies when the
# controller scales/replaces it.
#
# WHAT IT DOES, for STACK in {go,rust,java,node}:
#   1. Applies the k6 script ConfigMap (k6-load-configmap.yaml).
#   2. Renders k6-job.yaml with __STACK__ substituted, deletes any prior Job of
#      the same name, then applies the fresh Job.
#   3. Waits for the Job to complete (or fail / time out).
#   4. Streams k6 stdout with `kubectl logs` and saves it under results/.
#
# It DRIVES LOAD against the cluster. Do NOT start it while the cluster is in use
# by another process.
#
# PREREQUISITES (this script does NOT start them):
#   - K8s cluster up, namespace pas-thesis, the target stack deployed with its
#     three ClusterIP services (STACK-user / STACK-product / STACK-order :8080).
#   - The predictive/hybrid controller managing that stack, if you want to watch
#     it scale in response to the load.
#
# USAGE:
#   bash loadtest/incluster/run_incluster_scaling.sh                 # STACK=go
#   STACK=rust bash loadtest/incluster/run_incluster_scaling.sh      # another stack
#   TIMEOUT=900 STACK=java bash .../run_incluster_scaling.sh         # longer wait
#   DRY_RUN=1 bash .../run_incluster_scaling.sh                      # validate only
#   KEEP=1 bash .../run_incluster_scaling.sh                         # keep Job after
# =============================================================================
set -uo pipefail

NS=pas-thesis
STACK="${STACK:-go}"
TIMEOUT="${TIMEOUT:-1200}"     # seconds to wait for the Job to complete
DRY_RUN="${DRY_RUN:-0}"
KEEP="${KEEP:-0}"

case "$STACK" in go|rust|java|node) ;; *)
  echo "ERROR: STACK must be one of go|rust|java|node (got '$STACK')"; exit 1;; esac

# --- locate this script's dir (manifests live beside it) ---------------------
DIR="$(cd "$(dirname "$0")" && pwd)"
CM="$DIR/k6-load-configmap.yaml"
JOB_TMPL="$DIR/k6-job.yaml"
RESULTS="$DIR/results"
mkdir -p "$RESULTS"

JOB_NAME="k6-load-${STACK}"
TS="$(date +%Y%m%d_%H%M%S)"
RENDERED="$RESULTS/${JOB_NAME}_${TS}.job.yaml"
LOG="$RESULTS/${JOB_NAME}_${TS}.log"

# --- render the Job manifest (substitute __STACK__) --------------------------
sed "s/__STACK__/${STACK}/g" "$JOB_TMPL" > "$RENDERED"

echo "==================================================================="
echo " IN-CLUSTER k6 LOAD — stack=$STACK  ns=$NS"
echo " job      : $JOB_NAME"
echo " rendered : $RENDERED"
echo " log      : $LOG"
echo " timeout  : ${TIMEOUT}s   dry_run=$DRY_RUN   keep=$KEEP"
echo "==================================================================="

if [ "$DRY_RUN" = "1" ]; then
  echo "DRY_RUN: validating manifests (client-side), applying nothing."
  kubectl apply --dry-run=client -f "$CM"      || exit 1
  kubectl apply --dry-run=client -f "$RENDERED" || exit 1
  echo "DRY_RUN OK."
  exit 0
fi

# --- 1. ConfigMap (idempotent) ------------------------------------------------
kubectl apply -f "$CM"

# --- 2. fresh Job (delete any prior run of the same name) --------------------
kubectl -n "$NS" delete job "$JOB_NAME" --ignore-not-found --wait=true
kubectl apply -f "$RENDERED"

# --- 3. wait for completion (poll Complete vs Failed) ------------------------
echo "Waiting for Job/$JOB_NAME to finish (up to ${TIMEOUT}s)..."
kubectl -n "$NS" wait --for=condition=complete "job/$JOB_NAME" --timeout="${TIMEOUT}s" &
wait_complete=$!
kubectl -n "$NS" wait --for=condition=failed "job/$JOB_NAME" --timeout="${TIMEOUT}s" &
wait_failed=$!
# Whichever condition lands first wins; kill the other waiter.
wait -n "$wait_complete" "$wait_failed" 2>/dev/null
kill "$wait_complete" "$wait_failed" 2>/dev/null

# --- 4. capture k6 stdout (the run report) -----------------------------------
echo "Collecting k6 logs -> $LOG"
kubectl -n "$NS" logs "job/$JOB_NAME" --tail=-1 2>&1 | tee "$LOG"

# --- determine outcome --------------------------------------------------------
succeeded="$(kubectl -n "$NS" get job "$JOB_NAME" -o jsonpath='{.status.succeeded}' 2>/dev/null)"
failed_ct="$(kubectl -n "$NS" get job "$JOB_NAME" -o jsonpath='{.status.failed}' 2>/dev/null)"

echo "==================================================================="
if [ "${succeeded:-0}" = "1" ]; then
  echo " RESULT: Job succeeded. log=$LOG"
  rc=0
else
  echo " RESULT: Job did NOT report success (succeeded=${succeeded:-0} failed=${failed_ct:-0})."
  echo "         See $LOG and: kubectl -n $NS describe job/$JOB_NAME"
  rc=1
fi
echo "==================================================================="

# --- optional cleanup (Job also self-GCs via ttlSecondsAfterFinished) --------
if [ "$KEEP" != "1" ]; then
  kubectl -n "$NS" delete job "$JOB_NAME" --ignore-not-found --wait=false
fi

exit "$rc"
