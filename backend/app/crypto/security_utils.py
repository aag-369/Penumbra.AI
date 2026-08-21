"""Cryptographic primitives used around the FHE layer.

Nothing in this module is homomorphic. It provides the *classical* crypto
plumbing PENUMBRA needs: CSPRNG helpers, passphrase-based key derivation for
sealing a CKKS secret-key context at rest, AES-GCM sealing/unsealing, and
constant-time comparisons.

Design notes
------------
* All randomness comes from :mod:`secrets` (OS CSPRNG). ``random`` is never
  used for anything security-relevant.
* Passphrase -> key derivation uses scrypt with parameters chosen for
  interactive use (RFC 7914 "interactive" profile, N=2**15).
* Sealing uses AES-256-GCM, which gives confidentiality *and* integrity, so a
  tampered blob fails to open rather than decrypting to garbage.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from typing import Final

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# --- scrypt parameters -------------------------------------------------------
# N must be a power of two. r=8, p=1 is the standard pairing.
SCRYPT_N: Final[int] = 2 ** 15
SCRYPT_R: Final[int] = 8
SCRYPT_P: Final[int] = 1
SCRYPT_DKLEN: Final[int] = 32  # 256-bit key for AES-256-GCM
SALT_BYTES: Final[int] = 16
NONCE_BYTES: Final[int] = 12  # 96-bit nonce, the GCM-recommended size

SEAL_VERSION: Final[int] = 1


class SealError(Exception):
    """Raised when a sealed blob cannot be opened (wrong passphrase or tampering)."""


def random_bytes(n: int) -> bytes:
    """Return ``n`` cryptographically secure random bytes."""
    if n <= 0:
        raise ValueError("n must be positive")
    return secrets.token_bytes(n)


def random_token(n_bytes: int = 32) -> str:
    """Return a URL-safe random token, e.g. for session identifiers."""
    return secrets.token_urlsafe(n_bytes)


def b64e(data: bytes) -> str:
    """Base64-encode bytes to an ASCII string."""
    return base64.b64encode(data).decode("ascii")


def b64d(data: str) -> bytes:
    """Base64-decode an ASCII string to bytes."""
    return base64.b64decode(data.encode("ascii"))


def derive_key(passphrase: str, salt: bytes, dklen: int = SCRYPT_DKLEN) -> bytes:
    """Derive a symmetric key from a passphrase using scrypt.

    Args:
        passphrase: user-supplied secret. Never stored.
        salt: per-blob random salt, stored alongside the ciphertext.
        dklen: derived key length in bytes.
    """
    if not passphrase:
        raise ValueError("passphrase must not be empty")
    return hashlib.scrypt(
        passphrase.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=dklen,
        maxmem=SCRYPT_N * SCRYPT_R * 128 * 2,
    )


@dataclass(frozen=True)
class SealedBlob:
    """A passphrase-sealed payload plus the parameters needed to reopen it."""

    version: int
    salt_b64: str
    nonce_b64: str
    ciphertext_b64: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "version": self.version,
                "salt": self.salt_b64,
                "nonce": self.nonce_b64,
                "ct": self.ciphertext_b64,
            },
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, blob: str) -> "SealedBlob":
        try:
            raw = json.loads(blob)
            return cls(
                version=int(raw["version"]),
                salt_b64=raw["salt"],
                nonce_b64=raw["nonce"],
                ciphertext_b64=raw["ct"],
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise SealError("malformed sealed blob") from exc


def seal(plaintext: bytes, passphrase: str) -> str:
    """Encrypt ``plaintext`` under a passphrase. Returns a JSON envelope.

    Used to protect a CKKS *secret-key* context before it is written to
    browser storage or to a backup file. The server never calls this on user
    key material -- it exists so the same format can be produced and verified
    in tests and by the CLI.
    """
    salt = random_bytes(SALT_BYTES)
    nonce = random_bytes(NONCE_BYTES)
    key = derive_key(passphrase, salt)
    ct = AESGCM(key).encrypt(nonce, plaintext, None)
    return SealedBlob(SEAL_VERSION, b64e(salt), b64e(nonce), b64e(ct)).to_json()


def unseal(blob: str, passphrase: str) -> bytes:
    """Reverse :func:`seal`. Raises :class:`SealError` on wrong passphrase."""
    sealed = SealedBlob.from_json(blob)
    if sealed.version != SEAL_VERSION:
        raise SealError(f"unsupported seal version {sealed.version}")
    key = derive_key(passphrase, b64d(sealed.salt_b64))
    try:
        return AESGCM(key).decrypt(b64d(sealed.nonce_b64), b64d(sealed.ciphertext_b64), None)
    except Exception as exc:  # InvalidTag and friends
        raise SealError("could not open sealed blob: wrong passphrase or tampered data") from exc


def hmac_sha256(key: bytes, message: bytes) -> str:
    """Return a hex HMAC-SHA256 tag."""
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    """Compare two strings without leaking length-prefix timing information."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def fingerprint(data: bytes, length: int = 16) -> str:
    """Short, stable, non-reversible identifier for a blob (e.g. a public context).

    Used in audit logs so an operator can tell *which* key was used without the
    log itself carrying key material.
    """
    return hashlib.sha256(data).hexdigest()[:length]
