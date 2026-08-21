"""Server-side computation over CKKS ciphertexts.

Every method here runs on the PENUMBRA server using a *public* engine. None of
them can decrypt; if the modulus chain is exhausted or a rotation key is
missing, they raise rather than silently returning noise.

Two things worth understanding before reading the code:

**Depth.** Each multiplication consumes one level of the modulus chain. The
budget is ``CKKSParameters.multiplicative_depth``. A plaintext multiplication
costs one level; a ciphertext-ciphertext multiplication costs one level and
additionally needs relinearisation keys. When the budget runs out, SEAL throws
and we surface :class:`DepthExceeded` with a message that says which operation
ran out and what the budget was.

**Packing.** A CKKS ciphertext holds ``N/2`` float slots -- 4096 at the default
parameters -- and costs ~330 kB regardless of how many of those slots you
actually use. So a whole portfolio goes in *one* ciphertext, indexed by
position, not one ciphertext per ticker. See ``docs/SPEC_DEVIATIONS.md`` #2.

**Approximate arithmetic.** CKKS is approximate by design. Results carry
relative error on the order of 1e-6 at the default scale, growing with depth.
Never compare CKKS outputs for exact equality, and never use them where an
exact integer answer is required (share counts, for instance, should be
rounded on the client after decryption).
"""

from __future__ import annotations

import logging
from typing import Sequence

import numpy as np
import tenseal as ts

from .ckks_engine import CiphertextError, CKKSEngine, CryptoError

logger = logging.getLogger(__name__)


class DepthExceeded(CryptoError):
    """Raised when an operation would exhaust the modulus chain."""


class RotationKeysMissing(CryptoError):
    """Raised when an operation needs Galois (rotation) keys that were not generated."""


class EncryptedVector:
    """A live handle on a ciphertext, for chaining without re-serialising.

    Serialising a CKKS ciphertext costs ~330 kB and a memcpy. Chaining through
    ``EncryptedVector`` keeps the vector in memory across a sequence of
    operations and pays that cost once, at :meth:`dump`.
    """

    __slots__ = ("_vec", "_ops")

    def __init__(self, vec: ts.CKKSVector, ops: "HomomorphicOps") -> None:
        self._vec = vec
        self._ops = ops

    @property
    def raw(self) -> ts.CKKSVector:
        return self._vec

    def dump(self) -> str:
        """Serialise to base64, tagged with the evaluating key's fingerprint."""
        return CKKSEngine.dump_vector(self._vec, self._ops.engine.public_fingerprint)

    def __add__(self, other: "EncryptedVector | Sequence[float] | float") -> "EncryptedVector":
        rhs = other.raw if isinstance(other, EncryptedVector) else other
        return EncryptedVector(self._ops._guard("add", lambda: self._vec + rhs), self._ops)

    def __sub__(self, other: "EncryptedVector | Sequence[float] | float") -> "EncryptedVector":
        rhs = other.raw if isinstance(other, EncryptedVector) else other
        return EncryptedVector(self._ops._guard("sub", lambda: self._vec - rhs), self._ops)

    def __mul__(self, other: "EncryptedVector | Sequence[float] | float") -> "EncryptedVector":
        rhs = other.raw if isinstance(other, EncryptedVector) else other
        label = "mul(ct,ct)" if isinstance(other, EncryptedVector) else "mul(ct,pt)"
        return EncryptedVector(self._ops._guard(label, lambda: self._vec * rhs), self._ops)


