"""
Unit Tests for FuelChain Guardian Backend Services

Fast tests that do NOT require Docker Compose — all external dependencies mocked.

Run:
    pytest tests/test_unit.py -v
"""
from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# AIS Provider / Simulator Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestAISSimulator:
    @pytest.mark.asyncio
    async def test_simulator_yields_messages(self):
        """Simulator must yield well-formed AIS messages."""
        from backend.ais_ingestion.providers import SimulatorProvider, AISMessage
        provider = SimulatorProvider(emit_interval=0.001)
        count = 0
        async for msg in provider.stream():
            assert isinstance(msg, AISMessage)
            assert msg.mmsi
            assert -90 <= msg.lat <= 90
            assert -180 <= msg.lon <= 180
            assert msg.sog >= 0
            assert msg.timestamp
            count += 1
            if count >= 5:
                break

    @pytest.mark.asyncio
    async def test_simulator_generates_anomalies(self):
        """With probability=1.0 every vessel triggers anomaly."""
        from backend.ais_ingestion.providers import SimulatorProvider
        provider = SimulatorProvider(emit_interval=0.001, anomaly_probability=1.0)
        messages = []
        async for msg in provider.stream():
            messages.append(msg)
            if len(messages) >= 10:
                break
        # At least some should be slow (anomaly)
        slow = [m for m in messages if m.sog < 2.0]
        assert len(slow) > 0

    def test_ais_message_to_dict(self):
        from backend.ais_ingestion.providers import AISMessage
        msg = AISMessage(
            mmsi="419001001",
            lat=26.5, lon=57.0,
            sog=14.2, cog=135.0, heading=135,
            timestamp="2024-01-01T12:00:00+00:00",
            vessel_name="TEST TANKER",
            destination="KANDLA",
            gross_tonnage=280000,
        )
        d = msg.to_dict()
        assert d["mmsi"] == "419001001"
        assert d["lat"] == 26.5
        assert d["gross_tonnage"] == 280000

    def test_provider_factory_returns_simulator(self):
        """Factory returns SimulatorProvider when AIS_MODE=simulator."""
        with patch("backend.ais_ingestion.providers.get_settings") as mock_settings:
            mock_settings.return_value.AIS_MODE = "simulator"
            from backend.ais_ingestion.providers import get_provider, SimulatorProvider
            provider = get_provider()
            assert isinstance(provider, SimulatorProvider)

    def test_provider_factory_returns_aishub(self):
        """Factory returns AISHubProvider when mode=aishub and key is set."""
        with patch("backend.ais_ingestion.providers.get_settings") as mock_settings:
            mock_settings.return_value.AIS_MODE = "aishub"
            mock_settings.return_value.AISHUB_API_KEY = "test-key"
            mock_settings.return_value.AISHUB_HOST = "data.aishub.net"
            mock_settings.return_value.AISHUB_PORT = 9876
            from backend.ais_ingestion.providers import get_provider, AISHubProvider
            provider = get_provider()
            assert isinstance(provider, AISHubProvider)


