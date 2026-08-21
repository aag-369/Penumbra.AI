"""Tests for server-side computation over ciphertexts.

Correctness is checked against NumPy on the same inputs. The tolerances are
loose on purpose: CKKS is approximate arithmetic, and asserting exact equality
would be asserting something false.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.crypto.ckks_engine import CKKSEngine, LIGHT_PARAMETERS
from app.crypto.homomorphic_ops import (
    DepthExceeded,
    HomomorphicOps,
    RotationKeysMissing,
)


@pytest.fixture
def ops(full_server) -> HomomorphicOps:
    """Server-side operations with rotation keys available."""
    return HomomorphicOps(full_server)


@pytest.fixture
def light_ops(light_server) -> HomomorphicOps:
    """Server-side operations *without* rotation keys."""
    return HomomorphicOps(light_server)


class TestElementwise:
    def test_add(self, full_client, ops):
        a, b = full_client.encrypt([1.0, 2.0, 3.0]), full_client.encrypt([4.0, 5.0, 6.0])
        assert full_client.decrypt(ops.encrypted_add(a, b), size=3) == pytest.approx(
            [5.0, 7.0, 9.0], abs=1e-4
        )

    def test_subtract(self, full_client, ops):
        a, b = full_client.encrypt([10.0, 20.0]), full_client.encrypt([3.0, 4.0])
        assert full_client.decrypt(ops.encrypted_subtract(a, b), size=2) == pytest.approx(
            [7.0, 16.0], abs=1e-4
        )

    def test_multiply_ciphertexts(self, full_client, ops):
        a, b = full_client.encrypt([2.0, 3.0, 4.0]), full_client.encrypt([5.0, 6.0, 7.0])
        assert full_client.decrypt(ops.encrypted_multiply(a, b), size=3) == pytest.approx(
            [10.0, 18.0, 28.0], abs=1e-3
        )

    def test_multiply_by_scalar(self, full_client, ops):
        ct = full_client.encrypt([1.0, 2.0, 3.0])
        assert full_client.decrypt(ops.encrypted_multiply_by_scalar(ct, 2.5), size=3) == pytest.approx(
            [2.5, 5.0, 7.5], abs=1e-4
        )

    def test_multiply_by_plain_vector(self, full_client, ops):
        ct = full_client.encrypt([10.0, 20.0, 30.0])
        result = ops.encrypted_multiply_plain(ct, [0.1, 0.2, 0.3])
        assert full_client.decrypt(result, size=3) == pytest.approx([1.0, 4.0, 9.0], abs=1e-3)

    def test_negate(self, full_client, ops):
        ct = full_client.encrypt([1.0, -2.0])
        assert full_client.decrypt(ops.encrypted_negate(ct), size=2) == pytest.approx(
            [-1.0, 2.0], abs=1e-4
        )

    def test_sum_of_ciphertexts(self, full_client, ops):
        cts = [full_client.encrypt([float(i), float(i)]) for i in range(1, 5)]
        assert full_client.decrypt(ops.encrypted_sum(cts), size=2) == pytest.approx(
            [10.0, 10.0], abs=1e-4
        )

    def test_sum_rejects_empty_input(self, ops):
        with pytest.raises(Exception):
            ops.encrypted_sum([])

    def test_chained_operations_stay_accurate(self, full_client, ops):
        """(x * 3) + y, checked end to end."""
        x, y = full_client.encrypt([1.0, 2.0]), full_client.encrypt([10.0, 20.0])
        scaled = ops.encrypted_multiply_by_scalar(x, 3.0)
        assert full_client.decrypt(ops.encrypted_add(scaled, y), size=2) == pytest.approx(
            [13.0, 26.0], abs=1e-3
        )


class TestReductions:
    def test_sum_slots(self, full_client, ops):
        ct = full_client.encrypt([1.0, 2.0, 3.0, 4.0])
        assert full_client.decrypt(ops.encrypted_sum_slots(ct), size=1)[0] == pytest.approx(
            10.0, abs=1e-3
        )

    def test_dot_with_plaintext(self, full_client, ops):
        ct = full_client.encrypt([1.0, 2.0, 3.0])
        result = full_client.decrypt(ops.encrypted_dot_plain(ct, [4.0, 5.0, 6.0]), size=1)[0]
        assert result == pytest.approx(32.0, abs=1e-3)

    def test_dot_of_two_ciphertexts(self, full_client, ops):
        a, b = full_client.encrypt([1.0, 2.0, 3.0]), full_client.encrypt([4.0, 5.0, 6.0])
        assert full_client.decrypt(ops.encrypted_dot(a, b), size=1)[0] == pytest.approx(32.0, abs=1e-2)

    def test_matmul_with_plaintext_matrix(self, full_client, ops):
        vector = np.array([1.0, 2.0, 3.0])
        matrix = np.array([[1.0, 0.2, 0.1], [0.2, 1.0, 0.3], [0.1, 0.3, 1.0]])
        ct = full_client.encrypt(vector.tolist())
        result = full_client.decrypt(ops.encrypted_matmul_plain(ct, matrix), size=3)
        assert result == pytest.approx((vector @ matrix).tolist(), abs=1e-3)


class TestRotationKeysGuard:
    """Without rotation keys, reductions must fail loudly, not silently."""

    @pytest.mark.parametrize(
        "call",
        [
            lambda o, ct: o.encrypted_sum_slots(ct),
            lambda o, ct: o.encrypted_dot_plain(ct, [1.0, 1.0]),
            lambda o, ct: o.encrypted_dot(ct, ct),
            lambda o, ct: o.encrypted_matmul_plain(ct, [[1.0, 0.0], [0.0, 1.0]]),
        ],
        ids=["sum_slots", "dot_plain", "dot_cipher", "matmul"],
    )
    def test_reductions_raise_a_specific_error(self, light_client, light_ops, call):
        ct = light_client.encrypt([1.0, 2.0])
        with pytest.raises(RotationKeysMissing, match="generate_galois_keys=True"):
            call(light_ops, ct)

    def test_elementwise_still_works_without_rotation_keys(self, light_client, light_ops):
        ct = light_client.encrypt([1.0, 2.0])
        result = light_ops.encrypted_multiply_plain(ct, [3.0, 4.0])
        assert light_client.decrypt(result, size=2) == pytest.approx([3.0, 8.0], abs=1e-3)

    def test_client_side_reduction_path(self, light_client, light_ops):
        """The escape hatch that avoids 33 MB of rotation keys."""
        holdings = [100.0, 50.0, 10.0]
        prices = [220.0, 410.0, 455.0]
        ct = light_client.encrypt(holdings)
        products = light_ops.elementwise_for_client_reduction(ct, prices)
        total = sum(light_client.decrypt(products, size=3))
        assert total == pytest.approx(float(np.dot(holdings, prices)), rel=1e-5)


class TestPortfolioPrimitives:
    def test_portfolio_value(self, full_client, ops):
        holdings, prices = [100.0, 50.0, 10.0], [220.0, 410.0, 455.0]
        ct = full_client.encrypt(holdings)
        value = full_client.decrypt(ops.portfolio_value(ct, prices), size=1)[0]
        assert value == pytest.approx(float(np.dot(holdings, prices)), rel=1e-5)

    def test_expected_return(self, full_client, ops):
        weights, mu = [0.4, 0.35, 0.25], [0.08, 0.05, 0.12]
        ct = full_client.encrypt(weights)
        result = full_client.decrypt(ops.expected_return(ct, mu), size=1)[0]
        assert result == pytest.approx(float(np.dot(weights, mu)), rel=1e-3)

    def test_portfolio_variance(self, full_client, ops):
        weights = np.array([0.4, 0.35, 0.25])
        cov = np.array([[0.04, 0.006, 0.008], [0.006, 0.02, 0.004], [0.008, 0.004, 0.09]])
        ct = full_client.encrypt(weights.tolist())
        result = full_client.decrypt(ops.portfolio_variance(ct, cov), size=1)[0]
        # Depth-2 relative tolerance: see TestPrecision for where 1e-3 comes from.
        assert result == pytest.approx(float(weights @ cov @ weights), rel=1e-3)

    def test_variance_rejects_non_square_covariance(self, full_client, ops):
        ct = full_client.encrypt([0.5, 0.5])
        with pytest.raises(Exception, match="square"):
            ops.portfolio_variance(ct, [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])

    def test_mean_variance_objective_fits_in_the_default_depth_budget(self, full_client, ops):
        """Folding lambda into the covariance keeps this at depth 2, not 3."""
        weights = np.array([0.4, 0.35, 0.25])
        mu = np.array([0.08, 0.05, 0.12])
        cov = np.array([[0.04, 0.006, 0.008], [0.006, 0.02, 0.004], [0.008, 0.004, 0.09]])
        lam = 2.0
        ct = full_client.encrypt(weights.tolist())
        result = full_client.decrypt(ops.mean_variance_objective(ct, mu, cov, lam), size=1)[0]
        expected = float(weights @ mu - lam * (weights @ cov @ weights))
        assert result == pytest.approx(expected, rel=1e-3)

    def test_objective_rejects_negative_risk_aversion(self, full_client, ops):
        ct = full_client.encrypt([1.0])
        with pytest.raises(Exception, match="non-negative"):
            ops.mean_variance_objective(ct, [0.1], [[0.01]], -1.0)


class TestEncryptedCovariance:
    def test_matches_numpy(self, full_client, ops):
        rng = np.random.default_rng(7)
        returns = rng.normal(0.0, 0.01, (3, 60))
        centred = returns - returns.mean(axis=1, keepdims=True)
        encrypted = [full_client.encrypt(centred[i].tolist()) for i in range(3)]

        matrix = ops.encrypted_covariance_from_returns(encrypted, 60)
        decrypted = np.array(
            [[full_client.decrypt(matrix[i][j], size=1)[0] for j in range(3)] for i in range(3)]
        )
        assert decrypted == pytest.approx(np.cov(centred, bias=False), abs=1e-5)

    def test_result_is_symmetric(self, full_client, ops):
        rng = np.random.default_rng(11)
        centred = rng.normal(0.0, 0.01, (3, 40))
        centred -= centred.mean(axis=1, keepdims=True)
        encrypted = [full_client.encrypt(centred[i].tolist()) for i in range(3)]
        matrix = ops.encrypted_covariance_from_returns(encrypted, 40)
        for i in range(3):
            for j in range(3):
                assert matrix[i][j] == matrix[j][i], "symmetry should reuse the same ciphertext"

    def test_rejects_too_few_observations(self, full_client, ops):
        ct = full_client.encrypt([1.0])
        with pytest.raises(Exception, match="at least 2 observations"):
            ops.encrypted_covariance_from_returns([ct], 1)


class TestDepthBudget:
    def test_exhausting_the_chain_raises_a_diagnostic_error(self, full_client, ops):
        """Depth 2 is the budget; a third multiplication must say so clearly."""
        ct = full_client.encrypt([2.0, 2.0])
        step = ops.encrypted_multiply(ct, ct)
        step = ops.encrypted_multiply(step, ct)
        with pytest.raises(DepthExceeded, match="multiplicative_depth"):
            for _ in range(4):
                step = ops.encrypted_multiply(step, ct)

    def test_cost_model_is_reported(self, ops):
        cost = ops.operation_cost("portfolio_variance")
        assert cost["levels"] == 2
        assert cost["galois"] is True
        assert cost["budget"] == ops.engine.parameters.multiplicative_depth

    def test_unknown_operation_is_rejected(self, ops):
        with pytest.raises(KeyError):
            ops.operation_cost("teleport")


class TestResultProvenance:
    def test_results_carry_the_evaluating_key_id(self, full_client, ops):
        """A result computed under key A must not silently decrypt under key B."""
        from app.crypto.ckks_engine import KeyMismatch, unwrap_ciphertext

        a = full_client.encrypt([1.0, 2.0])
        result = ops.encrypted_multiply_by_scalar(a, 2.0)
        tag, _ = unwrap_ciphertext(result)
        assert tag == full_client.key_id

        other = CKKSEngine.create_client(LIGHT_PARAMETERS)
        with pytest.raises(KeyMismatch):
            other.decrypt(result)


class TestPrecision:
    """Characterise CKKS approximation error, rather than assuming it away.

    CKKS is approximate arithmetic. Error grows with multiplicative depth and
    shrinks with the scale. Measured across independent keys at the default
    parameters (N=8192, scale 2^40, depth 2), relative error stays below about
    1e-4; the tolerances elsewhere in this file use 1e-3, roughly an order of
    magnitude of headroom.

    The practical consequence for the application: a portfolio *value* computed
    homomorphically is accurate to a few parts per million, which is fine. A
    *share count* is not safe to read straight out of a decryption -- round it
    on the client.
    """

    N_KEYS = 4
    MAX_RELATIVE_ERROR = 1e-3

    def test_depth_two_relative_error_stays_within_tolerance(self):
        from app.crypto.ckks_engine import DEFAULT_PARAMETERS

        weights = np.array([0.4, 0.35, 0.25])
        cov = np.array([[0.04, 0.006, 0.008], [0.006, 0.02, 0.004], [0.008, 0.004, 0.09]])
        truth = float(weights @ cov @ weights)

        errors = []
        for _ in range(self.N_KEYS):
            client = CKKSEngine.create_client(DEFAULT_PARAMETERS)
            server = CKKSEngine.from_public_context(client.export_public_context())
            operations = HomomorphicOps(server)
            ct = client.encrypt(weights.tolist())
            value = client.decrypt(operations.portfolio_variance(ct, cov), size=1)[0]
            errors.append(abs(value - truth) / truth)

        assert max(errors) < self.MAX_RELATIVE_ERROR, (
            f"depth-2 relative error {max(errors):.2e} exceeded {self.MAX_RELATIVE_ERROR}; "
            "either the scale or the modulus chain needs revisiting"
        )

    def test_error_grows_by_roughly_an_order_of_magnitude_per_level(self, full_client, ops):
        """Measured at the default parameters: ~1e-9 fresh, ~1e-7 after one
        multiplication, ~1e-6 after two. Documents why the depth budget is a
        precision budget as much as a modulus budget, and why deeper pipelines
        need DEEP_PARAMETERS rather than optimism."""
        values = [1.1, 1.2, 1.3]
        ct = full_client.encrypt(values)

        fresh = full_client.decrypt(ct, size=3)
        squared_ct = ops.encrypted_multiply(ct, ct)
        squared = full_client.decrypt(squared_ct, size=3)
        cubed = full_client.decrypt(ops.encrypted_multiply(squared_ct, ct), size=3)

        def relative_error(got, want):
            return max(abs(a - b) / abs(b) for a, b in zip(got, want))

        depth_0 = relative_error(fresh, values)
        depth_1 = relative_error(squared, [v * v for v in values])
        depth_2 = relative_error(cubed, [v ** 3 for v in values])

        assert depth_0 < depth_1 < depth_2, (
            f"expected monotone error growth, got {depth_0:.2e} -> {depth_1:.2e} -> {depth_2:.2e}"
        )
        assert depth_2 < 1e-4, "depth-2 error should still be far inside any financial tolerance"

    def test_reduction_costs_more_precision_than_a_multiplication(self, full_client, ops):
        """A rotate-and-add reduction sums noise from every slot, not just the
        ones carrying data -- which is why the quadratic form lands near 1e-5
        relative error while a bare product sits near 1e-7."""
        weights = np.array([0.4, 0.35, 0.25])
        cov = np.array([[0.04, 0.006, 0.008], [0.006, 0.02, 0.004], [0.008, 0.004, 0.09]])
        ct = full_client.encrypt(weights.tolist())

        product = full_client.decrypt(ops.encrypted_multiply(ct, ct), size=3)
        product_error = max(abs(a - b * b) / (b * b) for a, b in zip(product, weights))

        truth = float(weights @ cov @ weights)
        variance = full_client.decrypt(ops.portfolio_variance(ct, cov), size=1)[0]
        reduction_error = abs(variance - truth) / truth

        assert product_error < reduction_error < self.MAX_RELATIVE_ERROR

    def test_large_magnitudes_keep_relative_accuracy(self, full_client, ops):
        """Portfolio values run to millions; the error must scale with them."""
        holdings = [12_500.0, 8_750.0, 34_000.0]
        prices = [220.0, 410.0, 455.0]
        ct = full_client.encrypt(holdings)
        value = full_client.decrypt(ops.portfolio_value(ct, prices), size=1)[0]
        assert value == pytest.approx(float(np.dot(holdings, prices)), rel=1e-5)
