"""QAOA solver for the portfolio QUBO.

Phase 4. Not implemented.

Ansatz
------
Dicke-state initialisation plus an XY-mixer. The point of that pairing is that
both preserve Hamming weight: the initial state ``|D_n^k>`` is the uniform
superposition of all bitstrings with exactly ``k`` ones, and the XY-mixer
``sum_{i<j} (X_i X_j + Y_i Y_j) / 2`` moves amplitude only between states of
equal weight. So the cardinality constraint is satisfied by *every* state the
circuit can reach, and it never has to appear as a penalty term. That is
strictly better than penalising it: no penalty weight to tune, no infeasible
samples to discard, and a smaller effective search space.

The trade-off is circuit depth. A Dicke state on ``n`` qubits needs O(n*k) gates
to prepare, and a full XY-mixer needs O(n^2) two-qubit gates per layer. At
``p = 3`` layers and 20 qubits that is already deep enough that a real NISQ
device would decohere; on a simulator it is merely slow.

Honest expectations
-------------------
QAOA at shallow depth is not expected to beat a good classical solver on
problems this size. Mean-variance optimisation with a cardinality constraint is
a mixed-integer quadratic program, and for 10-30 assets a branch-and-bound
solver finds the exact optimum in milliseconds. The benchmark in
``tests/benchmarks`` should be written to *report* that honestly rather than to
manufacture a win: the interesting number is the approximation ratio as a
function of ``p`` and problem size, not a headline claim of quantum advantage.
``docs/SPEC_DEVIATIONS.md`` #7.

Backend
-------
PennyLane's ``default.qubit`` is the reference. Simulation cost is exponential
in qubit count: 20 qubits is comfortable, 28 is roughly the practical ceiling on
a laptop, and beyond that a tensor-network or GPU backend is needed. This is why
:attr:`app.config.Settings.max_qubits` defaults to 20.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .qubo_builder import QuboProblem


@dataclass(frozen=True)
class QAOAResult:
    """Outcome of one QAOA run."""

    bits: tuple[int, ...]
    objective: float
    n_qubits: int
    layers: int
    circuit_depth: int
    iterations: int
    shots: int
    runtime_ms: int
    #: Objective over the classical baseline's objective. Below 1.0 = QAOA lost.
    approximation_ratio: float | None = None
    #: Share of samples satisfying the cardinality constraint. Should be 1.0
    #: with a correct Dicke + XY-mixer ansatz; anything less indicates a bug.
    feasible_fraction: float | None = None


class QAOASolver:
    """Variational QAOA over a QUBO."""

    def __init__(
        self, *, layers: int = 3, max_iterations: int = 100, shots: int = 2048, seed: int | None = None
    ) -> None:
        self.layers = layers
        self.max_iterations = max_iterations
        self.shots = shots
        self.seed = seed

    def solve(self, problem: QuboProblem, *, target_cardinality: int | None = None) -> QAOAResult:
        """Run QAOA and return the best sampled bitstring."""
        raise NotImplementedError("Phase 4: QAOA solver")

    def _prepare_dicke_state(self, n_qubits: int, k: int) -> None:
        """Prepare ``|D_n^k>``, the uniform superposition over weight-``k`` strings."""
        raise NotImplementedError("Phase 4: QAOA solver")

    def _cost_layer(self, problem: QuboProblem, gamma: float) -> None:
        """Apply ``exp(-i*gamma*H_C)``: RZ per diagonal term, CNOT-RZ-CNOT per coupling."""
        raise NotImplementedError("Phase 4: QAOA solver")

    def _xy_mixer_layer(self, n_qubits: int, beta: float) -> None:
        """Apply the Hamming-weight-preserving XY mixer."""
        raise NotImplementedError("Phase 4: QAOA solver")

    @staticmethod
    def evaluate(problem: QuboProblem, bits: Sequence[int]) -> float:
        """Objective value of a bitstring. Implemented -- used by the benchmarks."""
        return problem.objective(bits)
