# AIS Data Integration Guide

## Development Mode (Simulator — Default)

No API key required. Set `AIS_MODE=simulator` in `.env`.

The simulator generates 5 synthetic India-bound tankers:
- MUMBAI SPIRIT → Mangalore
- GUJARAT TITAN → Kandla
- CHENNAI PRIDE → Ennore
- PARADIP VOYAGER → Paradip
- HALDIA ANCHOR → Haldia

Each follows a realistic route from the Strait of Hormuz.
With `anomaly_probability=0.05`, ~1 in 20 ticks triggers a slow-speed anomaly.

---

## Production Mode (AISHub)

### 1. Get AISHub API Key

1. Register at https://www.aishub.net/users/register
2. After approval, go to https://www.aishub.net/api
3. Copy your API key
4. Add to `.env`: `AISHUB_API_KEY=your_key_here`
5. Set `AIS_MODE=aishub`

AISHub provides:
- Global AIS coverage from 1,500+ receivers
- ~1-5 sec update frequency for busy waters
- Includes Strait of Hormuz and Indian Ocean

### 2. AISHub TCP Connection Details

The `AISHubProvider` connects to:
- Host: `data.aishub.net`
- Port: `9876`
- Protocol: TCP stream of NMEA 0183 sentences

### 3. Alternative: MarineTraffic API

If you prefer MarineTraffic, implement `MarineTrafficProvider` extending `AISProvider`:

```python
# backend/ais_ingestion/providers.py
class MarineTrafficProvider(AISProvider):
    """
    MarineTraffic API v2 — REST polling every 60s.
    Get key at: https://www.marinetraffic.com/en/online-services/plans
    """
    API_URL = "https://services.marinetraffic.com/api/exportvessel/v:8/{api_key}"

    def __init__(self):
        self.api_key = get_settings().MARINETRAFFIC_API_KEY

    async def stream(self) -> AsyncIterator[AISMessage]:
        async with httpx.AsyncClient() as client:
            while True:
                resp = await client.get(
                    self.API_URL.format(api_key=self.api_key),
                    params={
                        "protocol": "json",
                        "msgtype": "simple",
                        "shiptype": "8",      # Tankers
                        "minlat": "8",
                        "maxlat": "30",
                        "minlon": "50",
                        "maxlon": "90",       # Indian Ocean bounding box
                    }
                )
                for vessel in resp.json():
                    yield AISMessage(...)
                await asyncio.sleep(60)
```

### 4. Filtering for Relevant Vessels

The anomaly detector automatically filters vessels to those inside the Hormuz geofence. For efficiency, you can pre-filter at ingestion:

```python
# Only publish tankers in the Indian Ocean (lat 0-35, lon 50-100)
if 0 <= msg.lat <= 35 and 50 <= msg.lon <= 100:
    await producer.send("raw.ais.v1", ...)
```

---

## Geofence Configuration

Geofences are defined in `ais_ingestion/anomaly_detector.py` as Shapely polygons.

To add a new geofence (e.g., Malacca Strait):
```python
MALACCA_GEOFENCE = Polygon([
    (99.0, 1.0), (104.0, 1.0),
    (104.0, 6.0), (99.0, 6.0),
    (99.0, 1.0),
])
```

To persist geofences in the database (for runtime editing):
```sql
CREATE TABLE geofences (
    name TEXT PRIMARY KEY,
    description TEXT,
    polygon GEOMETRY(POLYGON, 4326) NOT NULL,
    active BOOLEAN DEFAULT TRUE
);

INSERT INTO geofences VALUES (
    'hormuz_tss',
    'Strait of Hormuz Traffic Separation Scheme',
    ST_GeomFromText('POLYGON((56 25.5, 59.5 25.5, 59.5 26.8, 56 26.8, 56 25.5))', 4326),
    TRUE
);
```
