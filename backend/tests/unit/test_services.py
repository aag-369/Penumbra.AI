"""Tests for the service layer: auth, keystore, portfolio validation, audit."""

from __future__ import annotations

import pytest

from app.crypto.ckks_engine import CKKSEngine, LIGHT_PARAMETERS
from app.models.audit_log import AuditAction, AuditSeverity
from app.models.user import UserRole
from app.services.audit_service import AuditService
from app.services.keystore_service import (
    ContextTooLarge,
    KeyNotFound,
    KeystoreError,
    SecretKeyRejected,
)
from app.services.portfolio_service import (
    PortfolioNotFound,
    PortfolioService,
    ValidationFailed,
)
from app.services.user_service import (
    AccountInactive,
    AccountLocked,
    InvalidCredentials,
    InvalidToken,
    UserService,
)


class TestPasswords:
    def test_hash_verifies(self):
        digest = UserService.hash_password("correct-horse-9")
        assert UserService.verify_password("correct-horse-9", digest)
        assert not UserService.verify_password("wrong", digest)

    def test_hashes_are_salted(self):
        assert UserService.hash_password("same") != UserService.hash_password("same")

    def test_rejects_password_beyond_bcrypts_limit(self):
        """bcrypt truncates at 72 bytes; truncating silently would make every
        suffix equivalent, so this raises instead."""
        with pytest.raises(ValueError, match="72-byte limit"):
            UserService.hash_password("x" * 73)

    def test_verify_survives_a_malformed_hash(self):
        assert not UserService.verify_password("anything", "not-a-bcrypt-hash")

    @pytest.mark.parametrize(
        "password,expected",
        [("short1", False), ("nodigitshere!", False), ("123456789012", False), ("correct-horse-9", True)],
    )
    def test_strength_rules(self, password, expected):
        assert (UserService.validate_password_strength(password) == []) is expected


class TestTokens:
    def test_roundtrip(self, db, user):
        assert UserService.resolve_token(db, UserService.create_token(user)).id == user.id

    def test_access_token_is_not_a_refresh_token(self, db, user):
        with pytest.raises(InvalidToken, match="expected a refresh token"):
            UserService.resolve_token(db, UserService.create_token(user, "access"), "refresh")

    def test_logout_invalidates_existing_tokens(self, db, user):
        token = UserService.create_token(user)
        UserService.invalidate_tokens(db, user)
        db.commit()
        with pytest.raises(InvalidToken, match="superseded"):
            UserService.resolve_token(db, token)

    def test_tampered_token_is_rejected(self, db, user):
        token = UserService.create_token(user)
        with pytest.raises(InvalidToken):
            UserService.resolve_token(db, token[:-6] + "AAAAAA")

    def test_deactivated_user_cannot_use_a_valid_token(self, db, user):
        token = UserService.create_token(user)
        user.is_active = False
        db.commit()
        with pytest.raises(AccountInactive):
            UserService.resolve_token(db, token)


class TestAuthentication:
    def test_correct_credentials_succeed(self, db, user):
        assert UserService.authenticate(db, user.email, "correct-horse-9").id == user.id

    def test_email_is_case_insensitive(self, db, user):
        assert UserService.authenticate(db, user.email.upper(), "correct-horse-9").id == user.id

    def test_wrong_password_fails(self, db, user):
        with pytest.raises(InvalidCredentials):
            UserService.authenticate(db, user.email, "wrong")

    def test_unknown_email_gives_the_same_error(self, db):
        with pytest.raises(InvalidCredentials, match="invalid email or password"):
            UserService.authenticate(db, "nobody@example.com", "whatever")

    def test_lockout_after_repeated_failures(self, db, user):
        from app.config import settings

        for _ in range(settings.login_max_attempts):
            with pytest.raises(InvalidCredentials):
                UserService.authenticate(db, user.email, "wrong")
        with pytest.raises(AccountLocked, match="locked for another"):
            UserService.authenticate(db, user.email, "correct-horse-9")

    def test_successful_login_clears_the_failure_counter(self, db, user):
        with pytest.raises(InvalidCredentials):
            UserService.authenticate(db, user.email, "wrong")
        UserService.authenticate(db, user.email, "correct-horse-9")
        assert user.failed_login_count == 0


