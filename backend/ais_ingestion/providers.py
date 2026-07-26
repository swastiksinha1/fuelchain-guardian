"""
AIS Provider abstraction layer.

AISProvider defines the interface. Two implementations:
  - SimulatorProvider: generates synthetic tanker tracks for dev/testing
  - AISHubProvider: connects to AISHub TCP feed with pyais parsing

Usage:
    from ais_ingestion.providers import get_provider
    async for msg in get_provider().stream():
        ...
"""
from __future__ import annotations

import asyncio
import json
import math
import random
import socket
import struct
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import AsyncIterator

import structlog

from shared.config import get_settings

logger = structlog.get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AISMessage:
    mmsi: str
    lat: float
    lon: float
    sog: float           # Speed over ground, knots
    cog: float           # Course over ground, degrees
    heading: int
    timestamp: str       # ISO 8601 UTC
    nav_status: str = "under_way"
    imo: str = ""
    vessel_name: str = ""
    vessel_type: str = "tanker"
    destination: str = ""
    gross_tonnage: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────────
# Abstract base
# ─────────────────────────────────────────────────────────────────────────────

class AISProvider(ABC):
    """Abstract AIS data provider."""

    @abstractmethod
    async def stream(self) -> AsyncIterator[AISMessage]:
        """Yield AIS messages indefinitely."""
        ...


# ─────────────────────────────────────────────────────────────────────────────
# Simulator
# ─────────────────────────────────────────────────────────────────────────────

# Indian Ocean / Hormuz tanker routes (simplified waypoints)
TANKER_ROUTES = [
    {
        "mmsi": "419001001",
        "name": "MUMBAI SPIRIT",
        "waypoints": [
            (26.5, 56.5),   # Strait of Hormuz entry
            (24.0, 60.0),   # Gulf of Oman
            (22.0, 63.0),
            (20.0, 65.0),
            (18.0, 67.0),
            (16.0, 68.0),
            (15.0, 70.0),
            (14.0, 72.0),   # Approaching India
            (13.0, 74.0),   # Mangalore
        ],
        "destination": "MANGALORE",
        "tonnage": 280000,
        "speed_knots": 14.0,
    },
    {
        "mmsi": "419002002",
        "name": "GUJARAT TITAN",
        "waypoints": [
            (26.5, 56.5),
            (24.0, 60.0),
            (22.0, 63.5),
            (20.5, 66.0),
            (19.0, 69.0),
            (18.0, 71.5),   # Approaching Kandla / Mundra
            (23.0, 70.5),   # Kandla, Gujarat
        ],
        "destination": "KANDLA",
        "tonnage": 320000,
        "speed_knots": 13.5,
    },
    {
        "mmsi": "419003003",
        "name": "CHENNAI PRIDE",
        "waypoints": [
            (26.5, 56.5),
            (24.0, 59.5),
            (20.0, 64.0),
            (15.0, 68.0),
            (10.0, 73.0),
            (10.5, 79.5),   # Ennore / Chennai
        ],
        "destination": "ENNORE",
        "tonnage": 250000,
        "speed_knots": 15.0,
    },
    {
        "mmsi": "419004004",
        "name": "PARADIP VOYAGER",
        "waypoints": [
            (26.5, 56.5),
            (23.0, 60.0),
            (18.0, 64.0),
            (12.0, 72.0),
            (8.0, 77.0),
            (10.0, 80.5),
            (11.0, 83.0),
            (20.5, 86.7),   # Paradip, Odisha
        ],
        "destination": "PARADIP",
        "tonnage": 300000,
        "speed_knots": 12.0,
    },
    {
        "mmsi": "419005005",
        "name": "HALDIA ANCHOR",
        "waypoints": [
            (26.5, 56.5),
            (22.0, 61.0),
            (18.0, 66.0),
            (15.0, 73.0),
            (8.0, 77.0),
            (12.0, 81.0),
            (16.0, 84.0),
            (22.0, 88.1),   # Haldia, West Bengal
        ],
        "destination": "HALDIA",
        "tonnage": 180000,
        "speed_knots": 11.5,
    },
]