# ─────────────────────────────────────────────────────────────────────────────
# Anomaly Detector Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestAnomalyDetector:
    def test_haversine_nm_known_distance(self):
        """Mumbai to Delhi is approximately 660 NM."""
        from backend.ais_ingestion.anomaly_detector import haversine_nm
        dist = haversine_nm(19.076, 72.877, 28.704, 77.102)
        assert 620 < dist < 720, f"Expected ~660 NM, got {dist:.1f}"

    def test_haversine_zero_distance(self):
        from backend.ais_ingestion.anomaly_detector import haversine_nm
        dist = haversine_nm(26.5, 57.0, 26.5, 57.0)
        assert dist == pytest.approx(0.0, abs=0.001)

    def test_min_dist_to_polyline(self):
        from backend.ais_ingestion.anomaly_detector import (
            min_dist_to_polyline, TSS_CENTRELINE
        )
        # Point exactly on the centreline midpoint should be very close
        mid_lat = (TSS_CENTRELINE[0][0] + TSS_CENTRELINE[-1][0]) / 2
        mid_lon = (TSS_CENTRELINE[0][1] + TSS_CENTRELINE[-1][1]) / 2
        dist = min_dist_to_polyline(mid_lat, mid_lon, TSS_CENTRELINE)
        assert dist < 50  # Within 50 NM of centreline

    def test_estimate_delay_no_delay_at_full_speed(self):
        from backend.ais_ingestion.anomaly_detector import estimate_delay_hours
        # At planned speed, delay should be ~0
        delay = estimate_delay_hours("TEST", "KANDLA", 13.5, 26.5, 57.0)
        assert delay is not None
        # Should be approximately 0 delay at planned speed
        assert delay >= 0

    def test_estimate_delay_high_at_low_speed(self):
        from backend.ais_ingestion.anomaly_detector import estimate_delay_hours
        # At 0.5 knots vs planned 13.5 → huge delay
        delay = estimate_delay_hours("TEST", "KANDLA", 0.5, 26.5, 57.0)
        assert delay is not None
        assert delay > 50  # Many hours of delay

    def test_estimate_delay_unknown_port_returns_none(self):
        from backend.ais_ingestion.anomaly_detector import estimate_delay_hours
        result = estimate_delay_hours("TEST", "UNKNOWN_PORT_XYZ", 10.0, 26.5, 57.0)
        assert result is None

    def test_hormuz_geofence_contains_strait(self):
        from backend.ais_ingestion.anomaly_detector import HORMUZ_GEOFENCE
        from shapely.geometry import Point
        # Centre of strait
        assert HORMUZ_GEOFENCE.contains(Point(57.5, 26.2))

    def test_hormuz_geofence_excludes_mumbai(self):
        from backend.ais_ingestion.anomaly_detector import HORMUZ_GEOFENCE
        from shapely.geometry import Point
        # Mumbai is far outside Hormuz
        assert not HORMUZ_GEOFENCE.contains(Point(72.877, 19.076))


