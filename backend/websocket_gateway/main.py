"""
WebSocket Gateway

Bridges Kafka topics to WebSocket clients (React dashboard).
Clients connect to ws://host:8002/ws and receive real-time events.

Topics subscribed:
  - state.vessels      → vessel position/status updates
  - state.pumps        → pump inventory changes
  - alerts.anomaly.v1  → tanker anomaly events
  - metrics.disruption → disruption index updates
  - social.panics.v1   → panic index updates
  - state.alerts       → reassurance alerts

Run:  python -m websocket_gateway.main
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Optional

import structlog
import uvicorn
from aiokafka import AIOKafkaConsumer
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import Counter, Gauge, make_asgi_app

from shared.config import configure_logging, get_settings

logger = structlog.get_logger(__name__)
configure_logging("ws-gateway")
settings = get_settings()

# ── Metrics ────────────────────────────────────────────────────────────────
ws_connections = Gauge("ws_gateway_active_connections", "Active WebSocket connections")
messages_forwarded = Counter(
    "ws_gateway_messages_total", "Messages forwarded to clients", ["topic"]
)

# ── Connection Manager ─────────────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self.active.append(ws)
        ws_connections.set(len(self.active))
        logger.info("WebSocket client connected", total=len(self.active))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            if ws in self.active:
                self.active.remove(ws)
        ws_connections.set(len(self.active))
        logger.info("WebSocket client disconnected", total=len(self.active))

    async def broadcast(self, message: dict) -> None:
        if not self.active:
            return

        payload = json.dumps(message)
        dead: list[WebSocket] = []

        for ws in list(self.active):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)

        for ws in dead:
            await self.disconnect(ws)


manager = ConnectionManager()

# ── Kafka Consumer Background Task ────────────────────────────────────────

TOPICS = [
    "state.vessels",
    "state.pumps",
    "alerts.anomaly.v1",
    "metrics.disruption",
    "social.panics.v1",
    "state.alerts",
]

# Topic → event_type mapping for client filtering
TOPIC_EVENT_TYPES = {
    "state.vessels": "vessel_update",
    "state.pumps": "pump_update",
    "alerts.anomaly.v1": "anomaly_alert",
    "metrics.disruption": "disruption_update",
    "social.panics.v1": "panic_update",
    "state.alerts": "reassurance_alert",
}


async def kafka_consumer_loop() -> None:
    """Consume Kafka topics and broadcast to WebSocket clients."""
    consumer = AIOKafkaConsumer(
        *TOPICS,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id="ws-gateway-group",
        value_deserializer=lambda v: json.loads(v.decode()),
        auto_offset_reset="latest",
    )

    while True:
        try:
            await consumer.start()
            logger.info("Kafka consumer started for WebSocket gateway", topics=TOPICS)

            async for msg in consumer:
                event_type = TOPIC_EVENT_TYPES.get(msg.topic, "unknown")
                envelope = {
                    "type": event_type,
                    "topic": msg.topic,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "data": msg.value,
                }
                await manager.broadcast(envelope)
                messages_forwarded.labels(topic=msg.topic).inc()

        except Exception as exc:
            logger.error("Kafka consumer error, reconnecting in 10s", error=str(exc))
            try:
                await consumer.stop()
            except Exception:
                pass
            await asyncio.sleep(10)


# ── FastAPI App ───────────────────────────────────────────────────────────

app = FastAPI(title="FuelChain WebSocket Gateway", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


@app.on_event("startup")
async def startup():
    asyncio.create_task(kafka_consumer_loop())
    logger.info("WebSocket gateway started")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "active_connections": len(manager.active),
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # Send welcome message with current state hint
        await websocket.send_json({
            "type": "connected",
            "message": "Connected to FuelChain Guardian real-time feed",
            "topics": TOPICS,
        })

        # Keep connection alive — client can send pings
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")

    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(websocket)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8002, log_config=None)
