"""Execution-Simulation Agent -- solves, re-maps, and prices the trades.

Phase 2/4. Not implemented.

Responsibilities, in order:

1. Obfuscate the QUBO (:mod:`app.optimization.qubo_obfuscator`).
2. Solve the obfuscated instance (:mod:`app.optimization.qaoa_solver`).
3. Recover the true allocation from the obfuscated solution.
4. Simulate execution: slippage, market impact, commission, timeline.
5. Encrypt the final recommendation under the user's public key.

Step 5 is the one that is easy to get wrong. The recommendation must be
encrypted with the *user's* public engine before it is written to the job row,
or the server ends up storing plaintext advice that reveals the allocation and,
combined with the ticker list, most of the portfolio. There is a test in
``tests/integration`` reserved for exactly this.
"""

from __future__ import annotations

from typing import Any, Sequence

from ..crypto.ckks_engine import CKKSEngine
from ..optimization.qaoa_solver import QAOASolver
from ..optimization.qubo_obfuscator import QUBOObfuscator


class ExecutionAgent:
    """Runs the optimiser and turns its output into a priced trade plan."""

    def __init__(
        self, engine: CKKSEngine, solver: QAOASolver, obfuscator: QUBOObfuscator
    ) -> None:
        self.engine = engine
        self.solver = solver
        self.obfuscator = obfuscator

    async def optimize(
        self, qubo: dict[tuple[int, int], float], asset_mapping: dict[int, Any], *, obfuscate: bool = True
    ) -> dict[str, Any]:
        """Obfuscate, solve, and de-obfuscate.

        Returns ``{"weights": [...], "solution_bits": [...], "metadata": {...}}``
        where metadata carries circuit depth, iteration count, approximation
        ratio against the classical baseline, and reconstruction fidelity.
        """
        raise NotImplementedError("Phase 4: Execution Agent")

    async def simulate_execution(
        self,
        target_weights: Sequence[float],
        current_holdings_ciphertext: str,
        prices: Sequence[float],
        tickers: Sequence[str],
    ) -> dict[str, Any]:
        """Price the rebalancing trades.

        The trade *sizes* depend on current holdings, which are encrypted, so
        the deltas are computed homomorphically and returned encrypted. Slippage
        and commission models are public functions of trade size, and applying
        them to an encrypted size means they must be linear or polynomial --
        a square-root market-impact model cannot be evaluated under CKKS without
        a polynomial approximation. Note which approximation you use and its
        error bound; do not quietly linearise.
        """
        raise NotImplementedError("Phase 4: Execution Agent")

    async def generate_recommendation(
        self, optimization: dict[str, Any], execution_plan: dict[str, Any], goals: dict[str, Any]
    ) -> str:
        """Write the natural-language recommendation.

        Must be encrypted under the user's public key before it is persisted.
        """
        raise NotImplementedError("Phase 4: Execution Agent")
