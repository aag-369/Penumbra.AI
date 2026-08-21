"""FastAPI dependency injection.

The channel and orchestrator singletons live here so that endpoints depend on
an interface rather than reaching into module state, which keeps them testable
with ``app.dependency_overrides``.
"""

from __future__ import annotations

import functools
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ...config import Settings, get_settings, settings
from ...crypto.post_quantum_channel import PostQuantumChannel
from ...database import get_db
from ...models.user import User
from ...services.keystore_service import KeystoreService, get_keystore
from ...services.user_service import UserService

bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")


@functools.lru_cache(maxsize=1)
def get_channel() -> PostQuantumChannel:
    """Process-wide session manager.

    In-process, so a multi-worker deployment needs a shared store behind the
    same interface -- see the note on :class:`PostQuantumChannel`.
    """
    return PostQuantumChannel(
        use_bb84_simulation=settings.enable_bb84_simulation,
        session_ttl=settings.session_ttl_seconds,
    )


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """Resolve the bearer token to a live, active user.

    Raises 401 when the header is missing; the concrete auth failures raised by
    :class:`UserService` are mapped to their own status codes by the exception
    handlers.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = UserService.resolve_token(db, credentials.credentials, "access")
    UserService.touch(db, user)
    db.commit()
    return user


def get_admin_user(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    """Require the admin role."""
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="administrator access required")
    return current_user


def get_request(request: Request) -> Request:
    """Expose the raw request so endpoints can pass it to the audit service."""
    return request


DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
AdminUser = Annotated[User, Depends(get_admin_user)]
Keystore = Annotated[KeystoreService, Depends(get_keystore)]
Channel = Annotated[PostQuantumChannel, Depends(get_channel)]
AppSettings = Annotated[Settings, Depends(get_settings)]
Req = Annotated[Request, Depends(get_request)]
