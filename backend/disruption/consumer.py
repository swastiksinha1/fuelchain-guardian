"""
Disruption Index Service

Consumes alerts.anomaly.v1 and eta-updates.
Aggregates delayed tonnage per destination port over a 6-hour rolling window.
Computes Disruption Index (0-100) = (delayed_tonnage / expected_tonnage) * 100

Publishes to:
  - Redis: disruption:{port_code} → JSON
  - Kafka: metrics.disruption

REST API is part of the main FastAPI app (app/routers/disruption.py).

Run:  python -m disruption.consumer
"""
from __future__ import annotations

import asyncio
import json
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any

import redis.asyncio as aioredis
import structlog
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from prometheus_client import Counter, Gauge, start_http_server
from sqlalchemy import text

from shared.config import configure_logging, get_settings
from shared.database import AsyncSessionLocal

logger = structlog.get_logger(__name__)

disruption_updates = Counter("disruption_index_updates_total", "DI updates computed", ["port"])
disruption_gauge = Gauge("disruption_index_value", "Current disruption index", ["port"])

# Expected total tonnage per port per 6-hour window (approximate, in tonnes)
EXPECTED_TONNAGE = {
    "MANGALORE": 280000,
    "KANDLA": 640000,
    "ENNORE": 250000,
    "PARADIP": 300000,
    "HALDIA": 360000,
}

# Rolling window: port → list of (timestamp, tonnage, delay_hours)
WINDOW_HOURS = 6
port_anomalies: dict[str, deque] = defaultdict(lambda: deque(maxlen=500))


def compute_disruption_index(port: str) -> float:
    """Compute Disruption Index 0-100 for a port from current window."""
    window = port_anomalies[port]
    if not window:
        return 0.0

    cutoff = datetime.now(timezone.utc) - timedelta(hours=WINDOW_HOURS)
    recent = [e for e in window if e["ts"] > cutoff]

    if not recent:
        return 0.0

    delayed_tonnage = sum(e["tonnage"] for e in recent)
    expected = EXPECTED_TONNAGE.get(port.upper(), 300000)

    index = min(100.0, (delayed_tonnage / expected) * 100)
    return round(index, 2)


async def process_anomaly(data: dict, redis: aioredis.Redis, producer: AIOKafkaProducer) -> None:
    port = data.get("destination_port", "").upper()
    if not port:
        return

    tonnage = data.get("gross_tonnage", 100000)
    delay_hours = data.get("estimated_delay_hours", 0)

    port_anomalies[port].append(
        {
            "ts": datetime.now(timezone.utc),
            "tonnage": tonnage,
            "delay_hours": delay_hours,
            "mmsi": data.get("mmsi"),
        }
    )

    index = compute_disruption_index(port)

    payload: dict[str, Any] = {
        "port_code": port,
        "disruption_index": index,
        "delayed_tonnage": sum(e["tonnage"] for e in port_anomalies[port]),
        "expected_tonnage": EXPECTED_TONNAGE.get(port, 300000),
        "window_hours": WINDOW_HOURS,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "active_anomalies": len(
            [e for e in port_anomalies[port]
             if e["ts"] > datetime.now(timezone.utc) - timedelta(hours=WINDOW_HOURS)]
        ),
    }

    # Persist to Redis with 1-hour TTL
    await redis.setex(f"disruption:{port}", 3600, json.dumps(payload))

    # Publish to metrics topic for dashboard
    await producer.send_and_wait(
        topic="metrics.disruption",
        key=port.encode(),
        value=json.dumps(payload).encode(),
    )

    disruption_updates.labels(port=port).inc()
    disruption_gauge.labels(port=port).set(index)

    # Also persist to DB for historical analysis
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("""
                INSERT INTO anomaly_events
                    (id, mmsi, event_type, lat, lon, sog, estimated_delay_hours, destination_port, details)
                VALUES
                    (:id, :mmsi, :event_type, :lat, :lon, :sog, :delay, :port, :details)
            """),
            {
                "id": data.get("event_id"),
                "mmsi": data.get("mmsi"),
                "event_type": data.get("event_type", "anomaly"),
                "lat": data.get("lat"),
                "lon": data.get("lon"),
                "sog": data.get("sog"),
                "delay": delay_hours,
                "port": port,
                "details": json.dumps(data),
            },
        )
        await session.commit()

    logger.info("Disruption index updated", port=port, index=index)


async def run() -> None:
    settings = get_settings()
    configure_logging("disruption-service")
    start_http_server(9104)

    redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)

    consumer = AIOKafkaConsumer(
        "alerts.anomaly.v1",
        "eta-updates",
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id="disruption-service-group",
        value_deserializer=lambda v: json.loads(v.decode()),
        auto_offset_reset="earliest",
    )

    producer = AIOKafkaProducer(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        acks="all",
    )

    await consumer.start()
    await producer.start()
    logger.info("Disruption service started")

    try:
        async for msg in consumer:
            try:
                await process_anomaly(msg.value, redis, producer)
            except Exception as exc:
                logger.error("Error processing anomaly", error=str(exc), data=msg.value)
    finally:
        await consumer.stop()
        await producer.stop()
        await redis.close()


if __name__ == "__main__":
    asyncio.run(run())
