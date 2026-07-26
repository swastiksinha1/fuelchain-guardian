"""Initial schema with PostGIS and TimescaleDB

Revision ID: 001_initial
Revises: 
Create Date: 2024-01-01 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
import geoalchemy2

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Enable PostgreSQL extensions ──────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")   # for text search

    # ── users ─────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255)),
        sa.Column("role", sa.String(20), server_default="dealer"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_users_email", "users", ["email"])

    # ── vessels ───────────────────────────────────────────
    op.create_table(
        "vessels",
        sa.Column("mmsi", sa.String(9), primary_key=True),
        sa.Column("imo", sa.String(10)),
        sa.Column("name", sa.String(255)),
        sa.Column("vessel_type", sa.String(100)),
        sa.Column("flag", sa.String(3)),
        sa.Column("gross_tonnage", sa.Integer),
        sa.Column("destination", sa.String(255)),
        sa.Column("eta_utc", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── vessel_positions (TimescaleDB hypertable) ─────────
    op.create_table(
        "vessel_positions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("mmsi", sa.String(9), sa.ForeignKey("vessels.mmsi"), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lat", sa.Float, nullable=False),
        sa.Column("lon", sa.Float, nullable=False),
        sa.Column("sog", sa.Float),
        sa.Column("cog", sa.Float),
        sa.Column("heading", sa.Integer),
        sa.Column("nav_status", sa.String(50)),
        sa.Column(
            "location",
            geoalchemy2.Geometry(geometry_type="POINT", srid=4326),
        ),
    )
    op.create_index("ix_vessel_positions_mmsi_ts", "vessel_positions", ["mmsi", "timestamp"])

    # Convert to TimescaleDB hypertable (partition by timestamp, 1-day chunks)
    op.execute(
        "SELECT create_hypertable('vessel_positions', 'timestamp', "
        "chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE)"
    )

    # ── anomaly_events ────────────────────────────────────
    op.create_table(
        "anomaly_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("mmsi", sa.String(9), sa.ForeignKey("vessels.mmsi"), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("lat", sa.Float),
        sa.Column("lon", sa.Float),
        sa.Column("sog", sa.Float),
        sa.Column("deviation_nm", sa.Float),
        sa.Column("estimated_delay_hours", sa.Float),
        sa.Column("destination_port", sa.String(10)),
        sa.Column("details", JSONB),
        sa.Column("resolved", sa.Boolean, server_default="false"),
    )
    op.create_index("ix_anomaly_events_mmsi", "anomaly_events", ["mmsi"])
    op.create_index("ix_anomaly_events_detected_at", "anomaly_events", ["detected_at"])

    # ── pump_stations ─────────────────────────────────────
    op.create_table(
        "pump_stations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("dealer_id", sa.String(50)),
        sa.Column("city", sa.String(100), nullable=False),
        sa.Column("state", sa.String(100), nullable=False),
        sa.Column("lat", sa.Float, nullable=False),
        sa.Column("lon", sa.Float, nullable=False),
        sa.Column("location", geoalchemy2.Geometry(geometry_type="POINT", srid=4326)),
        sa.Column("depot_code", sa.String(20)),
        sa.Column("serving_port", sa.String(10)),
        sa.Column("petrol_capacity_l", sa.Integer, server_default="50000"),
        sa.Column("diesel_capacity_l", sa.Integer, server_default="50000"),
        sa.Column("lpg_capacity_kg", sa.Integer, server_default="2000"),
        sa.Column("petrol_sales_rate", sa.Float, server_default="5000"),
        sa.Column("diesel_sales_rate", sa.Float, server_default="8000"),
        sa.Column("active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.execute(
        "CREATE INDEX ix_pump_stations_location ON pump_stations "
        "USING GIST (location)"
    )

    # ── pump_inventory (hypertable) ───────────────────────
    op.create_table(
        "pump_inventory",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("pump_id", UUID(as_uuid=True), sa.ForeignKey("pump_stations.id"), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("petrol_stock_l", sa.Float, nullable=False),
        sa.Column("diesel_stock_l", sa.Float, nullable=False),
        sa.Column("lpg_stock_kg", sa.Float, server_default="0"),
        sa.Column("petrol_pct", sa.Float),
        sa.Column("diesel_pct", sa.Float),
        sa.Column("status", sa.String(10)),
        sa.Column("panic_multiplier", sa.Float, server_default="1.0"),
        sa.Column("hours_to_empty_petrol", sa.Float),
        sa.Column("hours_to_empty_diesel", sa.Float),
        sa.Column("next_replenishment_at", sa.DateTime(timezone=True)),
        sa.Column("queue_density", sa.Integer, server_default="1"),
    )
    op.create_index("ix_pump_inventory_pump_ts", "pump_inventory", ["pump_id", "timestamp"])
    op.execute(
        "SELECT create_hypertable('pump_inventory', 'timestamp', "
        "chunk_time_interval => INTERVAL '6 hours', if_not_exists => TRUE)"
    )

    # ── panic_events ──────────────────────────────────────
    op.create_table(
        "panic_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tweet_id", sa.String(50), unique=True),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("city", sa.String(100)),
        sa.Column("panic_score", sa.Float),
        sa.Column("is_panic", sa.Boolean),
        sa.Column("language", sa.String(10)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_panic_events_city", "panic_events", ["city"])

    # ── panic_index ───────────────────────────────────────
    op.create_table(
        "panic_index",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("city", sa.String(100), nullable=False),
        sa.Column("hour_bucket", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tweet_count", sa.Integer, server_default="0"),
        sa.Column("panic_count", sa.Integer, server_default="0"),
        sa.Column("panic_index", sa.Float),
        sa.Column("alert_sent", sa.Boolean, server_default="false"),
    )
    op.create_index("ix_panic_index_city_hour", "panic_index", ["city", "hour_bucket"], unique=True)

    # ── dealers ───────────────────────────────────────────
    op.create_table(
        "dealers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("business_name", sa.String(255), nullable=False),
        sa.Column("gstin", sa.String(15), unique=True),
        sa.Column("pan", sa.String(10), unique=True),
        sa.Column("pump_id", UUID(as_uuid=True), sa.ForeignKey("pump_stations.id")),
        sa.Column("omc", sa.String(20)),
        sa.Column("credit_limit", sa.Numeric(12, 2), server_default="500000"),
        sa.Column("outstanding", sa.Numeric(12, 2), server_default="0"),
        sa.Column("verified", sa.Boolean, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── credit_applications ───────────────────────────────
    op.create_table(
        "credit_applications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("dealer_id", UUID(as_uuid=True), sa.ForeignKey("dealers.id"), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("omc_invoice_ref", sa.String(100)),
        sa.Column("omc_dispatch_id", sa.String(100)),
        sa.Column("invoice_verified", sa.Boolean, server_default="false"),
        sa.Column("status", sa.String(20), server_default="pending"),
        sa.Column("applied_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("disbursed_at", sa.DateTime(timezone=True)),
        sa.Column("due_date", sa.DateTime(timezone=True)),
        sa.Column("repaid_at", sa.DateTime(timezone=True)),
        sa.Column("notes", sa.Text),
    )
    op.create_index("ix_credit_applications_dealer", "credit_applications", ["dealer_id"])

    # ── transactions ──────────────────────────────────────
    op.create_table(
        "transactions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("application_id", UUID(as_uuid=True), sa.ForeignKey("credit_applications.id"), nullable=False),
        sa.Column("tx_type", sa.String(20)),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("gateway", sa.String(50)),
        sa.Column("gateway_tx_id", sa.String(100), unique=True),
        sa.Column("status", sa.String(20), server_default="pending"),
        sa.Column("upi_ref", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("metadata", JSONB),
    )


def downgrade() -> None:
    op.drop_table("transactions")
    op.drop_table("credit_applications")
    op.drop_table("dealers")
    op.drop_table("panic_index")
    op.drop_table("panic_events")
    op.drop_table("pump_inventory")
    op.drop_table("pump_stations")
    op.drop_table("anomaly_events")
    op.drop_table("vessel_positions")
    op.drop_table("vessels")
    op.drop_table("users")
    op.execute("DROP EXTENSION IF EXISTS timescaledb CASCADE")
    op.execute("DROP EXTENSION IF EXISTS postgis")