class SimulatorProvider(AISProvider):
    """
    Generates synthetic tanker positions along realistic India-bound routes.
    Ships also randomly experience anomalies (slow speed, deviation) for testing.
    """

    def __init__(
        self,
        emit_interval: float = 5.0,    # seconds between position updates
        anomaly_probability: float = 0.05,
    ):
        self.emit_interval = emit_interval
        self.anomaly_probability = anomaly_probability
        # Track each vessel's progress along its route
        self._vessel_progress: dict[str, float] = {
            r["mmsi"]: random.uniform(0, 0.5) for r in TANKER_ROUTES
        }
        self._vessel_anomaly: dict[str, bool] = {r["mmsi"]: False for r in TANKER_ROUTES}

    def _interpolate_position(
        self, waypoints: list[tuple[float, float]], progress: float
    ) -> tuple[float, float]:
        """Linearly interpolate position along waypoints."""
        if progress >= 1.0:
            return waypoints[-1]
        n = len(waypoints) - 1
        seg = progress * n
        i = int(seg)
        t = seg - i
        lat1, lon1 = waypoints[min(i, n - 1)]
        lat2, lon2 = waypoints[min(i + 1, n)]
        return (lat1 + t * (lat2 - lat1), lon1 + t * (lon2 - lon1))

    def _calc_cog(
        self, waypoints: list[tuple[float, float]], progress: float
    ) -> float:
        """Approximate course-over-ground from current heading."""
        p1 = progress
        p2 = min(progress + 0.001, 1.0)
        lat1, lon1 = self._interpolate_position(waypoints, p1)
        lat2, lon2 = self._interpolate_position(waypoints, p2)
        angle = math.degrees(math.atan2(lon2 - lon1, lat2 - lat1))
        return (angle + 360) % 360

    async def stream(self) -> AsyncIterator[AISMessage]:
        logger.info("AIS Simulator started", vessel_count=len(TANKER_ROUTES))
        while True:
            for route in TANKER_ROUTES:
                mmsi = route["mmsi"]
                progress = self._vessel_progress[mmsi]

                if progress >= 1.0:
                    # Reset to beginning with jitter
                    self._vessel_progress[mmsi] = 0.0
                    self._vessel_anomaly[mmsi] = False
                    progress = 0.0

                lat, lon = self._interpolate_position(route["waypoints"], progress)
                cog = self._calc_cog(route["waypoints"], progress)

                # Apply anomaly
                is_anomaly = self._vessel_anomaly[mmsi]
                if not is_anomaly and random.random() < self.anomaly_probability:
                    self._vessel_anomaly[mmsi] = True
                    is_anomaly = True
                    logger.info("Anomaly triggered", mmsi=mmsi)

                if is_anomaly:
                    sog = random.uniform(0.5, 1.8)  # Slow / stopped
                    # Add lateral deviation
                    lat += random.uniform(-0.05, 0.05)
                    lon += random.uniform(-0.05, 0.05)
                    # Recover after ~10% of route
                    if random.random() < 0.1:
                        self._vessel_anomaly[mmsi] = False
                else:
                    sog = route["speed_knots"] + random.gauss(0, 0.5)
                    sog = max(0, sog)

                # Advance progress based on speed
                total_distance_nm = 1200  # Approximate Hormuz→India
                speed_progress_per_tick = (sog * self.emit_interval / 3600) / total_distance_nm
                self._vessel_progress[mmsi] = min(1.0, progress + speed_progress_per_tick)

                msg = AISMessage(
                    mmsi=mmsi,
                    lat=round(lat, 5),
                    lon=round(lon, 5),
                    sog=round(sog, 1),
                    cog=round(cog, 1),
                    heading=int(cog),
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    vessel_name=route["name"],
                    destination=route["destination"],
                    gross_tonnage=route["tonnage"],
                )
                yield msg

            await asyncio.sleep(self.emit_interval)


# ─────────────────────────────────────────────────────────────────────────────
# AISHub Live Provider
# ─────────────────────────────────────────────────────────────────────────────

class AISHubProvider(AISProvider):
    """
    Connects to AISHub TCP data feed.

    Requires:
      - AISHUB_API_KEY env var  (get from https://www.aishub.net/api)
      - AISHUB_HOST / AISHUB_PORT env vars

    AISHub sends NMEA sentences; we parse with pyais.
    """

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.AISHUB_API_KEY
        self.host = settings.AISHUB_HOST
        self.port = settings.AISHUB_PORT

        if not self.api_key:
            raise ValueError("AISHUB_API_KEY is required for AISHubProvider")

    async def stream(self) -> AsyncIterator[AISMessage]:
        try:
            from pyais.stream import TCPConnection
        except ImportError:
            raise RuntimeError("pyais is not installed: pip install pyais")

        logger.info("Connecting to AISHub", host=self.host, port=self.port)

        while True:
            try:
                # pyais TCPConnection is synchronous; run in executor
                loop = asyncio.get_event_loop()
                async for msg in self._tcp_stream(loop):
                    yield msg
            except Exception as exc:
                logger.error("AISHub connection lost, retrying in 30s", error=str(exc))
                await asyncio.sleep(30)

    async def _tcp_stream(self, loop) -> AsyncIterator[AISMessage]:
        from pyais.stream import TCPConnection
        conn = TCPConnection(self.host, self.port)
        try:
            for raw in conn:
                try:
                    decoded = raw.decode()
                    if not hasattr(decoded, "mmsi"):
                        continue
                    msg = AISMessage(
                        mmsi=str(decoded.mmsi),
                        lat=float(decoded.lat) if hasattr(decoded, "lat") else 0.0,
                        lon=float(decoded.lon) if hasattr(decoded, "lon") else 0.0,
                        sog=float(decoded.speed) if hasattr(decoded, "speed") else 0.0,
                        cog=float(decoded.course) if hasattr(decoded, "course") else 0.0,
                        heading=int(decoded.heading) if hasattr(decoded, "heading") else 0,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        vessel_name=getattr(decoded, "shipname", ""),
                        destination=getattr(decoded, "destination", ""),
                    )
                    yield msg
                except Exception as e:
                    logger.warning("Failed to decode AIS message", error=str(e))
        finally:
            conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────────────────

def get_provider() -> AISProvider:
    """Return the appropriate AIS provider based on config."""
    mode = get_settings().AIS_MODE
    if mode == "aishub":
        logger.info("Using AISHub live provider")
        return AISHubProvider()
    else:
        logger.info("Using AIS Simulator provider")
        return SimulatorProvider()
