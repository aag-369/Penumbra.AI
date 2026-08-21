"""Tests for the classical optimisers.

These matter because every claim about QAOA's performance is a claim *relative*
to this module. A benchmark against a broken baseline is worthless, so the
solvers are checked against closed-form results and against brute force.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.optimization.classical_baseline import ClassicalBaseline as CB


@pytest.fixture
def market():
    """A small, well-conditioned three-asset problem."""
    mu = np.array([0.08, 0.05, 0.12])
    cov = np.array([[0.04, 0.006, 0.008], [0.006, 0.02, 0.004], [0.008, 0.004, 0.09]])
    return mu, cov


class TestMeanVariance:
    def test_weights_sum_to_one(self, market):
        mu, cov = market
        result = CB.mean_variance(mu, cov, risk_aversion=2.0)
        assert sum(result.weights) == pytest.approx(1.0, abs=1e-8)
        assert result.converged

    def test_respects_box_bounds(self, market):
        mu, cov = market
        result = CB.mean_variance(mu, cov, risk_aversion=1.0, min_position=0.1, max_position=0.5)
        assert all(0.1 - 1e-8 <= w <= 0.5 + 1e-8 for w in result.weights)

    def test_higher_risk_aversion_lowers_volatility(self, market):
        mu, cov = market
        timid = CB.mean_variance(mu, cov, risk_aversion=50.0)
        bold = CB.mean_variance(mu, cov, risk_aversion=0.1)
        timid_vol = CB.portfolio_stats(timid.weights, mu, cov)["volatility"]
        bold_vol = CB.portfolio_stats(bold.weights, mu, cov)["volatility"]
        assert timid_vol < bold_vol

    def test_zero_risk_aversion_concentrates_in_the_best_asset(self, market):
        mu, cov = market
        result = CB.mean_variance(mu, cov, risk_aversion=0.0)
        assert int(np.argmax(result.weights)) == int(np.argmax(mu))

    def test_uncorrelated_equal_assets_give_equal_weights(self):
        """A case with a known answer: identical means, identical variances,
        no correlation, so the optimum is equal weighting."""
        n = 4
        result = CB.mean_variance(np.full(n, 0.07), np.eye(n) * 0.04, risk_aversion=1.0)
        assert result.weights == pytest.approx([1 / n] * n, abs=1e-6)

    def test_rejects_mismatched_covariance(self, market):
        mu, _ = market
        with pytest.raises(ValueError, match="covariance must be"):
            CB.mean_variance(mu, np.eye(2))

    def test_rejects_infeasible_position_cap(self, market):
        """Three assets capped at 20% each cannot reach a total of 100%."""
        mu, cov = market
        with pytest.raises(ValueError, match="cannot reach a total of 1.0"):
            CB.mean_variance(mu, cov, max_position=0.2)


class TestMaxSharpe:
    def test_weights_sum_to_one(self, market):
        mu, cov = market
        assert sum(CB.max_sharpe(mu, cov).weights) == pytest.approx(1.0, abs=1e-8)

    def test_beats_equal_weight_on_sharpe(self, market):
        mu, cov = market
        tangency = CB.max_sharpe(mu, cov)
        equal = [1 / 3] * 3
        assert CB.sharpe_ratio(tangency.weights, mu, cov) >= CB.sharpe_ratio(equal, mu, cov)


class TestSimulatedAnnealing:
    @pytest.fixture
    def problem(self):
        rng = np.random.default_rng(2)
        matrix = rng.normal(0, 1, (10, 10))
        return (matrix + matrix.T) / 2

    def test_finds_the_exact_optimum_on_a_small_instance(self, problem):
        bits, energy, _ = CB.simulated_annealing(problem, n_sweeps=600, seed=0)
        exact_bits, exact_energy = CB.exhaustive(problem)
        assert energy == pytest.approx(exact_energy, abs=1e-9)
        assert np.array_equal(bits, exact_bits)

    def test_is_reproducible_with_a_seed(self, problem):
        first = CB.simulated_annealing(problem, n_sweeps=200, seed=42)[0]
        second = CB.simulated_annealing(problem, n_sweeps=200, seed=42)[0]
        assert np.array_equal(first, second)

    def test_cardinality_constraint_is_preserved_exactly(self, problem):
        """Swap moves keep the Hamming weight fixed, mirroring the XY-mixer."""
        for k in (0, 1, 4, 10):
            bits, _, _ = CB.simulated_annealing(problem, n_sweeps=100, target_cardinality=k, seed=1)
            assert int(bits.sum()) == k

    def test_rejects_impossible_cardinality(self, problem):
        with pytest.raises(ValueError, match="between 0 and n"):
            CB.simulated_annealing(problem, target_cardinality=99)

    def test_scales_the_temperature_to_the_problem(self):
        """The same problem in different units must give the same solution."""
        rng = np.random.default_rng(5)
        matrix = rng.normal(0, 1, (8, 8))
        matrix = (matrix + matrix.T) / 2
        small, _, _ = CB.simulated_annealing(matrix * 1e-6, n_sweeps=400, seed=3)
        large, _, _ = CB.simulated_annealing(matrix * 1e6, n_sweeps=400, seed=3)
        assert np.array_equal(small, large)

    def test_reports_runtime(self, problem):
        assert CB.simulated_annealing(problem, n_sweeps=50, seed=0)[2] >= 0


class TestExhaustive:
    def test_matches_a_hand_computed_optimum(self):
        """Q = [[-1, 0], [0, 2]] is minimised by x = (1, 0) with value -1."""
        bits, energy = CB.exhaustive(np.array([[-1.0, 0.0], [0.0, 2.0]]))
        assert list(bits) == [1, 0]
        assert energy == pytest.approx(-1.0)

    def test_refuses_an_intractable_size(self):
        with pytest.raises(ValueError, match="2\\^30"):
            CB.exhaustive(np.zeros((30, 30)))


class TestMetrics:
    def test_sharpe_matches_the_definition(self, market):
        mu, cov = market
        weights = np.array([0.4, 0.35, 0.25])
        expected = (weights @ mu - 0.02) / np.sqrt(weights @ cov @ weights)
        assert CB.sharpe_ratio(weights, mu, cov) == pytest.approx(float(expected))

    def test_zero_variance_portfolio_does_not_divide_by_zero(self):
        assert CB.sharpe_ratio([1.0], [0.05], [[0.0]]) == 0.0

    def test_herfindahl_bounds(self, market):
        mu, cov = market
        concentrated = CB.portfolio_stats([1.0, 0.0, 0.0], mu, cov)
        spread = CB.portfolio_stats([1 / 3] * 3, mu, cov)
        assert concentrated["herfindahl"] == pytest.approx(1.0)
        assert spread["herfindahl"] == pytest.approx(1 / 3)
        assert spread["n_effective_holdings"] == pytest.approx(3.0)

    def test_stats_are_internally_consistent(self, market):
        mu, cov = market
        weights = [0.5, 0.3, 0.2]
        stats = CB.portfolio_stats(weights, mu, cov)
        assert stats["expected_return"] == pytest.approx(float(np.dot(weights, mu)))
        assert stats["sharpe_ratio"] == pytest.approx(
            (stats["expected_return"] - 0.02) / stats["volatility"]
        )


class TestQuboProblem:
    def test_objective_and_decode_agree_with_the_mapping(self):
        from app.optimization.qubo_builder import QuboProblem, QUBOBuilder

        builder = QUBOBuilder(n_assets=2, n_bits_per_asset=2)
        problem = QuboProblem(
            coefficients={(0, 0): -1.0, (0, 3): 0.5, (3, 3): -2.0},
            offset=1.0,
            n_qubits=4,
            n_assets=2,
            n_bits_per_asset=2,
            asset_mapping=builder.build_asset_mapping(),
            tickers=("AAPL", "MSFT"),
        )
        # x = (1, 0, 0, 1): -1*1 + 0.5*1*1 + -2*1 = -2.5, plus offset 1.0
        assert problem.objective([1, 0, 0, 1]) == pytest.approx(-1.5)
        assert problem.decode([1, 0, 0, 1]) == {"AAPL": 0.5, "MSFT": 0.25}

    def test_objective_rejects_a_wrong_length_bitstring(self):
        from app.optimization.qubo_builder import QuboProblem, QUBOBuilder

        problem = QuboProblem({}, 0.0, 4, 2, 2, QUBOBuilder(2, 2).build_asset_mapping())
        with pytest.raises(ValueError, match="expected 4 bits"):
            problem.objective([1, 0])

    def test_asset_mapping_indices_do_not_collide(self):
        from app.optimization.qubo_builder import QUBOBuilder

        mapping = QUBOBuilder(n_assets=5, n_bits_per_asset=3).build_asset_mapping()
        assert len(mapping) == 15
        assert sorted(mapping) == list(range(15))

    def test_density_of_a_diagonal_problem(self):
        from app.optimization.qubo_builder import QuboProblem, QUBOBuilder

        problem = QuboProblem(
            {(i, i): 1.0 for i in range(4)}, 0.0, 4, 2, 2, QUBOBuilder(2, 2).build_asset_mapping()
        )
        assert problem.density == pytest.approx(4 / 10)
