"""
conftest.py — shared pytest fixtures and setup.

Sets sys.path so backend modules are importable from tests/.
Provides async event loop, mock settings, and mock Redis/Kafka fixtures.
"""
from __future__ import annotations

import asyncio
import sys
import os
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# ── Path setup ────────────────────────────────────────────────────────────
# Allow `from backend.xxx import yyy` in test files
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(ROOT, "backend")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

# ── Event loop ────────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()


# ── Mock settings that don't need real services ──────────────────────────
@pytest.fixture(autouse=True)
def mock_settings(monkeypatch):
    """Override settings so tests never need real DB/Kafka/Redis."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret-32-chars-minimum!!")
    monkeypatch.setenv("AIS_MODE", "simulator")
    monkeypatch.setenv("SOCIAL_MODE", "simulator")
    monkeypatch.setenv("PAYMENT_MODE", "mock")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")


# ── Mock Redis client ─────────────────────────────────────────────────────
@pytest.fixture
def mock_redis():
    """In-memory mock Redis client for unit tests."""
    store: dict[str, str] = {}

    redis = MagicMock()
    redis.get = AsyncMock(side_effect=lambda key: store.get(key))
    redis.set = AsyncMock(side_effect=lambda key, val, **kw: store.update({key: val}))
    redis.setex = AsyncMock(side_effect=lambda key, ttl, val: store.update({key: val}))
    redis.exists = AsyncMock(side_effect=lambda key: int(key in store))
    redis.delete = AsyncMock(side_effect=lambda key: store.pop(key, None))
    redis.close = AsyncMock()

    async def scan_iter(pattern="*"):
        import fnmatch
        for k in list(store.keys()):
            if fnmatch.fnmatch(k, pattern):
                yield k

    redis.scan_iter = scan_iter
    return redis


# ── Mock Kafka producer ───────────────────────────────────────────────────
@pytest.fixture
def mock_kafka_producer():
    """Mock Kafka producer that captures published messages."""
    published: list[dict] = []

    producer = MagicMock()
    producer.start = AsyncMock()
    producer.stop = AsyncMock()

    async def send_and_wait(topic, key=None, value=None):
        published.append({"topic": topic, "key": key, "value": value})

    async def send(topic, key=None, value=None):
        published.append({"topic": topic, "key": key, "value": value})

    producer.send_and_wait = send_and_wait
    producer.send = send
    producer.published = published
    return producer


# ── Mock DB session ───────────────────────────────────────────────────────
@pytest.fixture
def mock_db_session():
    """Mock async DB session."""
    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(
        fetchone=MagicMock(return_value=None),
        fetchall=MagicMock(return_value=[]),
        scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
        scalar_one_or_none=MagicMock(return_value=None),
    ))
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    session.add = MagicMock()
    session.refresh = AsyncMock()
    return session


# ── Sample data fixtures ──────────────────────────────────────────────────
@pytest.fixture
def sample_ais_message():
    return {
        "mmsi": "419001001",
        "lat": 26.5,
        "lon": 57.0,
        "sog": 14.2,
        "cog": 135.0,
        "heading": 135,
        "timestamp": "2024-01-01T12:00:00+00:00",
        "vessel_name": "MUMBAI SPIRIT",
        "vessel_type": "tanker",
        "destination": "KANDLA",
        "gross_tonnage": 280000,
    }


@pytest.fixture
def sample_anomaly_event():
    import uuid
    return {
        "event_id": str(uuid.uuid4()),
        "mmsi": "419001001",
        "event_type": "slow_speed",
        "detected_at": "2024-01-01T12:00:00+00:00",
        "lat": 26.2,
        "lon": 57.5,
        "sog": 0.8,
        "avg_sog": 1.1,
        "deviation_nm": 0.5,
        "estimated_delay_hours": 12.0,
        "destination_port": "KANDLA",
        "vessel_name": "MUMBAI SPIRIT",
        "gross_tonnage": 280000,
    }


@pytest.fixture
def sample_pump_payload():
    return {
        "id": "PUMP0001",
        "name": "Mumbai Pump 1",
        "city": "Mumbai",
        "state": "Maharashtra",
        "lat": 19.082,
        "lon": 72.891,
        "petrol_pct": 42.5,
        "diesel_pct": 67.2,
        "status": "YELLOW",
        "panic_multiplier": 1.3,
        "hours_to_empty_petrol": 18.5,
        "hours_to_empty_diesel": None,
        "updated_at": "2024-01-01T12:30:00+00:00",
    }


@pytest.fixture
def sample_tweet():
    import uuid
    return {
        "tweet_id": str(uuid.uuid4().int)[:18],
        "text": "No petrol at any pump in Mumbai! Huge queues everywhere #FuelCrisis",
        "city": "Mumbai",
        "lang": "en",
        "created_at": "2024-01-01T12:00:00+00:00",
        "author_id": "987654321",
        "simulated": True,
    }
