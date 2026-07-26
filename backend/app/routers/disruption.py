"""Disruption Index router."""
from __future__ import annotations

import json
from typing import Optional

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends, HTTPException
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


@router.get("/{port_code}")
async def get_disruption_index(
    port_code: str,
    redis: aioredis.Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
):
    """Return latest Disruption Index for a port."""
    port_code = port_code.upper()
    cached = await redis.get(f"disruption:{port_code}")

    if cached:
        return json.loads(cached)

    # Fallback: compute from DB
    result = await db.execute(
        text("""
            SELECT COUNT(*) as anomaly_count,
                   SUM(COALESCE((details->>'gross_tonnage')::float, 100000)) as delayed_tonnage
            FROM anomaly_events
            WHERE destination_port = :port
              AND detected_at > now() - interval '6 hours'
              AND resolved = false
        """),
        {"port": port_code},
    )
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Port {port_code} not found")

    delayed = float(row.delayed_tonnage or 0)
    expected = {
        "MANGALORE": 280000, "KANDLA": 640000, "ENNORE": 250000,
        "PARADIP": 300000, "HALDIA": 360000,
    }.get(port_code, 300000)

    index = min(100.0, (delayed / expected) * 100)

    return {
        "port_code": port_code,
        "disruption_index": round(index, 2),
        "delayed_tonnage": delayed,
        "expected_tonnage": expected,
        "source": "db_fallback",
    }


@router.get("")
async def list_disruption_indices(
    redis: aioredis.Redis = Depends(get_redis),
):
    """Return disruption indices for all ports."""
    ports = ["MANGALORE", "KANDLA", "ENNORE", "PARADIP", "HALDIA"]
    result = []
    for port in ports:
        cached = await redis.get(f"disruption:{port}")
        if cached:
            result.append(json.loads(cached))
        else:
            result.append({"port_code": port, "disruption_index": 0.0})
    return {"ports": result}
