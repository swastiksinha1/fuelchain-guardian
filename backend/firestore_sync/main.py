"""
Firestore Sync Service

Consumes state.pumps and state.alerts from Kafka and writes them to
Firestore so the Flutter PumpCast app gets real-time updates without
polling the REST API.

Collections written:
  pump_status/{pump_id}   — live inventory status
  panic_alerts/{city}     — official reassurance messages

When FIREBASE_PROJECT_ID is empty the service runs in no-op mode
(logs a warning and still consumes Kafka without writing to Firestore).

Run:  python -m firestore_sync.main
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone

import structlog
from aiokafka import AIOKafkaConsumer
from prometheus_client import Counter, start_http_server

from shared.config import configure_logging, get_settings

logger = structlog.get_logger(__name__)
synced_pumps  = Counter("firestore_sync_pumps_total",  "Pump docs written to Firestore")
synced_alerts = Counter("firestore_sync_alerts_total", "Alert docs written to Firestore")


# ── Firestore client factory ──────────────────────────────────────────────

def _get_firestore_client():
    settings = get_settings()

    if not settings.FIREBASE_PROJECT_ID:
        logger.warning(
            "FIREBASE_PROJECT_ID not set — Firestore sync disabled. "
            "Flutter app will rely on REST polling instead of real-time updates."
        )
        return None

    try:
        import firebase_admin
        from firebase_admin import credentials, firestore

        sa_path = settings.FIREBASE_SERVICE_ACCOUNT_JSON
        if not firebase_admin._apps:
            if os.path.exists(sa_path):
                cred = credentials.Certificate(sa_path)
            else:
                cred = credentials.ApplicationDefault()
            firebase_admin.initialize_app(
                cred, {"projectId": settings.FIREBASE_PROJECT_ID}
            )
        return firestore.client()
    except ImportError:
        logger.warning("firebase-admin not installed — skipping Firestore sync")
        return None
    except Exception as exc:
        logger.error("Firestore init failed", error=str(exc))
        return None


# ── Write helpers (run sync Firestore calls in an executor) ───────────────

async def _write_pump(db, pump: dict) -> None:
    pump_id = pump.get("id")
    if not pump_id:
        return
    loop = asyncio.get_event_loop()
    try:
        ref = db.collection("pump_status").document(pump_id)
        payload = {**pump, "syncedAt": datetime.now(timezone.utc).isoformat()}
        await loop.run_in_executor(None, lambda: ref.set(payload))
        synced_pumps.inc()
    except Exception as exc:
        logger.error("Firestore pump write failed", pump_id=pump_id, error=str(exc))


async def _write_alert(db, alert: dict) -> None:
    city = alert.get("city")
    if not city:
        return
    loop = asyncio.get_event_loop()
    try:
        ref = db.collection("panic_alerts").document(city)
        payload = {**alert, "syncedAt": datetime.now(timezone.utc).isoformat()}
        await loop.run_in_executor(None, lambda: ref.set(payload))
        synced_alerts.inc()
        logger.info("Alert synced", city=city, index=alert.get("panic_index"))
    except Exception as exc:
        logger.error("Firestore alert write failed", city=city, error=str(exc))


# ── Main loop ─────────────────────────────────────────────────────────────

async def run() -> None:
    settings = get_settings()
    configure_logging("firestore-sync")
    start_http_server(9108)

    db = _get_firestore_client()

    consumer = AIOKafkaConsumer(
        "state.pumps",
        "state.alerts",
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id="firestore-sync-group",
        value_deserializer=lambda v: json.loads(v.decode()),
        auto_offset_reset="latest",
    )

    await consumer.start()
    logger.info(
        "Firestore sync started",
        firebase_enabled=(db is not None),
        project=settings.FIREBASE_PROJECT_ID or "N/A",
    )

    try:
        async for msg in consumer:
            if db is None:
                continue  # no-op when Firebase not configured
            data = msg.value
            if msg.topic == "state.pumps":
                await _write_pump(db, data)
            elif msg.topic == "state.alerts":
                await _write_alert(db, data)
    finally:
        await consumer.stop()
        logger.info("Firestore sync stopped")


if __name__ == "__main__":
    asyncio.run(run())
