"""
Prometheus metrics for the predictive controller.

Exposes (on METRICS_PORT, default 9095):
  - predictive_predicted_p95_ms{stack,deployment}          gauge
  - predictive_current_replicas{stack,deployment}          gauge
  - predictive_scaling_events_total{stack,deployment,action} counter

Grafana scrapes this endpoint to chart the PREDICTIVE controller's decisions on
the same dashboard as the reactive HPA (which exposes its own kube-state-metrics
`kube_horizontalpodautoscaler_status_*`). Overlaying the two makes the
reaction-time lead of the predictive approach visible.

`prometheus_client` is imported lazily so predictive_controller.py and sim.py
still import when it is not installed (metrics are simply disabled).
"""

from __future__ import annotations

class ControllerMetrics:
    def __init__(self, port: int = 9095):

        from prometheus_client import Gauge, Counter
        self.port = port
        self._started = False
        self.predicted_p95 = Gauge(
            "predictive_predicted_p95_ms",
            "ML-forecast P95 latency (ms) 30s ahead, per managed deployment",
            ["stack", "deployment"],
        )
        self.current_replicas = Gauge(
            "predictive_current_replicas",
            "Replica count the predictive controller currently targets",
            ["stack", "deployment"],
        )
        self.scaling_events = Counter(
            "predictive_scaling_events_total",
            "Scaling decisions taken by the predictive controller",
            ["stack", "deployment", "action"],
        )

    def start(self) -> None:
        if self._started:
            return
        from prometheus_client import start_http_server
        start_http_server(self.port)
        self._started = True

    def observe(self, stack: str, deployment: str, predicted_p95_ms: float,
                current_replicas: int, action: str) -> None:
        self.predicted_p95.labels(stack=stack, deployment=deployment).set(predicted_p95_ms)
        self.current_replicas.labels(stack=stack, deployment=deployment).set(current_replicas)
        if action != "no_change":
            self.scaling_events.labels(stack=stack, deployment=deployment, action=action).inc()

if __name__ == "__main__":

    import time
    m = ControllerMetrics()
    m.start()
    m.observe("go", "go-user", 150.0, 2, "no_change")
    print("metrics server on :9095/metrics — Ctrl-C to exit")
    while True:
        time.sleep(1)
