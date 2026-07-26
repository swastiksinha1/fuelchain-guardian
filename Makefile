# FuelChain Guardian — Makefile
# Run `make help` to see all available targets

.PHONY: help up down build logs migrate seed topics test test-unit test-e2e \
        clean format lint k8s-apply k8s-delete flutter-run frontend-install

COMPOSE  = docker compose
BACKEND  = $(COMPOSE) exec backend
FLUTTER  = cd flutter && flutter

##@ Setup
help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z_0-9-]+:.*?##/ { printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

env: ## Copy example env file
	@[ -f .env ] || cp .env.example .env && echo "✅  .env created — edit API keys before starting"

##@ Docker
up: env ## Start all services (detached)
	$(COMPOSE) up --build -d
	@echo "⏳  Waiting for services to be healthy..."
	@sleep 10
	@$(MAKE) migrate
	@$(MAKE) topics
	@$(MAKE) seed
	@echo ""
	@echo "🚀  FuelChain Guardian is running!"
	@echo "   Dashboard → http://localhost:3000"
	@echo "   API docs  → http://localhost:8000/docs"
	@echo "   Grafana   → http://localhost:3001  (admin/admin)"
	@echo "   Kafka UI  → http://localhost:8080"

down: ## Stop and remove containers
	$(COMPOSE) down

down-v: ## Stop containers AND delete volumes (full reset)
	$(COMPOSE) down -v
	@echo "⚠️  All data wiped"

build: ## Rebuild all images without cache
	$(COMPOSE) build --no-cache

logs: ## Tail logs from all services
	$(COMPOSE) logs -f

logs-backend: ## Tail backend logs only
	$(COMPOSE) logs -f backend

logs-ais: ## Tail AIS + anomaly logs
	$(COMPOSE) logs -f ais-ingestion vessel-tracker anomaly-detector

logs-panic: ## Tail NLP + social logs
	$(COMPOSE) logs -f panic-nlp social-ingestion panic-aggregator

ps: ## Show running containers
	$(COMPOSE) ps

##@ Database
migrate: ## Run Alembic migrations
	$(BACKEND) alembic upgrade head

migrate-down: ## Roll back last migration
	$(BACKEND) alembic downgrade -1

migrate-history: ## Show migration history
	$(BACKEND) alembic history --verbose

seed: ## Seed demo data (admin + dealer users)
	$(BACKEND) python -m scripts.seed_demo

shell-db: ## Open psql shell
	$(COMPOSE) exec postgres psql -U fuelchain -d fuelchain

##@ Kafka
topics: ## Create all Kafka topics
	$(BACKEND) python -m scripts.init_kafka

topics-list: ## List all Kafka topics
	$(COMPOSE) exec redpanda rpk topic list

topics-reset: ## Delete and recreate all topics (WARNING: loses data)
	@read -p "⚠️  Delete all Kafka topics? [y/N] " ans && [ "$$ans" = "y" ]
	$(COMPOSE) exec redpanda rpk topic delete raw.ais.v1 raw.social.v1 \
	  alerts.anomaly.v1 eta-updates state.vessels state.pumps \
	  state.alerts metrics.disruption social.panics.v1 || true
	$(MAKE) topics

consume-ais: ## Watch raw AIS messages in real-time
	$(COMPOSE) exec redpanda rpk topic consume raw.ais.v1 --offset end

consume-anomaly: ## Watch anomaly alerts in real-time
	$(COMPOSE) exec redpanda rpk topic consume alerts.anomaly.v1 --offset end

consume-panic: ## Watch panic events in real-time
	$(COMPOSE) exec redpanda rpk topic consume social.panics.v1 --offset end

##@ Testing
test: ## Run all tests (unit + e2e)
	$(MAKE) test-unit
	$(MAKE) test-e2e

test-unit: ## Run fast unit tests (no Docker needed)
	cd backend && python -m pytest ../tests/test_unit.py -v --tb=short \
	  --cov=. --cov-report=term-missing

test-e2e: ## Run integration tests (requires docker compose up)
	python -m pytest tests/test_e2e.py -v --tb=short -x

test-nlp: ## Quick NLP smoke test
	curl -s -X POST http://localhost:8001/classify \
	  -H "Content-Type: application/json" \
	  -d '{"text":"No petrol in Mumbai! #FuelCrisis","city":"Mumbai"}' | python -m json.tool

##@ Development
format: ## Format Python code with black + isort
	cd backend && python -m black . && python -m isort .

lint: ## Lint Python code
	cd backend && python -m ruff check .

train-nlp: ## Train panic NLP model (takes 10-20 min CPU)
	$(BACKEND) python -m panic_nlp.train --samples 2000 --epochs 3

shell-backend: ## Open shell in backend container
	$(BACKEND) /bin/bash

##@ Frontend
frontend-install: ## Install frontend npm dependencies
	cd frontend && npm install

frontend-dev: ## Run frontend dev server (without Docker)
	cd frontend && npm run dev

frontend-build: ## Build frontend for production
	cd frontend && npm run build

##@ Flutter
flutter-install: ## Get Flutter dependencies
	$(FLUTTER) pub get

flutter-run: ## Run Flutter app on connected device
	$(FLUTTER) run

flutter-build-apk: ## Build Android APK
	$(FLUTTER) build apk --release

flutter-build-ios: ## Build iOS (macOS only)
	$(FLUTTER) build ios --release

##@ Kubernetes
k8s-apply: ## Apply all Kubernetes manifests
	kubectl apply -f k8s/namespace.yaml
	kubectl apply -f k8s/configmap.yaml
	kubectl apply -f k8s/infra.yaml
	kubectl apply -f k8s/deployment-backend.yaml
	@echo "✅  K8s manifests applied"

k8s-status: ## Check pod status
	kubectl get pods -n fuelchain -o wide

k8s-logs: ## Get backend logs from K8s
	kubectl logs -n fuelchain -l app=backend --tail=100 -f

k8s-delete: ## Delete all FuelChain K8s resources
	@read -p "⚠️  Delete fuelchain namespace? [y/N] " ans && [ "$$ans" = "y" ]
	kubectl delete namespace fuelchain

k8s-port-forward: ## Port-forward API and dashboard locally
	kubectl port-forward -n fuelchain svc/backend 8000:8000 &
	kubectl port-forward -n fuelchain svc/ws-gateway 8002:8002 &
	kubectl port-forward -n fuelchain svc/frontend 3000:3000 &
	@echo "✅  Port forwards active"

##@ Cleanup
clean: ## Remove Python cache and build files
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	@echo "✅  Cleaned"

clean-all: down-v clean ## Full wipe: stop services + volumes + cache
	docker system prune -f
	@echo "✅  Full clean complete"
