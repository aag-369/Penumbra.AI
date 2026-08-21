"""End-to-end API tests.

These drive the real FastAPI application through a TestClient, with only the
database session and keystore overridden. They cover the full journey a user
takes: register, generate a keypair in "the browser", register its public half,
encrypt a portfolio, upload it, and read it back.
"""

from __future__ import annotations

import pytest

from app.crypto.ckks_engine import CKKSEngine, LIGHT_PARAMETERS
from app.services.portfolio_service import PortfolioService

CSV = "ticker,quantity,cost_basis\nAAPL,100,150.0\nMSFT,50,300.5\nBRK.B,10,400\n"


@pytest.fixture
def registered(client, auth_headers, light_client):
    """A user with a registered public context."""
    response = client.post(
        "/api/v1/portfolio/keys",
        json={"public_context": light_client.export_public_context(), "label": "browser key"},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return auth_headers, response.json()


class TestHealth:
    def test_health_is_unauthenticated(self, client):
        assert client.get("/health").json()["status"] == "ok"

    def test_root_describes_the_privacy_property(self, client):
        assert "no secret key" in client.get("/").json()["privacy"]

    def test_openapi_is_served(self, client):
        assert "/api/v1/auth/login" in client.get("/openapi.json").json()["paths"]


class TestAuthFlow:
    def test_register_returns_tokens(self, client):
        response = client.post(
            "/api/v1/auth/register",
            json={"email": "new@example.com", "password": "correct-horse-9"},
        )
        assert response.status_code == 201
        assert response.json()["access_token"]

    def test_first_user_becomes_the_administrator(self, client):
        response = client.post(
            "/api/v1/auth/register", json={"email": "first@example.com", "password": "correct-horse-9"}
        )
        assert response.json()["role"] == "admin"

    def test_second_user_is_an_ordinary_user(self, client):
        client.post(
            "/api/v1/auth/register", json={"email": "first@example.com", "password": "correct-horse-9"}
        )
        response = client.post(
            "/api/v1/auth/register", json={"email": "second@example.com", "password": "correct-horse-9"}
        )
        assert response.json()["role"] == "user"

    def test_duplicate_registration_is_not_an_enumeration_oracle(self, client):
        payload = {"email": "dup@example.com", "password": "correct-horse-9"}
        client.post("/api/v1/auth/register", json=payload)
        response = client.post("/api/v1/auth/register", json=payload)
        assert response.status_code == 401
        assert "cannot be registered" in response.json()["detail"]

    def test_weak_password_is_rejected_with_a_reason(self, client):
        response = client.post(
            "/api/v1/auth/register", json={"email": "weak@example.com", "password": "short"}
        )
        assert response.status_code == 422
        assert response.json()["code"] == "request_invalid"

    def test_login_and_me(self, client):
        client.post(
            "/api/v1/auth/register", json={"email": "who@example.com", "password": "correct-horse-9"}
        )
        login = client.post(
            "/api/v1/auth/login", json={"email": "who@example.com", "password": "correct-horse-9"}
        )
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        assert client.get("/api/v1/auth/me", headers=headers).json()["email"] == "who@example.com"

    def test_wrong_password_returns_401(self, client):
        client.post(
            "/api/v1/auth/register", json={"email": "who@example.com", "password": "correct-horse-9"}
        )
        response = client.post(
            "/api/v1/auth/login", json={"email": "who@example.com", "password": "nope"}
        )
        assert response.status_code == 401
        assert response.json()["code"] == "invalid_credentials"

    def test_protected_route_requires_a_token(self, client):
        assert client.get("/api/v1/auth/me").status_code == 401

    def test_logout_invalidates_the_token(self, client, auth_headers):
        assert client.post("/api/v1/auth/logout", headers=auth_headers).status_code == 200
        assert client.get("/api/v1/auth/me", headers=auth_headers).status_code == 401

    def test_refresh_issues_a_new_pair(self, client):
        registered = client.post(
            "/api/v1/auth/register", json={"email": "r@example.com", "password": "correct-horse-9"}
        ).json()
        response = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": registered["refresh_token"]}
        )
        assert response.status_code == 200
        assert response.json()["access_token"]

    def test_an_access_token_cannot_be_used_to_refresh(self, client):
        registered = client.post(
            "/api/v1/auth/register", json={"email": "r@example.com", "password": "correct-horse-9"}
        ).json()
        response = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": registered["access_token"]}
        )
        assert response.status_code == 401


