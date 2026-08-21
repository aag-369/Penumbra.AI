"""Portfolio request and response models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class EncryptedPortfolioUpload(BaseModel):
    """The normal upload path: the browser encrypts, the server stores.

    ``tickers[i]`` names the asset in slot ``i`` of every ciphertext, so the
    ordering is shared across holdings and cost basis.
    """

    tickers: list[str] = Field(min_length=1, max_length=200)
    holdings_ciphertext: str = Field(repr=False)
    cost_basis_ciphertext: str | None = Field(default=None, repr=False)
    name: str = Field(default="My Portfolio", max_length=128)


class PortfolioOut(BaseModel):
    """A stored portfolio. Ciphertexts are omitted; fetch them explicitly."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    tickers: list[str]
    n_assets: int
    ciphertext_bytes: int
    encryption_key_id: str
    is_active: bool
    created_at: datetime


class PortfolioWithCiphertext(PortfolioOut):
    """A portfolio including its ciphertexts, for client-side decryption."""

    holdings_ciphertext: str = Field(repr=False)
    cost_basis_ciphertext: str | None = Field(default=None, repr=False)


class CsvValidationResult(BaseModel):
    """Result of a dry-run CSV check.

    Only the *shape* is returned -- tickers and row count. Quantities parsed
    here are discarded; this endpoint exists so the browser can surface format
    errors before it spends time on encryption.
    """

    valid: bool
    n_assets: int
    tickers: list[str]
    has_cost_basis: bool
    problems: list[str] = []
