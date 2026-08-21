"""Storage and validation of client CKKS public contexts.

This is the gate that enforces the central privacy property. Every public
context arriving from a client passes through :meth:`KeystoreService.register`,
which:

1. Deserialises it and **refuses it if it contains a secret key**. A client
   that exports with ``save_secret_key=True`` by mistake gets a 400 and an
   audit row, not silent storage of the one secret that matters.
2. Checks the parameters against the Homomorphic Encryption Security Standard
   table, so a client cannot downgrade itself to an insecure modulus chain.
3. Writes the blob to the keystore directory, keyed by fingerprint, and records
   only a path plus metadata in the database.

Storage note: the keystore is a directory here. In production it should be
object storage with server-side encryption; the interface is deliberately small
so that swap is a single class.
"""

from __future__ import annotations

import functools
import logging
from pathlib import Path

from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..config import settings
from ..crypto.ckks_engine import (
    CKKSEngine,
    ContextInfo,
    CryptoError,
    InsecureParameters,
)
from ..models.encryption_key import EncryptionKey

logger = logging.getLogger(__name__)


class KeystoreError(Exception):
    """Base class for keystore failures."""


class SecretKeyRejected(KeystoreError):
    """The uploaded context contained a secret key. Refused and audited."""


class ContextTooLarge(KeystoreError):
    """The uploaded context exceeds ``settings.max_public_context_bytes``."""


class KeyNotFound(KeystoreError):
    """No active key for this user, or the blob is missing from disk."""


