"""
Production Hardening Middleware

Additional security and resilience middleware for the FastAPI app:
  - Request ID injection (for distributed tracing)
  - Security headers (HSTS, CSP, X-Frame-Options, etc.)
  - Request size limiting
  - Trusted host enforcement
  - Structured request logging with timing

Add to app/main.py:
    from app.middleware import add_middleware
    add_middleware(app)
"""
from __future__ import annotations

import time
import uuid
from typing import Callable

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

logger = structlog.get_logger(__name__)

# ── Request ID Middleware ─────────────────────────────────────────────────

class RequestIDMiddleware(BaseHTTPMiddleware):
    """Injects X-Request-ID header into every request and response."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        structlog.contextvars.bind_contextvars(request_id=request_id)

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id

        structlog.contextvars.clear_contextvars()
        return response


# ── Security Headers Middleware ───────────────────────────────────────────

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds security response headers to every response."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"

        # Enable XSS protection in older browsers
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # HSTS — only in production (HTTPS)
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )

        # Referrer policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Content Security Policy (permissive for API — tighten for dashboard)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "connect-src 'self' wss: https:;"
        )

        return response


# ── Request Logging Middleware ────────────────────────────────────────────

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Structured JSON logging for every request with timing."""

    SKIP_PATHS = {"/health", "/metrics", "/favicon.ico"}

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in self.SKIP_PATHS:
            return await call_next(request)

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        log_fn = logger.warning if response.status_code >= 400 else logger.info
        log_fn(
            "HTTP request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round(duration_ms, 2),
            client=request.client.host if request.client else "unknown",
            user_agent=request.headers.get("user-agent", ""),
        )

        return response


# ── Body Size Limiting ────────────────────────────────────────────────────

class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Rejects requests larger than max_size bytes (default 10 MB)."""

    def __init__(self, app, max_size: int = 10 * 1024 * 1024):
        super().__init__(app)
        self.max_size = max_size

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.max_size:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=413,
                content={"detail": f"Request body too large (max {self.max_size} bytes)"},
            )
        return await call_next(request)


# ── Assembler ─────────────────────────────────────────────────────────────

def add_middleware(app: FastAPI, production: bool = False) -> None:
    """Add all middleware in the correct order (outermost last)."""
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestSizeLimitMiddleware, max_size=10 * 1024 * 1024)

    if production:
        # In production, only allow requests from known hosts
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=["api.fuelchain.dev", "*.fuelchain.dev", "localhost"],
        )
