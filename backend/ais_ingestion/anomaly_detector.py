"""
Tanker Anomaly Detector

Consumes raw.ais.v1 and detects:
  1. Slow speed (SOG < 2 knots) inside Hormuz geofence
  2. Off-TSS deviation > 3 NM

Emits anomaly events to alerts.anomaly.v1
Estimates ETA delay and emits to state.vessels

Geofences defined as Shapely polygons.

Run:  python -m ais_ingestion.anomaly_detector
"""
from __future__ import annotations

import asyncio
import json
import math
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Optional

import structlog
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from prometheus_client import Counter, start_http_server
from shapely.geometry import Point, Polygon

from shared.config import configure_logging, get_settings

logger = structlog.get_logger(__name__)

anomalies_detected = Counter("anomaly_detector_events_total", "Anomaly events emitted", ["type"])

# ── Geofences ──────────────────────────────────────────────────────────────
# Strait of Hormuz TSS (Traffic Separation Scheme) bounding polygon
HORMUZ_GEOFENCE = Polygon([
    (56.0, 25.5),
    (59.5, 25.5),
    (59.5, 26.8),
    (56.0, 26.8),
    (56.0, 25.5),
])

# TSS centreline (simplified) — used for lateral deviation check
TSS_CENTRELINE = [
    (56.0, 26.0),
    (57.0, 26.2),
    (58.0, 26.4),
    (59.0, 26.5),
    (59.5, 26.6),
]

# Major Indian destination ports: code → (lat, lon, expected_speed_kt, route_nm)
INDIAN_PORTS = {
    "MANGALORE": (12.87, 74.84, 14.0, 1600),
    "KANDLA": (23.03, 70.22, 13.5, 1200),
    "ENNORE": (13.22, 80.32, 15.0, 1900),
    "PARADIP": (20.26, 86.68, 12.0, 2400),
    "HALDIA": (22.02, 88.07, 11.5, 2700),
}

# Sliding window: mmsi → deque of (timestamp, sog, lat, lon)
WINDOW_MINUTES = 15
vessel_windows: dict[str, deque] = defaultdict(lambda: deque(maxlen=200))


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in nautical miles between two lat/lon points."""
    R_nm = 3440.065
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R_nm * 2 * math.asin(math.sqrt(a))


def min_dist_to_polyline(lat: float, lon: float, line: list[tuple]) -> float:
    """Minimum distance in NM from point to a polyline."""
    min_dist = float("inf")
    for i in range(len(line) - 1):
        # Simple point-to-segment approximation
        alat, alon = line[i]
        blast, blon = line[i + 1]
        d = haversine_nm(lat, lon, (alat + blast) / 2, (alon + blon) / 2)
        min_dist = min(min_dist, d)
    return min_dist


def estimate_delay_hours(
    mmsi: str,
    destination: str,
    current_sog: float,
    lat: float,
    lon: float,
) -> Optional[float]:
    """Estimate delay in hours based on current speed vs planned."""
    port_info = INDIAN_PORTS.get(destination.upper())
    if not port_info:
        return None

    port_lat, port_lon, planned_speed, _ = port_info
    remaining_nm = haversine_nm(lat, lon, port_lat, port_lon)

    if current_sog < 0.5:
        current_sog = 0.5  # avoid division by zero

    planned_hours = remaining_nm / planned_speed
    actual_hours = remaining_nm / current_sog

    delay = max(0, actual_hours - planned_hours)
    return round(delay, 1)


async def process_message(
    data: dict,
    producer: AIOKafkaProducer,
) -> None:
    mmsi = data.get("mmsi")
    lat = data.get("lat", 0.0)
    lon = data.get("lon", 0.0)
    sog = data.get("sog", 0.0)
    ts = data.get("timestamp")
    destination = data.get("destination", "")

    if not mmsi or not ts:
        return

    point = Point(lon, lat)

    # Only analyse vessels inside Hormuz
    if not HORMUZ_GEOFENCE.contains(point):
        return

    # Add to sliding window
    window = vessel_windows[mmsi]
    window.append({"ts": ts, "sog": sog, "lat": lat, "lon": lon})

    # Keep only last WINDOW_MINUTES minutes
    try:
        now = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        cutoff_ts = now.timestamp() - WINDOW_MINUTES * 60
        while window and datetime.fromisoformat(
            window[0]["ts"].replace("Z", "+00:00")
        ).timestamp() < cutoff_ts:
            window.popleft()
    except Exception:
        pass

    if len(window) < 3:
        return

    avg_sog = sum(w["sog"] for w in window) / len(window)
    dev_nm = min_dist_to_polyline(lat, lon, TSS_CENTRELINE)

    anomaly_type = None
    if avg_sog < 2.0:
        anomaly_type = "slow_speed"
    elif dev_nm > 3.0:
        anomaly_type = "off_course"

    if anomaly_type:
        delay_hours = estimate_delay_hours(mmsi, destination, avg_sog, lat, lon)

        event = {
            "event_id": str(uuid.uuid4()),
            "mmsi": mmsi,
            "event_type": anomaly_type,
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "lat": lat,
            "lon": lon,
            "sog": sog,
            "avg_sog": round(avg_sog, 2),
            "deviation_nm": round(dev_nm, 2),
            "estimated_delay_hours": delay_hours,
            "destination_port": destination,
            "vessel_name": data.get("vessel_name", ""),
            "gross_tonnage": data.get("gross_tonnage", 0),
        }

        await producer.send_and_wait(
            topic="alerts.anomaly.v1",
            key=mmsi,
            value=json.dumps(event).encode(),
        )

        if delay_hours:
            eta_event = {
                "mmsi": mmsi,
                "destination": destination,
                "delay_hours": delay_hours,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "tonnage": data.get("gross_tonnage", 0),
            }
            await producer.send_and_wait(
                topic="eta-updates",
                key=mmsi,
                value=json.dumps(eta_event).encode(),
            )

        anomalies_detected.labels(type=anomaly_type).inc()
        logger.warning(
            "Anomaly detected",
            mmsi=mmsi,
            type=anomaly_type,
            avg_sog=avg_sog,
            deviation_nm=dev_nm,
            delay_hours=delay_hours,
        )


async def run() -> None:
    settings = get_settings()
    configure_logging("anomaly-detector")
    start_http_server(9103)

    consumer = AIOKafkaConsumer(
        "raw.ais.v1",
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id="anomaly-detector-group",
        value_deserializer=lambda v: json.loads(v.decode()),
        auto_offset_reset="latest",
    )

    producer = AIOKafkaProducer(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        value_serializer=lambda v: v if isinstance(v, bytes) else v.encode(),
        acks="all",
    )

    await consumer.start()
    await producer.start()
    logger.info("Anomaly detector started")

    try:
        async for msg in consumer:
            await process_message(msg.value, producer)
    finally:
        await consumer.stop()
        await producer.stop()


if __name__ == "__main__":
    asyncio.run(run())
