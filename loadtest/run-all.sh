#!/usr/bin/env bash
#
# run-all.sh — run every k6 scenario against every stack, sequentially.
#
# Requires k6 (https://k6.io). Verify with:  k6 version
#
# For each (stack, scenario) it writes:
#   - results/{stack}-{scenario}.json      end-of-test summary (--summary-export)
#   - results/{stack}-{scenario}.ndjson    full per-point sample stream (--out json)
#
# The NDJSON stream is the raw latency time-series that feeds the ML pipeline
# (see README.md "How the output feeds the ML pipeline").
#
# Usage:
#   ./run-all.sh                       # all stacks, all scenarios
#   STACKS="go rust" ./run-all.sh      # subset of stacks
#   SCENARIOS="load spike" ./run-all.sh
#
set -euo pipefail

# --- Config -----------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESULTS_DIR="${SCRIPT_DIR}/results"
SCENARIO_DIR="${SCRIPT_DIR}/scenarios"

# Override via env vars if desired.
STACKS="${STACKS:-go rust java node}"
SCENARIOS="${SCENARIOS:-load stress spike soak}"

# --- Preflight --------------------------------------------------------------
if ! command -v k6 >/dev/null 2>&1; then
  echo "ERROR: k6 is not installed or not on PATH." >&2
  echo "Install it from https://k6.io/docs/get-started/installation/ and verify with: k6 version" >&2
  exit 1
fi

echo "Using $(k6 version)"
mkdir -p "${RESULTS_DIR}"

# --- Run matrix -------------------------------------------------------------
for stack in ${STACKS}; do
  for scenario in ${SCENARIOS}; do
    script="${SCENARIO_DIR}/${scenario}.js"
    if [[ ! -f "${script}" ]]; then
      echo "SKIP: no scenario script at ${script}" >&2
      continue
    fi

    summary_out="${RESULTS_DIR}/${stack}-${scenario}.json"
    stream_out="${RESULTS_DIR}/${stack}-${scenario}.ndjson"

    echo ""
    echo "=============================================================="
    echo ">>> stack=${stack}  scenario=${scenario}"
    echo "    summary -> ${summary_out}"
    echo "    stream  -> ${stream_out}"
    echo "=============================================================="

    # Do not let one failing run (e.g. threshold breach under stress) abort the
    # whole matrix — record the result and move on.
    if ! k6 run \
        -e "STACK=${stack}" \
        --summary-export "${summary_out}" \
        --out "json=${stream_out}" \
        "${script}"; then
      echo "WARN: k6 run for stack=${stack} scenario=${scenario} exited non-zero (thresholds or errors). Continuing." >&2
    fi
  done
done

echo ""
echo "All runs complete. Results in: ${RESULTS_DIR}"
