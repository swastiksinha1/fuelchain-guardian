# FuelChain Guardian — Kafka Topic Schemas

All messages use JSON encoding. Field types follow JSON Schema conventions.

---

## `raw.ais.v1`
**Key**: MMSI string  
**Partitions**: 5  
**Retention**: 1 day  
**Producer**: `ais_ingestion.producer`

```json
{
  "mmsi": "419001001",
  "lat": 26.5,
  "lon": 57.0,
  "sog": 14.2,
  "cog": 135.0,
  "heading": 135,
  "timestamp": "2024-01-01T12:00:00+00:00",
  "nav_status": "under_way",
  "vessel_name": "MUMBAI SPIRIT",
  "vessel_type": "tanker",
  "destination": "KANDLA",
  "gross_tonnage": 280000,
  "imo": "9234567"
}
```

---

## `raw.social.v1`
**Key**: tweet_id  
**Partitions**: 3  
**Retention**: 12 hours  
**Producer**: `panic_nlp.social_producer`

```json
{
  "tweet_id": "1234567890123456789",
  "text": "No petrol at any pump in Mumbai! #FuelCrisis",
  "city": "Mumbai",
  "lang": "en",
  "created_at": "2024-01-01T12:00:00+00:00",
  "author_id": "987654321",
  "simulated": false
}
```

---

## `alerts.anomaly.v1`
**Key**: MMSI string  
**Partitions**: 2  
**Retention**: 7 days  
**Producer**: `ais_ingestion.anomaly_detector`

```json
{
  "event_id": "uuid-v4",
  "mmsi": "419001001",
  "event_type": "slow_speed | off_course",
  "detected_at": "2024-01-01T12:00:00+00:00",
  "lat": 26.2,
  "lon": 57.5,
  "sog": 0.8,
  "avg_sog": 1.2,
  "deviation_nm": 0.0,
  "estimated_delay_hours": 12.0,
  "destination_port": "KANDLA",
  "vessel_name": "MUMBAI SPIRIT",
  "gross_tonnage": 280000
}
```

---

## `eta-updates`
**Key**: MMSI string  
**Partitions**: 2  
**Retention**: 1 day  
**Producer**: `ais_ingestion.anomaly_detector`

```json
{
  "mmsi": "419001001",
  "destination": "KANDLA",
  "delay_hours": 12.0,
  "updated_at": "2024-01-01T12:00:00+00:00",
  "tonnage": 280000
}
```

---

## `state.vessels`
**Key**: MMSI string  
**Partitions**: 3  
**Cleanup policy**: compact (latest value per key)  
**Producer**: `ais_ingestion.vessel_tracker`

Same schema as `raw.ais.v1` plus `status: "on_time|delayed|anomaly"`.

---

## `state.pumps`
**Key**: pump_id string  
**Partitions**: 3  
**Cleanup policy**: compact  
**Producer**: `inventory.simulator`

```json
{
  "id": "PUMP0001",
  "name": "Mumbai Pump 1",
  "city": "Mumbai",
  "state": "Maharashtra",
  "lat": 19.082,
  "lon": 72.891,
  "petrol_pct": 42.5,
  "diesel_pct": 67.2,
  "status": "YELLOW",
  "panic_multiplier": 1.3,
  "hours_to_empty_petrol": 18.5,
  "hours_to_empty_diesel": null,
  "updated_at": "2024-01-01T12:30:00+00:00"
}
```

---

## `metrics.disruption`
**Key**: port_code string  
**Partitions**: 1  
**Retention**: 30 days  
**Producer**: `disruption.consumer`

```json
{
  "port_code": "KANDLA",
  "disruption_index": 45.2,
  "delayed_tonnage": 289600,
  "expected_tonnage": 640000,
  "window_hours": 6,
  "computed_at": "2024-01-01T12:00:00+00:00",
  "active_anomalies": 2
}
```

---

## `social.panics.v1`
**Key**: city string  
**Partitions**: 3  
**Retention**: 7 days  
**Producer**: `panic_nlp.aggregator`

```json
{
  "city": "Mumbai",
  "panic_index": 72.4,
  "is_panic": true,
  "updated_at": "2024-01-01T12:00:00+00:00"
}
```

---

## `state.alerts`
**Key**: city string  
**Partitions**: 1  
**Retention**: 7 days  
**Producer**: `panic_nlp.aggregator`

```json
{
  "city": "Mumbai",
  "panic_index": 72.4,
  "message": "OMCs confirm adequate fuel stocks. Please avoid panic buying.",
  "issued_at": "2024-01-01T12:00:00+00:00",
  "type": "reassurance"
}
```

---

## Schema Registry Note

For production deployments with multiple teams, consider using Confluent Schema Registry with Avro schemas. The JSON schemas above are the authoritative source; generate Avro schemas from these definitions.

Redpanda ships with a built-in Schema Registry accessible at port 18081.
To register a schema:
```bash
curl -X POST http://localhost:18081/subjects/raw.ais.v1-value/versions \
  -H 'Content-Type: application/vnd.schemaregistry.v1+json' \
  -d '{"schema": "{\"type\":\"record\",\"name\":\"AISMessage\",...}"}'
```