class TestKeyRegistration:
    def test_public_context_is_accepted(self, client, auth_headers, light_client):
        response = client.post(
            "/api/v1/portfolio/keys",
            json={"public_context": light_client.export_public_context()},
            headers=auth_headers,
        )
        assert response.status_code == 201
        body = response.json()
        assert body["fingerprint"] == light_client.key_id
        assert body["security_level_bits"] >= 128

    def test_a_context_containing_a_secret_key_is_refused(self, client, auth_headers, light_client):
        """The single most important API test: the server will not take the secret."""
        response = client.post(
            "/api/v1/portfolio/keys",
            json={"public_context": light_client.export_private_context()},
            headers=auth_headers,
        )
        assert response.status_code == 400
        assert response.json()["code"] == "secret_key_rejected"

    def test_the_refusal_is_audited_as_critical(self, client, auth_headers, light_client, db):
        from app.models.audit_log import AuditAction, AuditSeverity

        client.post(
            "/api/v1/portfolio/keys",
            json={"public_context": light_client.export_private_context()},
            headers=auth_headers,
        )
        from app.services.audit_service import AuditService

        rows = AuditService.recent(db, actions=[AuditAction.KEY_REJECTED_SECRET_PRESENT])
        assert rows and rows[0].severity is AuditSeverity.CRITICAL

    def test_there_is_no_server_side_keypair_endpoint(self, client):
        """A regression guard: the original spec had one, and it was the bug."""
        paths = client.get("/openapi.json").json()["paths"]
        assert not any("generate-keypair" in p for p in paths)

    def test_inspect_reports_real_parameters(self, client, auth_headers, light_client):
        response = client.post(
            "/api/v1/portfolio/keys/inspect",
            json={"public_context": light_client.export_public_context()},
            headers=auth_headers,
        )
        body = response.json()
        assert body["poly_modulus_degree"] == LIGHT_PARAMETERS.poly_modulus_degree
        assert body["has_galois_keys"] is False
        assert body["security_level_bits"] >= 128

    def test_active_key_is_reported(self, client, registered):
        headers, key = registered
        assert client.get("/api/v1/portfolio/keys/active", headers=headers).json()["id"] == key["id"]

    def test_missing_key_returns_404(self, client, auth_headers):
        response = client.get("/api/v1/portfolio/keys/active", headers=auth_headers)
        assert response.status_code == 404
        assert response.json()["code"] == "encryption_key_not_found"


