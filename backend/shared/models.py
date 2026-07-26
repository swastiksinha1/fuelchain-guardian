"""
SQLAlchemy ORM models for FuelChain Guardian.
All tables including hypertable declarations for TimescaleDB.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from geoalchemy2 import Geometry
from sqlalchemy import (
    DECIMAL,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.database import Base


def now_utc():
    return datetime.utcnow()


# ─────────────────────────────────────────────────────────────────────────────
# Vessel / AIS Models
# ─────────────────────────────────────────────────────────────────────────────

class Vessel(Base):
    """Static vessel metadata."""
    __tablename__ = "vessels"

    mmsi: Mapped[str] = mapped_column(String(9), primary_key=True)
    imo: Mapped[Optional[str]] = mapped_column(String(10))
    name: Mapped[Optional[str]] = mapped_column(String(255))
    vessel_type: Mapped[Optional[str]] = mapped_column(String(100))
    flag: Mapped[Optional[str]] = mapped_column(String(3))
    gross_tonnage: Mapped[Optional[int]] = mapped_column(Integer)
    destination: Mapped[Optional[str]] = mapped_column(String(255))
    eta_utc: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    positions: Mapped[list["VesselPosition"]] = relationship(
        back_populates="vessel", lazy="select"
    )


class VesselPosition(Base):
    """
    TimescaleDB hypertable — time-series of vessel positions.
    Partitioned by timestamp automatically via TimescaleDB.
    """
    __tablename__ = "vessel_positions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    mmsi: Mapped[str] = mapped_column(
        String(9), ForeignKey("vessels.mmsi"), nullable=False, index=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    sog: Mapped[Optional[float]] = mapped_column(Float)      # Speed over ground (knots)
    cog: Mapped[Optional[float]] = mapped_column(Float)      # Course over ground (degrees)
    heading: Mapped[Optional[int]] = mapped_column(Integer)
    nav_status: Mapped[Optional[str]] = mapped_column(String(50))
    location: Mapped[Optional[object]] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326)
    )

    vessel: Mapped["Vessel"] = relationship(back_populates="positions")

    __table_args__ = (
        Index("ix_vessel_positions_mmsi_ts", "mmsi", "timestamp"),
    )


class AnomalyEvent(Base):
    """Detected anomalies (slow tankers, off-TSS deviations)."""
    __tablename__ = "anomaly_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    mmsi: Mapped[str] = mapped_column(String(9), ForeignKey("vessels.mmsi"), index=True)
    event_type: Mapped[str] = mapped_column(String(50))  # 'slow_speed' | 'off_course'
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    sog: Mapped[Optional[float]] = mapped_column(Float)
    deviation_nm: Mapped[Optional[float]] = mapped_column(Float)
    estimated_delay_hours: Mapped[Optional[float]] = mapped_column(Float)
    destination_port: Mapped[Optional[str]] = mapped_column(String(10))
    details: Mapped[Optional[dict]] = mapped_column(JSONB)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)


# ─────────────────────────────────────────────────────────────────────────────
# Pump Inventory Models
# ─────────────────────────────────────────────────────────────────────────────

class PumpStation(Base):
    """Petrol pump / fuel station master data."""
    __tablename__ = "pump_stations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    dealer_id: Mapped[Optional[str]] = mapped_column(String(50))
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(100), nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    location: Mapped[Optional[object]] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326)
    )
    depot_code: Mapped[Optional[str]] = mapped_column(String(20))
    serving_port: Mapped[Optional[str]] = mapped_column(String(10))
    petrol_capacity_l: Mapped[int] = mapped_column(Integer, default=50000)
    diesel_capacity_l: Mapped[int] = mapped_column(Integer, default=50000)
    lpg_capacity_kg: Mapped[int] = mapped_column(Integer, default=2000)
    petrol_sales_rate: Mapped[float] = mapped_column(Float, default=5000.0)  # L/day
    diesel_sales_rate: Mapped[float] = mapped_column(Float, default=8000.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PumpInventory(Base):
    """
    Current inventory snapshot for each pump.
    Also a TimescaleDB hypertable for historical tracking.
    """
    __tablename__ = "pump_inventory"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    pump_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pump_stations.id"), nullable=False, index=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    petrol_stock_l: Mapped[float] = mapped_column(Float, nullable=False)
    diesel_stock_l: Mapped[float] = mapped_column(Float, nullable=False)
    lpg_stock_kg: Mapped[float] = mapped_column(Float, default=0)
    petrol_pct: Mapped[float] = mapped_column(Float)  # 0-100
    diesel_pct: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(10))    # GREEN | YELLOW | RED
    panic_multiplier: Mapped[float] = mapped_column(Float, default=1.0)
    hours_to_empty_petrol: Mapped[Optional[float]] = mapped_column(Float)
    hours_to_empty_diesel: Mapped[Optional[float]] = mapped_column(Float)
    next_replenishment_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    queue_density: Mapped[int] = mapped_column(Integer, default=1)  # 1-4 scale

    __table_args__ = (
        Index("ix_pump_inventory_pump_ts", "pump_id", "timestamp"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Panic / Social Media Models
# ─────────────────────────────────────────────────────────────────────────────

class PanicEvent(Base):
    """Classified social media posts indicating panic."""
    __tablename__ = "panic_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tweet_id: Mapped[Optional[str]] = mapped_column(String(50), unique=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    city: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    panic_score: Mapped[float] = mapped_column(Float)  # 0.0-1.0
    is_panic: Mapped[bool] = mapped_column(Boolean)
    language: Mapped[Optional[str]] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PanicIndex(Base):
    """Hourly aggregated Panic Index per city."""
    __tablename__ = "panic_index"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    hour_bucket: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    tweet_count: Mapped[int] = mapped_column(Integer, default=0)
    panic_count: Mapped[int] = mapped_column(Integer, default=0)
    panic_index: Mapped[float] = mapped_column(Float)  # 0-100
    alert_sent: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        Index("ix_panic_index_city_hour", "city", "hour_bucket", unique=True),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Credit / Dealer Models
# ─────────────────────────────────────────────────────────────────────────────

class Dealer(Base):
    """Petrol pump dealer / distributor."""
    __tablename__ = "dealers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    business_name: Mapped[str] = mapped_column(String(255), nullable=False)
    gstin: Mapped[Optional[str]] = mapped_column(String(15), unique=True)
    pan: Mapped[Optional[str]] = mapped_column(String(10), unique=True)
    pump_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pump_stations.id")
    )
    omc: Mapped[str] = mapped_column(String(20))  # 'IOCL' | 'BPCL' | 'HPCL'
    credit_limit: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=500000)
    outstanding: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CreditApplication(Base):
    """Dealer micro-credit application."""
    __tablename__ = "credit_applications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    dealer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dealers.id"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    omc_invoice_ref: Mapped[Optional[str]] = mapped_column(String(100))
    omc_dispatch_id: Mapped[Optional[str]] = mapped_column(String(100))
    invoice_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # pending | approved | disbursed | repaid | overdue
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    disbursed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    repaid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    notes: Mapped[Optional[str]] = mapped_column(Text)


class Transaction(Base):
    """UPI transaction records for credit disbursal/repayment."""
    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("credit_applications.id"), nullable=False
    )
    tx_type: Mapped[str] = mapped_column(String(20))  # 'disbursal' | 'repayment'
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    gateway: Mapped[str] = mapped_column(String(50))   # 'mock' | 'razorpay' | 'cashfree'
    gateway_tx_id: Mapped[Optional[str]] = mapped_column(String(100), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # pending | success | failed
    upi_ref: Mapped[Optional[str]] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    tx_metadata: Mapped[Optional[dict]] = mapped_column("metadata", JSONB)


# ─────────────────────────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────────────────────────

class User(Base):
    """Application users (dealers + admin)."""
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="dealer")  # dealer | admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
