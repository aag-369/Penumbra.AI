"""Request logging with a correlation id.

Deliberately does not log request bodies. Bodies on this API carry ciphertexts
and public contexts -- megabytes each, and exactly the material the system
exists to protect. Only method, path, status, duration and size are recorded.
"""

from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("penumbra.access")

#: Paths that are too chatty to log at INFO.
_QUIET_PATHS = {"/health", "/healthz", "/metrics", "/docs", "/openapi.json", "/redoc"}


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        request.state.request_id = request_id

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed = (time.perf_counter() - started) * 1000
            logger.exception(
                "[%s] %s %s -> raised after %.1fms",
                request_id, request.method, request.url.path, elapsed,
            )
            raise

        elapsed = (time.perf_counter() - started) * 1000
        response.headers["x-request-id"] = request_id
        response.headers["x-response-time-ms"] = f"{elapsed:.1f}"

        if request.url.path not in _QUIET_PATHS:
            level = logging.WARNING if response.status_code >= 500 else logging.INFO
            logger.log(
                level,
                "[%s] %s %s -> %d in %.1fms",
                request_id, request.method, request.url.path, response.status_code, elapsed,
            )
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Set the headers a browser needs to enforce the client-side trust model.

    The private key lives in the browser, so cross-site script injection is not
    merely an XSS -- it is a key-exfiltration path. These headers are the
    baseline; the frontend must also avoid ``dangerouslySetInnerHTML`` and must
    keep the key out of ``localStorage`` in unsealed form.
    """

    def __init__(self, app, *, hsts: bool = False) -> None:
        super().__init__(app)
        self.hsts = hsts

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )
        if self.hsts:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response