class TestPortfolioFlow:
    def test_csv_validation_returns_shape_only(self, client, auth_headers):
        response = client.post(
            "/api/v1/portfolio/validate-csv",
            files={"file": ("portfolio.csv", CSV, "text/csv")},
            headers=auth_headers,
        )
        body = response.json()
        assert body["valid"] is True
        assert body["tickers"] == ["AAPL", "MSFT", "BRK.B"]
        assert "quantities" not in body, "the server must not echo back what it parsed"

    def test_csv_validation_reports_problems(self, client, auth_headers):
        response = client.post(
            "/api/v1/portfolio/validate-csv",
            files={"file": ("bad.csv", "ticker,quantity\nAAPL,abc\n", "text/csv")},
            headers=auth_headers,
        )
        assert response.json()["valid"] is False
        assert response.json()["problems"]

    def test_upload_and_read_back(self, client, registered, light_client):
        headers, _ = registered
        parsed = PortfolioService.parse_csv(CSV)
        payload = PortfolioService.encrypt_locally(light_client, parsed)

        created = client.post(
            "/api/v1/portfolio/",
            json={
                "tickers": payload["tickers"],
                "holdings_ciphertext": payload["holdings_ciphertext"],
                "cost_basis_ciphertext": payload["cost_basis_ciphertext"],
                "name": "Retirement",
            },
            headers=headers,
        )
        assert created.status_code == 201, created.text
        assert created.json()["tickers"] == ["AAPL", "MSFT", "BRK.B"]

        fetched = client.get("/api/v1/portfolio/current", headers=headers).json()
        decrypted = light_client.decrypt(fetched["holdings_ciphertext"], size=3)
        assert decrypted == pytest.approx([100.0, 50.0, 10.0], abs=1e-4)

    def test_the_server_never_returns_plaintext_holdings(self, client, registered, light_client):
        """Scan every field of the response for the user's real numbers."""
        headers, _ = registered
        parsed = PortfolioService.parse_csv(CSV)
        payload = PortfolioService.encrypt_locally(light_client, parsed)
        client.post(
            "/api/v1/portfolio/",
            json={
                "tickers": payload["tickers"],
                "holdings_ciphertext": payload["holdings_ciphertext"],
            },
            headers=headers,
        )
        body = client.get("/api/v1/portfolio/current", headers=headers).json()
        body.pop("holdings_ciphertext")
        body.pop("cost_basis_ciphertext", None)
        serialised = str(body)
        for quantity in ("100.0", "50.0", "300.5", "150.0"):
            assert quantity not in serialised

    def test_upload_without_a_key_fails(self, client, auth_headers, light_client):
        response = client.post(
            "/api/v1/portfolio/",
            json={"tickers": ["AAPL"], "holdings_ciphertext": light_client.encrypt([1.0])},
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_ciphertext_from_the_wrong_key_is_rejected(self, client, registered, full_client):
        headers, _ = registered
        response = client.post(
            "/api/v1/portfolio/",
            json={"tickers": ["AAPL"], "holdings_ciphertext": full_client.encrypt([1.0])},
            headers=headers,
        )
        assert response.status_code == 422
        assert "registered key" in response.json()["detail"]

    def test_invalid_tickers_are_rejected(self, client, registered, light_client):
        headers, _ = registered
        response = client.post(
            "/api/v1/portfolio/",
            json={"tickers": ["123$"], "holdings_ciphertext": light_client.encrypt([1.0])},
            headers=headers,
        )
        assert response.status_code == 422

    def test_delete(self, client, registered, light_client):
        headers, _ = registered
        created = client.post(
            "/api/v1/portfolio/",
            json={"tickers": ["AAPL"], "holdings_ciphertext": light_client.encrypt([1.0])},
            headers=headers,
        ).json()
        assert client.delete(f"/api/v1/portfolio/{created['id']}", headers=headers).status_code == 200
        assert client.get("/api/v1/portfolio/current", headers=headers).status_code == 404

    def test_another_user_cannot_read_this_portfolio(self, client, registered, light_client):
        headers, _ = registered
        created = client.post(
            "/api/v1/portfolio/",
            json={"tickers": ["AAPL"], "holdings_ciphertext": light_client.encrypt([1.0])},
            headers=headers,
        ).json()
        other = client.post(
            "/api/v1/auth/register", json={"email": "other@example.com", "password": "correct-horse-9"}
        ).json()
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}
        assert (
            client.get(f"/api/v1/portfolio/{created['id']}", headers=other_headers).status_code == 404
        )


class TestSessions:
    def test_open_and_close(self, client, registered):
        headers, key = registered
        opened = client.post("/api/v1/portfolio/session", json={}, headers=headers)
        assert opened.status_code == 200
        body = opened.json()
        assert body["key_fingerprint"] == key["fingerprint"]
        assert body["mac_key"]
        assert (
            client.delete(f"/api/v1/portfolio/session/{body['session_id']}", headers=headers).status_code
            == 200
        )

    def test_session_requires_a_registered_key(self, client, auth_headers):
        assert client.post("/api/v1/portfolio/session", json={}, headers=auth_headers).status_code == 404


