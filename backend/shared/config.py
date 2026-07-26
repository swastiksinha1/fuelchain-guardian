"""
Shared configuration and settings for all FuelChain Guardian services.
Uses pydantic-settings for type-safe env var loading.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Literal

import structlog
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # ── Database ──────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://fuelchain:secret@localhost:5432/fuelchain"

    # ── Cache ─────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── Kafka / Redpanda ──────────────────────────────────
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"

    # ── Auth ──────────────────────────────────────────────
    JWT_SECRET: str = "dev-secret-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440

    # ── AIS Provider ──────────────────────────────────────
    AIS_MODE: Literal["aishub", "simulator"] = "simulator"
    AISHUB_API_KEY: str = ""              # Set this for real AIS data
    AISHUB_HOST: str = "data.aishub.net"
    AISHUB_PORT: int = 9876

    # ── Social Media ──────────────────────────────────────
    SOCIAL_MODE: Literal["twitter", "simulator"] = "simulator"
    TWITTER_BEARER_TOKEN: str = ""        # Set this for real Twitter data

    # ── Payment ───────────────────────────────────────────
    PAYMENT_MODE: Literal["mock", "live"] = "mock"
    RAZORPAY_KEY_ID: str = ""             # Set this for real UPI disbursals
    RAZORPAY_KEY_SECRET: str = ""

    # ── Firebase ──────────────────────────────────────────
    FIREBASE_PROJECT_ID: str = ""
    FIREBASE_SERVICE_ACCOUNT_JSON: str = "./secrets/firebase-service-account.json"

    # ── NLP Service ───────────────────────────────────────
    NLP_SERVICE_URL: str = "http://localhost:8001"
    MODEL_PATH: str = "./models/panic_classifier"

    # ── Inventory Simulator ───────────────────────────────
    TICK_INTERVAL_SECONDS: int = 1800

    # ── Panic ─────────────────────────────────────────────
    PANIC_THRESHOLD: int = 65

    # ── Logging ───────────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    SERVICE: str = "fuelchain-backend"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def configure_logging(service: str = "fuelchain") -> None:
    """Configure structured JSON logging."""
    log_level = get_settings().LOG_LEVEL.upper()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level, logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )

    # Also configure stdlib logging
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, log_level, logging.INFO),
    )
