"""Risk Agent -- risk metrics and QUBO formulation.

Phase 2. Not implemented.

Design decision the implementer must respect
--------------------------------------------
Expected returns and the covariance matrix are estimated from **public market
history**, not from the user's holdings. They are therefore plaintext, and
computing them under encryption would protect nothing -- the inputs are already
public. What stays encrypted is the *weights*: which assets the user holds and
in what proportion.

This is not a weakening of the original design. The spec proposed a
homomorphic covariance over encrypted returns, and
:meth:`~app.crypto.homomorphic_ops.HomomorphicOps.encrypted_covariance_from_returns`
implements exactly that and is tested. It is the right tool when return series
are themselves private -- a fund's proprietary factor returns, say. For a retail
portfolio of listed equities the return series are on Yahoo Finance. See
``docs/SPEC_DEVIATIONS.md`` #3.

The pieces this agent needs already exist and are tested:
:meth:`~app.crypto.homomorphic_ops.HomomorphicOps.expected_return`,
:meth:`~app.crypto.homomorphic_ops.HomomorphicOps.portfolio_variance` and
:meth:`~app.crypto.homomorphic_ops.HomomorphicOps.mean_variance_objective`
all evaluate the Markowitz objective on encrypted weights at depth 2.
"""

from __future__ import annotations

from typing import Any, Sequence

from ..crypto.ckks_engine import CKKSEngine
from ..crypto.homomorphic_ops import HomomorphicOps
from ..optimization.qubo_builder import QUBOBuilder


class RiskAgent:
    """Computes risk metrics and hands a QUBO to the Execution Agent."""

    def __init__(self, engine: CKKSEngine, ops: HomomorphicOps, qubo_builder: QUBOBuilder) -> None:
        self.engine = engine
        self.ops = ops
        self.qubo_builder = qubo_builder

    async def estimate_market_parameters(
        self, tickers: Sequence[str], lookback_days: int = 756
    ) -> tuple[list[float], list[list[float]]]:
        """Estimate mean returns and covariance from public price history.

        Returns:
            ``(mean_returns, covariance)``, both plaintext.

        Implementation notes: use a shrinkage estimator (Ledoit-Wolf) rather
        than the sample covariance -- with 756 daily observations and more than
        ~30 assets the sample estimate is badly conditioned, and the optimiser
        will happily exploit its spurious eigenvalues.
        """
        raise NotImplementedError("Phase 2: Risk Agent")

    async def compute_encrypted_risk_metrics(
        self,
        holdings_ciphertext: str,
        mean_returns: Sequence[float],
        covariance: Sequence[Sequence[float]],
        risk_aversion: float,
    ) -> dict[str, str]:
        """Evaluate the current portfolio's risk under encryption.

        Returns a dict of ciphertexts: ``expected_return``, ``variance``,
        ``objective``. Every value is encrypted under the user's key.

        The underlying homomorphic operations are implemented and tested; this
        method is the thin orchestration over them.
        """
        raise NotImplementedError("Phase 2: Risk Agent")

    async def formulate_qubo(
        self,
        mean_returns: Sequence[float],
        covariance: Sequence[Sequence[float]],
        constraints: dict[str, Any],
    ) -> dict[str, Any]:
        """Build the QUBO for the optimiser.

        Returns ``{"qubo": {(i, j): coeff}, "asset_mapping": {...}, "n_qubits": int}``.
        """
        raise NotImplementedError("Phase 2: Risk Agent")
