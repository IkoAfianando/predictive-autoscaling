# Predictive auto-scaling controller — small, non-root image.
FROM python:3.12-slim AS base

# No .pyc, unbuffered stdout so kubectl logs stream the JSON decisions live.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install deps first for layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code.
COPY scaling_logic.py predictive_controller.py metrics_exporter.py sim.py ./

# Non-root user (SPEC §7 parity: never run as root).
RUN useradd --create-home --uid 10001 controller \
    && mkdir -p /app/logs \
    && chown -R controller:controller /app
USER controller

# Prometheus metrics port (see metrics_exporter.py / k8s Service).
EXPOSE 9095

# Sensible in-cluster defaults; override via the Deployment env / ConfigMap.
ENV PREDICT_URL=http://ml-serve:8000/predict \
    NAMESPACE=autoscale \
    SCALE_UP_THRESHOLD=200 \
    SCALE_DOWN_THRESHOLD=80 \
    MIN_REPLICAS=1 \
    MAX_REPLICAS=10 \
    INTERVAL_SECONDS=15 \
    COOLDOWN_SECONDS=60 \
    DRY_RUN=false

ENTRYPOINT ["python3", "predictive_controller.py"]
