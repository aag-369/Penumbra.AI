"""Bitstring -> portfolio allocation.

Phase 3. Not implemented.

Two steps that must not be confused:

* :meth:`SolutionMapper.to_weights` decodes bits into raw weights via the QUBO's
  asset mapping. Those weights need not sum to 1 -- the budget constraint was a
  penalty, and QAOA satisfies penalties approximately.
* :meth:`SolutionMapper.normalise` projects onto the feasible set. Do this
  *after* decoding and report the size of the projection: a large correction
  means the penalty weights were mistuned, and silently normalising hides that.
"""

from __future__ import annotations

from typing import Sequence

from .qubo_builder import QuboProblem


class SolutionMapper:
    @staticmethod
    def to_weights(problem: QuboProblem, bits: Sequence[int]) -> dict[str, float]:
        """Decode a bitstring into raw per-ticker weights."""
        raise NotImplementedError("Phase 3: solution mapper")

    @staticmethod
    def normalise(
        weights: dict[str, float], *, min_position: float = 0.0, max_position: float = 1.0
    ) -> tuple[dict[str, float], float]:
        """Project onto ``sum(w) = 1`` with box bounds.

        Returns ``(projected_weights, correction_magnitude)``. Log the
        correction; do not discard it.
        """
        raise NotImplementedError("Phase 3: solution mapper")