class TestUnimplementedSurfaces:
    """Phase 2/4 endpoints answer 501, not 500 and not a fake success."""

    def test_chat_turn_reports_not_implemented(self, client, auth_headers):
        response = client.post("/api/v1/chat/turn", json={"message": "hello"}, headers=auth_headers)
        assert response.status_code == 501
        assert response.json()["code"] == "not_implemented"

    def test_advisory_job_is_created_then_fails_honestly(self, client, registered, light_client):
        headers, _ = registered
        client.post(
            "/api/v1/portfolio/",
            json={"tickers": ["AAPL"], "holdings_ciphertext": light_client.encrypt([1.0])},
            headers=headers,
        )
        queued = client.post(
            "/api/v1/advisor/generate",
            json={"goals": {"risk_tolerance": 6, "horizon_years": 5}},
            headers=headers,
        )
        assert queued.status_code == 202
        job_id = queued.json()["id"]

        polled = client.get(f"/api/v1/advisor/jobs/{job_id}", headers=headers).json()
        assert polled["status"] == "failed"
        assert "NotImplementedError" in polled["error_message"]
        assert polled["recommendation_ciphertext"] is None

    def test_advisory_goals_are_validated(self, client, registered, light_client):
        headers, _ = registered
        client.post(
            "/api/v1/portfolio/",
            json={"tickers": ["AAPL"], "holdings_ciphertext": light_client.encrypt([1.0])},
            headers=headers,
        )
        response = client.post(
            "/api/v1/advisor/generate",
            json={"goals": {"risk_tolerance": 99, "horizon_years": 5}},
            headers=headers,
        )
        assert response.status_code == 422


class TestAdminSurface:
    @pytest.fixture
    def admin_headers(self, client):
        response = client.post(
            "/api/v1/auth/register", json={"email": "boss@example.com", "password": "correct-horse-9"}
        ).json()
        assert response["role"] == "admin"
        return {"Authorization": f"Bearer {response['access_token']}"}

    def test_ordinary_users_are_refused(self, client, admin_headers):
        user = client.post(
            "/api/v1/auth/register", json={"email": "peon@example.com", "password": "correct-horse-9"}
        ).json()
        headers = {"Authorization": f"Bearer {user['access_token']}"}
        assert client.get("/api/v1/admin/users", headers=headers).status_code == 403

    def test_lists_users(self, client, admin_headers):
        response = client.get("/api/v1/admin/users", headers=admin_headers)
        assert response.status_code == 200
        assert response.json()[0]["email"] == "boss@example.com"

    def test_system_health_runs_a_real_crypto_selftest(self, client, admin_headers):
        body = client.get("/api/v1/admin/system-health", headers=admin_headers).json()
        assert body["database_ok"] is True
        assert body["crypto_ok"] is True
        assert body["crypto_selftest_ms"] > 0

    def test_encryption_stats(self, client, admin_headers, light_client):
        client.post(
            "/api/v1/portfolio/keys",
            json={"public_context": light_client.export_public_context()},
            headers=admin_headers,
        )
        body = client.get("/api/v1/admin/encryption-stats", headers=admin_headers).json()
        assert body["active_keys"] == 1
        assert body["total_megabytes"] > 0

    def test_audit_log_is_populated_and_carries_no_secrets(self, client, admin_headers, light_client):
        client.post(
            "/api/v1/portfolio/keys",
            json={"public_context": light_client.export_public_context()},
            headers=admin_headers,
        )
        rows = client.get("/api/v1/admin/audit-logs", headers=admin_headers).json()
        assert any(r["action"] == "key_registered" for r in rows)
        serialised = str(rows)
        assert light_client.export_public_context()[:200] not in serialised

    def test_admin_cannot_deactivate_themselves(self, client, admin_headers):
        me = client.get("/api/v1/auth/me", headers=admin_headers).json()
        response = client.post(f"/api/v1/admin/users/{me['id']}/deactivate", headers=admin_headers)
        assert response.status_code == 422

    def test_deactivation_signs_the_user_out(self, client, admin_headers):
        user = client.post(
            "/api/v1/auth/register", json={"email": "doomed@example.com", "password": "correct-horse-9"}
        ).json()
        headers = {"Authorization": f"Bearer {user['access_token']}"}
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
        client.post(f"/api/v1/admin/users/{user['user_id']}/deactivate", headers=admin_headers)
        assert client.get("/api/v1/auth/me", headers=headers).status_code in (401, 403)


class TestResponseHygiene:
    def test_security_headers_are_set(self, client):
        headers = client.get("/health").headers
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "DENY"

    def test_request_id_is_echoed(self, client):
        response = client.get("/health", headers={"X-Request-Id": "abc123"})
        assert response.headers["x-request-id"] == "abc123"

    def test_errors_use_the_standard_envelope(self, client):
        body = client.get("/api/v1/auth/me").json()
        assert "detail" in body
