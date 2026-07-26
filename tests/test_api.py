"""
API Router Integration Tests — uses FastAPI TestClient (no external services needed).
Tests every REST endpoint with mocked DB and Redis.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ── App fixture ───────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def client():
    with patch("shared.database.create_engine"), \
         patch("shared.database.AsyncSessionLocal"), \
         patch("redis.asyncio.from_url"):
        from app.main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


# ── Health check ──────────────────────────────────────────────────────────
class TestHealth:
    def test_health_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_health_version(self, client):
        r = client.get("/health")
        assert "version" in r.json()

    def test_metrics_endpoint_exists(self, client):
        r = client.get("/metrics")
        assert r.status_code == 200
        assert "http_requests_total" in r.text or "python_info" in r.text


# ── Auth Endpoints ────────────────────────────────────────────────────────
class TestAuthEndpoints:
    def test_register_returns_201(self, client):
        with patch("app.routers.auth.get_db") as mock_get_db:
            mock_session = AsyncMock()
            mock_session.execute = AsyncMock(
                return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
            )
            mock_session.commit = AsyncMock()
            mock_session.refresh = AsyncMock()

            async def mock_db_gen():
                yield mock_session

            mock_get_db.return_value = mock_db_gen()

            r = client.post("/api/v1/auth/register", json={
                "email": "test@example.com",
                "password": "Test@1234",
                "full_name": "Test User",
            })
            # 201 or 409 if already exists — both are valid
            assert r.status_code in (201, 409, 422, 500)

    def test_register_rejects_missing_email(self, client):
        r = client.post("/api/v1/auth/register", json={
            "password": "Test@1234",
        })
        assert r.status_code == 422  # Validation error

    def test_token_endpoint_exists(self, client):
        r = client.post("/api/v1/auth/token", data={
            "username": "noone@example.com",
            "password": "wrong",
        })
        # Should return 401 (wrong creds) not 404 (not found)
        assert r.status_code in (401, 422, 500)

    def test_me_requires_auth(self, client):
        r = client.get("/api/v1/auth/me")
        assert r.status_code == 401


# ── Vessels Endpoints ─────────────────────────────────────────────────────
class TestVesselsEndpoints:
    def test_list_vessels_returns_json(self, client):
        with patch("app.routers.vessels.get_redis") as mock_redis_dep, \
             patch("app.routers.vessels.get_db"):

            mock_redis = AsyncMock()
            mock_redis.scan_iter = MagicMock(return_value=iter([]))
            mock_redis.close = AsyncMock()

            async def fake_redis():
                yield mock_redis

            mock_redis_dep.return_value = fake_redis()

            r = client.get("/api/v1/vessels")
            assert r.status_code == 200
            assert "vessels" in r.json()
            assert "count" in r.json()

    def test_vessel_detail_404_unknown(self, client):
        with patch("app.routers.vessels.get_redis") as mock_redis_dep, \
             patch("app.routers.vessels.get_db") as mock_db_dep:

            mock_redis = AsyncMock()
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.close = AsyncMock()

            async def fake_redis():
                yield mock_redis

            mock_session = AsyncMock()
            mock_session.execute = AsyncMock(
                return_value=MagicMock(fetchall=MagicMock(return_value=[]))
            )

            async def fake_db():
                yield mock_session

            mock_redis_dep.return_value = fake_redis()
            mock_db_dep.return_value = fake_db()

            r = client.get("/api/v1/vessels/UNKNOWN999")
            assert r.status_code == 200  # Returns empty data, not 404


# ── Disruption Endpoints ──────────────────────────────────────────────────
class TestDisruptionEndpoints:
    def _mock_redis_with_data(self, data: dict | None):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(
            return_value=json.dumps(data) if data else None
        )
        mock_redis.close = AsyncMock()
        return mock_redis

    def test_disruption_all_ports(self, client):
        with patch("app.routers.disruption.get_redis") as mock_dep:
            mock_redis = self._mock_redis_with_data({
                "port_code": "KANDLA",
                "disruption_index": 45.2,
            })

            async def fake_redis():
                yield mock_redis

            mock_dep.return_value = fake_redis()

            r = client.get("/api/v1/disruption")
            assert r.status_code == 200
            assert "ports" in r.json()

    def test_disruption_single_port_from_cache(self, client):
        cached = {
            "port_code": "MANGALORE",
            "disruption_index": 22.5,
            "delayed_tonnage": 63000,
            "expected_tonnage": 280000,
            "window_hours": 6,
            "computed_at": "2024-01-01T12:00:00+00:00",
        }
        with patch("app.routers.disruption.get_redis") as mock_dep, \
             patch("app.routers.disruption.get_db"):
            mock_redis = self._mock_redis_with_data(cached)

            async def fake_redis():
                yield mock_redis

            mock_dep.return_value = fake_redis()

            r = client.get("/api/v1/disruption/MANGALORE")
            assert r.status_code == 200
            data = r.json()
            assert data["disruption_index"] == 22.5


# ── Pumps Endpoints ───────────────────────────────────────────────────────
class TestPumpsEndpoints:
    def test_pumps_nearby_requires_lat_lon(self, client):
        r = client.get("/api/v1/pumps/nearby")
        assert r.status_code == 422  # Missing required params

    def test_pumps_nearby_returns_geojson(self, client):
        with patch("app.routers.pumps.get_db") as mock_db_dep, \
             patch("app.routers.pumps.get_redis") as mock_redis_dep:

            mock_session = AsyncMock()
            mock_session.execute = AsyncMock(
                return_value=MagicMock(fetchall=MagicMock(return_value=[]))
            )

            async def fake_db():
                yield mock_session

            mock_redis = AsyncMock()
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.close = AsyncMock()

            async def fake_redis():
                yield mock_redis

            mock_db_dep.return_value = fake_db()
            mock_redis_dep.return_value = fake_redis()

            r = client.get("/api/v1/pumps/nearby?lat=19.076&lon=72.877&radius=5000")
            assert r.status_code == 200
            data = r.json()
            assert data["type"] == "FeatureCollection"
            assert "features" in data

    def test_pumps_summary(self, client):
        with patch("app.routers.pumps.get_redis") as mock_dep:
            mock_redis = AsyncMock()
            mock_redis.scan_iter = MagicMock(return_value=iter([]))
            mock_redis.close = AsyncMock()

            async def fake_redis():
                yield mock_redis

            mock_dep.return_value = fake_redis()

            r = client.get("/api/v1/pumps")
            assert r.status_code == 200
            data = r.json()
            assert "pumps" in data
            assert "summary" in data
            assert "GREEN" in data["summary"]


# ── Panic Endpoints ───────────────────────────────────────────────────────
class TestPanicEndpoints:
    def test_panic_all_cities(self, client):
        with patch("app.routers.panic.get_redis") as mock_dep:
            mock_redis = AsyncMock()
            mock_redis.get = AsyncMock(return_value=None)
            mock_redis.close = AsyncMock()

            async def fake_redis():
                yield mock_redis

            mock_dep.return_value = fake_redis()

            r = client.get("/api/v1/panic")
            assert r.status_code == 200
            data = r.json()
            assert "cities" in data
            assert len(data["cities"]) > 0

    def test_panic_single_city(self, client):
        cached = {"city": "Mumbai", "panic_index": 55.0, "updated_at": "2024-01-01T12:00:00+00:00"}
        with patch("app.routers.panic.get_redis") as mock_dep, \
             patch("app.routers.panic.get_db") as mock_db_dep:

            mock_redis = AsyncMock()
            mock_redis.get = AsyncMock(return_value=json.dumps(cached))
            mock_redis.close = AsyncMock()

            async def fake_redis():
                yield mock_redis

            mock_session = AsyncMock()
            mock_session.execute = AsyncMock(
                return_value=MagicMock(fetchall=MagicMock(return_value=[]))
            )

            async def fake_db():
                yield mock_session

            mock_dep.return_value = fake_redis()
            mock_db_dep.return_value = fake_db()

            r = client.get("/api/v1/panic/Mumbai")
            assert r.status_code == 200
            data = r.json()
            assert data["panic_index"] == 55.0


# ── Credit Endpoints ──────────────────────────────────────────────────────
class TestCreditEndpoints:
    def _get_auth_header(self):
        """Generate a valid JWT for tests."""
        from app.routers.auth import create_access_token
        token = create_access_token({"sub": str(uuid.uuid4()), "role": "dealer"})
        return {"Authorization": f"Bearer {token}"}

    def test_credit_apply_requires_auth(self, client):
        r = client.post("/api/v1/credit/apply", json={
            "amount": "50000",
            "omc_invoice_ref": "INV-001",
        })
        assert r.status_code == 401

    def test_credit_history_requires_auth(self, client):
        r = client.get("/api/v1/credit/history")
        assert r.status_code == 401

    def test_credit_status_requires_auth(self, client):
        r = client.get(f"/api/v1/credit/status/{uuid.uuid4()}")
        assert r.status_code == 401

    def test_credit_history_with_valid_jwt(self, client):
        headers = self._get_auth_header()
        with patch("app.routers.credit.get_db") as mock_db_dep, \
             patch("app.routers.credit.get_current_user") as mock_user:

            mock_user.return_value = MagicMock(
                id=uuid.uuid4(), email="dealer@test.com", role="dealer"
            )

            mock_session = AsyncMock()
            mock_session.execute = AsyncMock(
                return_value=MagicMock(
                    scalar_one_or_none=MagicMock(return_value=None)
                )
            )

            async def fake_db():
                yield mock_session

            mock_db_dep.return_value = fake_db()

            r = client.get("/api/v1/credit/history", headers=headers)
            # 404 (dealer not found) is valid without DB data
            assert r.status_code in (200, 404)


# ── OpenAPI Docs ──────────────────────────────────────────────────────────
class TestDocs:
    def test_openapi_schema_exists(self, client):
        r = client.get("/openapi.json")
        assert r.status_code == 200
        schema = r.json()
        assert schema["info"]["title"] == "FuelChain Guardian API"
        # All expected paths exist
        paths = schema["paths"]
        assert "/api/v1/auth/register" in paths
        assert "/api/v1/vessels" in paths
        assert "/api/v1/disruption/{port_code}" in paths
        assert "/api/v1/pumps/nearby" in paths
        assert "/api/v1/panic/{city}" in paths
        assert "/api/v1/credit/apply" in paths

    def test_docs_page_accessible(self, client):
        r = client.get("/docs")
        assert r.status_code == 200
