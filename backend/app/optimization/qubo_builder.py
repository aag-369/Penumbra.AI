"""Portfolio selection -> QUBO.

Phase 3. Not implemented; the encoding is specified here so that the
implementation is a transcription rather than a design exercise.

The problem
-----------
Maximise ``mu^T w - lambda * w^T Sigma w`` subject to ``sum(w) = 1``, a
cardinality cap, per-position bounds and sector limits. QUBO admits neither
continuous variables nor constraints, so both have to be encoded.

Binarising the weights
----------------------
Each asset gets ``b`` bits with weights ``2^-1, 2^-2, ..., 2^-b`` scaled by a
budget factor, so asset ``i``'s weight is::

    w_i = W * sum_{k=0}^{b-1} 2^-(k+1) * x_{i,b+k}

with ``W`` chosen so the maximum representable total is 1. This costs
``n_assets * b`` qubits. The granularity is ``W * 2^-b``: at ``b = 3`` the
finest distinguishable allocation is 12.5% of ``W``, which is coarse. Raising
``b`` to 5 gives 3.1% granularity but multiplies the qubit count by 5/3, and
simulation cost is exponential in qubits. This trade-off is the practical limit
on portfolio size, not anything about the encryption -- see
``docs/SPEC_DEVIATIONS.md`` #6.

Constraints as penalties
------------------------
Each constraint becomes a squared-violation penalty added to the objective:

* budget:      ``P_b * (sum_i w_i - 1)^2``
* cardinality: ``P_c * (sum_i y_i - K)^2`` with ``y_i`` an indicator that asset
  ``i`` is held. Requires either extra indicator qubits with linking constraints,
  or -- better -- a Dicke-state initialisation plus an XY-mixer in QAOA, which
  enforces the cardinality by construction and removes the penalty entirely.
  :mod:`app.optimization.qaoa_solver` takes the second route.
* bounds:      slack-variable encoding, or clamping through the bit weights.

Penalty magnitudes matter more than they look. Too small and the optimiser
returns infeasible solutions; too large and the objective is swamped, so every
feasible solution looks equally good and QAOA's landscape flattens. The standard
heuristic -- set each penalty just above the largest objective coefficient it
must dominate -- should be implemented in
:meth:`QUBOBuilder.estimate_penalty_weights` rather than hard-coded, because the
right value depends on the covariance scale of the specific problem.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np


@dataclass(frozen=True)
class QuboProblem:
    """A QUBO instance plus the mapping back to portfolio space."""

    #: Upper-triangular coefficients, keyed ``(i, j)`` with ``i <= j``.
    coefficients: dict[tuple[int, int], float]
    #: Constant offset. Irrelevant to argmin, needed to compare objective values.
    offset: float
    n_qubits: int
    n_assets: int
    n_bits_per_asset: int
    #: qubit index -> ``{"asset_index", "bit_position", "weight"}``
    asset_mapping: dict[int, dict[str, Any]]
    tickers: tuple[str, ...] = ()

    @property
    def density(self) -> float:
        """Fraction of the upper triangle that is non-zero."""
        total = self.n_qubits * (self.n_qubits + 1) / 2
        return len(self.coefficients) / total if total else 0.0

    def to_matrix(self) -> np.ndarray:
        """Dense symmetric matrix ``M`` with ``x^T M x`` equal to the objective.

        The coefficient dictionary is upper-triangular: ``coefficients[(i, j)]``
        with ``i < j`` is the coefficient of the single term ``x_i x_j``, and the
        objective is ``sum_{i <= j} Q_ij x_i x_j``.

        Symmetrising therefore has to **halve** the off-diagonal entries. Copying
        the value into both triangles instead -- the obvious implementation --
        makes ``x^T M x`` count every coupling twice, which silently doubles the
        weight of the covariance term relative to the returns term and produces
        a portfolio that is far too conservative. The error is invisible without
        a test that computes the objective by hand, which is what
        ``TestQuboProblem`` does.
        """
        matrix = np.zeros((self.n_qubits, self.n_qubits))
        for (i, j), value in self.coefficients.items():
            if i == j:
                matrix[i, i] = value
            else:
                matrix[i, j] = matrix[j, i] = value / 2.0
        return matrix

    def objective(self, bits: Sequence[int]) -> float:
        """Evaluate ``x^T Q x + offset`` for a bitstring."""
        x = np.asarray(bits, dtype=float)
        if x.size != self.n_qubits:
            raise ValueError(f"expected {self.n_qubits} bits, got {x.size}")
        return float(x @ self.to_matrix() @ x) + self.offset

    def decode(self, bits: Sequence[int]) -> dict[str, float]:
        """Turn a bitstring into ``{ticker: weight}``."""
        weights = np.zeros(self.n_assets)
        for qubit, meta in self.asset_mapping.items():
            if bits[qubit]:
                weights[meta["asset_index"]] += meta["weight"]
        names = self.tickers or tuple(f"asset_{i}" for i in range(self.n_assets))
        return {names[i]: float(w) for i, w in enumerate(weights)}


class QUBOBuilder:
    """Builds :class:`QuboProblem` instances. See module docstring for the encoding."""

    def __init__(self, n_assets: int, n_bits_per_asset: int = 3) -> None:
        if n_bits_per_asset < 1:
            raise ValueError("need at least one bit per asset")
        self.n_assets = n_assets
        self.n_bits_per_asset = n_bits_per_asset

    @property
    def n_qubits(self) -> int:
        return self.n_assets * self.n_bits_per_asset

    def build(
        self,
        mean_returns: Sequence[float],
        covariance: Sequence[Sequence[float]],
        constraints: dict[str, Any],
        tickers: Sequence[str] = (),
    ) -> QuboProblem:
        """Construct the QUBO. Not implemented."""
        raise NotImplementedError("Phase 3: QUBO builder")

    def estimate_penalty_weights(
        self, mean_returns: Sequence[float], covariance: Sequence[Sequence[float]]
    ) -> dict[str, float]:
        """Scale penalties to the problem rather than hard-coding them."""
        raise NotImplementedError("Phase 3: QUBO builder")

    def build_asset_mapping(self) -> dict[int, dict[str, Any]]:
        """Qubit index -> asset, bit position and the weight that bit contributes.

        Implemented because it is pure bookkeeping, it is what
        :meth:`QuboProblem.decode` and the obfuscator's de-mapping both depend
        on, and getting the index arithmetic wrong is a silent correctness bug.
        """
        mapping: dict[int, dict[str, Any]] = {}
        for asset in range(self.n_assets):
            for bit in range(self.n_bits_per_asset):
                qubit = asset * self.n_bits_per_asset + bit
                mapping[qubit] = {
                    "asset_index": asset,
                    "bit_position": bit,
                    "weight": 2.0 ** -(bit + 1),
                }
        return mapping
