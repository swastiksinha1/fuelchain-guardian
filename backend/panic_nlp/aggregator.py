"""
Panic Aggregator

Consumes raw.social.v1, calls NLP service to classify each tweet,
aggregates panic counts per city per hour, and publishes Panic Index.

Triggers reassurance notifications when index exceeds threshold.

Run:  python -m panic_nlp.aggregator
"""
from __future__ import annotations

import asyncio
import json
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import httpx
import redis.asyncio as aioredis
import structlog
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from prometheus_client import Counter, Gauge, start_http_server
from sqlalchemy import text

from shared.config import configure_logging, get_settings
from shared.database import AsyncSessionLocal

logger = structlog.get_logger(__name__)

panic_index_gauge = Gauge("panic_index_value", "Current panic index", ["city"])
tweets_classified = Counter("panic_aggregator_classified_total", "Tweets classified")
alerts_sent = Counter("panic_aggregator_alerts_total", "Reassurance alerts sent", ["city"])

# In-memory hourly buckets: city → {hour_bucket → {count, panic_count}}
city_buckets: dict[str, dict] = defaultdict(lambda: defaultdict(lambda: {"count": 0, "panic": 0}))


def current_hour_bucket() -> str:
    now = datetime.now(timezone.utc)
    return now.replace(minute=0, second=0, microsecond=0).isoformat()


def compute_panic_index(city: str, hour: str) -> float:
    bucket = city_buckets[city].get(hour, {"count": 0, "panic": 0})
    if bucket["count"] == 0:
        return 0.0
    return round((bucket["panic"] / bucket["count"]) * 100, 1)


REASSURANCE_MESSAGES = [
    "OMCs confirm adequate fuel stocks. Please avoid panic buying. Supply is normal.",
    "Government ensures fuel supply is stable. No shortage — queue at your nearest pump calmly.",
    "Official: India's strategic fuel reserves are sufficient. Rumours of dry-outs are FALSE.",
    "Ministry of Petroleum: All depots operational. Tanker fleet on schedule. No shortage.",
]


async def send_reassurance(
    city: str,
    panic_index: float,
    redis: aioredis.Redis,
    producer: AIOKafkaProducer,
) -> None:
    import random
    message = random.choice(REASSURANCE_MESSAGES)
    alert = {
        "city": city,
        "panic_index": panic_index,
        "message": message,
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "type": "reassurance",
    }

    # Push to Redis for Flutter app to pick up
    await redis.setex(f"panic_alert:{city}", 3600, json.dumps(alert))

    # Publish to Kafka for dashboard
    await producer.send_and_wait(
        topic="state.alerts",
        key=city.encode(),
        value=json.dumps(alert).encode(),
    )

    alerts_sent.labels(city=city).inc()
    logger.warning("Reassurance alert issued", city=city, index=panic_index)


async def run() -> None:
    settings = get_settings()
    configure_logging("panic-aggregator")
    start_http_server(9107)

    redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)

    consumer = AIOKafkaConsumer(
        "raw.social.v1",
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id="panic-aggregator-group",
        value_deserializer=lambda v: json.loads(v.decode()),
        auto_offset_reset="latest",
    )

    producer = AIOKafkaProducer(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        acks=1,
    )

    await consumer.start()
    await producer.start()
    logger.info("Panic aggregator started", nlp_url=settings.NLP_SERVICE_URL)

    async with httpx.AsyncClient(timeout=5.0) as http:
        try:
            async for msg in consumer:
                tweet = msg.value
                text_content = tweet.get("text", "")
                city = tweet.get("city")
                tweet_id = tweet.get("tweet_id")

                # Call NLP service
                try:
                    resp = await http.post(
                        f"{settings.NLP_SERVICE_URL}/classify",
                        json={
                            "text": text_content,
                            "city": city,
                            "tweet_id": tweet_id,
                        },
                    )
                    result = resp.json()
                    is_panic = result.get("is_panic", False)
                    score = result.get("score", 0.0)
                    city = result.get("city") or city or "Unknown"
                except Exception as e:
                    logger.warning("NLP service error, using fallback", error=str(e))
                    # Simple keyword fallback
                    kws = ["shortage", "khatam", "queue", "empty", "crisis"]
                    is_panic = any(kw in text_content.lower() for kw in kws)
                    score = 0.6 if is_panic else 0.2
                    city = city or "Unknown"

                tweets_classified.inc()
                hour = current_hour_bucket()

                # Update in-memory bucket
                city_buckets[city][hour]["count"] += 1
                if is_panic:
                    city_buckets[city][hour]["panic"] += 1

                index = compute_panic_index(city, hour)
                panic_index_gauge.labels(city=city).set(index)

                # Persist event
                async with AsyncSessionLocal() as session:
                    await session.execute(
                        text("""
                            INSERT INTO panic_events (id, tweet_id, text, city, panic_score, is_panic)
                            VALUES (:id, :tweet_id, :text, :city, :score, :is_panic)
                            ON CONFLICT (tweet_id) DO NOTHING
                        """),
                        {
                            "id": str(uuid.uuid4()),
                            "tweet_id": tweet_id,
                            "text": text_content[:2000],
                            "city": city,
                            "score": score,
                            "is_panic": is_panic,
                        },
                    )
                    # Upsert panic index
                    await session.execute(
                        text("""
                            INSERT INTO panic_index (id, city, hour_bucket, tweet_count, panic_count, panic_index)
                            VALUES (:id, :city, :hour, :tc, :pc, :pi)
                            ON CONFLICT (city, hour_bucket) DO UPDATE SET
                                tweet_count = panic_index.tweet_count + 1,
                                panic_count = panic_index.panic_count + :pc,
                                panic_index = :pi
                        """),
                        {
                            "id": str(uuid.uuid4()),
                            "city": city,
                            "hour": hour,
                            "tc": 1,
                            "pc": 1 if is_panic else 0,
                            "pi": index,
                        },
                    )
                    await session.commit()

                # Publish current panic index
                pi_payload = {
                    "city": city,
                    "panic_index": index,
                    "is_panic": is_panic,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                await producer.send(
                    "social.panics.v1",
                    key=city.encode(),
                    value=json.dumps(pi_payload).encode(),
                )
                await redis.setex(f"panic:{city}", 3600, json.dumps(pi_payload))

                # Check if reassurance needed
                alert_key = f"panic_alert_sent:{city}:{hour}"
                if index >= settings.PANIC_THRESHOLD and not await redis.exists(alert_key):
                    await send_reassurance(city, index, redis, producer)
                    await redis.setex(alert_key, 3600, "1")

        finally:
            await consumer.stop()
            await producer.stop()
            await redis.close()


if __name__ == "__main__":
    asyncio.run(run())
