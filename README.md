# FuelChain Guardian 🛢️⚓

> End-to-end fuel supply chain intelligence platform for India — tracking Strait of Hormuz disruptions, predicting pump shortages, enabling dealer micro-credit, and fighting panic-buying with data.

---
# Screenshot

<img width="1920" height="1080" alt="Screenshot 2026-05-23 205955" src="https://github.com/user-attachments/assets/28faf3b4-4d70-4652-a539-dff61124b648" />

---
<img width="1920" height="1080" alt="Screenshot 2026-05-25 235734" src="https://github.com/user-attachments/assets/e609a807-ddf7-4581-bf71-e325bf5833dc" />

<img width="1920" height="1080" alt="Screenshot 2026-05-25 235825" src="https://github.com/user-attachments/assets/629507ad-a25d-459b-9f5c-da28378cef37" />

<img width="1920" height="1080" alt="Screenshot 2026-05-25 235830" src="https://github.com/user-attachments/assets/d589299d-7b70-4a02-bc84-15eedc7fc956" />

<img width="1920" height="1080" alt="Screenshot 2026-05-25 235838" src="https://github.com/user-attachments/assets/4cf8a2c1-73bd-4bf4-8923-8c8aa2b4ed19" />

<img width="1920" height="1080" alt="Screenshot 2026-05-26 000041" src="https://github.com/user-attachments/assets/482ff388-711c-4c87-b36c-f30221e66d96" />

<img width="1918" height="1078" alt="Screenshot 2026-05-26 000057" src="https://github.com/user-attachments/assets/6e745246-7c4c-4e68-9c81-5c7cb9d89154" />


---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        EXTERNAL DATA SOURCES                            │
│   AIS Hub / Simulator    Twitter API v2     OMC Mock API                │
└────────┬─────────────────────┬──────────────────┬───────────────────────┘
         │                     │                  │
         ▼                     ▼                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         KAFKA / REDPANDA                                │
│  raw.ais.v1  raw.social.v1  alerts.anomaly.v1  state.vessels            │
│  state.pumps  social.panics.v1  metrics.disruption  eta-updates         │
└──────┬──────────────┬───────────────┬──────────────┬────────────────────┘
       │              │               │              │
       ▼              ▼               ▼              ▼
┌──────────┐  ┌──────────────┐  ┌─────────┐  ┌──────────────┐
│  Vessel  │  │  Disruption  │  │ Panic   │  │  Inventory   │
│ Tracker  │  │  Index Svc   │  │  NLP    │  │  Simulator   │
└──────────┘  └──────────────┘  └─────────┘  └──────────────┘
       │              │               │              │
       └──────────────┴───────────────┴──────────────┘
                              │
                    ┌─────────▼─────────┐
                    │  PostgreSQL 15     │
                    │  + PostGIS         │
                    │  + TimescaleDB     │
                    └─────────┬─────────┘
                              │
                    ┌─────────▼─────────┐
                    │  FastAPI Backend  │
                    │  (Main API GW)    │──── Redis 7
                    └─────────┬─────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
      ┌──────────────┐ ┌──────────┐  ┌──────────────┐
      │ React Web    │ │ Flutter  │  │  WebSocket   │
      │ Dashboard    │ │ PumpCast │  │  Gateway     │
      └──────────────┘ └──────────┘  └──────────────┘
