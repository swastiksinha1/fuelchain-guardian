"""
Depot-to-Pump Inventory Simulator

Agent-based model:
  - Each pump agent tracks petrol/diesel stock, sales rate, replenishment schedule
  - Every tick (configurable, default 30 min), stocks decrease by sales_rate * dt * panic_multiplier
  - Disruption events reduce replenishment rate from serving port
  - Panic multiplier from Redis panic index per city

Publishes state changes to state.pumps Kafka topic.
Writes snapshots to pump_inventory table (TimescaleDB).
Updates Redis for fast reads.

Run:  python -m inventory.simulator
"""
from __future__ import annotations

import asyncio
import json
import math
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import redis.asyncio as aioredis
import structlog
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from prometheus_client import Counter, Gauge, start_http_server
from sqlalchemy import text

from shared.config import configure_logging, get_settings
from shared.database import AsyncSessionLocal

logger = structlog.get_logger(__name__)

ticks_processed = Counter("inventory_ticks_total", "Simulator ticks executed")
pumps_red = Gauge("inventory_pumps_red_count", "Pumps in RED status")
pumps_yellow = Gauge("inventory_pumps_yellow_count", "Pumps in YELLOW status")


@dataclass
class PumpAgent:
    id: str
    name: str
    city: str
    state: str
    lat: float
    lon: float
    petrol_capacity: float = 50000.0
    diesel_capacity: float = 50000.0
    petrol_stock: float = 40000.0
    diesel_stock: float = 40000.0
    petrol_sales_rate: float = 5000.0   # L/day
    diesel_sales_rate: float = 8000.0
    serving_port: str = "KANDLA"
    replenishment_interval_days: float = 3.0
    last_replenishment: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    # Modified by external events
    replenishment_factor: float = 1.0   # < 1 means disrupted supply
    panic_multiplier: float = 1.0

    def tick(self, dt_hours: float) -> None:
        """Advance simulation by dt_hours."""
        dt_days = dt_hours / 24.0

        # Consume stock
        petrol_consumed = self.petrol_sales_rate * dt_days * self.panic_multiplier
        diesel_consumed = self.diesel_sales_rate * dt_days * self.panic_multiplier

        self.petrol_stock = max(0, self.petrol_stock - petrol_consumed)
        self.diesel_stock = max(0, self.diesel_stock - diesel_consumed)

        # Check replenishment
        now = datetime.now(timezone.utc)
        days_since = (now - self.last_replenishment).total_seconds() / 86400
        effective_interval = self.replenishment_interval_days / self.replenishment_factor

        if days_since >= effective_interval:
            # Refill proportional to replenishment_factor
            fill_pct = 0.9 * self.replenishment_factor
            self.petrol_stock = min(
                self.petrol_capacity, self.petrol_stock + self.petrol_capacity * fill_pct
            )
            self.diesel_stock = min(
                self.diesel_capacity, self.diesel_stock + self.diesel_capacity * fill_pct
            )
            self.last_replenishment = now
            logger.debug("Pump replenished", pump_id=self.id, factor=self.replenishment_factor)

    @property
    def petrol_pct(self) -> float:
        return (self.petrol_stock / self.petrol_capacity) * 100

    @property
    def diesel_pct(self) -> float:
        return (self.diesel_stock / self.diesel_capacity) * 100

    @property
    def status(self) -> str:
        min_pct = min(self.petrol_pct, self.diesel_pct)
        if min_pct > 50:
            return "GREEN"
        elif min_pct > 20:
            return "YELLOW"
        else:
            return "RED"

    def hours_to_empty(self, fuel: str) -> Optional[float]:
        """Hours until a fuel runs out at current consumption rate."""
        if fuel == "petrol":
            stock, rate = self.petrol_stock, self.petrol_sales_rate * self.panic_multiplier
        else:
            stock, rate = self.diesel_stock, self.diesel_sales_rate * self.panic_multiplier
        if rate <= 0:
            return None
        return round((stock / rate) * 24, 1)  # rate is per day

    def to_redis_payload(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "city": self.city,
            "state": self.state,
            "lat": self.lat,
            "lon": self.lon,
            "petrol_pct": round(self.petrol_pct, 1),
            "diesel_pct": round(self.diesel_pct, 1),
            "status": self.status,
            "panic_multiplier": self.panic_multiplier,
            "hours_to_empty_petrol": self.hours_to_empty("petrol"),
            "hours_to_empty_diesel": self.hours_to_empty("diesel"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }


def create_demo_pumps() -> list[PumpAgent]:
    """Create a set of demo pump agents for Indian cities."""
    cities = [
        ("Mumbai", "Maharashtra", 19.076, 72.877, "KANDLA"),
        ("Delhi", "Delhi", 28.704, 77.102, "PARADIP"),
        ("Bangalore", "Karnataka", 12.971, 77.594, "MANGALORE"),
        ("Chennai", "Tamil Nadu", 13.083, 80.270, "ENNORE"),
        ("Kolkata", "West Bengal", 22.572, 88.363, "HALDIA"),
        ("Hyderabad", "Telangana", 17.385, 78.487, "ENNORE"),
        ("Pune", "Maharashtra", 18.520, 73.856, "KANDLA"),
        ("Ahmedabad", "Gujarat", 23.022, 72.571, "KANDLA"),
        ("Jaipur", "Rajasthan", 26.913, 75.787, "KANDLA"),
        ("Lucknow", "Uttar Pradesh", 26.846, 80.946, "PARADIP"),
        ("Ranchi", "Jharkhand", 23.345, 85.309, "HALDIA"),
        ("Bhopal", "Madhya Pradesh", 23.259, 77.412, "KANDLA"),
    ]

    pumps = []
    pump_id = 1
    for city, state, base_lat, base_lon, port in cities:
        # 5 pumps per city with slight coordinate jitter
        for i in range(5):
            lat = base_lat + random.uniform(-0.05, 0.05)
            lon = base_lon + random.uniform(-0.05, 0.05)
            pumps.append(
                PumpAgent(
                    id=f"PUMP{pump_id:04d}",
                    name=f"{city} Pump {i+1}",
                    city=city,
                    state=state,
                    lat=lat,
                    lon=lon,
                    petrol_stock=random.uniform(20000, 45000),
                    diesel_stock=random.uniform(20000, 45000),
                    petrol_sales_rate=random.uniform(3000, 8000),
                    diesel_sales_rate=random.uniform(5000, 12000),
                    serving_port=port,
                )
            )
            pump_id += 1

    return pumps


async def sync_pumps_to_db(pumps: list[PumpAgent]) -> None:
    """Upsert pump_stations metadata on startup."""
    async with AsyncSessionLocal() as session:
        for pump in pumps:
            await session.execute(
                text("""
                    INSERT INTO pump_stations
                        (id, name, city, state, lat, lon, location, serving_port,
                         petrol_capacity_l, diesel_capacity_l, petrol_sales_rate, diesel_sales_rate)
                    VALUES
                        (:id, :name, :city, :state, :lat, :lon,
                         ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
                         :port, :petrol_cap, :diesel_cap, :petrol_rate, :diesel_rate)
                    ON CONFLICT (id) DO UPDATE SET
                        petrol_sales_rate = EXCLUDED.petrol_sales_rate,
                        diesel_sales_rate = EXCLUDED.diesel_sales_rate
                """),
                {
                    "id": pump.id,
                    "name": pump.name,
                    "city": pump.city,
                    "state": pump.state,
                    "lat": pump.lat,
                    "lon": pump.lon,
                    "port": pump.serving_port,
                    "petrol_cap": pump.petrol_capacity,
                    "diesel_cap": pump.diesel_capacity,
                    "petrol_rate": pump.petrol_sales_rate,
                    "diesel_rate": pump.diesel_sales_rate,
                },
            )
        await session.commit()
    logger.info("Pump stations synced to DB", count=len(pumps))


async def write_snapshots(pumps: list[PumpAgent], session) -> None:
    """Write inventory snapshots to TimescaleDB."""
    now = datetime.now(timezone.utc)
    for pump in pumps:
        await session.execute(
            text("""
                INSERT INTO pump_inventory
                    (id, pump_id, timestamp, petrol_stock_l, diesel_stock_l,
                     petrol_pct, diesel_pct, status, panic_multiplier,
                     hours_to_empty_petrol, hours_to_empty_diesel)
                VALUES
                    (:id, :pump_id, :ts, :petrol, :diesel,
                     :petrol_pct, :diesel_pct, :status, :panic,
                     :petrol_tte, :diesel_tte)
            """),
            {
                "id": str(uuid.uuid4()),
                "pump_id": pump.id,
                "ts": now,
                "petrol": pump.petrol_stock,
                "diesel": pump.diesel_stock,
                "petrol_pct": pump.petrol_pct,
                "diesel_pct": pump.diesel_pct,
                "status": pump.status,
                "panic": pump.panic_multiplier,
                "petrol_tte": pump.hours_to_empty("petrol"),
                "diesel_tte": pump.hours_to_empty("diesel"),
            },
        )


async def listen_for_disruptions(
    pumps: list[PumpAgent],
    redis: aioredis.Redis,
    bootstrap_servers: str,
) -> None:
    """Background task: update pump agents based on disruption/panic events."""
    consumer = AIOKafkaConsumer(
        "metrics.disruption",
        "social.panics.v1",
        bootstrap_servers=bootstrap_servers,
        group_id="inventory-updater-group",
        value_deserializer=lambda v: json.loads(v.decode()),
        auto_offset_reset="latest",
    )
    await consumer.start()
    logger.info("Disruption listener started")

    try:
        async for msg in consumer:
            data = msg.value
            topic = msg.topic

            if topic == "metrics.disruption":
                port = data.get("port_code", "").upper()
                di = data.get("disruption_index", 0)
                # Reduce replenishment factor based on disruption index
                factor = max(0.1, 1.0 - (di / 100) * 0.8)
                for pump in pumps:
                    if pump.serving_port == port:
                        pump.replenishment_factor = factor
                logger.info("Updated replenishment factor", port=port, di=di, factor=factor)

            elif topic == "social.panics.v1":
                city = data.get("city")
                panic_index = data.get("panic_index", 0)
                # Panic multiplier: 1.0 (normal) to 2.5 (full panic)
                multiplier = 1.0 + (panic_index / 100) * 1.5
                for pump in pumps:
                    if pump.city == city:
                        pump.panic_multiplier = round(multiplier, 2)
                logger.info("Updated panic multiplier", city=city, multiplier=multiplier)
    finally:
        await consumer.stop()


async def run() -> None:
    settings = get_settings()
    configure_logging("inventory-simulator")
    start_http_server(9105)

    redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)

    producer = AIOKafkaProducer(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        acks="all",
    )
    await producer.start()

    pumps = create_demo_pumps()
    await sync_pumps_to_db(pumps)

    # Start disruption/panic listener in background
    asyncio.create_task(
        listen_for_disruptions(pumps, redis, settings.KAFKA_BOOTSTRAP_SERVERS)
    )

    tick_dt_hours = settings.TICK_INTERVAL_SECONDS / 3600.0
    logger.info(
        "Inventory simulator started",
        pump_count=len(pumps),
        tick_interval=settings.TICK_INTERVAL_SECONDS,
    )

    while True:
        # Advance simulation
        for pump in pumps:
            pump.tick(tick_dt_hours)

        # Write to DB
        async with AsyncSessionLocal() as session:
            await write_snapshots(pumps, session)
            await session.commit()

        # Update Redis and publish state changes
        red_count = 0
        yellow_count = 0

        for pump in pumps:
            payload = pump.to_redis_payload()
            await redis.setex(f"pump:{pump.id}", 3600, json.dumps(payload))

            # Publish status to Kafka
            await producer.send(
                topic="state.pumps",
                key=pump.id.encode(),
                value=json.dumps(payload).encode(),
            )

            if pump.status == "RED":
                red_count += 1
            elif pump.status == "YELLOW":
                yellow_count += 1

        pumps_red.set(red_count)
        pumps_yellow.set(yellow_count)

        ticks_processed.inc()
        logger.info(
            "Inventory tick complete",
            pumps=len(pumps),
            red=red_count,
            yellow=yellow_count,
        )

        await asyncio.sleep(settings.TICK_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(run())
