"""PENUMBRA API entry point.

Run locally::

    uvicorn app.main:app --reload

Interactive docs at ``/docs``.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.v1 import api_router
from .config import settings
from .database import init_db
from .middleware import (
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
    register_exception_handlers,
)
from .utils.logger import configure_logging

logger = logging.getLogger(__name__)

DESCRIPTION = """
Privacy-preserving, quantum-enhanced investment advisory.

**The guarantee.** Portfolio holdings are encrypted in the browser under a CKKS
keypair whose secret half never leaves the device. The server stores and computes
on ciphertexts and has no ability to decrypt them -- not by policy, but because
it does not possess the key. CKKS rests on Ring-LWE, which no known quantum
algorithm solves efficiently, so the guarantee is expected to survive a
cryptographically relevant quantum computer.

**What the server does know.** Ticker symbols, asset counts, timestamps and
ciphertext sizes. It does not know quantities, cost basis, portfolio value or
the recommended allocation. See `docs/CRYPTO_ASSUMPTIONS.md` for the full threat
model, including the residual leakage this design accepts.

**Implementation status.** The cryptographic layer, authentication, key
registry, portfolio storage and admin surface are implemented and tested. The
agent pipeline, QUBO formulation and QAOA solver are specified but not yet
built; their endpoints return `501 Not Implemented`.
"""


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    settings.assert_production_ready()
    init_db()
    logger.info(
        "%s starting in %s mode (database=%s, bb84_simulation=%s)",
        settings.app_name,
        settings.environment,
        "sqlite" if settings.is_sqlite else "postgresql",
        settings.enable_bb84_simulation,
    )
    yield
    logger.info("%s stopped", settings.app_name)


app = FastAPI(
    title=settings.app_name,
    description=DESCRIPTION,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-Id"],
    expose_headers=["X-Request-Id", "X-Response-Time-Ms"],
)
app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_production)
app.add_middleware(RequestLoggingMiddleware)

register_exception_handlers(app)
app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    """Unauthenticated liveness probe."""
    return {"status": "ok", "service": "penumbra-api", "version": "1.0.0"}


@app.get("/", tags=["meta"])
def root() -> dict[str, object]:
    """Service description and where to find the docs."""
    return {
        "service": settings.app_name,
        "version": "1.0.0",
        "docs": "/docs",
        "api": settings.api_v1_prefix,
        "privacy": "portfolio ciphertexts are opaque to this server; it holds no secret key",
    }