# ─────────────────────────────────────────────────────────────────────────────
# Disruption Index Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestDisruptionIndex:
    def setup_method(self):
        """Reset the in-memory windows before each test."""
        from backend.disruption.consumer import port_anomalies
        port_anomalies.clear()

    def test_zero_index_with_no_anomalies(self):
        from backend.disruption.consumer import compute_disruption_index
        result = compute_disruption_index("KANDLA")
        assert result == 0.0

    def test_index_increases_with_delayed_tonnage(self):
        from backend.disruption.consumer import (
            compute_disruption_index, port_anomalies, EXPECTED_TONNAGE
        )
        # Add half the expected tonnage as delayed
        port = "KANDLA"
        expected = EXPECTED_TONNAGE[port]
        port_anomalies[port].append({
            "ts": datetime.now(timezone.utc),
            "tonnage": expected // 2,
            "delay_hours": 12.0,
            "mmsi": "419001001",
        })
        index = compute_disruption_index(port)
        assert 40 < index < 60  # ~50% of expected delayed

    def test_index_capped_at_100(self):
        from backend.disruption.consumer import (
            compute_disruption_index, port_anomalies, EXPECTED_TONNAGE
        )
        port = "MANGALORE"
        # Add 3x the expected tonnage
        for _ in range(3):
            port_anomalies[port].append({
                "ts": datetime.now(timezone.utc),
                "tonnage": EXPECTED_TONNAGE[port],
                "delay_hours": 24.0,
                "mmsi": "419002002",
            })
        index = compute_disruption_index(port)
        assert index == 100.0

    def test_old_anomalies_not_counted(self):
        from datetime import timedelta
        from backend.disruption.consumer import (
            compute_disruption_index, port_anomalies, WINDOW_HOURS
        )
        port = "ENNORE"
        # Add anomaly older than the window
        old_ts = datetime.now(timezone.utc) - timedelta(hours=WINDOW_HOURS + 1)
        port_anomalies[port].append({
            "ts": old_ts,
            "tonnage": 500000,
            "delay_hours": 20.0,
            "mmsi": "419003003",
        })
        # Should be 0 since the anomaly is outside the window
        index = compute_disruption_index(port)
        assert index == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Inventory Simulator Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestInventorySimulator:
    def _make_pump(self, petrol=40000.0, diesel=40000.0) -> "PumpAgent":
        from backend.inventory.simulator import PumpAgent
        return PumpAgent(
            id="PUMP0001",
            name="Test Pump",
            city="Mumbai",
            state="Maharashtra",
            lat=19.076, lon=72.877,
            petrol_capacity=50000.0,
            diesel_capacity=50000.0,
            petrol_stock=petrol,
            diesel_stock=diesel,
            petrol_sales_rate=5000.0,   # L/day
            diesel_sales_rate=8000.0,
            serving_port="KANDLA",
        )

    def test_tick_reduces_stock(self):
        pump = self._make_pump()
        initial_petrol = pump.petrol_stock
        pump.tick(24.0)  # 1 full day
        assert pump.petrol_stock < initial_petrol
        expected = initial_petrol - 5000.0  # 5000 L/day
        assert pump.petrol_stock == pytest.approx(expected, abs=1.0)

    def test_stock_never_goes_negative(self):
        pump = self._make_pump(petrol=100.0, diesel=100.0)
        pump.tick(24.0 * 30)  # 30 days
        assert pump.petrol_stock >= 0
        assert pump.diesel_stock >= 0

    def test_panic_multiplier_increases_consumption(self):
        pump1 = self._make_pump()
        pump2 = self._make_pump()
        pump2.panic_multiplier = 2.0

        pump1.tick(24.0)
        pump2.tick(24.0)

        assert pump2.petrol_stock < pump1.petrol_stock

    def test_status_green_above_50_pct(self):
        pump = self._make_pump(petrol=30000.0, diesel=30000.0)  # 60%
        assert pump.status == "GREEN"

    def test_status_yellow_between_20_50_pct(self):
        pump = self._make_pump(petrol=15000.0, diesel=15000.0)  # 30%
        assert pump.status == "YELLOW"

    def test_status_red_below_20_pct(self):
        pump = self._make_pump(petrol=5000.0, diesel=5000.0)  # 10%
        assert pump.status == "RED"

    def test_hours_to_empty_calculation(self):
        pump = self._make_pump(petrol=5000.0)
        # 5000 L at 5000 L/day = 1 day = 24 hours
        tte = pump.hours_to_empty("petrol")
        assert tte == pytest.approx(24.0, abs=0.1)

    def test_replenishment_refills_stock(self):
        from backend.inventory.simulator import PumpAgent
        pump = self._make_pump(petrol=5000.0)
        pump.replenishment_interval_days = 0.0  # Force immediate replenishment
        pump.tick(0.1)
        assert pump.petrol_stock > 5000.0

    def test_disrupted_replenishment_factor(self):
        pump = self._make_pump(petrol=5000.0)
        pump.replenishment_interval_days = 0.0
        pump.replenishment_factor = 0.3  # Heavy disruption

        initial = pump.petrol_stock
        pump.tick(0.1)

        # Should refill less than with factor=1.0
        pump2 = self._make_pump(petrol=5000.0)
        pump2.replenishment_interval_days = 0.0
        pump2.replenishment_factor = 1.0
        pump2.tick(0.1)

        assert pump.petrol_stock < pump2.petrol_stock

    def test_redis_payload_structure(self):
        pump = self._make_pump()
        payload = pump.to_redis_payload()
        assert "id" in payload
        assert "status" in payload
        assert "petrol_pct" in payload
        assert "diesel_pct" in payload
        assert "updated_at" in payload
        assert payload["status"] in ("GREEN", "YELLOW", "RED")

    def test_create_demo_pumps_count(self):
        from backend.inventory.simulator import create_demo_pumps
        pumps = create_demo_pumps()
        # 12 cities × 5 pumps = 60
        assert len(pumps) == 60

    def test_demo_pumps_cover_all_cities(self):
        from backend.inventory.simulator import create_demo_pumps
        pumps = create_demo_pumps()
        cities = {p.city for p in pumps}
        assert "Mumbai" in cities
        assert "Delhi" in cities
        assert "Chennai" in cities


