"""Global exception handlers.

Two jobs. First, translate the domain exceptions raised by the crypto, service
and optimisation layers into the right HTTP status with a stable machine-readable
``code``. Second, make sure an unexpected exception returns a generic message --
a stack trace or a SQL fragment in an error body is an information leak, and in
this application the bodies are one layer away from key material.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ..config import settings
from ..crypto.ckks_engine import (
    CiphertextError,
    CryptoError,
    InsecureParameters,
    SecretKeyUnavailable,
)
from ..crypto.homomorphic_ops import DepthExceeded, RotationKeysMissing
from ..crypto.post_quantum_channel import (
    AuthenticationFailed,
    EavesdropperDetected,
    SessionExpired,
)
from ..crypto.security_utils import SealError
from ..services.keystore_service import (
    ContextTooLarge,
    KeyNotFound,
    KeystoreError,
    SecretKeyRejected,
)
from ..services.portfolio_service import PortfolioNotFound, ValidationFailed
from ..services.user_service import (
    AccountInactive,
    AccountLocked,
    InvalidCredentials,
    InvalidToken,
)

logger = logging.getLogger(__name__)

#: exception type -> (status code, stable error code)
EXCEPTION_MAP: list[tuple[type[Exception], int, str]] = [
    # authentication
    (InvalidCredentials, status.HTTP_401_UNAUTHORIZED, "invalid_credentials"),
    (InvalidToken, status.HTTP_401_UNAUTHORIZED, "invalid_token"),
    (AccountLocked, status.HTTP_429_TOO_MANY_REQUESTS, "account_locked"),
    (AccountInactive, status.HTTP_403_FORBIDDEN, "account_inactive"),
    # channel
    (SessionExpired, status.HTTP_401_UNAUTHORIZED, "session_expired"),
    (AuthenticationFailed, status.HTTP_401_UNAUTHORIZED, "ciphertext_auth_failed"),
    (EavesdropperDetected, status.HTTP_409_CONFLICT, "eavesdropper_detected"),
    # keystore -- order matters, subclasses first
    (SecretKeyRejected, status.HTTP_400_BAD_REQUEST, "secret_key_rejected"),
    (ContextTooLarge, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "context_too_large"),
    (KeyNotFound, status.HTTP_404_NOT_FOUND, "encryption_key_not_found"),
    (KeystoreError, status.HTTP_400_BAD_REQUEST, "keystore_error"),
    # crypto
    (InsecureParameters, status.HTTP_400_BAD_REQUEST, "insecure_parameters"),
    (SecretKeyUnavailable, status.HTTP_500_INTERNAL_SERVER_ERROR, "secret_key_unavailable"),
    (DepthExceeded, status.HTTP_422_UNPROCESSABLE_ENTITY, "modulus_depth_exceeded"),
    (RotationKeysMissing, status.HTTP_422_UNPROCESSABLE_ENTITY, "rotation_keys_missing"),
    (CiphertextError, status.HTTP_400_BAD_REQUEST, "invalid_ciphertext"),
    (SealError, status.HTTP_400_BAD_REQUEST, "seal_error"),
    (CryptoError, status.HTTP_400_BAD_REQUEST, "crypto_error"),
    # portfolio
    (ValidationFailed, status.HTTP_422_UNPROCESSABLE_ENTITY, "validation_failed"),
    (PortfolioNotFound, status.HTTP_404_NOT_FOUND, "portfolio_not_found"),
]


def _body(code: str, detail: str, context: dict | None = None) -> dict:
    payload: dict = {"code": code, "detail": detail}
    if context:
        payload["context"] = context
    return payload


def register_exception_handlers(app: FastAPI) -> None:
    """Attach every handler to the application."""

    for exc_type, http_status, code in EXCEPTION_MAP:
        app.add_exception_handler(
            exc_type, _make_handler(http_status, code)  # type: ignore[arg-type]
        )

    @app.exception_handler(NotImplementedError)
    async def _not_implemented(_request: Request, exc: NotImplementedError) -> JSONResponse:
        """Phase 2/3/4 surfaces answer honestly rather than pretending to work.

        A 501 with the phase named is more useful to a reviewer than a 500, and
        it keeps the OpenAPI contract accurate: the route exists, the behaviour
        does not yet.
        """
        return JSONResponse(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            content=_body("not_implemented", str(exc) or "this capability is not implemented yet"),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_request: Request, exc: RequestValidationError) -> JSONResponse:
        problems = [
            {"field": ".".join(str(p) for p in err["loc"][1:]), "message": err["msg"]}
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_body("request_invalid", "the request body failed validation", {"problems": problems}),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Correlation id lets an operator find the stack trace in the logs
        # without the client ever seeing it.
        incident = uuid.uuid4().hex[:12]
        logger.exception(
            "unhandled exception [%s] on %s %s", incident, request.method, request.url.path
        )
        detail = (
            f"{type(exc).__name__}: {exc}"
            if settings.debug
            else "an internal error occurred; quote the incident id when reporting it"
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_body("internal_error", detail, {"incident_id": incident}),
        )


def _make_handler(http_status: int, code: str):
    async def handler(_request: Request, exc: Exception) -> JSONResponse:
        logger.info("%s -> %d %s", type(exc).__name__, http_status, code)
        return JSONResponse(status_code=http_status, content=_body(code, str(exc)))

    return handler