class TestKeystore:
    def test_registers_a_public_context(self, db, user, keystore, light_client):
        key = keystore.register(db, user.id, light_client.export_public_context())
        assert key.fingerprint == light_client.key_id
        assert key.security_level_bits >= 128
        assert key.has_galois_keys is False

    def test_refuses_a_context_containing_a_secret_key(self, db, user, keystore, light_client):
        """The privacy guarantee, enforced at the API boundary."""
        with pytest.raises(SecretKeyRejected, match="refuses to store it"):
            keystore.register(db, user.id, light_client.export_private_context())

    def test_stores_the_blob_outside_the_database(self, db, user, keystore, light_client):
        key = keystore.register(db, user.id, light_client.export_public_context())
        assert (keystore.root / key.context_path).exists()
        assert len(key.context_path) < 200, "the row holds a path, not the bytes"

    def test_registering_the_same_key_twice_is_idempotent(self, db, user, keystore, light_client):
        first = keystore.register(db, user.id, light_client.export_public_context())
        second = keystore.register(db, user.id, light_client.export_public_context())
        assert first.id == second.id

    def test_a_new_key_deactivates_the_previous_one(self, db, user, keystore, light_client, full_client):
        old = keystore.register(db, user.id, light_client.export_public_context())
        keystore.register(db, user.id, full_client.export_public_context())
        db.refresh(old)
        assert old.is_active is False

    def test_oversized_context_is_rejected(self, db, user, keystore, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "max_public_context_bytes", 100)
        with pytest.raises(ContextTooLarge, match="limit is"):
            keystore.register(db, user.id, "x" * 200)

    def test_garbage_context_is_rejected(self, db, user, keystore):
        with pytest.raises(KeystoreError):
            keystore.register(db, user.id, "bm90LWEtY29udGV4dA==")

    def test_missing_key_raises(self, db, user, keystore):
        with pytest.raises(KeyNotFound, match="no active encryption key"):
            keystore.active_key(db, user.id)

    def test_engine_built_from_the_store_cannot_decrypt(self, db, user, keystore, light_client):
        """Round-tripping through the keystore must not resurrect a secret key."""
        keystore.register(db, user.id, light_client.export_public_context())
        assert keystore.engine_for(db, user.id).is_private is False

    def test_usage_stats(self, db, user, keystore, light_client):
        keystore.register(db, user.id, light_client.export_public_context())
        stats = keystore.usage_stats(db)
        assert stats["total_keys"] == 1 and stats["active_keys"] == 1
        assert stats["total_megabytes"] > 0


class TestCsvParsing:
    def test_parses_a_well_formed_file(self):
        parsed = PortfolioService.parse_csv(
            "ticker,quantity,cost_basis\nAAPL,100,150.0\nMSFT,50,300.5\n"
        )
        assert parsed.tickers == ("AAPL", "MSFT")
        assert parsed.quantities == (100.0, 50.0)
        assert parsed.cost_basis == (150.0, 300.5)

    def test_tolerates_whitespace_and_blank_lines(self):
        parsed = PortfolioService.parse_csv("ticker,quantity\n aapl , 100 \n\nMSFT,50\n")
        assert parsed.tickers == ("AAPL", "MSFT")
        assert parsed.quantities == (100.0, 50.0)

    def test_handles_quoted_thousands_separators(self):
        """Excel exports quote them, which is the only way they survive CSV."""
        parsed = PortfolioService.parse_csv('ticker,quantity\nAAPL,"1,250"\n')
        assert parsed.quantities == (1250.0,)

    def test_column_order_does_not_matter(self):
        parsed = PortfolioService.parse_csv("quantity,ticker\n100,AAPL\n")
        assert parsed.tickers == ("AAPL",)

    def test_cost_basis_is_optional(self):
        assert PortfolioService.parse_csv("ticker,quantity\nAAPL,10\n").cost_basis is None

    def test_accepts_class_share_tickers(self):
        assert PortfolioService.parse_csv("ticker,quantity\nBRK.B,10\n").tickers == ("BRK.B",)

    @pytest.mark.parametrize(
        "content,match",
        [
            ("ticker\nAAPL\n", "missing required column"),
            ("ticker,quantity\nAAPL,abc\n", "not a number"),
            ("ticker,quantity\nAAPL,-5\n", "negative quantity"),
            ("ticker,quantity\nAAPL,10\nAAPL,5\n", "more than once"),
            ("ticker,quantity\n123$,10\n", "not a valid ticker"),
            ("", "no header row"),
        ],
    )
    def test_rejects_malformed_input(self, content, match):
        with pytest.raises(ValidationFailed, match=match):
            PortfolioService.parse_csv(content)

    def test_reports_every_problem_at_once(self):
        with pytest.raises(ValidationFailed) as excinfo:
            PortfolioService.parse_csv("ticker,quantity\nAAPL,abc\nMSFT,xyz\n")
        assert str(excinfo.value).count(";") >= 1, "a user fixing a file should see all errors"

    def test_rejects_oversized_upload(self, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "max_upload_bytes", 32)
        with pytest.raises(ValidationFailed, match="upload limit"):
            PortfolioService.parse_csv("ticker,quantity\n" + "AAPL,1\n" * 50)


