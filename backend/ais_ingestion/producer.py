"""
AIS Kafka Producer

Reads from AIS provider (real or simulated) and publishes to raw.ais.v1 topic.
Key: MMSI, Value: JSON AIS message.

Run:  python -m ais_ingestion.producer
"""
from __future__ import annotations

import asyncio
import json
import signal
import sys

import structlog
from aiokafka import AIOKafkaProducer
from prometheus_client import Counter, start_http_server

from shared.config import configure_logging, get_settings
from ais_ingestion.providers import get_provider

logger = structlog.get_logger(__name__)

# ── Metrics ────────────────────────────────────────────────────────────────
messages_produced = Counter(
    "ais_producer_messages_total", "AIS messages published to Kafka"
)
producer_errors = Counter(
    "ais_producer_errors_total", "Kafka producer errors"
)


async def run() -> None:
    settings = get_settings()
    configure_logging("ais-producer")

    # Start Prometheus metrics server
    start_http_server(9101)
    logger.info("Prometheus metrics available", port=9101)

    provider = get_provider()

    producer = AIOKafkaProducer(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        key_serializer=lambda k: k.encode("utf-8") if k else None,
        compression_type="gzip",
        acks="all",                # Wait for all replicas
        max_batch_size=16384,
        linger_ms=5,
        retry_backoff_ms=200,
    )

    await producer.start()
    logger.info(
        "AIS producer started",
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        topic="raw.ais.v1",
    )

    # Graceful shutdown handler
    loop = asyncio.get_event_loop()
    stopping = asyncio.Event()

    def _handle_signal(sig):
        logger.info("Shutdown signal received", signal=sig.name)
        stopping.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: _handle_signal(s))

    try:
        async for msg in provider.stream():
            if stopping.is_set():
                break
            try:
                await producer.send_and_wait(
                    topic="raw.ais.v1",
                    key=msg.mmsi,
                    value=msg.to_dict(),
                )
                messages_produced.inc()
                logger.debug(
                    "AIS message published",
                    mmsi=msg.mmsi,
                    lat=msg.lat,
                    lon=msg.lon,
                    sog=msg.sog,
                )
            except Exception as exc:
                producer_errors.inc()
                logger.error("Failed to publish AIS message", error=str(exc), mmsi=msg.mmsi)
    finally:
        await producer.stop()
        logger.info("AIS producer stopped")


if __name__ == "__main__":
    asyncio.run(run())
