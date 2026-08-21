"""Tests for BB84 simulation, sessions and ciphertext authentication."""

from __future__ import annotations

import time

import pytest

from app.crypto.post_quantum_channel import (
    QBER_ABORT_THRESHOLD,
    AuthenticationFailed,
    EavesdropperDetected,
    PostQuantumChannel,
    SessionExpired,
    simulate_bb84,
)


class TestBB84:
    def test_clean_channel_has_no_errors(self):
        result = simulate_bb84(4096)
        assert result.qber == 0.0
        assert not result.aborted
        assert len(result.sifted_key_bits) > 1000

    def test_sift_rate_is_about_half(self):
        """Alice and Bob choose bases independently, so half should agree."""
        result = simulate_bb84(8192)
        assert result.sift_rate == pytest.approx(0.5, abs=0.03)

    def test_intercept_resend_produces_the_expected_error_rate(self):
        """Eve guesses the basis wrong half the time; Bob then errs half of those."""
        result = simulate_bb84(8192, eavesdropper=True)
        assert result.qber == pytest.approx(0.25, abs=0.04)

    def test_eavesdropper_is_detected_and_the_key_is_discarded(self):
        result = simulate_bb84(4096, eavesdropper=True)
        assert result.aborted
        assert result.sifted_key_bits == ()

    def test_modest_channel_noise_does_not_trigger_an_abort(self):
        result = simulate_bb84(8192, channel_noise=0.03)
        assert result.qber < QBER_ABORT_THRESHOLD
        assert not result.aborted

    def test_noise_above_the_threshold_does_trigger_an_abort(self):
        result = simulate_bb84(8192, channel_noise=0.25)
        assert result.aborted

    def test_runs_differ_from_each_other(self):
        """The bits come from the OS CSPRNG, not a seeded PRNG."""
        assert simulate_bb84(1024).sifted_key_bits != simulate_bb84(1024).sifted_key_bits

    @pytest.mark.parametrize("n", [0, 8, 15])
    def test_rejects_too_few_qubits(self, n):
        with pytest.raises(ValueError, match="at least 16"):
            simulate_bb84(n)

    @pytest.mark.parametrize("fraction", [0.0, 1.0, 1.5, -0.1])
    def test_rejects_invalid_test_fraction(self, fraction):
        with pytest.raises(ValueError, match="test_fraction"):
            simulate_bb84(1024, test_fraction=fraction)

    def test_statistics_are_serialisable(self):
        stats = simulate_bb84(512).as_dict()
        assert set(stats) >= {"n_sent", "n_sifted", "qber", "aborted", "sift_rate"}


class TestSessions:
    @pytest.fixture
    def channel(self) -> PostQuantumChannel:
        return PostQuantumChannel(use_bb84_simulation=False)

    def test_establish_returns_a_usable_session(self, channel, light_client):
        session = channel.establish_session("user-1", light_client.key_id)
        assert session["user_id"] == "user-1"
        assert session["mac_key"]
        assert channel.active_sessions == 1

    def test_session_is_bound_to_the_declared_key(self, channel, light_client, full_client):
        one = channel.establish_session("u", light_client.key_id)
        two = channel.establish_session("u", full_client.key_id)
        assert one["key_fingerprint"] == light_client.key_id
        assert two["key_fingerprint"] == full_client.key_id
        assert one["key_fingerprint"] != two["key_fingerprint"]

    def test_unknown_session_is_rejected(self, channel):
        with pytest.raises(SessionExpired, match="unknown session"):
            channel.get_session("no-such-session")

    def test_expired_session_is_rejected(self, light_client):
        channel = PostQuantumChannel(session_ttl=1)
        session_id = channel.establish_session("u", light_client.key_id)["session_id"]
        channel.get_session(session_id).created_at = time.time() - 10
        with pytest.raises(SessionExpired, match="expired"):
            channel.get_session(session_id)

    def test_close_is_idempotent(self, channel, light_client):
        session_id = channel.establish_session("u", light_client.key_id)["session_id"]
        channel.close_session(session_id)
        channel.close_session(session_id)
        assert channel.active_sessions == 0

    def test_purge_removes_only_expired_sessions(self, light_client):
        channel = PostQuantumChannel(session_ttl=3600)
        stale = channel.establish_session("u", light_client.key_id)["session_id"]
        channel.establish_session("v", light_client.key_id)
        channel.get_session(stale).created_at = time.time() - 7200
        assert channel.purge_expired() == 1
        assert channel.active_sessions == 1

    def test_bb84_statistics_are_attached_when_enabled(self, light_client):
        channel = PostQuantumChannel(use_bb84_simulation=True)
        session = channel.establish_session("u", light_client.key_id, bb84_qubits=512)
        assert session["bb84"] is not None
        assert session["bb84"]["n_sent"] == 512

    def test_describe_states_where_the_security_comes_from(self, channel):
        assert "Ring-LWE" in str(channel.describe()["security_basis"])


