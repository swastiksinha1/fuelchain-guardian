"""
Pumps router — serves pump inventory status.
Uses Redis for hot reads; PostgreSQL/PostGIS for geo queries.
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


@router.get("/nearby")
async def pumps_nearby(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius: float = Query(default=5000, ge=100, le=50000),  # meters
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """
    Return pumps within radius meters of (lat, lon) as GeoJSON FeatureCollection.
    Status and predictions from Redis; geometry from PostGIS.
    """
    result = await db.execute(
        text("""
            SELECT
                p.id::text, p.name, p.city, p.state, p.lat, p.lon,
                ST_Distance(
                    p.location::geography,
                    ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
                ) AS distance_m
            FROM pump_stations p
            WHERE ST_DWithin(
                p.location::geography,
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                :radius
            )
            AND p.active = true
            ORDER BY distance_m
            LIMIT 50
        """),
        {"lat": lat, "lon": lon, "radius": radius},
    )
    rows = result.fetchall()

    features = []
    for row in rows:
        pump_id = row.id
        # Enrich with live status from Redis
        redis_data = await redis.get(f"pump:{pump_id}")
        live = json.loads(redis_data) if redis_data else {}

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [row.lon, row.lat],
            },
            "properties": {
                "id": pump_id,
                "name": row.name,
                "city": row.city,
                "state": row.state,
                "distance_m": round(row.distance_m, 0),
                "status": live.get("status", "UNKNOWN"),
                "petrol_pct": live.get("petrol_pct"),
                "diesel_pct": live.get("diesel_pct"),
                "hours_to_empty_petrol": live.get("hours_to_empty_petrol"),
                "hours_to_empty_diesel": live.get("hours_to_empty_diesel"),
                "panic_multiplier": live.get("panic_multiplier", 1.0),
                "updated_at": live.get("updated_at"),
            },
        })

    return {
        "type": "FeatureCollection",
        "features": features,
        "meta": {
            "total": len(features),
            "radius_m": radius,
            "center": {"lat": lat, "lon": lon},
        },
    }


@router.get("/{pump_id}")
async def get_pump(
    pump_id: str,
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
):
    """Return pump detail including 24-hour inventory history."""
    redis_data = await redis.get(f"pump:{pump_id}")
    live = json.loads(redis_data) if redis_data else {}

    result = await db.execute(
        text("""
            SELECT timestamp, petrol_stock_l, diesel_stock_l,
                   petrol_pct, diesel_pct, status, panic_multiplier,
                   hours_to_empty_petrol, hours_to_empty_diesel
            FROM pump_inventory
            WHERE pump_id = :pump_id
            ORDER BY timestamp DESC
            LIMIT 48
        """),
        {"pump_id": pump_id},
    )
    history = [dict(row._mapping) for row in result]

    return {
        "pump_id": pump_id,
        "current": live,
        "history": history,
    }


@router.get("")
async def list_pumps_summary(
    city: Optional[str] = None,
    status: Optional[str] = None,
    redis: aioredis.Redis = Depends(get_redis),
):
    """Return summary of all pumps from Redis."""
    pumps = []
    async for key in redis.scan_iter("pump:*"):
        data = await redis.get(key)
        if data:
            pump = json.loads(data)
            if city and pump.get("city", "").lower() != city.lower():
                continue
            if status and pump.get("status") != status.upper():
                continue
            pumps.append(pump)

    red = sum(1 for p in pumps if p.get("status") == "RED")
    yellow = sum(1 for p in pumps if p.get("status") == "YELLOW")
    green = sum(1 for p in pumps if p.get("status") == "GREEN")

    return {
        "pumps": pumps,
        "total": len(pumps),
        "summary": {"GREEN": green, "YELLOW": yellow, "RED": red},
    }


@router.post("/{pump_id}/queue")
async def report_queue(
    pump_id: str,
    payload: dict,
    redis: aioredis.Redis = Depends(get_redis),
):
    """Consumer-reported queue density for a pump (1=empty .. 4=heavy)."""
    density = payload.get("density", 1)
    if density not in (1, 2, 3, 4):
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="density must be 1-4")

    # Update Redis entry
    data_raw = await redis.get(f"pump:{pump_id}")
    if data_raw:
        pump_data = json.loads(data_raw)
        pump_data["queue_density"] = density
        await redis.setex(f"pump:{pump_id}", 3600, json.dumps(pump_data))

    return {"pump_id": pump_id, "queue_density": density, "status": "recorded"}
