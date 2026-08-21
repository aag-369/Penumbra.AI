"""Registration, login, logout and token refresh."""

from __future__ import annotations

from fastapi import APIRouter, status

from ....config import settings
from ....models.audit_log import AuditAction, AuditSeverity
from ....models.user import User, UserRole
from ....schemas.common import Message
from ....schemas.user_schema import (
    RefreshRequest,
    TokenPair,
    UserLogin,
    UserPublic,
    UserRegister,
)
from ....services.audit_service import AuditService
from ....services.user_service import (
    AccountLocked,
    InvalidCredentials,
    UserService,
)
from ..dependencies import CurrentUser, DbSession, Req

router = APIRouter()


def _issue(user: User) -> TokenPair:
    return TokenPair(
        access_token=UserService.create_token(user, "access"),
        refresh_token=UserService.create_token(user, "refresh"),
        expires_in=settings.access_token_ttl_seconds,
        user_id=user.id,
        role=user.role.value,
    )


@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
def register(payload: UserRegister, db: DbSession, request: Req) -> TokenPair:
    """Create an account.

    Registration does not create encryption keys. The client generates its own
    CKKS keypair in the browser and registers only the public half via
    ``POST /portfolio/keys``. The server has no way to produce a keypair on the
    user's behalf without holding the secret, which is the whole point.
    """
    email = payload.email.strip().lower()
    if db.query(User).filter(User.email == email).first() is not None:
        # Deliberately the same shape as a validation error, so registration
        # is not an account-enumeration oracle for an unauthenticated caller.
        raise InvalidCredentials("that email cannot be registered")

    #: The first account to register becomes the administrator. Any later
    #: promotion is an explicit admin action with an audit row.
    role = UserRole.ADMIN if db.query(User).count() == 0 else UserRole.USER
    user = UserService.create_user(db, email, payload.password, role)
    AuditService.record(
        db, AuditAction.USER_REGISTERED, actor_user_id=user.id, request=request, role=role.value
    )
    db.commit()
    return _issue(user)


@router.post("/login", response_model=TokenPair)
def login(payload: UserLogin, db: DbSession, request: Req) -> TokenPair:
    """Exchange credentials for a token pair.

    Repeated failures lock the account for ``LOGIN_LOCKOUT_SECONDS``.
    """
    try:
        user = UserService.authenticate(db, payload.email, payload.password)
    except (InvalidCredentials, AccountLocked) as exc:
        AuditService.record(
            db,
            AuditAction.USER_LOGIN_FAILED,
            request=request,
            severity=AuditSeverity.WARNING,
            email=payload.email.strip().lower(),
            reason=type(exc).__name__,
        )
        db.commit()
        raise

    AuditService.record(db, AuditAction.USER_LOGIN, actor_user_id=user.id, request=request)
    db.commit()
    return _issue(user)


@router.post("/logout", response_model=Message)
def logout(current_user: CurrentUser, db: DbSession, request: Req) -> Message:
    """Invalidate every token issued to this user.

    Implemented by bumping the user's ``token_version``, so the effect is
    immediate on every device with no blacklist to maintain.
    """
    UserService.invalidate_tokens(db, current_user)
    AuditService.record(
        db, AuditAction.USER_LOGOUT, actor_user_id=current_user.id, request=request
    )
    db.commit()
    return Message(message="signed out on all devices")


@router.post("/refresh", response_model=TokenPair)
def refresh(payload: RefreshRequest, db: DbSession) -> TokenPair:
    """Exchange a refresh token for a new pair."""
    user = UserService.resolve_token(db, payload.refresh_token, "refresh")
    return _issue(user)


@router.get("/me", response_model=UserPublic)
def me(current_user: CurrentUser) -> User:
    """The authenticated user."""
    return current_user