```

## Modules

| Module | Description | Status |
|--------|-------------|--------|
| 1 - AIS Ingestion | Tanker tracking via AISHub/Simulator | ✅ |
| 2 - Disruption Index | Port-level supply disruption scoring | ✅ |
| 3 - Inventory Simulator | Depot-to-pump agent-based model | ✅ |
| 4 - Panic NLP | Tweet classification + Panic Index | ✅ |
| 5 - Dealer Credit | Micro-credit disbursement via UPI mock | ✅ |
| 6 - WebSocket Gateway | Real-time Kafka→Web bridge | ✅ |
| 7 - React Dashboard | Authorities web interface | ✅ |
| 8 - Flutter PumpCast | Consumer mobile app | ✅ |

---

## Quick Start (Docker Compose)

### Prerequisites
- Docker Desktop ≥ 24.0
- Docker Compose ≥ 2.20
- 8 GB RAM minimum (16 GB recommended)

### 1. Clone and configure

```bash
git clone <repo-url> fuelchain-guardian
cd fuelchain-guardian
cp .env.example .env
# Edit .env with your API keys (see comments inside)
```

### 2. Start all services

```bash
docker compose up --build -d
```

### 3. Run database migrations

```bash
docker compose exec backend alembic upgrade head
```

### 4. Initialize Kafka topics

```bash
docker compose exec backend python -m scripts.init_kafka
```

### 5. Seed demo data (optional)

```bash
docker compose exec backend python -m scripts.seed_demo
```

### Service URLs

| Service | URL |
|---------|-----|
| React Dashboard | http://localhost:3000 |
| FastAPI Docs | http://localhost:8000/docs |
| Grafana | http://localhost:3001 (admin/admin) |
| Prometheus | http://localhost:9090 |
| Redpanda Console | http://localhost:8080 |
| pgAdmin | http://localhost:5050 |

---

## Environment Variables

Copy `.env.example` to `.env` and fill in:

```
# AIS Data Source
AISHUB_API_KEY=your_key_here          # Get from aishub.net
AIS_MODE=simulator                    # 'aishub' | 'simulator'

# Twitter API v2
TWITTER_BEARER_TOKEN=your_token_here  # developer.twitter.com
SOCIAL_MODE=simulator                 # 'twitter' | 'simulator'

# Database
DATABASE_URL=postgresql+asyncpg://fuelchain:secret@postgres:5432/fuelchain
REDIS_URL=redis://redis:6379/0

# Auth
JWT_SECRET=change-this-in-production-to-random-256-bit-string
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=1440

# Firebase (for Flutter app push notifications)
FIREBASE_PROJECT_ID=your-project-id
FIREBASE_SERVICE_ACCOUNT_JSON=./secrets/firebase-service-account.json

# Payment (mocked by default)
RAZORPAY_KEY_ID=your_key              # razorpay.com - set PAYMENT_MODE=live for real
RAZORPAY_KEY_SECRET=your_secret
PAYMENT_MODE=mock                     # 'mock' | 'live'
```

---

## Production Deployment (Kubernetes)

### Prerequisites
- Kubernetes cluster ≥ 1.28 (EKS, GKE, or k3s)
- `kubectl` configured
- `helm` 3.x

### Deploy

```bash
# Create namespace and config
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml

# Create secrets (edit first!)
kubectl apply -f k8s/secrets.yaml

# Deploy infrastructure (Postgres, Redis, Redpanda)
kubectl apply -f k8s/infra/

# Deploy application services
kubectl apply -f k8s/services/

# Deploy ingress
kubectl apply -f k8s/ingress.yaml

# Check status
kubectl get pods -n fuelchain
```

---

## API Reference

### AIS / Tanker Endpoints
- `GET /api/v1/vessels` — All tracked vessels
- `GET /api/v1/vessels/{mmsi}` — Vessel detail + track
- `GET /api/v1/disruption/{port_code}` — Disruption Index for port

### Pump Inventory Endpoints
- `GET /api/v1/pumps/nearby?lat=&lon=&radius=` — GeoJSON pump status
- `GET /api/v1/pumps/{pump_id}` — Pump detail + prediction

### Panic Index Endpoints
- `GET /api/v1/panic/{city}` — Current Panic Index

### Credit Endpoints (JWT required)
- `POST /api/v1/credit/apply` — Apply for dealer credit
- `GET /api/v1/credit/status/{loan_id}` — Check loan status
- `GET /api/v1/credit/history` — Dealer's loan history

### Auth
- `POST /api/v1/auth/token` — Get JWT token
- `POST /api/v1/auth/register` — Register dealer

---

## Testing

```bash
# Unit tests
docker compose exec backend pytest tests/ -v

# End-to-end integration tests
pytest tests/test_e2e.py -v --docker
```

---

## Architecture Decisions

1. **Redpanda over Kafka** — Kafka-compatible, single binary, easier local dev, no ZooKeeper
2. **TimescaleDB** — PostgreSQL extension for vessel position time-series; keeps everything in one DB
3. **ONNX for NLP** — Run transformer inference without heavy ML framework in production
4. **Simulator providers** — All external APIs (AIS, Twitter, UPI) have simulator implementations so the full system runs without API keys
5. **Redis for hot data** — Pump statuses and disruption index cached in Redis; DB is source of truth

---

## License
MIT — Rishi Raj, 2026
