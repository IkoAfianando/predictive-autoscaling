"""Shared configuration for the ML pipeline.

Single source of truth for stacks, metric names, paths, and the horizon/step
timing used across collection, feature engineering, training and serving.
"""
from __future__ import annotations

import os

STACKS = ["go", "rust", "java", "node"]

METRIC = "http_request_duration_seconds"

STEP_SECONDS = 15
HORIZON_SECONDS = 30
LOOKBACK_SECONDS = 60

HORIZON_STEPS = max(1, round(HORIZON_SECONDS / STEP_SECONDS))
LOOKBACK_STEPS = max(1, round(LOOKBACK_SECONDS / STEP_SECONDS))

FEATURE_COLS = ["request_rate", "error_rate", "cpu", "memory", "p95"]
TARGET_COL = "p95"

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
RESULTS_DIR = os.path.join(HERE, "results")
MODELS_DIR = os.path.join(HERE, "models")

for _d in (DATA_DIR, RESULTS_DIR, MODELS_DIR):
    os.makedirs(_d, exist_ok=True)

def data_csv(stack: str) -> str:
    """Path to a stack's per-stack CSV (timestamp + features + p95)."""
    return os.path.join(DATA_DIR, f"{stack}.csv")

def promql_p95(stack: str) -> str:
    return (
        f'histogram_quantile(0.95, '
        f'sum(rate({METRIC}_bucket{{stack="{stack}"}}[1m])) by (le))'
    )

def promql_request_rate(stack: str) -> str:
    return f'sum(rate({METRIC}_count{{stack="{stack}"}}[1m]))'

def promql_error_rate(stack: str) -> str:

    return (
        f'sum(rate({METRIC}_count{{stack="{stack}",status=~"5.."}}[1m])) '
        f'/ clamp_min(sum(rate({METRIC}_count{{stack="{stack}"}}[1m])), 1e-9)'
    )

def promql_cpu(stack: str) -> str:

    return (
        f'avg(rate(process_cpu_seconds_total{{stack="{stack}"}}[1m]))'
    )

def promql_memory(stack: str) -> str:

    return (
        f'avg(process_resident_memory_bytes{{stack="{stack}"}}) / 1024 / 1024'
    )

def query_map(stack: str) -> dict[str, str]:
    return {
        "request_rate": promql_request_rate(stack),
        "error_rate": promql_error_rate(stack),
        "cpu": promql_cpu(stack),
        "memory": promql_memory(stack),
        "p95": promql_p95(stack),
    }