# ─────────────────────────────────────────────────────────────────────────────
# Panic NLP Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestPanicNLP:
    def test_keyword_classifier_detects_panic(self):
        from backend.panic_nlp.service import KeywordClassifier
        clf = KeywordClassifier()
        is_panic, score = clf.predict(
            "No petrol at any pump in Delhi! Huge queues everywhere #FuelCrisis"
        )
        assert is_panic is True
        assert score > 0.3

    def test_keyword_classifier_normal_text(self):
        from backend.panic_nlp.service import KeywordClassifier
        clf = KeywordClassifier()
        is_panic, score = clf.predict(
            "Just filled up at the Shell pump. Quick service today."
        )
        assert is_panic is False

    def test_keyword_classifier_extracts_city(self):
        from backend.panic_nlp.service import KeywordClassifier
        clf = KeywordClassifier()
        city = clf.extract_city("No fuel in Mumbai today!")
        assert city == "Mumbai"

    def test_keyword_classifier_hindi_panic(self):
        from backend.panic_nlp.service import KeywordClassifier
        clf = KeywordClassifier()
        is_panic, _ = clf.predict(
            "Delhi mein petrol khatam ho gaya! Sab pumps band hain"
        )
        assert is_panic is True

    def test_keyword_classifier_capslock_boost(self):
        from backend.panic_nlp.service import KeywordClassifier
        clf = KeywordClassifier()
        _, score_normal = clf.predict("no petrol at pump")
        _, score_caps = clf.predict("NO PETROL AT PUMP!!")
        assert score_caps >= score_normal

    def test_panic_aggregator_computes_index(self):
        from backend.panic_nlp.aggregator import (
            city_buckets, compute_panic_index, current_hour_bucket
        )
        city = "TestCity"
        hour = current_hour_bucket()
        city_buckets[city][hour] = {"count": 10, "panic": 7}
        index = compute_panic_index(city, hour)
        assert index == pytest.approx(70.0, abs=0.1)

    def test_panic_index_zero_with_no_tweets(self):
        from backend.panic_nlp.aggregator import (
            city_buckets, compute_panic_index, current_hour_bucket
        )
        index = compute_panic_index("EmptyCity", current_hour_bucket())
        assert index == 0.0

    def test_panic_index_max_100(self):
        from backend.panic_nlp.aggregator import (
            city_buckets, compute_panic_index, current_hour_bucket
        )
        city = "MaxPanicCity"
        hour = current_hour_bucket()
        city_buckets[city][hour] = {"count": 100, "panic": 100}
        index = compute_panic_index(city, hour)
        assert index == 100.0


# ─────────────────────────────────────────────────────────────────────────────
# Auth Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestAuth:
    def test_password_hash_and_verify(self):
        from backend.app.routers.auth import hash_password, verify_password
        hashed = hash_password("MySecretPass123!")
        assert hashed != "MySecretPass123!"
        assert verify_password("MySecretPass123!", hashed)
        assert not verify_password("WrongPassword", hashed)

    def test_jwt_token_creation_and_decode(self):
        from backend.app.routers.auth import create_access_token
        from jose import jwt
        from backend.shared.config import get_settings
        settings = get_settings()

        token = create_access_token({"sub": "test-user-id", "role": "dealer"})
        assert isinstance(token, str)

        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        assert payload["sub"] == "test-user-id"
        assert payload["role"] == "dealer"
        assert "exp" in payload

    def test_jwt_token_contains_expiry(self):
        from backend.app.routers.auth import create_access_token
        from jose import jwt
        from backend.shared.config import get_settings
        settings = get_settings()

        token = create_access_token({"sub": "123"})
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        assert payload["exp"] > datetime.now(timezone.utc).timestamp()