class TestPortfolioPersistence:
    def test_stores_an_encrypted_portfolio(self, db, user, keystore, light_client):
        keystore.register(db, user.id, light_client.export_public_context())
        parsed = PortfolioService.parse_csv("ticker,quantity\nAAPL,100\nMSFT,50\n")
        payload = PortfolioService.encrypt_locally(light_client, parsed)
        portfolio = PortfolioService.create(
            db,
            user.id,
            tickers=payload["tickers"],
            holdings_ciphertext=payload["holdings_ciphertext"],
            keystore=keystore,
        )
        assert portfolio.tickers == ["AAPL", "MSFT"]
        assert portfolio.n_assets == 2

    def test_the_owner_can_decrypt_what_was_stored(self, db, user, keystore, light_client):
        keystore.register(db, user.id, light_client.export_public_context())
        parsed = PortfolioService.parse_csv("ticker,quantity\nAAPL,100\nMSFT,50\n")
        payload = PortfolioService.encrypt_locally(light_client, parsed)
        portfolio = PortfolioService.create(
            db, user.id, tickers=payload["tickers"],
            holdings_ciphertext=payload["holdings_ciphertext"], keystore=keystore,
        )
        assert light_client.decrypt(portfolio.holdings_ciphertext, size=2) == pytest.approx(
            [100.0, 50.0], abs=1e-4
        )

    def test_ciphertext_from_the_wrong_key_is_rejected_at_upload(
        self, db, user, keystore, light_client, full_client
    ):
        keystore.register(db, user.id, light_client.export_public_context())
        foreign = full_client.encrypt([1.0, 2.0])
        with pytest.raises(ValidationFailed, match="does not parse under your registered key"):
            PortfolioService.create(
                db, user.id, tickers=["AAPL", "MSFT"], holdings_ciphertext=foreign, keystore=keystore
            )

    def test_upload_without_a_key_fails_clearly(self, db, user, keystore, light_client):
        with pytest.raises(KeyNotFound):
            PortfolioService.create(
                db, user.id, tickers=["AAPL"],
                holdings_ciphertext=light_client.encrypt([1.0]), keystore=keystore,
            )

    def test_a_new_upload_deactivates_the_previous_portfolio(self, db, user, keystore, light_client):
        keystore.register(db, user.id, light_client.export_public_context())
        first = PortfolioService.create(
            db, user.id, tickers=["AAPL"],
            holdings_ciphertext=light_client.encrypt([1.0]), keystore=keystore,
        )
        PortfolioService.create(
            db, user.id, tickers=["MSFT"],
            holdings_ciphertext=light_client.encrypt([2.0]), keystore=keystore,
        )
        db.refresh(first)
        assert first.is_active is False
        assert PortfolioService.current(db, user.id).tickers == ["MSFT"]

    def test_missing_portfolio_raises(self, db, user):
        with pytest.raises(PortfolioNotFound):
            PortfolioService.current(db, user.id)

    def test_encrypt_locally_refuses_a_public_engine(self, light_server):
        parsed = PortfolioService.parse_csv("ticker,quantity\nAAPL,1\n")
        with pytest.raises(Exception, match="client operation"):
            PortfolioService.encrypt_locally(light_server, parsed)


class TestAudit:
    def test_records_an_entry(self, db, user):
        entry = AuditService.record(
            db, AuditAction.USER_LOGIN, actor_user_id=user.id, source="test"
        )
        assert entry.action is AuditAction.USER_LOGIN
        assert entry.details["source"] == "test"

    def test_redacts_forbidden_keys(self, db, user):
        """An audit row must never carry key material or a ciphertext body."""
        entry = AuditService.record(
            db,
            AuditAction.KEY_REGISTERED,
            actor_user_id=user.id,
            ciphertext="AAAA-secret-body",
            password="hunter2",
            mac_key="deadbeef",
            fingerprint="safe-to-log",
        )
        assert entry.details["ciphertext"] == "<redacted>"
        assert entry.details["password"] == "<redacted>"
        assert entry.details["mac_key"] == "<redacted>"
        assert entry.details["fingerprint"] == "safe-to-log"

    def test_truncates_long_values(self, db, user):
        entry = AuditService.record(db, AuditAction.USER_LOGIN, actor_user_id=user.id, blob="x" * 5000)
        assert "omitted" in entry.details["blob"]

    def test_filters_by_action_and_user(self, db, user, admin):
        AuditService.record(db, AuditAction.USER_LOGIN, actor_user_id=user.id)
        AuditService.record(db, AuditAction.USER_LOGOUT, actor_user_id=admin.id)
        assert len(AuditService.recent(db, actions=[AuditAction.USER_LOGIN])) == 1
        assert len(AuditService.recent(db, user_id=admin.id)) == 1

    def test_severity_is_recorded(self, db, user):
        entry = AuditService.record(
            db,
            AuditAction.KEY_REJECTED_SECRET_PRESENT,
            actor_user_id=user.id,
            severity=AuditSeverity.CRITICAL,
        )
        assert entry.severity is AuditSeverity.CRITICAL
