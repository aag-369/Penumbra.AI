"""Session establishment and ciphertext authentication.

Read this first
---------------
PENUMBRA's post-quantum security comes from **one** place: CKKS is built on
Ring-LWE, and no known quantum algorithm solves Ring-LWE in polynomial time.
Shor's algorithm breaks the discrete-log and factoring problems behind RSA and
ECC; it does not apply to lattice problems. That is the whole argument, and it
is the argument NIST relied on when standardising ML-KEM and ML-DSA, which rest
on the same family of assumptions.

The BB84 code in this module is a **simulation of a protocol**, not a source of
security. There is no quantum channel here -- photons are Python integers, and
an attacker who can read process memory reads the "quantum" states directly. It
is included because the protocol is worth demonstrating and because the
eavesdropper-detection property is instructive, and it is deliberately
constrained so it cannot be mistaken for real key material:

* :meth:`PostQuantumChannel.establish_session` derives the session MAC key from
  OS randomness, *always*. The BB84 output is mixed in as additional input but
  can never be the sole source.
* If ``use_bb84_simulation`` is off, sessions still work identically.

See ``docs/CRYPTO_ASSUMPTIONS.md`` for the formal threat model, and
``docs/SPEC_DEVIATIONS.md`` #5 for why this was scoped down from the original
"post-quantum secure channel" framing.

What this module actually provides
----------------------------------
1. A session record binding a session id to a user and to the *fingerprint* of
   the CKKS public context they uploaded, so a ciphertext produced under key A
   cannot be replayed into a session established under key B.
2. HMAC-SHA256 authentication of ciphertexts, which gives integrity and origin
   authentication on top of the confidentiality CKKS already provides.
3. Replay protection via monotonic sequence numbers per session.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Final

from .security_utils import (
    b64e,
    constant_time_equals,
    hmac_sha256,
    random_bytes,
    random_token,
)

logger = logging.getLogger(__name__)

SESSION_TTL_SECONDS: Final[int] = 3600
MAC_KEY_BYTES: Final[int] = 32

#: Above this quantum bit-error rate, BB84 assumes the channel is tapped.
#: Intercept-resend on every qubit produces ~25% QBER; the conventional
#: abort threshold sits around 11%, which is where the security proof of
#: Shor-Preskill stops working.
QBER_ABORT_THRESHOLD: Final[float] = 0.11


class ChannelError(Exception):
    """Base class for channel failures."""


class SessionExpired(ChannelError):
    """Raised when a session id is unknown or past its TTL."""


class AuthenticationFailed(ChannelError):
    """Raised when a ciphertext's MAC does not verify, or a sequence number replays."""


class EavesdropperDetected(ChannelError):
    """Raised when the simulated BB84 sift reports a QBER above the abort threshold."""


# ---------------------------------------------------------------------------
# BB84 simulation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BB84Result:
    """Outcome of one simulated BB84 run."""

    sifted_key_bits: tuple[int, ...]
    n_sent: int
    n_sifted: int
    n_tested: int
    qber: float
    aborted: bool

    @property
    def sift_rate(self) -> float:
        """Fraction of sent qubits surviving basis reconciliation (~0.5 in theory)."""
        return self.n_sifted / self.n_sent if self.n_sent else 0.0

    def as_dict(self) -> dict[str, object]:
        return {
            "n_sent": self.n_sent,
            "n_sifted": self.n_sifted,
            "n_tested": self.n_tested,
            "key_bits": len(self.sifted_key_bits),
            "sift_rate": round(self.sift_rate, 4),
            "qber": round(self.qber, 4),
            "qber_threshold": QBER_ABORT_THRESHOLD,
            "aborted": self.aborted,
        }