class HomomorphicOps:
    """High-level encrypted computation. Constructed with a public engine.

    Args:
        engine: the CKKS engine to evaluate under. Normally a public
            (server-side) engine; a private one also works, which is what the
            tests use so they can check results.
    """

    def __init__(self, engine: CKKSEngine) -> None:
        self.engine = engine

    # -- plumbing -----------------------------------------------------------
    def _guard(self, op: str, fn):
        """Run a SEAL operation, translating library errors into ours."""
        try:
            return fn()
        except Exception as exc:  # SEAL raises bare RuntimeError/ValueError
            msg = str(exc).lower()
            depth = self.engine.parameters.multiplicative_depth
            if "scale" in msg or "modulus" in msg or "parameter" in msg or "level" in msg:
                raise DepthExceeded(
                    f"operation {op!r} exhausted the modulus chain "
                    f"(multiplicative_depth={depth}). Use a longer coeff_mod_bit_sizes "
                    f"chain -- see CKKSParameters -- or restructure the computation. "
                    f"Underlying error: {exc}"
                ) from exc
            if "galois" in msg or "rotation" in msg:
                raise RotationKeysMissing(
                    f"operation {op!r} needs Galois keys; construct the context with "
                    f"CKKSParameters(generate_galois_keys=True). Underlying error: {exc}"
                ) from exc
            raise CiphertextError(f"operation {op!r} failed: {exc}") from exc

    def _dump(self, vec: ts.CKKSVector) -> str:
        """Serialise a result, tagged with this engine's key fingerprint."""
        return CKKSEngine.dump_vector(vec, self.engine.public_fingerprint)

    def load(self, ciphertext_b64: str) -> EncryptedVector:
        """Deserialise a ciphertext into a chainable handle."""
        return EncryptedVector(self.engine.load_vector(ciphertext_b64), self)

    def wrap(self, vec: ts.CKKSVector) -> EncryptedVector:
        return EncryptedVector(vec, self)

    # -- elementary operations ---------------------------------------------
    def encrypted_add(self, ct1: str, ct2: str) -> str:
        """``ct1 + ct2``, elementwise. Free in depth."""
        return (self.load(ct1) + self.load(ct2)).dump()

    def encrypted_subtract(self, ct1: str, ct2: str) -> str:
        """``ct1 - ct2``, elementwise. Used for rebalancing deltas."""
        return (self.load(ct1) - self.load(ct2)).dump()

    def encrypted_add_plain(self, ct: str, addend: Sequence[float] | float) -> str:
        """Add a plaintext vector or scalar to a ciphertext. Free in depth."""
        return (self.load(ct) + addend).dump()

    def encrypted_multiply_by_scalar(self, ct: str, scalar: float) -> str:
        """Multiply every slot by a plaintext scalar. Costs one level."""
        return (self.load(ct) * float(scalar)).dump()

    def encrypted_multiply_plain(self, ct: str, factors: Sequence[float]) -> str:
        """Elementwise multiply by a plaintext vector (e.g. prices). Costs one level."""
        return (self.load(ct) * list(map(float, factors))).dump()

    def encrypted_multiply(self, ct1: str, ct2: str) -> str:
        """Elementwise ciphertext-ciphertext product. Costs one level, needs relin keys."""
        return (self.load(ct1) * self.load(ct2)).dump()

    def encrypted_sum(self, ciphertexts: Sequence[str]) -> str:
        """Sum a list of ciphertexts elementwise. Free in depth."""
        if not ciphertexts:
            raise CiphertextError("encrypted_sum needs at least one ciphertext")
        acc = self.load(ciphertexts[0])
        for ct in ciphertexts[1:]:
            acc = acc + self.load(ct)
        return acc.dump()

    def encrypted_negate(self, ct: str) -> str:
        """Negate every slot. Free in depth."""
        return self.encrypted_multiply_by_scalar(ct, -1.0)

    # -- reductions ---------------------------------------------------------
    def encrypted_sum_slots(self, ct: str) -> str:
        """Sum all slots into slot 0. **Requires Galois keys.**

        This is the rotate-and-add trick: log2(N/2) rotations, each consuming a
        rotation key. It does not consume modulus levels.
        """
        vec = self.engine.load_vector(ct)
        return self._dump(self._guard("sum_slots", vec.sum))

    def encrypted_dot_plain(self, ct: str, weights: Sequence[float]) -> str:
        """Inner product of an encrypted vector with a plaintext vector.

        Returns a ciphertext whose slot 0 holds the scalar result. Costs one
        level and **requires Galois keys**: TenSEAL implements the reduction as
        rotate-and-add even when the right operand is plaintext. If you are
        running under :data:`~.ckks_engine.LIGHT_PARAMETERS`, use
        :meth:`elementwise_for_client_reduction` instead.
        """
        vec = self.engine.load_vector(ct)
        w = [float(x) for x in weights]
        return self._dump(self._guard("dot_plain", lambda: vec.dot(w)))

    def encrypted_dot(self, ct1: str, ct2: str) -> str:
        """Inner product of two encrypted vectors.

        Costs one level and **requires Galois keys** for the reduction step.
        """
        a = self.engine.load_vector(ct1)
        b = self.engine.load_vector(ct2)
        return self._dump(self._guard("dot(ct,ct)", lambda: a.dot(b)))

    def encrypted_matmul_plain(self, ct: str, matrix: Sequence[Sequence[float]]) -> str:
        """Row-vector times plaintext matrix: ``x @ M``. Costs one level.

        Used to form ``w @ Sigma`` on the way to a portfolio variance.
        """
        m = np.asarray(matrix, dtype=float)
        if m.ndim != 2:
            raise CiphertextError("matrix must be 2-dimensional")
        vec = self.engine.load_vector(ct)
        return CKKSEngine.dump_vector(
            self._guard("matmul_plain", lambda: vec.matmul(m.tolist()))
        )

    # -- portfolio-level primitives ----------------------------------------
    def portfolio_value(self, encrypted_holdings: str, prices: Sequence[float]) -> str:
        """Total market value of an encrypted holdings vector at plaintext prices.

        ``value = sum_i holdings_i * price_i``. Prices are public market data,
        so they stay in plaintext; only the holdings are secret. Result lands in
        slot 0. Costs one level and requires Galois keys.
        """
        return self.encrypted_dot_plain(encrypted_holdings, prices)

    def elementwise_for_client_reduction(
        self, encrypted_vector: str, plain_vector: Sequence[float]
    ) -> str:
        """Elementwise product, leaving the summation to the client.

        The rotation keys that a server-side ``dot`` needs cost ~33 MB of the
        ~35 MB public context. When the final consumer of a scalar is the user
        anyway, the server can return the encrypted *vector* of products and let
        the client sum after decrypting. The client learns nothing it did not
        already know -- it owns the plaintext -- and the public context drops to
        ~1.9 MB.

        Costs one level, no Galois keys. This is the reduction path used under
        :data:`~.ckks_engine.LIGHT_PARAMETERS`.
        """
        return self.encrypted_multiply_plain(encrypted_vector, plain_vector)

    def expected_return(self, encrypted_weights: str, mean_returns: Sequence[float]) -> str:
        """``mu^T w`` for encrypted weights and plaintext mean returns. One level."""
        return self.encrypted_dot_plain(encrypted_weights, mean_returns)

    def portfolio_variance(
        self, encrypted_weights: str, covariance: Sequence[Sequence[float]]
    ) -> str:
        """``w^T Sigma w`` for encrypted weights and a plaintext covariance matrix.

        Costs **two** levels: one for ``w @ Sigma`` and one for the
        ciphertext-ciphertext inner product with ``w``. Requires Galois keys for
        the final reduction. At default parameters this exactly exhausts the
        depth-2 budget, so do not chain a further multiplication onto the
        result -- fold any constant factor into ``covariance`` before calling,
        which is what :meth:`mean_variance_objective` does.
        """
        cov = np.asarray(covariance, dtype=float)
        if cov.ndim != 2 or cov.shape[0] != cov.shape[1]:
            raise CiphertextError("covariance must be a square matrix")
        w = self.engine.load_vector(encrypted_weights)
        u = self._guard("matmul_plain", lambda: w.matmul(cov.tolist()))
        w2 = self.engine.load_vector(encrypted_weights)
        return self._dump(self._guard("dot(ct,ct)", lambda: u.dot(w2)))

    def mean_variance_objective(
        self,
        encrypted_weights: str,
        mean_returns: Sequence[float],
        covariance: Sequence[Sequence[float]],
        risk_aversion: float,
    ) -> str:
        """``mu^T w - lambda * w^T Sigma w``, entirely under encryption.

        This is the Markowitz objective evaluated on a candidate allocation
        without the server learning the allocation.

        The risk-aversion coefficient is folded into the plaintext covariance
        matrix *before* the matmul rather than applied as a third multiplication
        afterwards. Doing it the naive way costs depth 3 and blows the default
        depth-2 budget; folding costs nothing, because scaling a plaintext
        operand is free. Depth 2 total, Galois required.
        """
        lam = float(risk_aversion)
        if lam < 0:
            raise CiphertextError("risk_aversion must be non-negative")
        scaled_cov = (-lam) * np.asarray(covariance, dtype=float)
        penalty = self.portfolio_variance(encrypted_weights, scaled_cov)
        ret = self.expected_return(encrypted_weights, mean_returns)
        return self._add_at_matched_level(ret, penalty)

    def _add_at_matched_level(self, ct_a: str, ct_b: str) -> str:
        """Add two ciphertexts that may sit at different levels of the chain."""
        a = self.engine.load_vector(ct_a)
        b = self.engine.load_vector(ct_b)
        return self._dump(self._guard("add(mismatched levels)", lambda: a + b))

    # -- statistics ---------------------------------------------------------
    def encrypted_mean(self, ct: str, n: int) -> str:
        """Mean of the first ``n`` slots, in slot 0. Requires Galois keys. One level."""
        if n <= 0:
            raise CiphertextError("n must be positive")
        summed = self.encrypted_sum_slots(ct)
        return self.encrypted_multiply_by_scalar(summed, 1.0 / n)

    def encrypted_sum_of_squares(self, ct: str) -> str:
        """``sum_i x_i^2`` in slot 0. Costs one level, requires Galois keys."""
        return self.encrypted_dot(ct, ct)

    def encrypted_covariance_from_returns(
        self, encrypted_returns: Sequence[str], n_observations: int
    ) -> list[list[str]]:
        """Covariance matrix over encrypted, already mean-centred return series.

        Each entry of ``encrypted_returns`` is one asset's demeaned return
        series packed into a single ciphertext. Entry ``(i, j)`` of the result
        is ``<r_i, r_j> / (n - 1)``.

        Cost warning: this is ``k(k+1)/2`` ciphertext-ciphertext inner products.
        At 10 assets that is 55 products of ~330 kB ciphertexts, which runs in
        seconds; at 100 assets it is 5050 and takes minutes. The production
        pipeline computes covariance from *public* market history instead and
        keeps only the weights encrypted -- see ``docs/SPEC_DEVIATIONS.md`` #3
        for why that loses nothing.

        Requires Galois keys and one level of depth.
        """
        k = len(encrypted_returns)
        if k == 0:
            raise CiphertextError("need at least one return series")
        if n_observations < 2:
            raise CiphertextError("need at least 2 observations to estimate covariance")
        scale = 1.0 / (n_observations - 1)
        logger.info("encrypted covariance: %d assets -> %d inner products", k, k * (k + 1) // 2)

        matrix: list[list[str | None]] = [[None] * k for _ in range(k)]
        for i in range(k):
            for j in range(i, k):
                prod = self.encrypted_dot(encrypted_returns[i], encrypted_returns[j])
                entry = self.encrypted_multiply_by_scalar(prod, scale)
                matrix[i][j] = entry
                matrix[j][i] = entry  # symmetric; same ciphertext, no recompute
        return matrix  # type: ignore[return-value]

    # -- diagnostics --------------------------------------------------------
    def operation_cost(self, operation: str) -> dict[str, object]:
        """Static cost model for an operation, surfaced on the admin dashboard."""
        costs: dict[str, dict[str, object]] = {
            "add": {"levels": 0, "galois": False},
            "sub": {"levels": 0, "galois": False},
            "multiply_plain": {"levels": 1, "galois": False},
            "multiply_cipher": {"levels": 1, "galois": False, "relin": True},
            "dot_plain": {"levels": 1, "galois": False},
            "dot_cipher": {"levels": 1, "galois": True, "relin": True},
            "matmul_plain": {"levels": 1, "galois": False},
            "sum_slots": {"levels": 0, "galois": True},
            "portfolio_variance": {"levels": 2, "galois": True, "relin": True},
        }
        if operation not in costs:
            raise KeyError(f"unknown operation {operation!r}; known: {sorted(costs)}")
        out = dict(costs[operation])
        out["budget"] = self.engine.parameters.multiplicative_depth
        return out


__all__ = ["HomomorphicOps", "EncryptedVector", "DepthExceeded", "RotationKeysMissing"]