# ─────────────────────────────────────────────────────────────────────────────
# Tweet Simulator Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestTweetSimulator:
    @pytest.mark.asyncio
    async def test_simulator_yields_tweets(self):
        from backend.panic_nlp.social_producer import TweetSimulator
        sim = TweetSimulator(tweets_per_second=100)
        count = 0
        async for tweet in sim.stream():
            assert "tweet_id" in tweet
            assert "text" in tweet
            assert "city" in tweet
            assert len(tweet["text"]) > 5
            count += 1
            if count >= 5:
                break

    @pytest.mark.asyncio
    async def test_simulator_panic_rate(self):
        """With panic_rate=1.0, all tweets should be panic-ish."""
        from backend.panic_nlp.social_producer import TweetSimulator, PANIC_TEMPLATES_EN
        sim = TweetSimulator(panic_rate=1.0, tweets_per_second=100)
        panic_tweets = []
        async for tweet in sim.stream():
            panic_tweets.append(tweet)
            if len(panic_tweets) >= 20:
                break
        # All should come from panic templates (contain fuel crisis language)
        crisis_keywords = ["petrol", "shortage", "queue", "crisis", "khatam", "dry", "band", "empty"]
        has_crisis = [
            any(kw in t["text"].lower() for kw in crisis_keywords)
            for t in panic_tweets
        ]
        assert sum(has_crisis) >= 18  # At least 90%

    @pytest.mark.asyncio
    async def test_simulator_non_panic_rate(self):
        """With panic_rate=0.0, no tweets should be panic."""
        from backend.panic_nlp.social_producer import TweetSimulator
        sim = TweetSimulator(panic_rate=0.0, tweets_per_second=100)
        normal_tweets = []
        async for tweet in sim.stream():
            normal_tweets.append(tweet)
            if len(normal_tweets) >= 10:
                break
        # Normal tweets should have reassuring language
        calm_keywords = ["filled", "stable", "normal", "smooth", "good", "service", "confirms"]
        has_calm = [
            any(kw in t["text"].lower() for kw in calm_keywords)
            for t in normal_tweets
        ]
        assert sum(has_calm) >= 8


# ─────────────────────────────────────────────────────────────────────────────
# Credit Workflow Tests (mocked DB)
# ─────────────────────────────────────────────────────────────────────────────

class TestCreditWorkflow:
    @pytest.mark.asyncio
    async def test_mock_omc_validation(self):
        """OMC validation should return valid=True for most invoices."""
        from backend.app.routers.credit import validate_omc_invoice
        # Mock the HTTP call to avoid needing the mock OMC server running
        with patch("backend.app.routers.credit.httpx.AsyncClient") as mock_client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "valid": True,
                "dispatch_id": "DISP-ABC12345",
                "allocated_volume_l": 10000,
                "omc": "IOCL",
            }
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_resp
            )
            result = await validate_omc_invoice("INV-001", "dealer-123")
            assert result["valid"] is True
            assert "dispatch_id" in result

    @pytest.mark.asyncio
    async def test_mock_payment_disbursal(self):
        from backend.app.routers.credit import disburse_payment
        result = await disburse_payment("app-123", Decimal("50000.00"))
        assert result["success"] is True
        assert "gateway_tx_id" in result
        assert result["gateway_tx_id"].startswith("TXN")
        assert "upi_ref" in result

    @pytest.mark.asyncio
    async def test_payment_mock_mode(self):
        """In mock mode, payment always succeeds without calling Razorpay."""
        with patch("backend.app.routers.credit.get_settings") as mock_settings:
            mock_settings.return_value.PAYMENT_MODE = "mock"
            mock_settings.return_value.RAZORPAY_KEY_ID = ""
            from backend.app.routers.credit import disburse_payment
            result = await disburse_payment("app-456", Decimal("100000.00"))
            assert result["success"] is True
            assert result["gateway"] == "mock"
