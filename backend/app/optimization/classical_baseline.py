"""Classical optimisers, for benchmarking QAOA against.

Implemented rather than stubbed, because a benchmark is only meaningful if the
thing being benchmarked against is real. Every number QAOA produces in
``tests/benchmarks`` is compared to output from this module.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Sequence

import numpy as np
from scipy.optimize import minimize

RISK_FREE_RATE = 0.02


@dataclass(frozen=True)
class OptimizationOutcome:
    weights: tuple[float, ...]
    objective: float
    runtime_ms: int
    converged: bool
    method: str


class ClassicalBaseline:
    """Reference solvers. All methods are static; there is no state to carry."""

    # -- continuous ---------------------------------------------------------
    @staticmethod
    def mean_variance(
        mean_returns: Sequence[float],
        covariance: Sequence[Sequence[float]],
        *,
        risk_aversion: float = 1.0,
        min_position: float = 0.0,
        max_position: float = 1.0,
    ) -> OptimizationOutcome:
        """Markowitz mean-variance with a budget constraint and box bounds.

        Maximises ``mu^T w - lambda * w^T Sigma w`` subject to ``sum(w) = 1``.
        The problem is convex when ``Sigma`` is positive semi-definite, so SLSQP
        finds the global optimum; ``converged`` reports whether it did.
        """
        mu = np.asarray(mean_returns, dtype=float)
        sigma = np.asarray(covariance, dtype=float)
        n = mu.size
        if sigma.shape != (n, n):
            raise ValueError(f"covariance must be {n}x{n}, got {sigma.shape}")
        if max_position * n < 1.0:
            raise ValueError(
                f"max_position={max_position} across {n} assets cannot reach a total of 1.0"
            )

        def negative_objective(w: np.ndarray) -> float:
            return -(w @ mu - risk_aversion * (w @ sigma @ w))

        def gradient(w: np.ndarray) -> np.ndarray:
            return -(mu - 2.0 * risk_aversion * (sigma @ w))

        started = time.perf_counter()
        result = minimize(
            negative_objective,
            x0=np.full(n, 1.0 / n),
            jac=gradient,
            method="SLSQP",
            bounds=[(min_position, max_position)] * n,
            constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1.0}],
            options={"maxiter": 500, "ftol": 1e-12},
        )
        elapsed = int((time.perf_counter() - started) * 1000)
        return OptimizationOutcome(
            weights=tuple(float(x) for x in result.x),
            objective=float(-result.fun),
            runtime_ms=elapsed,
            converged=bool(result.success),
            method="mean_variance_slsqp",
        )

    @staticmethod
    def max_sharpe(
        mean_returns: Sequence[float],
        covariance: Sequence[Sequence[float]],
        *,
        risk_free_rate: float = RISK_FREE_RATE,
        max_position: float = 1.0,
    ) -> OptimizationOutcome:
        """Tangency portfolio: maximise the Sharpe ratio subject to ``sum(w) = 1``."""
        mu = np.asarray(mean_returns, dtype=float)
        sigma = np.asarray(covariance, dtype=float)
        n = mu.size

        def negative_sharpe(w: np.ndarray) -> float:
            excess = w @ mu - risk_free_rate
            vol = np.sqrt(max(w @ sigma @ w, 1e-18))
            return -excess / vol

        started = time.perf_counter()
        result = minimize(
            negative_sharpe,
            x0=np.full(n, 1.0 / n),
            method="SLSQP",
            bounds=[(0.0, max_position)] * n,
            constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1.0}],
            options={"maxiter": 500, "ftol": 1e-12},
        )
        elapsed = int((time.perf_counter() - started) * 1000)
        return OptimizationOutcome(
            weights=tuple(float(x) for x in result.x),
            objective=float(-result.fun),
            runtime_ms=elapsed,
            converged=bool(result.success),
            method="max_sharpe_slsqp",
        )

    # -- discrete -----------------------------------------------------------
    @staticmethod
    def simulated_annealing(
        matrix: np.ndarray,
        *,
        n_sweeps: int = 2000,
        initial_temperature: float | None = None,
        target_cardinality: int | None = None,
        seed: int | None = None,
    ) -> tuple[np.ndarray, float, int]:
        """Minimise ``x^T Q x`` over binary ``x`` by simulated annealing.

        This is the fair comparison for QAOA: same discrete problem, same
        cardinality constraint, classical heuristic. When
        ``target_cardinality`` is set the proposal is a *swap* -- turn one bit
        off and another on -- which preserves the constraint exactly, mirroring
        what the Dicke + XY-mixer ansatz does on the quantum side.

        Returns:
            ``(bits, objective, runtime_ms)``.
        """
        rng = np.random.default_rng(seed)
        matrix = np.asarray(matrix, dtype=float)
        n = matrix.shape[0]

        if target_cardinality is not None:
            if not 0 <= target_cardinality <= n:
                raise ValueError("target_cardinality must be between 0 and n")
            x = np.zeros(n, dtype=int)
            x[rng.choice(n, size=target_cardinality, replace=False)] = 1
        else:
            x = rng.integers(0, 2, size=n)

        def energy(state: np.ndarray) -> float:
            return float(state @ matrix @ state)

        current = energy(x)
        best_x, best = x.copy(), current

        # Scale the starting temperature to the coefficient magnitudes, so the
        # schedule works regardless of whether returns are in percent or basis
        # points.
        t0 = initial_temperature or max(float(np.abs(matrix).max()), 1e-9)

        started = time.perf_counter()
        for sweep in range(n_sweeps):
            temperature = t0 * (1.0 - sweep / n_sweeps) + 1e-12
            for _ in range(n):
                candidate = x.copy()
                if target_cardinality is not None:
                    ones = np.flatnonzero(candidate == 1)
                    zeros = np.flatnonzero(candidate == 0)
                    if ones.size == 0 or zeros.size == 0:
                        break
                    candidate[rng.choice(ones)] = 0
                    candidate[rng.choice(zeros)] = 1
                else:
                    candidate[rng.integers(0, n)] ^= 1

                candidate_energy = energy(candidate)
                delta = candidate_energy - current
                if delta <= 0 or rng.random() < np.exp(-delta / temperature):
                    x, current = candidate, candidate_energy
                    if current < best:
                        best_x, best = x.copy(), current

        return best_x, best, int((time.perf_counter() - started) * 1000)

    @staticmethod
    def exhaustive(matrix: np.ndarray, *, max_qubits: int = 22) -> tuple[np.ndarray, float]:
        """Exact minimum by brute force. The ground truth for small instances.

        Refuses above ``max_qubits`` -- 2^22 is already 4 million evaluations.
        """
        matrix = np.asarray(matrix, dtype=float)
        n = matrix.shape[0]
        if n > max_qubits:
            raise ValueError(
                f"exhaustive search over {n} qubits means 2^{n} states; "
                f"raise max_qubits deliberately if you really want this"
            )
        best_x, best = None, np.inf
        for value in range(1 << n):
            x = np.fromiter(((value >> k) & 1 for k in range(n)), dtype=int, count=n)
            energy = float(x @ matrix @ x)
            if energy < best:
                best_x, best = x, energy
        assert best_x is not None
        return best_x, best

    # -- metrics ------------------------------------------------------------
    @staticmethod
    def sharpe_ratio(
        weights: Sequence[float],
        mean_returns: Sequence[float],
        covariance: Sequence[Sequence[float]],
        *,
        risk_free_rate: float = RISK_FREE_RATE,
    ) -> float:
        """Sharpe ratio of an allocation. Returns 0.0 for a zero-variance portfolio."""
        w = np.asarray(weights, dtype=float)
        mu = np.asarray(mean_returns, dtype=float)
        sigma = np.asarray(covariance, dtype=float)
        variance = float(w @ sigma @ w)
        if variance <= 1e-18:
            return 0.0
        return float((w @ mu - risk_free_rate) / np.sqrt(variance))

    @staticmethod
    def portfolio_stats(
        weights: Sequence[float],
        mean_returns: Sequence[float],
        covariance: Sequence[Sequence[float]],
        *,
        risk_free_rate: float = RISK_FREE_RATE,
    ) -> dict[str, float]:
        """Expected return, volatility, Sharpe ratio and concentration."""
        w = np.asarray(weights, dtype=float)
        mu = np.asarray(mean_returns, dtype=float)
        sigma = np.asarray(covariance, dtype=float)
        expected = float(w @ mu)
        volatility = float(np.sqrt(max(w @ sigma @ w, 0.0)))
        return {
            "expected_return": expected,
            "volatility": volatility,
            "sharpe_ratio": ClassicalBaseline.sharpe_ratio(
                w, mu, sigma, risk_free_rate=risk_free_rate
            ),
            # Herfindahl index: 1/n for an equal-weight portfolio, 1.0 for a
            # single holding. A concise concentration-risk measure.
            "herfindahl": float(np.sum(w ** 2)),
            "n_effective_holdings": float(1.0 / np.sum(w ** 2)) if np.any(w) else 0.0,
        }
