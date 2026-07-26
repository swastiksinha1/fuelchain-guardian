"""
Vessel State API router — current vessel states from Redis + TimescaleDB track.
"""
from __future__ import annotations

import json
from typing import Optional

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.config import get_settings
from shared.database import get_db

router = APIRouter()
logger = structlog.get_logger(__name__)
settings = get_settings()


async def get_redis():
    r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        yield r
    finally:
        await r.close()


@router.get("")
async def list_vessels(
    redis: aioredis.Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
):
    vessels = []
    async for key in redis.scan_iter("vessel:*"):
        data = await redis.get(key)
        if data:
            vessels.append(json.loads(data))

    if not vessels:
        result = await db.execute(
            text("SELECT mmsi, name AS vessel_name, destination FROM vessels LIMIT 200")
        )
        vessels = [dict(row._mapping) for row in result.fetchall()]

    return {"vessels": vessels, "count": len(vessels)}


@router.get("/{mmsi}")
async def get_vessel(
    mmsi: str,
    hours: int = Query(default=6, ge=1, le=48),
    redis: aioredis.Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
):
    state_json = await redis.get(f"vessel:{mmsi}")
    vessel_data = json.loads(state_json) if state_json else {}

    track_result = await db.execute(
        text("""
            SELECT lat, lon, sog, cog, timestamp
            FROM vessel_positions
            WHERE mmsi = :mmsi
              AND timestamp > now() - (:hours || ' hours')::interval
            ORDER BY timestamp DESC
            LIMIT 500
        """),
        {"mmsi": mmsi, "hours": hours},
    )
    track = [dict(r._mapping) for r in track_result.fetchall()]

    anomaly_result = await db.execute(
        text("""
            SELECT event_type, detected_at, estimated_delay_hours, destination_port
            FROM anomaly_events
            WHERE mmsi = :mmsi AND resolved = false
            ORDER BY detected_at DESC LIMIT 10
        """),
        {"mmsi": mmsi},
    )
    anomalies = [dict(r._mapping) for r in anomaly_result.fetchall()]

    return {"mmsi": mmsi, **vessel_data, "track": track, "active_anomalies": anomalies}
