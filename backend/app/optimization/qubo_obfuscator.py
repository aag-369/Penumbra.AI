"""Hiding the QUBO instance from the optimisation backend.

Phase 3. Not implemented -- but read this before implementing it, because the
scheme in the original specification does not work.

Why the specified scheme is a no-op
-----------------------------------
The spec's "digit-wise splitting" reads::

    parts = [randn() * coeff for _ in range(k - 1)]
    parts.append(coeff - sum(parts))
    qubo_obfuscated[(i, j)] = sum(parts)

``sum(parts)`` is ``coeff`` by construction. The coefficient that reaches the
solver is bit-for-bit the original. The decoy loop has the same problem: it adds
``d`` and then immediately adds ``-d``, so the entry is zero. Neither step
changes anything an adversary sees. This is worth stating plainly in the write-up
rather than shipping it and hoping nobody evaluates it.

What actually hides structure
-----------------------------
Three transformations that a solver cannot invert but that preserve the argmin:

1. **Permutation.** Relabel the variables. Hides which qubit is which asset.
   On its own it is weak: the coefficient multiset, the degree sequence and the
   spectrum of ``Q`` are all permutation-invariant, so an adversary who knows
   the problem *family* can still recognise "a 30-asset Markowitz instance" and
   can fingerprint a repeated portfolio across sessions.

2. **Gauge (spin-reversal) transformation.** For a random subset ``S``,
   substitute ``x_i -> 1 - x_i`` for ``i`` in ``S``. This is an exact symmetry:
   the transformed problem has the same optimal value, and the optimum maps back
   by flipping the same bits. It genuinely changes the coefficients, including
   their signs, and it is standard practice on quantum annealers where it is used
   to cancel hardware bias. Composed with a permutation it destroys the degree
   and sign structure that permutation alone leaves intact.

3. **Positive affine rescaling.** ``Q -> a*Q + b`` with ``a > 0`` preserves the
   argmin and hides absolute magnitudes, which would otherwise leak the
   covariance scale and hence the asset class.

What none of this achieves
--------------------------
This is obfuscation, not encryption. There is no hardness assumption behind it,
and an adversary who can query the solver adaptively, or who sees many instances
from the same user, can do considerably better than chance. The honest framing --
and the one to use in the write-up -- is that it raises the cost of casual
inspection by an untrusted optimisation provider, and that the *cryptographic*
guarantee in this system comes from CKKS, not from here. Anything stronger would
need genuine techniques from secure multi-party computation or verifiable
delegation, which is a research problem rather than an implementation task.

``docs/SPEC_DEVIATIONS.md`` #4 records this.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from .qubo_builder import QuboProblem


@dataclass(frozen=True)
class ObfuscationKey:
    """Everything needed to map a solution back. Never leaves the server."""

    permutation: tuple[int, ...]
    inverse_permutation: tuple[int, ...]
    #: Variables that were sign-flipped by the gauge transformation.
    flipped: frozenset[int] = field(default_factory=frozenset)
    scale: float = 1.0
    shift: float = 0.0


class QUBOObfuscator:
    """Applies permutation, gauge and rescaling transformations to a QUBO."""

    def obfuscate(self, problem: QuboProblem) -> tuple[QuboProblem, ObfuscationKey]:
        """Transform a QUBO into an equivalent instance with hidden structure."""
        raise NotImplementedError("Phase 3: QUBO obfuscator")

    def deobfuscate_solution(
        self, bits: Sequence[int], key: ObfuscationKey
    ) -> list[int]:
        """Map a solution of the obfuscated instance back to the original."""
        raise NotImplementedError("Phase 3: QUBO obfuscator")

    def verify_roundtrip(
        self, original: QuboProblem, obfuscated: QuboProblem, key: ObfuscationKey, bits: Sequence[int]
    ) -> float:
        """Reconstruction fidelity: recovered objective over original objective.

        Must be 1.0 to floating-point tolerance for every transformation above,
        since all three are exact symmetries. A value below 1.0 means the
        transformation is wrong, not that it is lossy -- there is nothing here
        that is allowed to lose anything. Assert on it in the tests.
        """
        raise NotImplementedError("Phase 3: QUBO obfuscator")