def simulate_bb84(
    n_qubits: int = 2048,
    *,
    eavesdropper: bool = False,
    test_fraction: float = 0.25,
    channel_noise: float = 0.0,
) -> BB84Result:
    """Run one simulated BB84 key exchange.

    The protocol, in the rectilinear/diagonal encoding:

    1. Alice picks a random bit and a random basis for each qubit.
    2. If Eve is present she measures in a random basis and resends what she
       measured. When her basis differs from Alice's -- half the time -- the
       state she forwards is uncorrelated with Alice's bit.
    3. Bob picks a random basis and measures. When his basis matches whoever
       prepared the state he read, he gets that bit; otherwise a coin flip.
    4. Alice and Bob publish their bases and keep positions where they agree
       (the "sift", ~50% of qubits).
    5. They sacrifice a random subset of the sifted bits to estimate the error
       rate. Intercept-resend on every qubit gives QBER ~25%: Eve guesses wrong
       half the time, and when she does Bob is right only half the time, so
       errors appear at 1/2 * 1/2 = 25%.

    Args:
        n_qubits: how many qubits Alice sends.
        eavesdropper: whether to run an intercept-resend attacker.
        test_fraction: share of sifted bits sacrificed for QBER estimation.
        channel_noise: probability of an independent bit flip, modelling a
            real, imperfect channel.

    Returns:
        A :class:`BB84Result`. ``aborted`` is true when the measured QBER
        exceeds :data:`QBER_ABORT_THRESHOLD`.
    """
    if n_qubits < 16:
        raise ValueError("n_qubits must be at least 16 for a meaningful estimate")
    if not 0.0 < test_fraction < 1.0:
        raise ValueError("test_fraction must be in (0, 1)")

    # Lazily refilled CSPRNG buffer. Each qubit consumes 3 bits with no
    # eavesdropper and up to 6 with one, so a fixed-size buffer would be a
    # latent IndexError; refilling keeps the cost of one syscall per block.
    _buf = bytearray()

    def _byte() -> int:
        if not _buf:
            _buf.extend(random_bytes(4096))
        return _buf.pop()

    def bit() -> int:
        return _byte() & 1

    def unit() -> float:
        """Uniform float in [0, 1)."""
        return _byte() / 256.0

    alice_bits, alice_bases, bob_bases, bob_bits = [], [], [], []
    for _ in range(n_qubits):
        a_bit, a_basis, b_basis = bit(), bit(), bit()
        carried_bit, carried_basis = a_bit, a_basis

        if eavesdropper:
            e_basis = bit()
            if e_basis == a_basis:
                e_bit = a_bit           # right basis: Eve learns the bit exactly
            else:
                e_bit = bit()           # wrong basis: outcome is random
            carried_bit, carried_basis = e_bit, e_basis  # Eve resends in her basis

        if b_basis == carried_basis:
            b_bit = carried_bit
        else:
            b_bit = bit()

        if channel_noise > 0 and unit() < channel_noise:
            b_bit ^= 1

        alice_bits.append(a_bit)
        alice_bases.append(a_basis)
        bob_bases.append(b_basis)
        bob_bits.append(b_bit)

    sifted = [
        (alice_bits[i], bob_bits[i])
        for i in range(n_qubits)
        if alice_bases[i] == bob_bases[i]
    ]
    n_sifted = len(sifted)
    n_test = max(1, int(n_sifted * test_fraction))
    test, keep = sifted[:n_test], sifted[n_test:]

    errors = sum(1 for a, b in test if a != b)
    qber = errors / n_test if n_test else 0.0
    aborted = qber > QBER_ABORT_THRESHOLD

    key_bits: tuple[int, ...] = () if aborted else tuple(a for a, _ in keep)
    result = BB84Result(key_bits, n_qubits, n_sifted, n_test, qber, aborted)
    logger.info("BB84 simulation: %s", result.as_dict())
    return result


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


@dataclass
class Session:
    """An authenticated session between one client key and the server."""

    session_id: str
    user_id: str
    key_fingerprint: str
    mac_key: bytes = field(repr=False)
    created_at: float
    ttl_seconds: int = SESSION_TTL_SECONDS
    last_sequence: int = -1
    bb84: BB84Result | None = None

    @property
    def expired(self) -> bool:
        return time.time() > self.created_at + self.ttl_seconds

    def public_view(self) -> dict[str, object]:
        """Everything about this session that is safe to return to a client."""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "key_fingerprint": self.key_fingerprint,
            "created_at": int(self.created_at),
            "expires_at": int(self.created_at + self.ttl_seconds),
            "bb84": self.bb84.as_dict() if self.bb84 else None,
        }


