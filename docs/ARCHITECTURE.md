# FuelChain Guardian — Architecture Deep Dive

## System Overview

FuelChain Guardian is a real-time fuel supply intelligence platform built around a Kafka event-streaming backbone. Every module is stateless and communicates only through well-defined Kafka topics, enabling horizontal scaling and independent deployment.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              DATA INGESTION LAYER                           │
│                                                                             │
│  ┌──────────────────┐   ┌──────────────────┐   ┌──────────────────────┐   │
│  │  AIS Provider    │   │  Social Producer  │   │   Inventory Tick     │   │
│  │  (AISHub/Sim)    │   │  (Twitter/Sim)    │   │   (APScheduler)      │   │
│  └────────┬─────────┘   └────────┬──────────┘   └──────────┬───────────┘   │
│           │ raw.ais.v1            │ raw.social.v1            │ internal      │
└───────────┼───────────────────────┼──────────────────────────┼──────────────┘
            │                       │                          │
┌───────────┼───────────────────────┼──────────────────────────┼──────────────┐
│           ▼                       ▼          KAFKA            ▼              │
│   ┌──────────────┐  ┌──────────────────┐  ┌────────────────────────────┐   │
│   │ raw.ais.v1   │  │ raw.social.v1    │  │ state.pumps (compacted)    │   │
│   │ (5 parts)    │  │ (3 parts)        │  │ alerts.anomaly.v1          │   │
│   │ 1d retention │  │ 12h retention    │  │ metrics.disruption         │   │
│   └──────┬───────┘  └────────┬─────────┘  │ social.panics.v1           │   │
│          │                   │             │ state.alerts               │   │
└──────────┼───────────────────┼─────────────┼────────────────────────────┘   
           │                   │             │