class KeystoreService:
    """Persists public contexts outside the database."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or settings.keystore_dir)
        self.root.mkdir(parents=True, exist_ok=True)

    # -- registration -------------------------------------------------------
    def register(
        self,
        db: Session,
        user_id: str,
        public_context_b64: str,
        *,
        label: str | None = None,
        deactivate_previous: bool = True,
    ) -> EncryptionKey:
        """Validate and store a client public context.

        Args:
            public_context_b64: output of the client's
                ``export_public_context()``. Must not contain a secret key.
            deactivate_previous: mark the user's other keys inactive. Portfolios
                stay bound to the key they were encrypted under, so old keys are
                deactivated rather than deleted.

        Raises:
            SecretKeyRejected: the blob carried a secret key.
            ContextTooLarge: the blob is over the configured limit.
            InsecureParameters: the parameters fail the security-standard check.
            KeystoreError: the blob is not a valid CKKS context.
        """
        size = len(public_context_b64.encode("ascii"))
        if size > settings.max_public_context_bytes:
            raise ContextTooLarge(
                f"public context is {size / 1e6:.1f} MB, limit is "
                f"{settings.max_public_context_bytes / 1e6:.0f} MB"
            )

        try:
            engine = CKKSEngine.from_public_context(public_context_b64)
        except CryptoError as exc:
            if "secret key" in str(exc):
                raise SecretKeyRejected(
                    "the uploaded context contains a secret key. The server refuses to "
                    "store it. Re-export with save_secret_key=False and rotate this key."
                ) from exc
            raise KeystoreError(f"not a valid CKKS public context: {exc}") from exc

        info = engine.inspect_context()
        # Validate what the client *sent*, not what it claimed. A downgraded
        # modulus chain would leave every ciphertext under this key breakable.
        info.assert_secure(minimum_bits=128)
        fingerprint = engine.public_fingerprint

        existing = (
            db.query(EncryptionKey)
            .filter(EncryptionKey.user_id == user_id, EncryptionKey.fingerprint == fingerprint)
            .one_or_none()
        )
        if existing is not None:
            existing.is_active = True
            db.flush()
            logger.info("re-activated existing key %s for user %s", fingerprint, user_id)
            return existing

        if deactivate_previous:
            db.query(EncryptionKey).filter(
                EncryptionKey.user_id == user_id, EncryptionKey.is_active.is_(True)
            ).update({"is_active": False}, synchronize_session=False)

        rel_path = f"{user_id}/{fingerprint}.ctx"
        dest = self.root / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(public_context_b64, encoding="ascii")

        record = EncryptionKey(
            user_id=user_id,
            fingerprint=fingerprint,
            context_path=rel_path,
            context_bytes=size,
            poly_modulus_degree=info.poly_modulus_degree,
            total_coeff_modulus_bits=info.total_coeff_modulus_bits,
            global_scale_bits=info.global_scale_bits,
            security_level_bits=info.security_level(),
            has_galois_keys=info.has_galois_keys,
            multiplicative_depth=info.multiplicative_depth,
            slot_count=info.slot_count,
            label=label,
        )
        db.add(record)
        db.flush()
        logger.info(
            "registered key %s for user %s (%.1f MB, N=%d, %d-bit security, galois=%s)",
            fingerprint, user_id, size / 1e6, info.poly_modulus_degree,
            info.security_level(), info.has_galois_keys,
        )
        return record

    # -- retrieval ----------------------------------------------------------
    def active_key(self, db: Session, user_id: str) -> EncryptionKey:
        """The user's current key record. Raises :class:`KeyNotFound` if absent."""
        key = (
            db.query(EncryptionKey)
            .filter(EncryptionKey.user_id == user_id, EncryptionKey.is_active.is_(True))
            .order_by(desc(EncryptionKey.created_at))
            .first()
        )
        if key is None:
            raise KeyNotFound(
                "no active encryption key for this user; generate one in the browser "
                "and register its public context first"
            )
        return key

    def load_context_b64(self, key: EncryptionKey) -> str:
        """Read a stored public context off disk."""
        path = self.root / key.context_path
        if not path.exists():
            raise KeyNotFound(f"keystore blob missing for fingerprint {key.fingerprint}")
        return path.read_text(encoding="ascii")

    def engine_for(self, db: Session, user_id: str) -> CKKSEngine:
        """Build the server-side (public) engine for a user's active key."""
        return CKKSEngine.from_public_context(self.load_context_b64(self.active_key(db, user_id)))

    def engine_for_key(self, key: EncryptionKey) -> CKKSEngine:
        """Build the server-side engine for a specific key record."""
        return CKKSEngine.from_public_context(self.load_context_b64(key))

    # -- revocation ---------------------------------------------------------
    def revoke(self, db: Session, key: EncryptionKey, *, delete_blob: bool = False) -> None:
        """Deactivate a key, optionally removing its blob from disk.

        Portfolios encrypted under a revoked key become undecryptable by the
        pipeline, so ``delete_blob`` defaults to False.
        """
        key.is_active = False
        db.flush()
        if delete_blob:
            path = self.root / key.context_path
            path.unlink(missing_ok=True)
        logger.info("revoked key %s (blob deleted=%s)", key.fingerprint, delete_blob)

    def usage_stats(self, db: Session) -> dict[str, object]:
        """Aggregate keystore statistics for the admin dashboard."""
        keys = db.query(EncryptionKey).all()
        total_bytes = sum(k.context_bytes for k in keys)
        active = [k for k in keys if k.is_active]
        return {
            "total_keys": len(keys),
            "active_keys": len(active),
            "total_bytes": total_bytes,
            "total_megabytes": round(total_bytes / 1e6, 2),
            "mean_key_megabytes": round(total_bytes / len(keys) / 1e6, 2) if keys else 0.0,
            "with_galois_keys": sum(1 for k in keys if k.has_galois_keys),
        }

    # -- helpers ------------------------------------------------------------
    @staticmethod
    def inspect(public_context_b64: str) -> ContextInfo:
        """Read a context's real parameters without storing it.

        Exposed so the client can dry-run a key before registering it.
        """
        return CKKSEngine.from_public_context(public_context_b64).inspect_context()


@functools.lru_cache(maxsize=1)
def get_keystore() -> KeystoreService:
    """Process-wide keystore rooted at ``settings.keystore_dir``.

    Cached so the directory is created once. Tests call
    ``get_keystore.cache_clear()`` after pointing ``settings.keystore_dir`` at
    a temporary directory.
    """
    return KeystoreService()