class PostQuantumChannel:
    """Manages sessions and authenticates ciphertexts.

    Args:
        use_bb84_simulation: run the BB84 demonstration on session setup and
            attach its statistics to the session record. Never the sole source
            of the MAC key.
        session_ttl: seconds before a session must be re-established.

    Note:
        Sessions live in a process-local dict. A multi-worker deployment needs
        Redis or a database table behind the same interface; the methods are
        written so that swapping the store is a localised change.
    """

    def __init__(
        self, *, use_bb84_simulation: bool = False, session_ttl: int = SESSION_TTL_SECONDS
    ) -> None:
        self.use_bb84_simulation = use_bb84_simulation
        self.session_ttl = session_ttl
        self._sessions: dict[str, Session] = {}

    # -- lifecycle ----------------------------------------------------------
    def establish_session(
        self, user_id: str, key_fingerprint: str, *, bb84_qubits: int = 2048
    ) -> dict[str, object]:
        """Open a session bound to a specific client key.

        Args:
            user_id: the authenticated user.
            key_fingerprint: the ``key_id`` of the client's registered CKKS
                context. Taken as given rather than derived here: hashing the
                context blob would produce an identifier that disagrees with the
                one the keystore recorded, since a context is not byte-stable
                across a secret-key round-trip. See ``CKKSEngine.key_id``.
            bb84_qubits: size of the simulated exchange, when enabled.

        Returns:
            The session's public view, including the MAC key the client needs
            in order to authenticate its ciphertexts. That key travels inside
            the TLS tunnel; it authenticates, it does not encrypt.

        Raises:
            EavesdropperDetected: if the BB84 simulation aborts.
        """
        mac_key = random_bytes(MAC_KEY_BYTES)

        bb84: BB84Result | None = None
        if self.use_bb84_simulation:
            bb84 = simulate_bb84(bb84_qubits)
            if bb84.aborted:
                raise EavesdropperDetected(
                    f"simulated QBER {bb84.qber:.3f} exceeds the {QBER_ABORT_THRESHOLD} "
                    "abort threshold; refusing to establish the session"
                )
            # Mix the sifted bits into the MAC key. XOR with OS randomness means
            # the result is no weaker than the OS randomness alone even if the
            # simulated bits were fully predictable -- which they are.
            packed = _pack_bits(bb84.sifted_key_bits, MAC_KEY_BYTES)
            mac_key = bytes(a ^ b for a, b in zip(mac_key, packed))

        session = Session(
            session_id=random_token(24),
            user_id=user_id,
            key_fingerprint=key_fingerprint,
            mac_key=mac_key,
            created_at=time.time(),
            ttl_seconds=self.session_ttl,
            bb84=bb84,
        )
        self._sessions[session.session_id] = session
        logger.info(
            "session %s established for user %s (key %s)",
            session.session_id, user_id, session.key_fingerprint,
        )
        return {**session.public_view(), "mac_key": b64e(mac_key)}

    def get_session(self, session_id: str) -> Session:
        """Fetch a live session. Raises :class:`SessionExpired` if unusable."""
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionExpired(f"unknown session {session_id!r}")
        if session.expired:
            self._sessions.pop(session_id, None)
            raise SessionExpired(f"session {session_id!r} expired; re-establish it")
        return session

    def close_session(self, session_id: str) -> None:
        """Drop a session. Idempotent."""
        self._sessions.pop(session_id, None)

    def purge_expired(self) -> int:
        """Remove expired sessions. Returns how many were dropped."""
        dead = [sid for sid, s in self._sessions.items() if s.expired]
        for sid in dead:
            del self._sessions[sid]
        return len(dead)

    # -- authentication -----------------------------------------------------
    def sign_ciphertext(self, ciphertext_b64: str, session_id: str, sequence: int) -> str:
        """Produce the MAC a client would attach to a ciphertext.

        Present on the server so tests and the reference client agree byte for
        byte on what gets signed.
        """
        session = self.get_session(session_id)
        return hmac_sha256(session.mac_key, _mac_message(ciphertext_b64, session_id, sequence))

    def verify_ciphertext_authenticity(
        self, ciphertext_b64: str, session_id: str, signature: str, sequence: int
    ) -> bool:
        """Verify a ciphertext's MAC and consume its sequence number.

        The MAC covers the ciphertext, the session id and the sequence number,
        so a valid ciphertext cannot be lifted from one session into another,
        and cannot be replayed within its own session.

        Raises:
            AuthenticationFailed: on a bad MAC or a non-increasing sequence.
            SessionExpired: if the session is gone.
        """
        session = self.get_session(session_id)
        if sequence <= session.last_sequence:
            raise AuthenticationFailed(
                f"sequence {sequence} replays or reorders "
                f"(last accepted {session.last_sequence})"
            )
        expected = hmac_sha256(
            session.mac_key, _mac_message(ciphertext_b64, session_id, sequence)
        )
        if not constant_time_equals(expected, signature):
            raise AuthenticationFailed("ciphertext MAC did not verify")
        session.last_sequence = sequence
        return True

    # -- introspection ------------------------------------------------------
    @property
    def active_sessions(self) -> int:
        return sum(1 for s in self._sessions.values() if not s.expired)

    def describe(self) -> dict[str, object]:
        return {
            "bb84_simulation_enabled": self.use_bb84_simulation,
            "session_ttl_seconds": self.session_ttl,
            "active_sessions": self.active_sessions,
            "security_basis": "Ring-LWE (CKKS); BB84 here is a protocol demo, not a key source",
        }


def _mac_message(ciphertext_b64: str, session_id: str, sequence: int) -> bytes:
    """Canonical byte encoding of what a ciphertext MAC covers.

    Length-prefixed so that no two distinct triples can produce the same
    message -- concatenating the fields directly would let a crafted session id
    absorb part of the ciphertext.
    """
    parts = [ciphertext_b64.encode("ascii"), session_id.encode("ascii"), str(sequence).encode("ascii")]
    out = bytearray()
    for part in parts:
        out += len(part).to_bytes(8, "big") + part
    return bytes(out)


def _pack_bits(bits: tuple[int, ...], n_bytes: int) -> bytes:
    """Pack a bit tuple into exactly ``n_bytes`` bytes, zero-padding if short."""
    out = bytearray(n_bytes)
    for i, b in enumerate(bits[: n_bytes * 8]):
        if b:
            out[i // 8] |= 1 << (i % 8)
    return bytes(out)


__all__ = [
    "PostQuantumChannel",
    "Session",
    "BB84Result",
    "simulate_bb84",
    "ChannelError",
    "SessionExpired",
    "AuthenticationFailed",
    "EavesdropperDetected",
    "QBER_ABORT_THRESHOLD",
]
