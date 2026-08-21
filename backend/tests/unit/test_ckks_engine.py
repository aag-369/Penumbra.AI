"""Tests for the CKKS engine.

The important tests here are not the round-trip ones -- those verify TenSEAL,
not us. They are the ones that verify the *asymmetry*: that a server-side engine
cannot decrypt, that it refuses a context carrying a secret key, and that weak
parameters are rejected. Those three properties are the privacy claim.
"""

from __future__ import annotations

import pytest

from app.crypto.ckks_engine import (
    DEFAULT_PARAMETERS,
    LIGHT_PARAMETERS,
    SECURITY_TABLE,
    CiphertextError,
    CKKSEngine,
    CKKSParameters,
    CryptoError,
    InsecureParameters,
    KeyMismatch,
    SecretKeyUnavailable,
)
from app.crypto.security_utils import SealError


class TestParameters:
    def test_defaults_are_valid(self):
        DEFAULT_PARAMETERS.validate()
        assert DEFAULT_PARAMETERS.multiplicative_depth == 2
        assert DEFAULT_PARAMETERS.slot_count == 4096

    def test_rejects_modulus_over_budget(self):
        with pytest.raises(InsecureParameters, match="exceeds the 218-bit budget"):
            CKKSParameters(poly_modulus_degree=8192, coeff_mod_bit_sizes=(60, 60, 60, 60, 60))

    def test_rejects_non_power_of_two_degree(self):
        with pytest.raises(InsecureParameters, match="poly_modulus_degree"):
            CKKSParameters(poly_modulus_degree=10000)

    def test_rejects_chain_too_short_for_a_multiplication(self):
        with pytest.raises(InsecureParameters, match="at least 3 primes"):
            CKKSParameters(coeff_mod_bit_sizes=(60, 60))

    @pytest.mark.parametrize("level", [128, 192, 256])
    def test_security_table_is_monotone_in_degree(self, level):
        budgets = [SECURITY_TABLE[level][n] for n in sorted(SECURITY_TABLE[level])]
        assert budgets == sorted(budgets), "a larger ring must allow a larger modulus"

    def test_higher_security_allows_less_modulus(self):
        assert SECURITY_TABLE[256][8192] < SECURITY_TABLE[192][8192] < SECURITY_TABLE[128][8192]


class TestKeyLifecycle:
    def test_client_engine_is_private(self, light_client):
        assert light_client.is_private

    def test_server_engine_is_public(self, light_server):
        assert not light_server.is_private

    def test_public_export_carries_no_secret_key(self, light_client):
        rebuilt = CKKSEngine.from_public_context(light_client.export_public_context())
        assert not rebuilt.is_private

    def test_server_refuses_a_context_containing_a_secret_key(self, light_client):
        """The single most important negative test in the suite."""
        with pytest.raises(CryptoError, match="refusing public context"):
            CKKSEngine.from_public_context(light_client.export_private_context())

    def test_public_engine_cannot_export_a_secret_key(self, light_server):
        with pytest.raises(SecretKeyUnavailable):
            light_server.export_private_context()

    def test_fingerprint_is_stable_and_key_specific(self, light_client, full_client):
        assert light_client.public_fingerprint == light_client.public_fingerprint
        assert light_client.public_fingerprint != full_client.public_fingerprint

    def test_garbage_context_is_rejected(self):
        with pytest.raises(CryptoError):
            CKKSEngine.from_public_context("not-a-context")


class TestSealedBackup:
    def test_roundtrip(self, light_client):
        sealed = light_client.export_sealed_private_context("a long enough passphrase")
        restored = CKKSEngine.from_sealed_private_context(sealed, "a long enough passphrase")
        assert restored.is_private
        ct = light_client.encrypt([3.25, 4.5])
        assert restored.decrypt(ct, size=2) == pytest.approx([3.25, 4.5], abs=1e-3)

    def test_wrong_passphrase_fails(self, light_client):
        sealed = light_client.export_sealed_private_context("a long enough passphrase")
        with pytest.raises(SealError):
            CKKSEngine.from_sealed_private_context(sealed, "wrong")

    def test_tampering_is_detected(self, light_client):
        import json

        sealed = json.loads(light_client.export_sealed_private_context("passphrase-here"))
        sealed["ct"] = "A" + sealed["ct"][1:]
        with pytest.raises(SealError):
            CKKSEngine.from_sealed_private_context(json.dumps(sealed), "passphrase-here")


