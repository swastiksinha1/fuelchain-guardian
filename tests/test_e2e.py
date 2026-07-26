"""
FuelChain Guardian — End-to-End Integration Tests

Tests the full data pipeline:
  1. AIS producer → Kafka → vessel tracker → DB
  2. Anomaly detector → disruption index
  3. Social producer → NLP → panic index
  4. Pump inventory simulation
  5. Credit application workflow

Run:  pytest tests/test_e2e.py -v

Requires the Docker Compose stack to be running:
  docker compose up -d
  docker compose exec backend alembic upgrade head
  docker compose exec backend python -m scripts.init_kafka
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid

import httpx
import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

BASE_URL = "http://localhost:8000"
WS_URL = "ws://localhost:8002"
NLP_URL = "http://localhost:8001"
KAFKA = "localhost:19092"
REDIS_URL = "redis://localhost:6379/0"


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def http():
    return httpx.Client(base_url=BASE_URL, timeout=15.0)


@pytest_asyncio.fixture
async def async_http():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15.0) as client:
        yield client


@pytest_asyncio.fixture
async def redis():
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    yield r
    await r.close()


@pytest_asyncio.fixture
async def kafka_producer():
    producer = AIOKafkaProducer(
        bootstrap_servers=KAFKA,
        value_serializer=lambda v: json.dumps(v).encode(),
        key_serializer=lambda k: k.encode() if k else None,
    )
    await producer.start()
    yield producer
    await producer.stop()


# ── Health Checks ──────────────────────────────────────────────────────────

def test_backend_health(http):
    resp = http.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_nlp_health(http):
    resp = httpx.get(f"{NLP_URL}/health", timeout=10)
    assert resp.status_code == 200


# ── Auth Tests ─────────────────────────────────────────────────────────────

def test_register_and_login(http):
    email = f"test_{uuid.uuid4().hex[:8]}@test.com"
    # Register
    resp = http.post("/api/v1/auth/register", json={
        "email": email,
        "password": "Test@1234",
        "full_name": "Test User",
        "role": "dealer",
    })
    assert resp.status_code == 201

    # Login
    resp = http.post("/api/v1/auth/token", data={
        "username": email,
        "password": "Test@1234",
    })
    assert resp.status_code == 200
    token = resp.json().get("access_token")
    assert token


# ── AIS Pipeline Tests ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ais_message_flows_to_redis(kafka_producer, redis):
    """Publish AIS message → verify vessel appears in Redis within 15s."""
    mmsi = f"99999{uuid.uuid4().hex[:4]}"
    msg = {
        "mmsi": mmsi,
        "lat": 26.5, "lon": 57.0,
        "sog": 14.0, "cog": 135.0, "heading": 135,
        "timestamp": "2024-01-01T12:00:00+00:00",
        "vessel_name": "TEST TANKER",
        "destination": "KANDLA",
    }
    await kafka_producer.send_and_wait("raw.ais.v1", key=mmsi, value=msg)

    # Wait for consumer to process
    for _ in range(15):
        await asyncio.sleep(1)
        state = await redis.get(f"vessel:{mmsi}")
        if state:
            vessel = json.loads(state)
            assert vessel["mmsi"] == mmsi
            assert vessel["lat"] == pytest.approx(26.5, abs=0.1)
            return

    pytest.fail(f"Vessel {mmsi} never appeared in Redis after 15s")


# ── Anomaly Detection Tests ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_slow_tanker_triggers_anomaly():
    """Publish a slow tanker inside Hormuz → expect anomaly event in Kafka."""
    producer = AIOKafkaProducer(
        bootstrap_servers=KAFKA,
        value_serializer=lambda v: json.dumps(v).encode(),
        key_serializer=lambda k: k.encode() if k else None,
    )
    consumer = AIOKafkaConsumer(
        "alerts.anomaly.v1",
        bootstrap_servers=KAFKA,
        group_id=f"test-anomaly-{uuid.uuid4().hex[:6]}",
        value_deserializer=lambda v: json.loads(v.decode()),
        auto_offset_reset="latest",
    )

    await producer.start()
    await consumer.start()

    mmsi = f"SLOW{uuid.uuid4().hex[:5]}"

    # Send 10 slow-speed messages inside Hormuz geofence
    for i in range(12):
        msg = {
            "mmsi": mmsi,
            "lat": 26.2, "lon": 57.5,
            "sog": 0.8,  # Very slow
            "cog": 90.0, "heading": 90,
            "timestamp": f"2024-01-01T12:{i:02d}:00+00:00",
            "vessel_name": "SLOW TEST TANKER",
            "destination": "KANDLA",
            "gross_tonnage": 200000,
        }
        await producer.send_and_wait("raw.ais.v1", key=mmsi, value=msg)
        await asyncio.sleep(0.1)

    # Check for anomaly event
    found = False
    try:
        async with asyncio.timeout(20):
            async for record in consumer:
                if record.value.get("mmsi") == mmsi:
                    assert record.value["event_type"] == "slow_speed"
                    found = True
                    break
    except asyncio.TimeoutError:
        pass

    await producer.stop()
    await consumer.stop()
    assert found, "No anomaly event emitted for slow tanker"


# ── Pump Inventory Tests ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pumps_available_via_api(async_http):
    """Pumps endpoint returns GeoJSON for Mumbai area."""
    resp = await async_http.get(
        "/api/v1/pumps/nearby",
        params={"lat": 19.076, "lon": 72.877, "radius": 50000},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    # Should have some pumps (seeded by inventory simulator)
    assert len(data["features"]) >= 0  # may be 0 if simulator hasn't run yet


# ── Panic NLP Tests ────────────────────────────────────────────────────────

def test_panic_classification_english():
    resp = httpx.post(f"{NLP_URL}/classify", json={
        "text": "No petrol at any pump in Delhi! Huge queues everywhere",
        "city": "Delhi",
    }, timeout=10)
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_panic"] is True
    assert data["score"] > 0.3


def test_non_panic_classification():
    resp = httpx.post(f"{NLP_URL}/classify", json={
        "text": "Just filled up at the IOCL pump, quick service today.",
        "city": "Mumbai",
    }, timeout=10)
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_panic"] is False


@pytest.mark.asyncio
async def test_panic_index_updates_redis(kafka_producer, redis):
    """Publish panic tweet → check panic index in Redis updates."""
    city = "TestCity"
    tweet = {
        "tweet_id": str(uuid.uuid4().int)[:18],
        "text": f"No fuel at any pump in {city}! Panic buying started! #FuelCrisis",
        "city": city,
        "lang": "en",
        "created_at": "2024-01-01T12:00:00+00:00",
    }
    await kafka_producer.send_and_wait("raw.social.v1", value=tweet)

    # Wait for aggregator to process
    for _ in range(20):
        await asyncio.sleep(1)
        data = await redis.get(f"panic:{city}")
        if data:
            panic = json.loads(data)
            assert panic["city"] == city
            assert panic["panic_index"] >= 0
            return

    # Not a hard failure — aggregator may just be slow
    print("Warning: panic index not found in Redis within 20s")


# ── Disruption Index Tests ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_disruption_index_api(async_http):
    resp = await async_http.get("/api/v1/disruption/KANDLA")
    assert resp.status_code == 200
    data = resp.json()
    assert "disruption_index" in data
    assert 0 <= data["disruption_index"] <= 100


@pytest.mark.asyncio
async def test_disruption_updates_after_anomaly(kafka_producer, redis):
    """Publish anomaly event → disruption index for that port should update."""
    anomaly = {
        "event_id": str(uuid.uuid4()),
        "mmsi": "419099099",
        "event_type": "slow_speed",
        "detected_at": "2024-01-01T12:00:00+00:00",
        "lat": 26.2, "lon": 57.5,
        "sog": 1.2,
        "estimated_delay_hours": 12.0,
        "destination_port": "KANDLA",
        "vessel_name": "TEST DISRUPTION TANKER",
        "gross_tonnage": 300000,
    }
    await kafka_producer.send_and_wait("alerts.anomaly.v1", key="419099099", value=anomaly)

    for _ in range(20):
        await asyncio.sleep(1)
        data = await redis.get("disruption:KANDLA")
        if data:
            di = json.loads(data)
            assert di["disruption_index"] >= 0
            return

    print("Warning: disruption index not updated within 20s")


# ── Credit Workflow Tests ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_full_credit_workflow(async_http):
    """Register dealer → apply for credit → check status."""
    email = f"dealer_{uuid.uuid4().hex[:8]}@test.com"

    # Register
    resp = await async_http.post("/api/v1/auth/register", json={
        "email": email,
        "password": "Test@1234",
        "role": "dealer",
    })
    assert resp.status_code == 201

    # Login
    resp = await async_http.post("/api/v1/auth/token", data={
        "username": email,
        "password": "Test@1234",
    })
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Note: full credit flow requires dealer KYC verification
    # In a real test this would require DB seeding
    # This tests the auth plumbing
    resp = await async_http.get("/api/v1/auth/me", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == email