class TestCiphertextAuthentication:
    @pytest.fixture
    def session(self, light_client):
        channel = PostQuantumChannel()
        opened = channel.establish_session("u", light_client.key_id)
        return channel, opened["session_id"]

    def test_valid_mac_is_accepted(self, session, light_client):
        channel, session_id = session
        ct = light_client.encrypt([1.0])
        signature = channel.sign_ciphertext(ct, session_id, 0)
        assert channel.verify_ciphertext_authenticity(ct, session_id, signature, 0)

    def test_tampered_ciphertext_is_rejected(self, session, light_client):
        channel, session_id = session
        ct = light_client.encrypt([1.0])
        signature = channel.sign_ciphertext(ct, session_id, 0)
        with pytest.raises(AuthenticationFailed, match="did not verify"):
            channel.verify_ciphertext_authenticity(ct[:-4] + "AAAA", session_id, signature, 0)

    def test_forged_mac_is_rejected(self, session, light_client):
        channel, session_id = session
        ct = light_client.encrypt([1.0])
        with pytest.raises(AuthenticationFailed):
            channel.verify_ciphertext_authenticity(ct, session_id, "0" * 64, 0)

    def test_replay_is_rejected(self, session, light_client):
        channel, session_id = session
        ct = light_client.encrypt([1.0])
        signature = channel.sign_ciphertext(ct, session_id, 0)
        channel.verify_ciphertext_authenticity(ct, session_id, signature, 0)
        with pytest.raises(AuthenticationFailed, match="replays"):
            channel.verify_ciphertext_authenticity(ct, session_id, signature, 0)

    def test_sequence_numbers_must_increase(self, session, light_client):
        channel, session_id = session
        ct = light_client.encrypt([1.0])
        channel.verify_ciphertext_authenticity(
            ct, session_id, channel.sign_ciphertext(ct, session_id, 5), 5
        )
        with pytest.raises(AuthenticationFailed, match="reorders"):
            channel.verify_ciphertext_authenticity(
                ct, session_id, channel.sign_ciphertext(ct, session_id, 3), 3
            )

    def test_mac_does_not_transfer_between_sessions(self, light_client):
        """The session id is inside the MAC, so a ciphertext cannot be lifted."""
        channel = PostQuantumChannel()
        first = channel.establish_session("u", light_client.key_id)["session_id"]
        second = channel.establish_session("u", light_client.key_id)["session_id"]
        ct = light_client.encrypt([1.0])
        signature = channel.sign_ciphertext(ct, first, 0)
        with pytest.raises(AuthenticationFailed):
            channel.verify_ciphertext_authenticity(ct, second, signature, 0)


class TestBB84IsNotTreatedAsKeyMaterial:
    def test_mac_key_is_full_length_even_when_bb84_is_off(self, light_client):
        from app.crypto.security_utils import b64d

        channel = PostQuantumChannel(use_bb84_simulation=False)
        session = channel.establish_session("u", light_client.key_id)
        assert len(b64d(session["mac_key"])) == 32

    def test_aborted_bb84_refuses_the_session(self, monkeypatch, light_client):
        """A detected eavesdropper must fail closed, not fall back silently."""
        import app.crypto.post_quantum_channel as module

        original = module.simulate_bb84
        monkeypatch.setattr(
            module, "simulate_bb84", lambda *a, **k: original(1024, eavesdropper=True)
        )
        channel = PostQuantumChannel(use_bb84_simulation=True)
        with pytest.raises(EavesdropperDetected, match="abort threshold"):
            channel.establish_session("u", light_client.key_id)
