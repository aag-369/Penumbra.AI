"""Tests for the classical crypto helpers."""

from __future__ import annotations

import pytest

from app.crypto.security_utils import (
    SealError,
    b64d,
    b64e,
    constant_time_equals,
    derive_key,
    fingerprint,
    hmac_sha256,
    random_bytes,
    random_token,
    seal,
    unseal,
)


class TestRandomness:
    def test_random_bytes_length(self):
        assert len(random_bytes(32)) == 32

    def test_random_bytes_are_not_repeated(self):
        assert len({random_bytes(16) for _ in range(200)}) == 200

    def test_rejects_non_positive_length(self):
        with pytest.raises(ValueError):
            random_bytes(0)

    def test_tokens_are_url_safe(self):
        token = random_token(32)
        assert all(c.isalnum() or c in "-_" for c in token)


class TestBase64:
    def test_roundtrip(self):
        data = random_bytes(1024)
        assert b64d(b64e(data)) == data


class TestKeyDerivation:
    def test_is_deterministic_for_a_given_salt(self):
        salt = random_bytes(16)
        assert derive_key("passphrase", salt) == derive_key("passphrase", salt)

    def test_salt_changes_the_key(self):
        assert derive_key("passphrase", random_bytes(16)) != derive_key("passphrase", random_bytes(16))

    def test_passphrase_changes_the_key(self):
        salt = random_bytes(16)
        assert derive_key("one", salt) != derive_key("two", salt)

    def test_rejects_empty_passphrase(self):
        with pytest.raises(ValueError):
            derive_key("", random_bytes(16))


class TestSealing:
    def test_roundtrip(self):
        payload = random_bytes(4096)
        assert unseal(seal(payload, "a good passphrase"), "a good passphrase") == payload

    def test_wrong_passphrase_is_rejected(self):
        with pytest.raises(SealError, match="wrong passphrase"):
            unseal(seal(b"secret", "right"), "wrong")

    def test_same_plaintext_seals_differently_each_time(self):
        """Fresh salt and nonce per call, so sealing is not a fingerprint."""
        assert seal(b"same", "passphrase") != seal(b"same", "passphrase")

    def test_malformed_envelope_is_rejected(self):
        with pytest.raises(SealError, match="malformed"):
            unseal("not json", "passphrase")

    def test_unknown_version_is_rejected(self):
        import json

        blob = json.loads(seal(b"x", "passphrase"))
        blob["version"] = 99
        with pytest.raises(SealError, match="unsupported seal version"):
            unseal(json.dumps(blob), "passphrase")

    def test_gcm_detects_ciphertext_tampering(self):
        import json

        blob = json.loads(seal(b"important", "passphrase"))
        raw = bytearray(b64d(blob["ct"]))
        raw[0] ^= 0xFF
        blob["ct"] = b64e(bytes(raw))
        with pytest.raises(SealError):
            unseal(json.dumps(blob), "passphrase")


class TestMac:
    def test_hmac_is_deterministic(self):
        key = random_bytes(32)
        assert hmac_sha256(key, b"message") == hmac_sha256(key, b"message")

    def test_hmac_depends_on_key_and_message(self):
        key = random_bytes(32)
        assert hmac_sha256(key, b"a") != hmac_sha256(key, b"b")
        assert hmac_sha256(key, b"a") != hmac_sha256(random_bytes(32), b"a")

    def test_constant_time_equals(self):
        assert constant_time_equals("abc", "abc")
        assert not constant_time_equals("abc", "abd")
        assert not constant_time_equals("abc", "abcd")


class TestFingerprint:
    def test_is_stable(self):
        assert fingerprint(b"data") == fingerprint(b"data")

    def test_differs_across_inputs(self):
        assert fingerprint(b"a") != fingerprint(b"b")

    def test_does_not_contain_the_input(self):
        secret = b"super-secret-key-material"
        assert secret.decode() not in fingerprint(secret, length=64)
