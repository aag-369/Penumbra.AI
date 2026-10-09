"""Configuration must load from the files and variables the docs tell people to use."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings

BACKEND = Path(__file__).resolve().parents[2]


def test_env_example_loads_as_a_dotenv_file(monkeypatch: pytest.MonkeyPatch) -> None:
    # `cp .env.example .env` is the documented first step; it has to start.
    # Real environment variables outrank the file, so clear the suite's own.
    for name in ("ENVIRONMENT", "CORS_ORIGINS"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings(_env_file=BACKEND / ".env.example")
    assert settings.cors_origins == ["http://localhost:3000", "http://127.0.0.1:3000"]
    assert settings.environment == "development"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://a.test,http://b.test", ["http://a.test", "http://b.test"]),
        (" http://a.test , ", ["http://a.test"]),
        ('["https://app.example"]', ["https://app.example"]),
    ],
)
def test_cors_origins_from_the_environment(monkeypatch: pytest.MonkeyPatch, raw: str, expected: list[str]) -> None:
    monkeypatch.setenv("CORS_ORIGINS", raw)
    assert Settings(_env_file=None).cors_origins == expected