┌──────────┼───────────────────┼─────────────┼──────────────────────────────┐
│          ▼                   ▼             ▼    STREAM PROCESSING          │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────────────┐   │
│  │Vessel Tracker│  │Panic NLP Svc │  │Disruption Index Consumer      │   │
│  │(consumer grp)│  │(ONNX/keyword)│  │(rolling 6h window, per-port)  │   │
│  ├──────────────┤  ├──────────────┤  ├───────────────────────────────┤   │
│  │Anomaly       │  │Panic         │  │Inventory Simulator            │   │
│  │Detector      │  │Aggregator    │  │(agent model, 60 pumps)        │   │
│  │(Shapely geo- │  │(hourly index │  │panic_multiplier from panics   │   │
│  │ fences+window│  │ + Firestore) │  │replenishment from disruption  │   │
│  └──────┬───────┘  └──────┬───────┘  └───────────────┬───────────────┘   │
└─────────┼─────────────────┼──────────────────────────┼────────────────────┘
          │                 │                          │
┌─────────┼─────────────────┼──────────────────────────┼────────────────────┐
│         ▼                 ▼          STORAGE           ▼                   │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  PostgreSQL 15 + PostGIS + TimescaleDB                               │  │
│  │  ┌────────────────┐ ┌────────────────┐ ┌────────────────────────┐   │  │
│  │  │vessel_positions│ │pump_inventory  │ │credit_applications     │   │  │
│  │  │(hypertable,    │ │(hypertable,    │ │transactions            │   │  │
│  │  │ 1-day chunks)  │ │ 6-hour chunks) │ │panic_events            │   │  │
│  │  └────────────────┘ └────────────────┘ └────────────────────────┘   │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  Redis 7  (hot cache — TTL-based)                                    │  │
│  │  vessel:{mmsi}  pump:{id}  disruption:{port}  panic:{city}           │  │
│  │  panic_alert:{city}  ais_dedup:{mmsi}:{ts}                          │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
          │
┌─────────┼──────────────────────────────────────────────────────────────────┐
│         ▼                    API LAYER                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  FastAPI (4 gunicorn workers, uvicorn)                              │   │
│  │  /api/v1/auth  /vessels  /disruption  /pumps  /panic  /credit      │   │
│  │  JWT auth + slowapi rate limiting + prometheus metrics              │   │
│  └───────────────────────────────┬─────────────────────────────────────┘   │
│                                  │                                          │
│  ┌───────────────────────────────┴────────┐                                │
│  │  WebSocket Gateway (2 replicas)        │                                │
│  │  Subscribes to 6 Kafka topics          │                                │
│  │  Broadcasts to connected React clients │                                │
│  └────────────────────────────────────────┘                                │
└─────────────────────────────────────────────────────────────────────────────┘
          │                              │
┌─────────┴──────────────┐  ┌───────────┴────────────────────────────────────┐
│  React Dashboard        │  │  Flutter PumpCast App                          │
│  MapLibre dark map      │  │  Firebase Phone Auth → Firestore real-time     │
│  Recharts analytics     │  │  flutter_map pump markers                      │
│  WS real-time updates   │  │  SQLite offline cache                          │
│  Credit applications    │  │  FCM push notifications                        │
└─────────────────────────┘  └────────────────────────────────────────────────┘
```

## Key Design Decisions

### 1. Redpanda over Apache Kafka
Redpanda is Kafka-compatible but ships as a single binary with no ZooKeeper dependency. For development and small production deployments this massively simplifies operations. For large-scale production (>100 GB/day), switch to a managed Kafka service (Confluent Cloud, AWS MSK).

### 2. TimescaleDB Hypertables
`vessel_positions` and `pump_inventory` are TimescaleDB hypertables (auto-partitioned time-series tables within PostgreSQL). Benefits:
- Automatic time-based partitioning (1-day chunks for positions, 6-hour for inventory)
- 10-100× faster `WHERE timestamp BETWEEN` queries vs plain PostgreSQL
- Transparent compression on old chunks (saves 90%+ disk space)
- Compatible with all PostGIS spatial queries

### 3. Redis as Hot Cache
All latency-sensitive reads (dashboard, mobile app) go to Redis first, then fall back to PostgreSQL. Redis keys have TTLs (1–24h) so stale data auto-expires. This allows the dashboard to load in <50ms even under heavy load.

### 4. Agent-Based Inventory Model
Instead of a pure mathematical model, each pump is an agent with:
- Individual stock levels (initialized from realistic ranges)
- Per-pump sales rates (sampled from city-specific distributions)
- External signals: panic multiplier (from Panic Index) and replenishment factor (from Disruption Index)
This makes the simulation realistic and allows future extension with ML-predicted sales rates.

### 5. ONNX for NLP Inference
The panic classifier exports from PyTorch to ONNX, then uses `onnxruntime` for inference. This eliminates the PyTorch dependency from the production inference service, reducing the Docker image from ~2 GB to ~400 MB and cutting inference time by 3-5×.

### 6. Stateless Services + Kafka Consumer Groups
Every service is stateless. State lives in:
- PostgreSQL (persistent source of truth)
- Redis (hot cache)  
- Kafka (event log, compacted topics for latest state)

Consumer groups (e.g., `vessel-tracker-group`) enable horizontal scaling: add more replicas and Kafka automatically distributes partitions across them.

## Data Flow Walkthrough

### Tanker Anomaly → Pump Shortage Warning (complete path)

1. **AIS Producer** reads from AISHub TCP socket → publishes `{mmsi, lat, lon, sog=0.8}` to `raw.ais.v1`
2. **Vessel Tracker** consumes `raw.ais.v1` → writes position to TimescaleDB → updates `vessel:{mmsi}` in Redis
3. **Anomaly Detector** consumes `raw.ais.v1` → vessel is inside Hormuz geofence → 15-min window avg_sog < 2 kn → emits `{event_type: slow_speed, estimated_delay_hours: 12}` to `alerts.anomaly.v1` and `eta-updates`
4. **Disruption Service** consumes `alerts.anomaly.v1` → adds 280,000 tonnes to KANDLA's 6h delayed-tonnage window → Disruption Index = 44% → writes to `disruption:KANDLA` in Redis → publishes to `metrics.disruption`
5. **Inventory Simulator** consumes `metrics.disruption` → sets `replenishment_factor=0.65` for all Mumbai/Pune/Kandla pumps → next tick reduces stock faster than replenishment → PUMP0003 drops below 20% → status becomes RED
6. **state.pumps** event published → **WebSocket Gateway** broadcasts to connected React clients → map marker turns red
7. **Firestore Sync** also writes the pump status to Firestore → Flutter app listener triggers → user sees red marker

### Panic Tweet → Reassurance Push (complete path)

1. **Social Producer** streams Twitter filtered feed → tweet "No petrol in Mumbai!" → `raw.social.v1`
2. **Panic Aggregator** consumes tweet → POST to NLP service `/classify` → `{is_panic: true, score: 0.87, city: Mumbai}`
3. Aggregator updates hourly bucket: Mumbai 12/15 panic = 80 index → writes `panic:Mumbai` to Redis → publishes `{city: Mumbai, panic_index: 80}` to `social.panics.v1`
4. Index > threshold (65) → `panic_alert:Mumbai` written to Redis → alert published to `state.alerts`
5. **Inventory Simulator** consumes `social.panics.v1` → `panic_multiplier=2.2` for Mumbai pumps → stock depletes faster
6. **Firestore Sync** writes alert to `panic_alerts/Mumbai` in Firestore
7. Flutter PumpCast app has Firestore stream listener → green reassurance banner appears for all Mumbai users
8. **WebSocket Gateway** broadcasts alert to React dashboard → AlertsFeed page shows new reassurance entry

## Scaling Targets

| Metric | Target | How |
|--------|--------|-----|
| AIS messages/sec | 500 | 5 Kafka partitions, 2 vessel-tracker replicas |
| Tweets classified/sec | 50 | 3 social partitions, ONNX ~5ms/inference |
| Concurrent dashboard users | 1,000 | 2 WS gateway replicas, Redis pub/sub |
| Pump status updates/min | 60 pumps × 1/30min = 2/min | Trivial |
| API latency p95 | <100ms | Redis cache for all hot reads |
| DB write throughput | 500 rows/sec | TimescaleDB with 10 async writer workers |
