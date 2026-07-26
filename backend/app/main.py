"""
FuelChain Guardian — Main FastAPI Application

Routers:
  /api/v1/auth        — JWT authentication
  /api/v1/vessels     — Tanker tracking
  /api/v1/disruption  — Disruption Index
  /api/v1/pumps       — Pump inventory
  /api/v1/panic       — Panic Index
  /api/v1/credit      — Dealer micro-credit

/metrics  — Prometheus metrics
/health   — Health check
/ready    — Readiness check (DB + Redis connectivity)
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
import structlog
import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from prometheus_client import Counter, Histogram, make_asgi_app
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import text

from shared.config import configure_logging, get_settings
from shared.database import engine, AsyncSessionLocal
from app.routers import auth, credit, disruption, panic, pumps, vessels

logger = structlog.get_logger(__name__)
configure_logging("api-gateway")
settings = get_settings()

# ── Prometheus metrics ─────────────────────────────────────────────────────
REQUEST_COUNT = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "path", "status"]
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds", "HTTP request latency", ["method", "path"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

# ── Rate limiter ──────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)


# ── Lifespan (startup / shutdown) ─────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("FuelChain Guardian API starting up", version="1.0.0")
    # Verify DB connection on startup
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        logger.info("Database connection OK")
    except Exception as e:
        logger.error("Database connection FAILED on startup", error=str(e))

    # Verify Redis connection
    try:
        r = aioredis.from_url(settings.REDIS_URL)
        await r.ping()
        await r.close()
        logger.info("Redis connection OK")
    except Exception as e:
        logger.error("Redis connection FAILED on startup", error=str(e))

    yield  # App is running

    logger.info("FuelChain Guardian API shutting down")
    await engine.dispose()


# ── App ────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="FuelChain Guardian API",
    version="1.0.0",
    description="""
## India Fuel Supply Chain Intelligence Platform

Real-time tanker tracking, pump inventory prediction,
dealer micro-credit, and panic-buying suppression.

### Authentication
Most endpoints require a JWT Bearer token.
Get one via `POST /api/v1/auth/token`.
    """,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production via CORS_ORIGINS env var
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def metrics_and_logging_middleware(request: Request, call_next):
    start = time.perf_counter()

    # Skip noisy paths from detailed logging
    skip = {"/health", "/ready", "/metrics", "/favicon.ico"}

    response: Response = await call_next(request)
    duration = time.perf_counter() - start
    path = request.url.path

    REQUEST_COUNT.labels(
        method=request.method,
        path=path,
        status=response.status_code,
    ).inc()
    REQUEST_LATENCY.labels(method=request.method, path=path).observe(duration)

    if path not in skip:
        log_fn = logger.warning if response.status_code >= 400 else logger.info
        log_fn(
            "request",
            method=request.method,
            path=path,
            status=response.status_code,
            ms=round(duration * 1000, 1),
        )

    return response


# ── Prometheus ASGI sub-app ───────────────────────────────────────────────
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# ── Routers ───────────────────────────────────────────────────────────────
app.include_router(auth.router,       prefix="/api/v1/auth",        tags=["auth"])
app.include_router(vessels.router,    prefix="/api/v1/vessels",     tags=["vessels"])
app.include_router(disruption.router, prefix="/api/v1/disruption",  tags=["disruption"])
app.include_router(pumps.router,      prefix="/api/v1/pumps",       tags=["pumps"])
app.include_router(panic.router,      prefix="/api/v1/panic",       tags=["panic"])
app.include_router(credit.router,     prefix="/api/v1/credit",      tags=["credit"])


# ── Health endpoints ──────────────────────────────────────────────────────
@app.get("/health", tags=["ops"], summary="Liveness probe")
async def health():
    """Returns 200 when the process is alive."""
    return {"status": "ok", "service": "fuelchain-backend", "version": "1.0.0"}


@app.get("/ready", tags=["ops"], summary="Readiness probe")
async def ready():
    """Returns 200 only when DB and Redis are reachable."""
    checks: dict[str, str] = {}

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception as e:
        checks["db"] = f"error: {e}"

    try:
        r = aioredis.from_url(settings.REDIS_URL)
        await r.ping()
        await r.close()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"

    all_ok = all(v == "ok" for v in checks.values())
    return Response(
        content=str({"status": "ready" if all_ok else "degraded", "checks": checks}),
        status_code=200 if all_ok else 503,
        media_type="application/json",
    )


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        log_config=None,
        reload=True,
    )
