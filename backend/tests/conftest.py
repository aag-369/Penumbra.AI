"""Shared pytest fixtures.

Design points worth knowing before adding tests:

* The database is a **file-backed** temporary SQLite database, not
  ``:memory:``. FastAPI's ``BackgroundTasks`` and the WebSocket handler open
  their own sessions, and an in-memory SQLite database is per-connection, so
  those sessions would see an empty schema.
* CKKS keys are generated **once per session** and reused. Key generation with
  rotation keys takes over a second and produces 35 MB; regenerating per test
  would dominate the run time.
* Every test that needs a keystore gets a temporary directory, so runs do not
  leak 35 MB blobs into the repository.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Iterator

import pytest

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("JWT_SECRET", "test-secret-not-used-outside-the-suite-0123456789")
os.environ.setdefault("DEBUG", "true")
# bcrypt at cost 12 makes the auth tests take seconds; 10 is the documented floor.
os.environ.setdefault("BCRYPT_ROUNDS", "10")

_TMP = Path(tempfile.mkdtemp(prefix="penumbra-test-"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TMP / 'test.db'}")
os.environ.setdefault("KEYSTORE_DIR", str(_TMP / "keystore"))

from app.config import get_settings, settings  # noqa: E402
from app.crypto.ckks_engine import (  # noqa: E402
    DEFAULT_PARAMETERS,
    LIGHT_PARAMETERS,
    CKKSEngine,
)
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.services.keystore_service import KeystoreService, get_keystore  # noqa: E402
from app.services.user_service import UserService  # noqa: E402


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def _schema() -> Iterator[None]:
    import app.models  # noqa: F401 -- registers the mappers

    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db() -> Iterator:
    """A session that is rolled back and cleaned after each test."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(table.delete())
        session.commit()
        session.close()


# ---------------------------------------------------------------------------
# Crypto -- generated once, reused everywhere
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def light_client() -> CKKSEngine:
    """Private engine without rotation keys. ~1.9 MB context, fast."""
    return CKKSEngine.create_client(LIGHT_PARAMETERS)


@pytest.fixture(scope="session")
def light_server(light_client: CKKSEngine) -> CKKSEngine:
    return CKKSEngine.from_public_context(light_client.export_public_context())


@pytest.fixture(scope="session")
def full_client() -> CKKSEngine:
    """Private engine with rotation keys. Needed for any reduction."""
    return CKKSEngine.create_client(DEFAULT_PARAMETERS)


@pytest.fixture(scope="session")
def full_server(full_client: CKKSEngine) -> CKKSEngine:
    return CKKSEngine.from_public_context(full_client.export_public_context())


@pytest.fixture
def keystore(tmp_path: Path) -> KeystoreService:
    """A keystore rooted in this test's temporary directory."""
    return KeystoreService(tmp_path / "keystore")


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


@pytest.fixture
def user(db):
    from app.models.user import UserRole

    u = UserService.create_user(db, "user@example.com", "correct-horse-9", UserRole.USER)
    db.commit()
    return u


@pytest.fixture
def admin(db):
    from app.models.user import UserRole

    u = UserService.create_user(db, "admin@example.com", "correct-horse-9", UserRole.ADMIN)
    db.commit()
    return u


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------


@pytest.fixture
def client(db, keystore) -> Iterator:
    """TestClient with the request session and keystore overridden."""
    from fastapi.testclient import TestClient

    from app.api.v1.dependencies import get_channel
    from app.crypto.post_quantum_channel import PostQuantumChannel
    from app.database import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_keystore] = lambda: keystore
    app.dependency_overrides[get_channel] = lambda: PostQuantumChannel(use_bb84_simulation=False)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers(client) -> dict[str, str]:
    """Register a user through the API and return their bearer header."""
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "api-user@example.com", "password": "correct-horse-9"},
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    """Keep the settings singleton consistent across tests."""
    yield
    get_settings.cache_clear()
    get_settings()
