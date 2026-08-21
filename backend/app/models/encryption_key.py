"""CKKS public-context registry.

What this table holds
---------------------
The *public* half of a user's CKKS context: evaluation keys, relinearisation
keys and, when enabled, rotation keys. That blob lets the server compute on
ciphertexts. It cannot decrypt anything.

What this table does not hold
-----------------------------
The secret key. There is no column for it. :func:`app.services.keystore_service`
rejects any upload whose context reports ``is_private()``, so a client that
misconfigures its export gets an error rather than silently handing over the
one thing that would void the entire privacy claim.

Why the blob is on disk
-----------------------
With rotation keys the context is ~35 MB at N=8192 and ~180 MB at N=16384.
Storing that in a database column makes every query that touches the row pay
for it. The row keeps a path and a fingerprint; the bytes live in
``settings.keystore_dir``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from .base import Timestamped, UUIDPrimaryKey

if TYPE_CHECKING:
    from .user import User


class EncryptionKey(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "encryption_keys"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    #: SHA-256 prefix of the serialised public context. Safe to log; lets an
    #: operator confirm which key a ciphertext belongs to without holding it.
    fingerprint: Mapped[str] = mapped_column(String(64), index=True, nullable=False)

    #: Path, relative to the keystore root, of the serialised public context.
    context_path: Mapped[str] = mapped_column(String(512), nullable=False)
    context_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    # -- parameters, mirrored for querying and for the admin dashboard ------
    poly_modulus_degree: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Sum of the modulus-chain prime bit-lengths. SEAL does not expose the
    #: individual primes through TenSEAL, and the total is what the security
    #: standard actually constrains.
    total_coeff_modulus_bits: Mapped[int] = mapped_column(Integer, nullable=False)
    global_scale_bits: Mapped[int] = mapped_column(Integer, nullable=False)
    security_level_bits: Mapped[int] = mapped_column(Integer, default=128, nullable=False)
    has_galois_keys: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    multiplicative_depth: Mapped[int] = mapped_column(Integer, nullable=False)
    slot_count: Mapped[int] = mapped_column(Integer, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    label: Mapped[str | None] = mapped_column(Text)

    user: Mapped["User"] = relationship(back_populates="encryption_keys")

    def __repr__(self) -> str:
        return (
            f"<EncryptionKey {self.fingerprint} N={self.poly_modulus_degree} "
            f"depth={self.multiplicative_depth} active={self.is_active}>"
        )
