# Troubleshooting Guide

## Common Issues

---

### `docker compose up` fails — port already in use

```
Error: bind: address already in use (port 5432)
```

**Fix:** Stop conflicting services:
```bash
# Stop local Postgres
sudo systemctl stop postgresql
# Or change the port in docker-compose.yml:
# "5433:5432" instead of "5432:5432"
```

---

### Redpanda not healthy after startup

```
fuelchain-redpanda | [ERROR] Cluster is not healthy
```

**Fix:** Give Redpanda more time or increase Docker memory:
```bash
# Check Docker memory limit (needs ≥ 4 GB)
docker info | grep Memory
# Restart with fresh volumes
docker compose down -v && docker compose up -d
```

---

### `alembic upgrade head` fails — PostGIS not found

```
ERROR: could not open extension control file ".../postgis.control"
```

**Fix:** The TimescaleDB HA image includes PostGIS. Use it:
```yaml
# docker-compose.yml — use this image:
image: timescale/timescaledb-ha:pg15-latest
# NOT: postgres:15
```

---

### Backend can't connect to Kafka

```
aiokafka.errors.NoBrokersAvailable
```

**Fix:** Wait for Redpanda to be ready (it takes ~20-30 seconds):
```bash
# Check Redpanda health
docker compose exec redpanda rpk cluster health
# Should show: Healthy: true

# Wait and retry
sleep 30 && docker compose restart backend
```

---

### NLP service missing ONNX model

```
ONNX model not found, using keyword fallback
```

This is **expected behaviour** on first run. The keyword classifier works fine for development. To train the real model:
```bash
docker compose exec panic-nlp python -m panic_nlp.train --samples 2000 --epochs 3
# Takes ~10 min on CPU, 2 min on GPU
```

---

### Flutter app can't connect to backend

```
DioException: Connection refused
```

**Fix:** Update `lib/services/api_service.dart`:
```dart
// Android emulator → localhost
static const _baseUrl = 'http://10.0.2.2:8000';

// iOS simulator → localhost
static const _baseUrl = 'http://127.0.0.1:8000';

// Physical device on same WiFi
static const _baseUrl = 'http://192.168.1.X:8000';
```

---

### React dashboard shows blank map

The map uses OpenFreeMap tiles (free, no API key). If tiles don't load:
1. Check browser console for CORS errors
2. Try a different free tile provider:
```tsx
// In frontend/src/pages/MapView.tsx, change:
const MAP_STYLE = 'https://tiles.openfreemap.org/styles/dark'
// To OpenStreetMap:
const MAP_STYLE = 'https://demotiles.maplibre.org/style.json'
```

---

### Pump markers not appearing on map

Pumps are created by the inventory simulator on startup. Check:
```bash
docker compose logs inventory-simulator | tail -20
# Should show: "Pump stations synced to DB, count=60"

# Also check Redis
docker compose exec redis redis-cli keys "pump:*" | wc -l
# Should show: 60
```

---

### pytest tests fail with import errors

```
ModuleNotFoundError: No module named 'backend'
```

**Fix:** Run tests from the project root with PYTHONPATH set:
```bash
cd /path/to/fuelchain-guardian
PYTHONPATH=. pytest tests/ -v
# Or use the Makefile:
make test-unit
```

---

### Credit application returns 403 "KYC not verified"

Demo dealer created by `seed_demo.py` has `verified=True`. If you registered manually, verify via SQL:
```bash
make shell-db
# In psql:
UPDATE dealers SET verified = TRUE WHERE user_id = (
  SELECT id FROM users WHERE email = 'your@email.com'
);
```

---

### Docker out of disk space

```
no space left on device
```

**Fix:**
```bash
# Remove unused images and volumes
docker system prune -af --volumes
# Then restart
make up
```

---

## Getting Help

1. Check service logs: `docker compose logs <service-name>`
2. Check Redpanda Console at http://localhost:8080
3. Check Grafana at http://localhost:3001 for metrics anomalies
4. Open an issue on GitHub with:
   - Output of `docker compose ps`
   - Relevant service logs
   - Your OS and Docker version
