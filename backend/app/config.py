"""Application configuration, loaded from the environment.

Everything secret comes from environment variables or a ``.env`` file. Nothing
secret has a usable default: :meth:`Settings.assert_production_ready` refuses to
start with development placeholders when ``ENVIRONMENT=production``.
"""

from __future__ import annotations

import functools
import json
import secrets
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent

#: Sentinel used as the development JWT secret. Refused in production.
DEV_SECRET_PLACEHOLDER = "dev-only-insecure-change-me"


class Settings(BaseSettings):
    """Runtime configuration."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # -- application --------------------------------------------------------
    app_name: str = "PENUMBRA.AI"
    environment: Literal["development", "test", "staging", "production"] = "development"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"

    # -- database -----------------------------------------------------------
    #: SQLite by default so the stack runs with no external services. Point
    #: this at PostgreSQL for anything beyond local development.
    database_url: str = f"sqlite:///{BASE_DIR / 'penumbra.db'}"
    database_echo: bool = False

    # -- authentication -----------------------------------------------------
    jwt_secret: str = DEV_SECRET_PLACEHOLDER
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 3600
    refresh_token_ttl_seconds: int = 60 * 60 * 24 * 14
    bcrypt_rounds: int = Field(default=12, ge=10, le=16)

    # -- rate limiting ------------------------------------------------------
    login_max_attempts: int = 5
    login_lockout_seconds: int = 900

    # -- cryptography -------------------------------------------------------
    #: CKKS public contexts are 35 MB with rotation keys at N=8192 and 180 MB
    #: at N=16384, so they are written to this directory rather than into a
    #: database column. Production should point this at object storage.
    keystore_dir: Path = BASE_DIR / "keystore"
    max_public_context_bytes: int = 256 * 1024 * 1024
    max_ciphertext_bytes: int = 64 * 1024 * 1024
    enable_bb84_simulation: bool = False
    session_ttl_seconds: int = 3600

    # -- portfolio limits ---------------------------------------------------
    max_assets_per_portfolio: int = 200
    max_upload_bytes: int = 5 * 1024 * 1024

    # -- agents / LLM -------------------------------------------------------
    anthropic_api_key: str | None = None
    llm_model: str = "claude-sonnet-4-5"
    llm_max_tokens: int = 4096
    agent_timeout_seconds: int = 300

    # -- optimisation -------------------------------------------------------
    qaoa_layers: int = 3
    qaoa_max_iterations: int = 100
    qaoa_shots: int = 2048
    max_qubits: int = 20

    # -- CORS ---------------------------------------------------------------
    #: ``NoDecode`` matters: without it pydantic-settings JSON-decodes list
    #: fields from ``.env`` and the environment *before* any validator runs, so
    #: the comma-separated form in ``.env.example`` failed to start the app.
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        """Accept a comma-separated string, or a JSON list, from the environment."""
        if isinstance(v, str):
            if v.strip().startswith("["):
                return json.loads(v)
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    # -- derived ------------------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    def assert_production_ready(self) -> None:
        """Fail fast on placeholder secrets in a production deployment."""
        if not self.is_production:
            return
        problems: list[str] = []
        if self.jwt_secret == DEV_SECRET_PLACEHOLDER or len(self.jwt_secret) < 32:
            problems.append("JWT_SECRET must be set to at least 32 random characters")
        if self.debug:
            problems.append("DEBUG must be false in production")
        if self.is_sqlite:
            problems.append("DATABASE_URL must point at PostgreSQL in production")
        if any(o.startswith("http://") for o in self.cors_origins):
            problems.append("CORS_ORIGINS must use https in production")
        if problems:
            raise RuntimeError(
                "refusing to start in production:\n  - " + "\n  - ".join(problems)
            )

    @staticmethod
    def generate_secret() -> str:
        """Produce a JWT secret suitable for ``.env``."""
        return secrets.token_urlsafe(48)


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    settings = Settings()
    settings.keystore_dir.mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()
