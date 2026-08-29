# Predictive Auto-Scaling Microservices — orchestration
# Iko Afianando (2602261970)

.PHONY: help up down build logs ps clean obs k8s-apply k8s-delete \
        loadtest-go loadtest-all ml-demo ml-collect controller-sim env

help:
	@echo "Targets:"
	@echo "  make env            Copy .env.example -> .env"
	@echo "  make build          Build all backend service images"
	@echo "  make up             Start full stack (postgres, redis, 12 services)"
	@echo "  make obs            Start observability stack (prometheus, grafana, otel)"
	@echo "  make down           Stop everything"
	@echo "  make ps             Show running containers"
	@echo "  make logs           Tail logs"
	@echo "  make k8s-apply      Deploy to Kubernetes (kubectl -k infra/k8s)"
	@echo "  make k8s-delete     Remove from Kubernetes"
	@echo "  make loadtest-go    Run stress scenario against the Go stack"
	@echo "  make loadtest-all   Run all scenarios against all stacks"
	@echo "  make ml-collect     Pull time-series from Prometheus -> ml/data"
	@echo "  make ml-demo        Run offline ML experiment on synthetic data"
	@echo "  make controller-sim Run predictive controller simulator (no cluster)"
	@echo "  make clean          Down + remove volumes"

env:
	@test -f .env || cp .env.example .env && echo ".env ready"

build:
	docker compose build

up: env
	docker compose up -d
	@echo "Backend up. Ports: Go 8001-8003, Rust 8011-8013, Java 8021-8023, Node 8031-8033"

obs:
	docker compose -f observability/docker-compose.observability.yml up -d
	@echo "Grafana http://localhost:3000 (admin/admin) | Prometheus http://localhost:9090"

down:
	-docker compose down
	-docker compose -f observability/docker-compose.observability.yml down

ps:
	docker compose ps

logs:
	docker compose logs -f --tail=100

k8s-apply:
	kubectl apply -k infra/k8s

k8s-delete:
	-kubectl delete -k infra/k8s

loadtest-go:
	cd loadtest && k6 run -e STACK=go scenarios/stress.js

loadtest-all:
	cd loadtest && ./run-all.sh

ml-collect:
	cd ml && python3 collect.py

ml-demo:
	cd ml && python3 synthetic.py && python3 evaluate.py

controller-sim:
	cd controller && python3 sim.py

clean:
	-docker compose down -v
	-docker compose -f observability/docker-compose.observability.yml down -v
