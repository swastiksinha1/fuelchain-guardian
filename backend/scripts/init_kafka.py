"""
Kafka Topic Initialization

Creates all required topics with partitions and retention.

Run:  python -m scripts.init_kafka
"""
from __future__ import annotations
import asyncio
import sys
import structlog
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from shared.config import configure_logging, get_settings

logger = structlog.get_logger(__name__)

TOPICS = [
    NewTopic("raw.ais.v1",         num_partitions=5, replication_factor=1,
             topic_configs={"retention.ms": "86400000",   "compression.type": "gzip"}),
    NewTopic("raw.social.v1",      num_partitions=3, replication_factor=1,
             topic_configs={"retention.ms": "43200000"}),
    NewTopic("alerts.anomaly.v1",  num_partitions=2, replication_factor=1,
             topic_configs={"retention.ms": "604800000"}),
    NewTopic("eta-updates",        num_partitions=2, replication_factor=1,
             topic_configs={"retention.ms": "86400000"}),
    NewTopic("state.vessels",      num_partitions=3, replication_factor=1,
             topic_configs={"cleanup.policy": "compact", "retention.ms": "604800000"}),
    NewTopic("state.pumps",        num_partitions=3, replication_factor=1,
             topic_configs={"cleanup.policy": "compact", "retention.ms": "86400000"}),
    NewTopic("state.alerts",       num_partitions=1, replication_factor=1,
             topic_configs={"retention.ms": "604800000"}),
    NewTopic("metrics.disruption", num_partitions=1, replication_factor=1,
             topic_configs={"retention.ms": "2592000000"}),
    NewTopic("social.panics.v1",   num_partitions=3, replication_factor=1,
             topic_configs={"retention.ms": "604800000"}),
]


async def init_topics() -> None:
    settings = get_settings()
    configure_logging("init-kafka")

    logger.info("Connecting", brokers=settings.KAFKA_BOOTSTRAP_SERVERS)
    admin = AIOKafkaAdminClient(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        client_id="fuelchain-admin",
    )

    for attempt in range(15):
        try:
            await admin.start()
            break
        except Exception as e:
            logger.warning(f"Not ready (attempt {attempt+1}/15)", error=str(e))
            await asyncio.sleep(3)
    else:
        logger.error("Could not connect to Kafka after 15 attempts")
        sys.exit(1)

    try:
        existing = await admin.list_topics()
        to_create = [t for t in TOPICS if t.name not in existing]
        if not to_create:
            logger.info("All topics already exist")
        else:
            result = await admin.create_topics(to_create, validate_only=False)
            for topic, exc in result.items():
                if exc is None:
                    logger.info("Topic created", topic=topic)
                else:
                    logger.error("Failed", topic=topic, error=str(exc))
        logger.info("Done", topics=[t.name for t in TOPICS])
    finally:
        await admin.close()


if __name__ == "__main__":
    asyncio.run(init_topics())
