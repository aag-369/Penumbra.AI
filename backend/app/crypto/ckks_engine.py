"""CKKS homomorphic-encryption engine.

This is the trust boundary of PENUMBRA. Everything above it (agents, QUBO,
QAOA) is supposed to run without ever seeing plaintext holdings; this module is
what makes that claim mean something.

Two modes
---------
``CKKSEngine`` exists in exactly one of two modes, and the mode is a property of
the object, not a convention:

* **private** -- holds the secret key. Only ever constructed *on the client*.
  Can encrypt and decrypt.
* **public**  -- holds evaluation keys but no secret key. This is what runs on
  the server. Can encrypt (CKKS is public-key) and can evaluate, but
  :meth:`decrypt` raises :class:`SecretKeyUnavailable`. There is no code path
  that turns a public engine into a private one.

That asymmetry is enforced by :meth:`decrypt` checking ``is_private`` on every
call, and is covered by tests in ``tests/unit/test_ckks_engine.py``.

Deviation from the original spec
--------------------------------
The spec's ``POST /portfolio/generate-keypair`` had the *server* generate the
keypair and then asserted the private key "is generated client-side, never
transmitted". Both cannot be true. Here, key generation happens only in
:meth:`CKKSEngine.create_client`, which the server never calls for a user; the
server only ever receives the output of :meth:`export_public_context`.
See ``docs/SPEC_DEVIATIONS.md`` #1.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Final, Iterable, Sequence

import tenseal as ts

from .security_utils import SealError, b64d, b64e, fingerprint, random_token, seal, unseal

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Security parameters
# ---------------------------------------------------------------------------

#: Maximum total coefficient-modulus bit-length for a given ring dimension, per
#: the Homomorphic Encryption Security Standard (HomomorphicEncryption.org,
#: 2018), Table 1, classical security, ternary secret distribution.
#: Exceeding these values silently destroys the security of the scheme -- SEAL
#: will happily let you do it, which is why we check.
SECURITY_TABLE: Final[dict[int, dict[int, int]]] = {
    128: {1024: 27, 2048: 54, 4096: 109, 8192: 218, 16384: 438, 32768: 881},
    192: {1024: 19, 2048: 37, 4096: 75, 8192: 152, 16384: 305, 32768: 611},
    256: {1024: 14, 2048: 29, 4096: 58, 8192: 118, 16384: 237, 32768: 476},
}

VALID_POLY_DEGREES: Final[tuple[int, ...]] = (1024, 2048, 4096, 8192, 16384, 32768)


class CryptoError(Exception):
    """Base class for every failure raised by the crypto layer."""


class InsecureParameters(CryptoError):
    """Raised when requested CKKS parameters do not meet the target security level."""


class SecretKeyUnavailable(CryptoError):
    """Raised when a decrypt is attempted on a server-side (public) engine."""


class CiphertextError(CryptoError):
    """Raised when a ciphertext is malformed, or does not belong to this context."""


class KeyMismatch(CiphertextError):
    """Raised when a ciphertext was produced under a different key.

    This exists because SEAL does not detect the case. Decrypting a ciphertext
    with the wrong secret key of the *same* parameters does not fail -- it
    returns numbers, typically of order 1e31, which a caller could mistake for
    data. The envelope described in :data:`CIPHERTEXT_PREFIX` turns that silent
    corruption into this exception.
    """


@dataclass(frozen=True)
class CKKSParameters:
    """Validated CKKS parameter set.

    Attributes:
        poly_modulus_degree: ring dimension N. Must be a power of two in
            :data:`VALID_POLY_DEGREES`. Larger N = more security and more
            multiplicative depth, but quadratically slower operations and
            larger ciphertexts.
        coeff_mod_bit_sizes: bit-lengths of the primes in the modulus chain.
            The first and last are "special" primes used for the initial and
            final levels; the middle ones each permit one rescale, so the
            usable multiplicative depth is ``len(coeff_mod_bit_sizes) - 2``.
        global_scale_bits: log2 of the CKKS scale. Should match the middle
            prime sizes; mismatches cause precision loss or overflow.
        security_level: target bits of classical security (128, 192 or 256).
        generate_galois_keys: whether to generate rotation keys. Required by
            *every* reduction -- ``sum``, ``dot``, ``matmul`` -- because they
            are implemented as rotate-and-add. Without them only elementwise
            operations work. These keys dominate the size of the public
            context: 6 MB at N=4096, 35 MB at N=8192, 180 MB at N=16384,
            against 0.4/1.9/7.9 MB without. That measurement is why the public
            context lives in a keystore on disk rather than in a database
            column -- see :mod:`app.services.keystore_service`.
    """

    poly_modulus_degree: int = 8192
    coeff_mod_bit_sizes: tuple[int, ...] = (60, 40, 40, 60)
    global_scale_bits: int = 40
    security_level: int = 128
    generate_galois_keys: bool = True

    def __post_init__(self) -> None:
        self.validate()

    # -- validation ---------------------------------------------------------
    def validate(self) -> None:
        """Raise :class:`InsecureParameters` if this parameter set is unsafe."""
        if self.poly_modulus_degree not in VALID_POLY_DEGREES:
            raise InsecureParameters(
                f"poly_modulus_degree must be one of {VALID_POLY_DEGREES}, "
                f"got {self.poly_modulus_degree}"
            )
        if self.security_level not in SECURITY_TABLE:
            raise InsecureParameters(
                f"security_level must be one of {sorted(SECURITY_TABLE)}, got {self.security_level}"
            )
        if len(self.coeff_mod_bit_sizes) < 3:
            raise InsecureParameters(
                "coeff_mod_bit_sizes needs at least 3 primes to support one multiplication"
            )
        total = sum(self.coeff_mod_bit_sizes)
        budget = SECURITY_TABLE[self.security_level][self.poly_modulus_degree]
        if total > budget:
            raise InsecureParameters(
                f"total coefficient modulus {total} bits exceeds the {budget}-bit budget for "
                f"N={self.poly_modulus_degree} at {self.security_level}-bit security. "
                f"Either raise poly_modulus_degree or shorten the modulus chain."
            )
        if not (20 <= self.global_scale_bits <= 60):
            raise InsecureParameters("global_scale_bits should be in [20, 60]")
        middle = self.coeff_mod_bit_sizes[1:-1]
        if middle and abs(self.global_scale_bits - middle[0]) > 10:
            logger.warning(
                "global_scale_bits=%d is far from the middle prime size %d; "
                "expect precision loss after rescaling",
                self.global_scale_bits,
                middle[0],
            )

    @property
    def multiplicative_depth(self) -> int:
        """How many ciphertext-ciphertext multiplications this chain supports."""
        return len(self.coeff_mod_bit_sizes) - 2

    @property
    def slot_count(self) -> int:
        """Number of float slots a single ciphertext can pack (N/2 for CKKS)."""
        return self.poly_modulus_degree // 2

    @property
    def modulus_budget_used(self) -> tuple[int, int]:
        """``(used_bits, allowed_bits)`` for the configured security level."""
        return sum(self.coeff_mod_bit_sizes), SECURITY_TABLE[self.security_level][
            self.poly_modulus_degree
        ]

    def describe(self) -> dict[str, object]:
        used, allowed = self.modulus_budget_used
        return {
            "poly_modulus_degree": self.poly_modulus_degree,
            "coeff_mod_bit_sizes": list(self.coeff_mod_bit_sizes),
            "global_scale_bits": self.global_scale_bits,
            "security_level_bits": self.security_level,
            "multiplicative_depth": self.multiplicative_depth,
            "slot_count": self.slot_count,
            "modulus_bits_used": used,
            "modulus_bits_allowed": allowed,
            "galois_keys": self.generate_galois_keys,
        }


#: Default profile. Depth 2 covers the Phase-1 pipeline: portfolio value,
#: expected return, and the ``w^T Sigma w`` quadratic form. Public context is
#: ~35 MB because rotation keys are on, which they must be for any reduction.
DEFAULT_PARAMETERS: Final[CKKSParameters] = CKKSParameters()

#: Elementwise-only profile. No rotation keys, so the public context is ~1.9 MB
#: instead of 35 MB -- but ``dot``, ``sum`` and ``matmul`` will raise
#: :class:`~.homomorphic_ops.RotationKeysMissing`. Use this when the server only
#: needs to scale and combine ciphertexts and the client performs the final
#: reduction after decryption, which costs nothing in privacy because the client
#: already knows its own data.
LIGHT_PARAMETERS: Final[CKKSParameters] = CKKSParameters(generate_galois_keys=False)

#: Deep profile for encrypted covariance work in Phase 2. N=16384 buys the
#: modulus budget for a depth-4 chain at 128-bit security. Costs ~180 MB of
#: rotation keys and ~1.4 s of key generation; do not make this the default.
DEEP_PARAMETERS: Final[CKKSParameters] = CKKSParameters(
    poly_modulus_degree=16384,
    coeff_mod_bit_sizes=(60, 40, 40, 40, 40, 60),
    global_scale_bits=40,
    generate_galois_keys=True,
)


# ---------------------------------------------------------------------------
# Key identity
# ---------------------------------------------------------------------------

#: Exported contexts are wrapped as ``{"v": 1, "key_id": "...", "ctx": "<b64>"}``.
#:
#: A key needs a stable identifier, and the obvious candidate -- a hash of the
#: serialised public context -- does not work. TenSEAL drops the public and
#: evaluation keys when it serialises a secret-key context and regenerates them
#: on load, and that regeneration is randomised. So a client that backs up its
#: key and restores it gets a *different* public context blob for the same
#: secret key, and any content-derived identifier changes underneath it.
#:
#: The fix is the one JWK uses: mint an explicit ``kid`` at key generation and
#: carry it alongside the material. It is an identifier, not a secret and not a
#: commitment -- a client could put any string here, and the only party harmed
#: by lying would be that client.
KEY_BUNDLE_VERSION: Final[int] = 1
KEY_ID_BYTES: Final[int] = 8


def _wrap_context(context_bytes: bytes, key_id: str) -> str:
    return json.dumps(
        {"v": KEY_BUNDLE_VERSION, "key_id": key_id, "ctx": b64e(context_bytes)},
        separators=(",", ":"),
    )


def _unwrap_context(blob: str) -> tuple[str | None, bytes]:
    """Split an export envelope into ``(key_id, context_bytes)``.

    A bare base64 blob -- no envelope -- returns ``(None, bytes)``. The caller
    then derives an identifier by hashing, which is stable for a public context
    because nothing about it is regenerated on load.
    """
    stripped = blob.strip()
    if not stripped.startswith("{"):
        try:
            return None, b64d(stripped)
        except Exception as exc:
            raise CryptoError("context blob is neither a key bundle nor valid base64") from exc
    try:
        parsed = json.loads(stripped)
        version = int(parsed["v"])
        if version != KEY_BUNDLE_VERSION:
            raise CryptoError(f"unsupported key bundle version {version}")
        return str(parsed["key_id"]), b64d(parsed["ctx"])
    except CryptoError:
        raise
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise CryptoError("malformed key bundle") from exc


# ---------------------------------------------------------------------------
# Ciphertext envelope
# ---------------------------------------------------------------------------

#: Ciphertexts are wrapped as ``pnb1.<key fingerprint>.<base64 body>``.
#:
#: The reason is a SEAL behaviour that is easy to miss: decrypting a ciphertext
#: with the wrong secret key does not raise, provided the parameters match. It
#: returns plausible-looking floats of order 1e31. A user who restores the wrong
#: key backup would see numbers rather than an error, and a portfolio stored
#: under a rotated key would silently produce nonsense advice.
#:
#: Tagging each ciphertext with its key's fingerprint costs 24 characters
#: against a ~440 kB body and turns that failure mode into :class:`KeyMismatch`.
#: The fingerprint is a hash of the *public* context, so it reveals nothing.
CIPHERTEXT_PREFIX: Final[str] = "pnb1"
_ENVELOPE_PARTS: Final[int] = 3


def wrap_ciphertext(body_b64: str, key_fingerprint: str) -> str:
    """Attach a key fingerprint to a serialised ciphertext."""
    return f"{CIPHERTEXT_PREFIX}.{key_fingerprint}.{body_b64}"


def unwrap_ciphertext(ciphertext: str) -> tuple[str | None, str]:
    """Split an envelope into ``(fingerprint, body)``.

    A bare base64 string -- no envelope -- returns ``(None, ciphertext)`` so
    that ciphertexts produced before the envelope existed, or by a third-party
    CKKS client that does not know about it, still load. The fingerprint check
    is then skipped rather than failing closed, which is the right trade-off for
    a format tag: it is an integrity aid, not a security boundary.
    """
    if not ciphertext.startswith(f"{CIPHERTEXT_PREFIX}."):
        return None, ciphertext
    parts = ciphertext.split(".", _ENVELOPE_PARTS - 1)
    if len(parts) != _ENVELOPE_PARTS:
        raise CiphertextError("ciphertext envelope is malformed")
    return parts[1], parts[2]


@dataclass(frozen=True)
class ContextInfo:
    """Parameters read back out of a *deserialised* context.

    When a client uploads a public context, the server must not take the
    client's word for what parameters it used -- it has to read them off the
    context itself. This is what :meth:`CKKSEngine.inspect_context` recovers,
    and what :mod:`app.services.keystore_service` runs the security check
    against.

    Note that ``coeff_mod_bit_sizes`` is deliberately absent: SEAL exposes the
    modulus chain only as unregistered ``seal::Modulus`` objects through
    TenSEAL's bindings, so the individual prime sizes cannot be recovered.
    ``total_coeff_modulus_bits`` and ``multiplicative_depth`` are both readable
    and are together sufficient for every check we need.
    """

    poly_modulus_degree: int
    total_coeff_modulus_bits: int
    multiplicative_depth: int
    global_scale_bits: int
    has_galois_keys: bool
    has_relin_keys: bool
    has_secret_key: bool

    @property
    def slot_count(self) -> int:
        return self.poly_modulus_degree // 2

    def security_level(self) -> int:
        """Highest standard security level these parameters actually satisfy.

        Returns 0 when the modulus budget is exceeded even at 128 bits, which
        means the parameters are outside the standard and must be refused.
        """
        for level in (256, 192, 128):
            budget = SECURITY_TABLE[level].get(self.poly_modulus_degree)
            if budget is not None and self.total_coeff_modulus_bits <= budget:
                return level
        return 0

    def assert_secure(self, minimum_bits: int = 128) -> None:
        """Raise :class:`InsecureParameters` if below ``minimum_bits``."""
        achieved = self.security_level()
        if achieved < minimum_bits:
            budget = SECURITY_TABLE[minimum_bits].get(self.poly_modulus_degree, 0)
            raise InsecureParameters(
                f"context uses {self.total_coeff_modulus_bits} modulus bits at "
                f"N={self.poly_modulus_degree}, which allows at most {budget} bits for "
                f"{minimum_bits}-bit security (achieved: "
                f"{achieved or 'below 128'} bits). Refusing the key."
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "poly_modulus_degree": self.poly_modulus_degree,
            "total_coeff_modulus_bits": self.total_coeff_modulus_bits,
            "multiplicative_depth": self.multiplicative_depth,
            "global_scale_bits": self.global_scale_bits,
            "slot_count": self.slot_count,
            "has_galois_keys": self.has_galois_keys,
            "has_relin_keys": self.has_relin_keys,
            "security_level_bits": self.security_level(),
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class CKKSEngine:
    """Owns a TenSEAL CKKS context and the encrypt/decrypt operations on it.

    Do not call the constructor directly; use one of the three classmethods,
    which make the client/server split explicit at the call site:

    * :meth:`create_client` -- generate fresh keys (client only)
    * :meth:`from_private_context` -- restore a client engine from a backup
    * :meth:`from_public_context` -- build the server-side engine
    """

    def __init__(self, context: ts.Context, params: CKKSParameters, key_id: str) -> None:
        self._ctx = context
        self._params = params
        self._key_id = key_id

    # -- construction -------------------------------------------------------
    @classmethod
    def create_client(cls, params: CKKSParameters | None = None) -> "CKKSEngine":
        """Generate a fresh keypair and return a *private* engine.

        This is the only place in the codebase where secret-key material comes
        into existence. In production it runs in the browser (node-seal); this
        Python implementation is the reference used by tests, the CLI, and any
        server-side self-test that operates on synthetic data.
        """
        params = params or DEFAULT_PARAMETERS
        params.validate()
        ctx = ts.context(
            ts.SCHEME_TYPE.CKKS,
            poly_modulus_degree=params.poly_modulus_degree,
            coeff_mod_bit_sizes=list(params.coeff_mod_bit_sizes),
        )
        ctx.global_scale = 2 ** params.global_scale_bits
        ctx.generate_relin_keys()
        if params.generate_galois_keys:
            ctx.generate_galois_keys()
        logger.info(
            "generated CKKS keypair: N=%d depth=%d slots=%d",
            params.poly_modulus_degree,
            params.multiplicative_depth,
            params.slot_count,
        )
        return cls(ctx, params, key_id=random_token(KEY_ID_BYTES)[:16])

    @classmethod
    def from_private_context(cls, context_b64: str, params: CKKSParameters | None = None) -> "CKKSEngine":
        """Rebuild a private engine from an exported secret-key context."""
        key_id, raw = _unwrap_context(context_b64)
        ctx = cls._deserialize(raw)
        if not ctx.is_private():
            raise CryptoError("blob does not contain a secret key; use from_public_context")
        return cls(ctx, params or DEFAULT_PARAMETERS, key_id=key_id or fingerprint(raw))

    @classmethod
    def from_public_context(cls, context_b64: str, params: CKKSParameters | None = None) -> "CKKSEngine":
        """Build the server-side engine from a client-supplied public context.

        Raises:
            CryptoError: if the blob contains a secret key. A client that
                uploads its secret key has made a catastrophic mistake, and the
                server refuses the material rather than storing it.
        """
        key_id, raw = _unwrap_context(context_b64)
        ctx = cls._deserialize(raw)
        if ctx.is_private():
            raise CryptoError(
                "refusing public context that contains a secret key -- "
                "the client must serialise with save_secret_key=False"
            )
        # A bare public context has no declared id, but hashing it is stable:
        # unlike a secret-key context, nothing in it is regenerated on load.
        return cls(ctx, params or DEFAULT_PARAMETERS, key_id=key_id or fingerprint(raw))

    @staticmethod
    def _deserialize(raw: bytes) -> ts.Context:
        try:
            return ts.context_from(raw)
        except Exception as exc:
            raise CryptoError("could not deserialise CKKS context") from exc

    # -- properties ---------------------------------------------------------
    @property
    def is_private(self) -> bool:
        """True if this engine holds a secret key and can therefore decrypt."""
        return self._ctx.is_private()

    @property
    def parameters(self) -> CKKSParameters:
        return self._params

    @property
    def context(self) -> ts.Context:
        """Raw TenSEAL context. For use by :mod:`.homomorphic_ops` only."""
        return self._ctx

    @property
    def key_id(self) -> str:
        """Stable identifier for this keypair. Safe to log; reveals nothing."""
        return self._key_id

    @property
    def public_fingerprint(self) -> str:
        """Alias for :attr:`key_id`, kept for readability at call sites."""
        return self._key_id

    def inspect_context(self) -> ContextInfo:
        """Read the real parameters back off the context.

        Used on key registration so the server validates what the client
        actually sent rather than what it declared.
        """
        ctx = self._ctx
        seal_ctx = ctx.seal_context().data
        key_data = seal_ctx.key_context_data()
        first_data = seal_ctx.first_context_data()
        scale = float(ctx.global_scale)
        return ContextInfo(
            poly_modulus_degree=key_data.parms().poly_modulus_degree(),
            total_coeff_modulus_bits=key_data.total_coeff_modulus_bit_count(),
            multiplicative_depth=first_data.chain_index(),
            global_scale_bits=max(0, round(scale).bit_length() - 1),
            has_galois_keys=ctx.has_galois_keys(),
            has_relin_keys=ctx.has_relin_keys(),
            has_secret_key=ctx.is_private(),
        )

    # -- export -------------------------------------------------------------
    def export_public_context(self) -> str:
        """Serialise the evaluation context *without* the secret key.

        This is the only key material that ever travels to the server.
        """
        return _wrap_context(self._ctx.serialize(save_secret_key=False), self._key_id)

    def export_private_context(self) -> str:
        """Serialise the full context including the secret key. Client only.

        Never send the result of this anywhere. Use :meth:`export_sealed_private_context`
        if it has to touch disk or browser storage.
        """
        if not self.is_private:
            raise SecretKeyUnavailable("this engine has no secret key to export")
        return _wrap_context(self._ctx.serialize(save_secret_key=True), self._key_id)

    def export_sealed_private_context(self, passphrase: str) -> str:
        """Passphrase-seal the secret-key context for at-rest storage."""
        return seal(self.export_private_context().encode("utf-8"), passphrase)

    @classmethod
    def from_sealed_private_context(
        cls, sealed: str, passphrase: str, params: CKKSParameters | None = None
    ) -> "CKKSEngine":
        """Open a sealed secret-key context. Raises :class:`SealError` on a bad passphrase."""
        return cls.from_private_context(unseal(sealed, passphrase).decode("utf-8"), params)

    # -- core operations ----------------------------------------------------
    def encrypt(self, plaintext: Sequence[float]) -> str:
        """Encrypt a vector of floats into a base64 CKKS ciphertext.

        CKKS is a public-key scheme, so this works on both private and public
        engines -- the server can encrypt its own public market data into the
        same context in order to combine it with user ciphertexts.

        Args:
            plaintext: values to encrypt. Length must not exceed
                :attr:`CKKSParameters.slot_count`.
        """
        values = self._coerce(plaintext)
        if len(values) > self._params.slot_count:
            raise CiphertextError(
                f"cannot pack {len(values)} values into {self._params.slot_count} slots; "
                "split the vector across several ciphertexts"
            )
        vec = ts.ckks_vector(self._ctx, values)
        return self.dump_vector(vec, self.public_fingerprint)

    def decrypt(self, ciphertext_b64: str, size: int | None = None) -> list[float]:
        """Decrypt a ciphertext. **Private engines only.**

        Args:
            ciphertext_b64: output of :meth:`encrypt` or of a homomorphic op.
            size: if given, truncate the result to this many slots. CKKS
                ciphertexts do not always remember the original vector length
                after certain operations.

        Raises:
            SecretKeyUnavailable: if called on a server-side engine. This is the
                guard that backs the privacy claim.
        """
        if not self.is_private:
            raise SecretKeyUnavailable(
                "decrypt() called on a public (server-side) engine -- the secret key "
                "never leaves the client, so this ciphertext cannot be opened here"
            )
        vec = self.load_vector(ciphertext_b64)
        out = [float(x) for x in vec.decrypt()]
        return out[:size] if size is not None else out

    def load_vector(self, ciphertext_b64: str) -> ts.CKKSVector:
        """Deserialise a ciphertext and bind it to this engine's context.

        Raises:
            KeyMismatch: if the envelope names a different key.
            CiphertextError: if the body is malformed or its parameters differ.
        """
        tag, body = unwrap_ciphertext(ciphertext_b64)
        if tag is not None and tag != self.public_fingerprint:
            raise KeyMismatch(
                f"ciphertext was produced under key {tag}, but this engine holds "
                f"{self.public_fingerprint}. Decrypting it would return noise, not data."
            )
        try:
            vec = ts.lazy_ckks_vector_from(b64d(body))
            vec.link_context(self._ctx)
            return vec
        except Exception as exc:
            raise CiphertextError(
                "ciphertext is malformed or was produced under a different context"
            ) from exc

    @staticmethod
    def dump_vector(vec: ts.CKKSVector, key_fingerprint: str | None = None) -> str:
        """Serialise a ciphertext, tagging it with a key fingerprint when given."""
        body = b64e(vec.serialize())
        return wrap_ciphertext(body, key_fingerprint) if key_fingerprint else body

    # -- introspection ------------------------------------------------------
    def ciphertext_size(self, ciphertext_b64: str) -> int:
        """Size in bytes of the raw (pre-base64, pre-envelope) ciphertext."""
        return len(b64d(unwrap_ciphertext(ciphertext_b64)[1]))

    def public_context_size(self) -> int:
        """Size in bytes of the serialised public context, excluding the envelope."""
        return len(self._ctx.serialize(save_secret_key=False))

    def expansion_factor(self, n_values: int, ciphertext_b64: str) -> float:
        """Ciphertext bytes per plaintext float. Reported on the admin dashboard."""
        if n_values <= 0:
            raise ValueError("n_values must be positive")
        return self.ciphertext_size(ciphertext_b64) / (n_values * 8)

    def describe(self) -> dict[str, object]:
        """Non-sensitive summary of this engine, safe for API responses and logs."""
        return {
            "mode": "private" if self.is_private else "public",
            "key_id": self.key_id,
            **self._params.describe(),
        }

    # -- helpers ------------------------------------------------------------
    @staticmethod
    def _coerce(values: Iterable[float]) -> list[float]:
        try:
            out = [float(v) for v in values]
        except (TypeError, ValueError) as exc:
            raise CiphertextError("plaintext must be an iterable of numbers") from exc
        if not out:
            raise CiphertextError("cannot encrypt an empty vector")
        if any(v != v or v in (float("inf"), float("-inf")) for v in out):
            raise CiphertextError("plaintext contains NaN or infinity")
        return out


__all__ = [
    "CKKSEngine",
    "CKKSParameters",
    "ContextInfo",
    "DEFAULT_PARAMETERS",
    "DEEP_PARAMETERS",
    "LIGHT_PARAMETERS",
    "SECURITY_TABLE",
    "CryptoError",
    "InsecureParameters",
    "SecretKeyUnavailable",
    "CiphertextError",
    "SealError",
]
