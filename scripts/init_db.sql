-- FuelChain Guardian Database Initialization
-- Runs automatically on first postgres container start

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Set TimescaleDB telemetry off (for privacy in dev)
ALTER SYSTEM SET timescaledb.telemetry_level = 'off';