class TestEncryptDecrypt:
    def test_roundtrip_preserves_values(self, light_client):
        plaintext = [1.5, 2.75, -3.25, 0.0, 100.125]
        out = light_client.decrypt(light_client.encrypt(plaintext), size=len(plaintext))
        assert out == pytest.approx(plaintext, abs=1e-4)

    def test_roundtrip_at_portfolio_magnitudes(self, light_client):
        plaintext = [1_250_000.50, 87_500.25, 3_400_000.75]
        out = light_client.decrypt(light_client.encrypt(plaintext), size=3)
        assert out == pytest.approx(plaintext, rel=1e-6)

    def test_server_cannot_decrypt(self, light_client, light_server):
        """The privacy guarantee, stated as a test."""
        ct = light_client.encrypt([42.0])
        with pytest.raises(SecretKeyUnavailable, match="never leaves the client"):
            light_server.decrypt(ct)

    def test_server_can_encrypt_under_the_same_key(self, light_client, light_server):
        """CKKS is public-key: the server encrypts its own market data too."""
        ct = light_server.encrypt([7.0, 8.0])
        assert light_client.decrypt(ct, size=2) == pytest.approx([7.0, 8.0], abs=1e-4)

    def test_full_slot_capacity(self, light_client):
        values = [float(i) / 7 for i in range(light_client.parameters.slot_count)]
        out = light_client.decrypt(light_client.encrypt(values), size=len(values))
        assert out == pytest.approx(values, abs=1e-4)

    def test_rejects_more_values_than_slots(self, light_client):
        too_many = [1.0] * (light_client.parameters.slot_count + 1)
        with pytest.raises(CiphertextError, match="slots"):
            light_client.encrypt(too_many)

    @pytest.mark.parametrize(
        "bad", [[], [float("nan")], [float("inf")], [float("-inf")]], ids=["empty", "nan", "inf", "-inf"]
    )
    def test_rejects_invalid_plaintext(self, light_client, bad):
        with pytest.raises(CiphertextError):
            light_client.encrypt(bad)

    def test_rejects_non_numeric_plaintext(self, light_client):
        with pytest.raises(CiphertextError):
            light_client.encrypt(["not a number"])  # type: ignore[list-item]

    def test_rejects_malformed_ciphertext(self, light_client):
        with pytest.raises(CiphertextError):
            light_client.decrypt("obviously-not-base64-ciphertext")

    def test_rejects_ciphertext_from_another_key(self, light_client, full_client):
        """Regression test for a SEAL behaviour that fails silently.

        Without the fingerprint envelope this call returns floats of order 1e31
        instead of raising, so a user restoring the wrong key backup would see
        numbers rather than an error.
        """
        foreign = full_client.encrypt([1.0, 2.0])
        with pytest.raises(KeyMismatch, match="would return noise"):
            light_client.decrypt(foreign)

    def test_wrong_key_of_identical_parameters_is_still_caught(self, light_client):
        other = CKKSEngine.create_client(LIGHT_PARAMETERS)
        with pytest.raises(KeyMismatch):
            light_client.decrypt(other.encrypt([100.0]))

    def test_bare_ciphertexts_without_an_envelope_still_load(self, light_client):
        """Backwards compatibility with pre-envelope and third-party ciphertexts."""
        from app.crypto.ckks_engine import unwrap_ciphertext

        _, body = unwrap_ciphertext(light_client.encrypt([5.0, 6.0]))
        assert light_client.decrypt(body, size=2) == pytest.approx([5.0, 6.0], abs=1e-4)

    def test_envelope_is_small_relative_to_the_body(self, light_client):
        from app.crypto.ckks_engine import unwrap_ciphertext

        full = light_client.encrypt([1.0])
        _, body = unwrap_ciphertext(full)
        assert len(full) - len(body) < 32

    def test_malformed_envelope_is_rejected(self, light_client):
        with pytest.raises(CiphertextError, match="envelope is malformed"):
            light_client.decrypt("pnb1.only-two-parts")


class TestIntrospection:
    def test_inspect_recovers_real_parameters(self, light_client):
        info = light_client.inspect_context()
        assert info.poly_modulus_degree == LIGHT_PARAMETERS.poly_modulus_degree
        assert info.total_coeff_modulus_bits == sum(LIGHT_PARAMETERS.coeff_mod_bit_sizes)
        assert info.multiplicative_depth == LIGHT_PARAMETERS.multiplicative_depth
        assert info.global_scale_bits == LIGHT_PARAMETERS.global_scale_bits
        assert info.has_secret_key is True

    def test_inspect_detects_rotation_keys(self, light_client, full_client):
        assert light_client.inspect_context().has_galois_keys is False
        assert full_client.inspect_context().has_galois_keys is True

    def test_security_level_is_computed_from_the_real_modulus(self, light_client):
        info = light_client.inspect_context()
        assert info.security_level() >= 128
        info.assert_secure(128)

    def test_assert_secure_rejects_an_over_budget_context(self, light_client):
        from dataclasses import replace

        weak = replace(light_client.inspect_context(), total_coeff_modulus_bits=900)
        assert weak.security_level() == 0
        with pytest.raises(InsecureParameters, match="Refusing the key"):
            weak.assert_secure(128)

    def test_rotation_keys_dominate_context_size(self, light_server, full_server):
        """Documents the 19x cost that drove the keystore-on-disk decision."""
        assert full_server.public_context_size() > 10 * light_server.public_context_size()

    def test_ciphertext_size_is_independent_of_value_count(self, light_client):
        """One value or a thousand, a CKKS ciphertext costs the same.

        This is why a portfolio is packed into one ciphertext rather than one
        per ticker.
        """
        one = light_client.ciphertext_size(light_client.encrypt([1.0]))
        many = light_client.ciphertext_size(light_client.encrypt([1.0] * 1000))
        assert abs(one - many) / one < 0.05

    def test_describe_does_not_leak_key_material(self, light_client):
        described = str(light_client.describe())
        assert light_client.export_private_context()[:64] not in described
        assert "private" in described
