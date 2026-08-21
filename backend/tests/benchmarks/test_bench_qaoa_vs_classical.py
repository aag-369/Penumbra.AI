"""QAOA against the classical baseline.

Phase 4. The classical half is implemented and runs today; the QAOA half is
stubbed and will raise until :mod:`app.optimization.qaoa_solver` exists.

Written this way on purpose. The harness reports whatever it measures. A
benchmark constructed to produce a favourable number is worse than no benchmark,
and at these problem sizes -- 10 to 30 assets, a mixed-integer quadratic program
that branch-and-bound solves exactly in milliseconds -- shallow QAOA on a
simulator is not expected to win. The defensible contribution of this project is
the privacy architecture. The interesting quantum result is the approximation
ratio as a function of circuit depth and problem size, not a headline claim.

Run with ``pytest tests/benchmarks -m benchmark -s``.
"""

from __future__ import annotations

import statistics

import numpy as np
import pytest

from app.optimization.classical_baseline import ClassicalBaseline


def random_market(n_assets: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """A random but plausible market: positive-definite covariance, sane means."""
    rng = np.random.default_rng(seed)
    factor = rng.normal(0, 1, (n_assets, n_assets))
    covariance = (factor @ factor.T) / (n_assets * 12)
    means = rng.uniform(0.02, 0.14, n_assets)
    return means, covariance


@pytest.mark.benchmark
@pytest.mark.parametrize("n_assets", [5, 10, 20])
def test_classical_baseline_scaling(n_assets: int) -> None:
    """Record how the classical solvers scale. Runs today; no QAOA required."""
    runtimes, sharpes = [], []
    for trial in range(5):
        means, covariance = random_market(n_assets, seed=trial)
        result = ClassicalBaseline.mean_variance(
            means, covariance, risk_aversion=2.0, max_position=0.4
        )
        runtimes.append(result.runtime_ms)
        sharpes.append(ClassicalBaseline.sharpe_ratio(result.weights, means, covariance))

    print(
        f"\n  n={n_assets:<3} mean-variance: {statistics.fmean(runtimes):6.1f} ms  "
        f"Sharpe {statistics.fmean(sharpes):.4f} +/- {statistics.stdev(sharpes):.4f}"
    )
    assert all(r < 1000 for r in runtimes)


@pytest.mark.benchmark
@pytest.mark.parametrize("n_qubits", [10, 14, 18])
def test_annealing_against_exact_optimum(n_qubits: int) -> None:
    """How close does simulated annealing get to the true optimum?

    This is the number QAOA has to beat, and it is a demanding target: on these
    sizes the annealer usually finds the exact optimum.
    """
    gaps = []
    for trial in range(3):
        rng = np.random.default_rng(trial)
        matrix = rng.normal(0, 1, (n_qubits, n_qubits))
        matrix = (matrix + matrix.T) / 2

        _, annealed, runtime_ms = ClassicalBaseline.simulated_annealing(
            matrix, n_sweeps=800, seed=trial
        )
        _, exact = ClassicalBaseline.exhaustive(matrix)
        gaps.append(abs(annealed - exact) / abs(exact) if exact else 0.0)

    print(
        f"\n  n={n_qubits:<3} annealing vs exact: mean relative gap "
        f"{statistics.fmean(gaps):.2e}  ({runtime_ms} ms)"
    )
    assert statistics.fmean(gaps) < 0.05


@pytest.mark.benchmark
@pytest.mark.skip(reason="Phase 4: QAOA solver not implemented")
@pytest.mark.parametrize("layers", [1, 3, 5])
def test_qaoa_approximation_ratio_by_depth(layers: int) -> None:
    """The headline Phase-4 measurement: approximation ratio against ``p``.

    Report it whichever way it comes out. Also record the feasible fraction --
    with a correct Dicke + XY-mixer ansatz it must be 1.0, and anything less
    means the cardinality constraint is not actually being preserved.
    """
    raise NotImplementedError("Phase 4: QAOA solver")
