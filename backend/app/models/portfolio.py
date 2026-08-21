"""Encrypted portfolios.

Layout decision
---------------
A portfolio is stored as **one** ciphertext holding the whole holdings vector,
plus a plaintext list of tickers giving the slot order. The spec had one
ciphertext per ticker; at the default parameters a CKKS ciphertext costs ~330 kB
whether it carries one value or four thousand, so per-ticker storage multiplies
the footprint by the number of assets for no benefit. See
``docs/SPEC_DEVIATIONS.md`` #2.

What the server learns
----------------------
The tickers and the number of assets. Not the quantities, not the cost basis,
not the portfolio value. Whether ticker identity should also be hidden is a
real design question -- it is discussed under "residual leakage" in
``docs/CRYPTO_ASSUMPTIONS.md``, along with the padding scheme that would fix it.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from .base import Timestamped, UUIDPrimaryKey

if TYPE_CHECKING:
    from .user import User


class Portfolio(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "portfolios"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    encryption_key_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("encryption_keys.id", ondelete="RESTRICT"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(128), default="My Portfolio", nullable=False)

    #: JSON array of tickers. Index i names the asset in slot i of every
    #: ciphertext below, so all three vectors share one ordering.
    tickers_json: Mapped[str] = mapped_column(Text, nullable=False)
    n_assets: Mapped[int] = mapped_column(Integer, nullable=False)

    #: Base64 CKKS ciphertexts. Opaque to the server.
    holdings_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    cost_basis_ciphertext: Mapped[str | None] = mapped_column(Text)

    ciphertext_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    user: Mapped["User"] = relationship(back_populates="portfolios")

    @property
    def tickers(self) -> list[str]:
        return json.loads(self.tickers_json)

    @tickers.setter
    def tickers(self, value: list[str]) -> None:
        self.tickers_json = json.dumps(list(value))
        self.n_assets = len(value)

    def __repr__(self) -> str:
        return f"<Portfolio {self.name} assets={self.n_assets} user={self.user_id}>"
