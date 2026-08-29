"""
Predictive Kubernetes auto-scaling controller.

Loop every INTERVAL_SECONDS:
  1. For each managed Deployment (12 = 4 stacks x 3 services), fetch the
     30s-ahead P95 latency forecast from the ML service for that Deployment's
     stack (GET {PREDICT_URL}?stack={stack}).
  2. Feed the forecast into the pure decision logic (scaling_logic.decide).
  3. Apply the resulting replica count via the Kubernetes scale subresource
     (unless DRY_RUN=true).
  4. Log every decision as structured JSON to stdout AND append it to
     logs/decisions.jsonl -> this file is the raw DATA for the Bab IV
     reaction-time / false-positive-rate evaluation.

Everything is configured through environment variables so the exact same image
runs in-cluster and in a laptop DRY_RUN demo.

The `kubernetes` and `requests` imports are guarded: the module imports fine
(and sim.py can reuse helpers) even when those packages are absent, as long as
you don't actually start the live loop without them.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Optional

from scaling_logic import ScalingConfig, DeploymentState, Decision, decide


try:
    import requests
except Exception:
    requests = None

try:
    from kubernetes import client, config as k8s_config
    from kubernetes.client.rest import ApiException
except Exception:
    client = None
    k8s_config = None
    ApiException = Exception

try:
    from metrics_exporter import ControllerMetrics
except Exception:
    ControllerMetrics = None


STACKS = ["go", "rust", "java", "node"]
SERVICES = ["user", "product", "order"]

def build_managed_deployments() -> list[tuple[str, str]]:
    """Return [(deployment_name, stack), ...] for the managed services.

    By default all 12 (4 stacks x 3 services). Restrict via env for a focused
    demo, e.g. MANAGED_STACKS=go keeps only go-user/go-product/go-order so the
    decision log is a clean single-stack up/down timeline.
    """
    stacks = [s.strip() for s in
              os.getenv("MANAGED_STACKS", ",".join(STACKS)).split(",") if s.strip()]
    services = [s.strip() for s in
                os.getenv("MANAGED_SERVICES", ",".join(SERVICES)).split(",") if s.strip()]
    out: list[tuple[str, str]] = []
    for stack in stacks:
        for svc in services:
            out.append((f"{stack}-{svc}", stack))
    return out


def _env_float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))

def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))

def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")

def _stack_scaling_config(base: ScalingConfig, stack: str) -> ScalingConfig:
    """Return a ScalingConfig for one stack, overriding the up/down thresholds
    from per-stack env vars when present.

        SCALE_UP_THRESHOLD_JAVA=1200   SCALE_DOWN_THRESHOLD_JAVA=700

    Different stacks' models have very different idle/loaded forecast baselines
    (e.g. the go/rust models sit near a few ms at idle, while the java/node
    models carry a much higher intercept). A single global threshold cannot fit
    all four, so each managed stack gets its own up/down band. Any stack without
    an override simply inherits the global SCALE_UP_THRESHOLD / SCALE_DOWN_THRESHOLD.
    """
    su = os.getenv(f"SCALE_UP_THRESHOLD_{stack.upper()}")
    sd = os.getenv(f"SCALE_DOWN_THRESHOLD_{stack.upper()}")
    return ScalingConfig(
        scale_up_threshold_ms=float(su) if su is not None else base.scale_up_threshold_ms,
        scale_down_threshold_ms=float(sd) if sd is not None else base.scale_down_threshold_ms,
        min_replicas=base.min_replicas,
        max_replicas=base.max_replicas,
        cooldown_seconds=base.cooldown_seconds,
        up_step_cap=base.up_step_cap,
        up_sustain_seconds=base.up_sustain_seconds,
    )

def load_config() -> dict:
    base_scaling = ScalingConfig(
        scale_up_threshold_ms=_env_float("SCALE_UP_THRESHOLD", 200.0),
        scale_down_threshold_ms=_env_float("SCALE_DOWN_THRESHOLD", 80.0),
        min_replicas=_env_int("MIN_REPLICAS", 1),
        max_replicas=_env_int("MAX_REPLICAS", 10),
        cooldown_seconds=_env_float("COOLDOWN_SECONDS", 60.0),
        up_step_cap=_env_int("UP_STEP_CAP", 4),
        up_sustain_seconds=_env_float("UP_SUSTAIN_SECONDS", 0.0),
    )


    scaling_by_stack = {s: _stack_scaling_config(base_scaling, s) for s in STACKS}
    return {
        "predict_url": os.getenv("PREDICT_URL", "http://ml-serve:8000/predict"),
        "namespace": os.getenv("NAMESPACE", "autoscale"),
        "interval_seconds": _env_float("INTERVAL_SECONDS", 15.0),
        "dry_run": _env_bool("DRY_RUN", False),
        "log_path": os.getenv("DECISION_LOG_PATH",
                              os.path.join(os.path.dirname(__file__), "logs", "decisions.jsonl")),
        "results_log_path": os.getenv("RESULTS_LOG_PATH", ""),
        "metrics_port": _env_int("METRICS_PORT", 9095),
        "enable_metrics": _env_bool("ENABLE_METRICS", True),
        "predict_timeout": _env_float("PREDICT_TIMEOUT_SECONDS", 3.0),
        "scaling": base_scaling,
        "scaling_by_stack": scaling_by_stack,
    }


class DecisionLogger:
    """Emit each decision as structured JSON to stdout AND append it to one or
    more JSONL files (the raw evaluation data). A second timestamped file under
    results/scaling/ makes every run self-contained and archivable."""

    def __init__(self, log_path: str, extra_paths: Optional[list[str]] = None):
        self.paths = [log_path] + list(extra_paths or [])
        for p in self.paths:
            os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)

    def emit(self, decision: Decision) -> None:
        line = json.dumps(decision.to_json_dict(), separators=(",", ":"))

        print(line, flush=True)

        for p in self.paths:
            with open(p, "a") as fh:
                fh.write(line + "\n")

def now_iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


class Predictor:
    """Fetch the 30s-ahead P95 forecast for a stack. Caches per-tick."""

    def __init__(self, predict_url: str, timeout: float):
        self.predict_url = predict_url
        self.timeout = timeout
        self._cache: dict[str, float] = {}
        self._live_cache: dict[str, Optional[float]] = {}

    def reset_tick(self) -> None:
        self._cache.clear()
        self._live_cache.clear()

    def live_p95_ms(self, stack: str) -> Optional[float]:
        """Measured live P95 in ms (from ml/serve.py 'live_p95_now', seconds).
        Returns None if unavailable. Populated as a side effect of predict_p95_ms."""
        return self._live_cache.get(stack)

    def predict_p95_ms(self, stack: str) -> Optional[float]:
        if stack in self._cache:
            return self._cache[stack]
        if requests is None:
            raise RuntimeError("requests not installed; cannot call ML service")
        resp = requests.get(self.predict_url, params={"stack": stack}, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()

        if isinstance(data, dict) and data.get("live_p95_now") is not None:
            try:
                self._live_cache[stack] = float(data["live_p95_now"]) * 1000.0
            except (TypeError, ValueError):
                self._live_cache[stack] = None

        value = None

        for key in ("predicted_p95_ms", "p95_ms"):
            if isinstance(data, dict) and key in data:
                value = float(data[key])
                break

        if value is None and isinstance(data, dict):
            for key in ("p95_pred", "p95", "predicted_p95", "value"):
                if key in data:
                    value = float(data[key]) * 1000.0
                    break
        if value is None and isinstance(data, (int, float)):
            value = float(data) * 1000.0
        if value is None:
            raise ValueError(f"cannot parse prediction from ML response: {data!r}")
        self._cache[stack] = value
        return value


class K8sScaler:
    def __init__(self, namespace: str, dry_run: bool):
        self.namespace = namespace
        self.dry_run = dry_run
        self.apps = None
        if not dry_run:
            if client is None:
                raise RuntimeError("kubernetes client not installed; set DRY_RUN=true")
            try:
                k8s_config.load_incluster_config()
            except Exception:
                k8s_config.load_kube_config()
            self.apps = client.AppsV1Api()

    def get_current_replicas(self, name: str) -> Optional[int]:
        if self.dry_run or self.apps is None:
            return None
        try:
            scale = self.apps.read_namespaced_deployment_scale(name, self.namespace)
            return scale.spec.replicas
        except ApiException as exc:
            print(json.dumps({"level": "warn", "event": "read_scale_failed",
                              "deployment": name, "status": getattr(exc, "status", None)}),
                  flush=True)
            return None

    def set_replicas(self, name: str, replicas: int) -> None:
        if self.dry_run or self.apps is None:
            return
        body = {"spec": {"replicas": replicas}}
        self.apps.patch_namespaced_deployment_scale(name, self.namespace, body)


class PredictiveController:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.scaling: ScalingConfig = cfg["scaling"]

        self.scaling_by_stack: dict[str, ScalingConfig] = cfg.get("scaling_by_stack", {})
        extra = [cfg["results_log_path"]] if cfg.get("results_log_path") else []
        self.logger = DecisionLogger(cfg["log_path"], extra_paths=extra)
        self.predictor = Predictor(cfg["predict_url"], cfg["predict_timeout"])
        self.scaler = K8sScaler(cfg["namespace"], cfg["dry_run"])
        self.metrics = None
        if cfg["enable_metrics"] and ControllerMetrics is not None:
            try:
                self.metrics = ControllerMetrics(cfg["metrics_port"])
                self.metrics.start()
            except Exception as exc:
                print(json.dumps({"level": "warn", "event": "metrics_disabled",
                                  "error": str(exc)}), flush=True)

        self.states: dict[str, DeploymentState] = {}
        for name, stack in build_managed_deployments():
            self.states[name] = DeploymentState(
                name=name, stack=stack,
                current_replicas=self.scaling.min_replicas,
            )
        self._running = True

    def stop(self, *_a) -> None:
        self._running = False

    def _sync_current_replicas(self, state: DeploymentState) -> None:
        live = self.scaler.get_current_replicas(state.name)
        if live is not None:
            state.current_replicas = live

    def tick(self, now: Optional[float] = None) -> list[Decision]:
        now = now if now is not None else time.time()
        self.predictor.reset_tick()
        decisions: list[Decision] = []

        for name, state in self.states.items():

            self._sync_current_replicas(state)
            before = state.current_replicas

            try:
                predicted = self.predictor.predict_p95_ms(state.stack)
            except Exception as exc:
                print(json.dumps({"level": "error", "event": "predict_failed",
                                  "deployment": name, "stack": state.stack,
                                  "error": str(exc)}), flush=True)
                continue

            scaling = self.scaling_by_stack.get(state.stack, self.scaling)
            measured = self.predictor.live_p95_ms(state.stack)
            new_replicas, action, reason = decide(state, predicted, scaling, now,
                                                  measured_p95_ms=measured)

            if action != "no_change":
                try:
                    self.scaler.set_replicas(name, new_replicas)
                except Exception as exc:
                    print(json.dumps({"level": "error", "event": "scale_failed",
                                      "deployment": name, "error": str(exc)}), flush=True)
                    continue
                if action == "scale_up":
                    state.last_scale_up_ts = now
                elif action == "scale_down":
                    state.last_scale_down_ts = now
                state.current_replicas = new_replicas

            decision = Decision(
                ts=now_iso(now), epoch=now, service=name, stack=state.stack,
                predicted_p95_ms=round(predicted, 3),
                current_replicas=before,
                new_replicas=new_replicas, action=action, reason=reason,
                threshold_up_ms=scaling.scale_up_threshold_ms,
                threshold_down_ms=scaling.scale_down_threshold_ms,
                dry_run=self.cfg["dry_run"],
            )
            self.logger.emit(decision)
            decisions.append(decision)

            if self.metrics is not None:
                self.metrics.observe(state.stack, name, predicted,
                                     state.current_replicas, action)
        return decisions

    def run(self) -> None:
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)
        interval = self.cfg["interval_seconds"]
        print(json.dumps({"level": "info", "event": "controller_start",
                          "dry_run": self.cfg["dry_run"], "namespace": self.cfg["namespace"],
                          "predict_url": self.cfg["predict_url"],
                          "managed_deployments": len(self.states),
                          "interval_seconds": interval}), flush=True)
        while self._running:
            start = time.time()
            self.tick(start)
            elapsed = time.time() - start
            sleep = max(0.0, interval - elapsed)

            slept = 0.0
            while self._running and slept < sleep:
                time.sleep(min(0.5, sleep - slept))
                slept += 0.5
        print(json.dumps({"level": "info", "event": "controller_stop"}), flush=True)

def main() -> int:
    cfg = load_config()
    controller = PredictiveController(cfg)
    controller.run()
    return 0

if __name__ == "__main__":
    sys.exit(main())
