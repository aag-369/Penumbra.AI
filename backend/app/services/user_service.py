"""User lifecycle: password hashing, JWT issuance, login throttling.

Password hashing uses the ``bcrypt`` package directly rather than passlib.
passlib 1.7.4 reads ``bcrypt.__about__.__version__``, which bcrypt 4.1 removed,
so the combination emits errors on every hash. Calling bcrypt directly is a
smaller dependency surface and behaves identically.

Token invalidation uses a per-user ``token_version`` counter rather than a
blacklist. Logout bumps the counter; every previously issued token carries the
old value and stops verifying. No Redis, no unbounded blacklist table, and
logout is effective immediately across all devices.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import bcrypt
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from ..config import settings
from ..models.base import utcnow
from ..models.user import User, UserRole

logger = logging.getLogger(__name__)

#: bcrypt silently truncates at 72 bytes, so a longer password would make every
#: suffix equivalent. Reject instead of truncating.
BCRYPT_MAX_BYTES = 72

TokenType = Literal["access", "refresh"]


class AuthError(Exception):
    """Base class for authentication failures."""


class InvalidCredentials(AuthError):
    """Wrong email or password."""


class AccountLocked(AuthError):
    """Too many failed attempts."""


class AccountInactive(AuthError):
    """The account has been deactivated by an administrator."""


class InvalidToken(AuthError):
    """The JWT is malformed, expired, or superseded by a logout."""


class UserService:
    """Stateless helpers over the :class:`~app.models.user.User` table."""

    # -- passwords ----------------------------------------------------------
    @staticmethod
    def hash_password(password: str) -> str:
        """Hash a password with bcrypt at the configured cost."""
        raw = password.encode("utf-8")
        if len(raw) > BCRYPT_MAX_BYTES:
            raise ValueError(
                f"password exceeds bcrypt's {BCRYPT_MAX_BYTES}-byte limit; "
                "bcrypt would silently ignore the remainder"
            )
        return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=settings.bcrypt_rounds)).decode("utf-8")

    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        """Constant-time password check. Never raises on a malformed hash."""
        try:
            return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
        except (ValueError, TypeError):
            return False

    @staticmethod
    def validate_password_strength(password: str) -> list[str]:
        """Return a list of problems. Empty list means the password is acceptable."""
        problems = []
        if len(password) < 12:
            problems.append("must be at least 12 characters")
        if len(password.encode("utf-8")) > BCRYPT_MAX_BYTES:
            problems.append(f"must be at most {BCRYPT_MAX_BYTES} bytes")
        if not any(c.isalpha() for c in password):
            problems.append("must contain a letter")
        if not any(c.isdigit() for c in password):
            problems.append("must contain a digit")
        return problems

    # -- tokens -------------------------------------------------------------
    @staticmethod
    def create_token(user: User, token_type: TokenType = "access") -> str:
        """Issue a signed JWT bound to the user's current ``token_version``."""
        ttl = (
            settings.access_token_ttl_seconds
            if token_type == "access"
            else settings.refresh_token_ttl_seconds
        )
        now = datetime.now(timezone.utc)
        claims: dict[str, Any] = {
            "sub": user.id,
            "email": user.email,
            "role": user.role.value,
            "typ": token_type,
            "ver": user.token_version,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=ttl)).timestamp()),
            "iss": settings.app_name,
        }
        return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)

    @staticmethod
    def decode_token(token: str, expected_type: TokenType = "access") -> dict[str, Any]:
        """Verify a JWT's signature, expiry, issuer and type.

        Raises:
            InvalidToken: on any verification failure. The message deliberately
                does not distinguish "expired" from "bad signature".
        """
        try:
            claims = jwt.decode(
                token,
                settings.jwt_secret,
                algorithms=[settings.jwt_algorithm],
                issuer=settings.app_name,
            )
        except JWTError as exc:
            raise InvalidToken("token is invalid or has expired") from exc
        if claims.get("typ") != expected_type:
            raise InvalidToken(f"expected a {expected_type} token")
        return claims

    @classmethod
    def resolve_token(cls, db: Session, token: str, expected_type: TokenType = "access") -> User:
        """Decode a token and return the live user it names.

        Rejects tokens whose ``ver`` claim is behind the user's current
        ``token_version`` -- that is how logout takes effect.
        """
        claims = cls.decode_token(token, expected_type)
        user = db.get(User, claims["sub"])
        if user is None:
            raise InvalidToken("token names a user that no longer exists")
        if not user.is_active:
            raise AccountInactive("this account has been deactivated")
        if claims.get("ver") != user.token_version:
            raise InvalidToken("token has been superseded; sign in again")
        return user

    # -- lifecycle ----------------------------------------------------------
    @classmethod
    def create_user(
        cls, db: Session, email: str, password: str, role: UserRole = UserRole.USER
    ) -> User:
        """Create a user. The caller is responsible for checking email uniqueness."""
        problems = cls.validate_password_strength(password)
        if problems:
            raise ValueError("password " + "; ".join(problems))
        user = User(
            email=email.strip().lower(),
            password_hash=cls.hash_password(password),
            role=role,
        )
        db.add(user)
        db.flush()
        return user

    @classmethod
    def authenticate(cls, db: Session, email: str, password: str) -> User:
        """Verify credentials, applying lockout.

        A failed attempt against a non-existent account still runs a bcrypt
        comparison against a dummy hash, so response timing does not reveal
        whether the email is registered.

        Raises:
            InvalidCredentials, AccountLocked, AccountInactive
        """
        user = db.query(User).filter(User.email == email.strip().lower()).one_or_none()

        if user is None:
            cls.verify_password(password, _DUMMY_HASH)
            raise InvalidCredentials("invalid email or password")

        now = utcnow()
        if user.locked_until and user.locked_until > now:
            remaining = int((user.locked_until - now).total_seconds())
            raise AccountLocked(f"account locked for another {remaining} seconds")

        if not user.is_active:
            raise AccountInactive("this account has been deactivated")

        if not cls.verify_password(password, user.password_hash):
            user.failed_login_count += 1
            if user.failed_login_count >= settings.login_max_attempts:
                user.locked_until = now + timedelta(seconds=settings.login_lockout_seconds)
                logger.warning("locked account %s after %d failures", user.email, user.failed_login_count)
            db.flush()
            raise InvalidCredentials("invalid email or password")

        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = now
        user.last_activity_at = now
        db.flush()
        return user

    @staticmethod
    def invalidate_tokens(db: Session, user: User) -> None:
        """Bump ``token_version``, invalidating every token already issued."""
        user.token_version += 1
        db.flush()

    @staticmethod
    def touch(db: Session, user: User) -> None:
        """Record activity. Called from the auth dependency on every request."""
        user.last_activity_at = utcnow()
        db.flush()


#: A real bcrypt hash of a random string, compared against when the email is
#: unknown so that the timing of a failed login does not leak account existence.
_DUMMY_HASH = bcrypt.hashpw(b"timing-equalisation-placeholder", bcrypt.gensalt(rounds=12)).decode()
