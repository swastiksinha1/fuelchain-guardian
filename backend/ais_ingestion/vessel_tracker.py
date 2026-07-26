"""
Vessel Tracker — Kafka Consumer

Consumes raw.ais.v1, deduplicates, writes to TimescaleDB vessel_positions hypertable,
and maintains current vessel state in Redis.

Consumer group: vessel-tracker-group (allows horizontal scaling)

Run:  python -m ais_ingestion.vessel_tracker
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone

import redis.asyncio as aioredis
import structlog
from aiokafka import AIOKafkaConsumer
from prometheus_client import Counter, Histogram, start_http_server
from sqlalchemy import text

from shared.config import configure_logging, get_settings
from shared.database import AsyncSessionLocal

logger = structlog.get_logger(__name__)

# ── Metrics ────────────────────────────────────────────────────────────────
messages_consumed = Counter(
    "vessel_tracker_messages_total", "AIS messages consumed"
)
db_write_latency = Histogram(
    "vessel_tracker_db_write_seconds", "DB write latency"
)
duplicates_skipped = Counter(
    "vessel_tracker_duplicates_total", "Duplicate messages skipped"
)

DEDUP_TTL = 60  # seconds — deduplicate within this window
VESSEL_STATE_TTL = 3600 * 24  # 24 hours in Redis


async def upsert_vessel(session, msg: dict) -> None:
    """Insert or update vessel metadata."""
    await session.execute(
        text("""
            INSERT INTO vessels (mmsi, name, vessel_type, destination, updated_at)
            VALUES (:mmsi, :name, :vessel_type, :destination, now())
            ON CONFLICT (mmsi) DO UPDATE SET
                name = EXCLUDED.name,
                destination = EXCLUDED.destination,
                updated_at = now()
        """),
        {
            "mmsi": msg["mmsi"],
            "name": msg.get("vessel_name", ""),
            "vessel_type": msg.get("vessel_type", "tanker"),
            "destination": msg.get("destination", ""),
        },
    )


async def insert_position(session, msg: dict) -> None:
    """Insert a vessel position into the TimescaleDB hypertable."""
    lon = msg["lon"]
    lat = msg["lat"]
    await session.execute(
        text("""
            INSERT INTO vessel_positions
                (id, mmsi, timestamp, lat, lon, sog, cog, heading, nav_status, location)
            VALUES
                (:id, :mmsi, :timestamp, :lat, :lon, :sog, :cog, :heading, :nav_status,
                 ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))
        """),
        {
            "id": str(uuid.uuid4()),
            "mmsi": msg["mmsi"],
            "timestamp": msg["timestamp"],
            "lat": lat,
            "lon": lon,
            "sog": msg.get("sog"),
            "cog": msg.get("cog"),
            "heading": msg.get("heading"),
            "nav_status": msg.get("nav_status", "under_way"),
        },
    )


async def run() -> None:
    settings = get_settings()
    configure_logging("vessel-tracker")
    start_http_server(9102)

    redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)

    consumer = AIOKafkaConsumer(
        "raw.ais.v1",
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id="vessel-tracker-group",
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        auto_offset_reset="latest",
        enable_auto_commit=False,
        max_poll_records=500,
    )

    await consumer.start()
    logger.info("Vessel tracker started", topic="raw.ais.v1")

    try:
        async for batch in consumer:
            # Process messages in batches
            messages_to_write = []

            for msg in [batch]:
                data = msg.value
                mmsi = data.get("mmsi")
                ts = data.get("timestamp")

                if not mmsi or not ts:
                    continue

                # Deduplication: skip if we've seen mmsi+timestamp recently
                dedup_key = f"ais_dedup:{mmsi}:{ts[:16]}"  # minute-level
                if await redis.exists(dedup_key):
                    duplicates_skipped.inc()
                    continue
                await redis.setex(dedup_key, DEDUP_TTL, "1")

                messages_to_write.append(data)
                messages_consumed.inc()

            if messages_to_write:
                with db_write_latency.time():
                    async with AsyncSessionLocal() as session:
                        for data in messages_to_write:
                            try:
                                await upsert_vessel(session, data)
                                await insert_position(session, data)
                            except Exception as e:
                                logger.error(
                                    "DB write failed", error=str(e), mmsi=data.get("mmsi")
                                )

                        await session.commit()

                # Update vessel state in Redis for fast dashboard reads
                for data in messages_to_write:
                    state_key = f"vessel:{data['mmsi']}"
                    await redis.setex(
                        state_key,
                        VESSEL_STATE_TTL,
                        json.dumps(data),
                    )

            await consumer.commit()

    finally:
        await consumer.stop()
        await redis.close()
        logger.info("Vessel tracker stopped")


if __name__ == "__main__":
    asyncio.run(run())
