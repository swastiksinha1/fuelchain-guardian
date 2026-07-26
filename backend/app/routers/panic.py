"""Panic Index router."""
from __future__ import annotations

import json

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends
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


@router.get("/{city}")
async def get_panic_index(
    city: str,
    redis: aioredis.Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
):
    """Return current Panic Index and alert for a city."""
    city_titled = city.title()
    cached = await redis.get(f"panic:{city_titled}")
    alert = await redis.get(f"panic_alert:{city_titled}")

    panic_data = json.loads(cached) if cached else {"city": city_titled, "panic_index": 0.0}
    alert_data = json.loads(alert) if alert else None

    # Last 24h trend from DB
    result = await db.execute(
        text("""
            SELECT hour_bucket, panic_index, tweet_count, panic_count
            FROM panic_index
            WHERE city = :city
            ORDER BY hour_bucket DESC
            LIMIT 24
        """),
        {"city": city_titled},
    )
    history = [dict(row._mapping) for row in result]

    return {
        **panic_data,
        "alert": alert_data,
        "trend": history,
    }


@router.get("")
async def list_panic_indices(redis: aioredis.Redis = Depends(get_redis)):
    """Return panic index for all cities."""
    cities = [
        "Mumbai", "Delhi", "Bangalore", "Chennai", "Kolkata",
        "Hyderabad", "Pune", "Ahmedabad", "Jaipur", "Lucknow",
    ]
    result = []
    for city in cities:
        cached = await redis.get(f"panic:{city}")
        if cached:
            result.append(json.loads(cached))
        else:
            result.append({"city": city, "panic_index": 0.0})
    return {"cities": result}
