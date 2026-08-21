"""Portfolio validation and persistence.

The server sees tickers and slot counts. It never sees quantities: those arrive
already encrypted from the browser. This module's job is to make sure the
*shape* of what arrives is coherent -- that the ticker list matches the
ciphertext's declared length, that the ciphertext parses under the user's
registered key, and that limits are respected -- before anything is stored.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass
from typing import Sequence

from sqlalchemy import desc
from sqlalchemy.orm import Session

from ..config import settings
from ..crypto.ckks_engine import CiphertextError, CKKSEngine
from ..models.portfolio import Portfolio
from .keystore_service import KeystoreService, get_keystore

logger = logging.getLogger(__name__)

#: Permissive enough for US equities, ETFs, class shares (BRK.B) and the
#: hyphenated forms some vendors use. Not a claim that the symbol trades.
TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{0,9}([.\-][A-Z]{1,4})?$")

REQUIRED_CSV_COLUMNS = ("ticker", "quantity")
OPTIONAL_CSV_COLUMNS = ("cost_basis",)


class PortfolioError(Exception):
    """Base class for portfolio failures."""


class ValidationFailed(PortfolioError):
    """The submitted portfolio is malformed. Message lists every problem found."""


class PortfolioNotFound(PortfolioError):
    """No such portfolio for this user."""


@dataclass(frozen=True)
class ParsedPortfolio:
    """A client-side CSV parse. Exists on the server only for the reference path.

    In the normal flow the browser parses the CSV, encrypts, and uploads
    ciphertext -- this class never sees a real user's numbers. It is used by
    tests, by the seed script, and by the ``--local`` CLI mode where a user
    deliberately chooses to let the server do the encryption.
    """

    tickers: tuple[str, ...]
    quantities: tuple[float, ...]
    cost_basis: tuple[float, ...] | None

    def __len__(self) -> int:
        return len(self.tickers)


class PortfolioService:
    # -- validation ---------------------------------------------------------
    @staticmethod
    def validate_tickers(tickers: Sequence[str]) -> list[str]:
        """Normalise and validate a ticker list.

        Raises:
            ValidationFailed: with every problem listed at once, so a user
                fixing a CSV does not have to resubmit once per error.
        """
        problems: list[str] = []
        if not tickers:
            problems.append("portfolio is empty")
        if len(tickers) > settings.max_assets_per_portfolio:
            problems.append(
                f"{len(tickers)} assets exceeds the limit of {settings.max_assets_per_portfolio}"
            )

        normalised: list[str] = []
        seen: set[str] = set()
        for raw in tickers:
            t = str(raw).strip().upper()
            if not TICKER_PATTERN.match(t):
                problems.append(f"{raw!r} is not a valid ticker symbol")
                continue
            if t in seen:
                problems.append(f"{t} appears more than once; combine the rows")
                continue
            seen.add(t)
            normalised.append(t)

        if problems:
            raise ValidationFailed("; ".join(problems))
        return normalised

    @staticmethod
    def parse_csv(content: bytes | str) -> ParsedPortfolio:
        """Parse a portfolio CSV into plaintext vectors.

        Expected columns: ``ticker``, ``quantity``, and optionally
        ``cost_basis``. Column order does not matter; header case does not
        matter.
        """
        text = content.decode("utf-8-sig") if isinstance(content, bytes) else content
        if len(text.encode("utf-8")) > settings.max_upload_bytes:
            raise ValidationFailed(
                f"file exceeds the {settings.max_upload_bytes // 1024} kB upload limit"
            )

        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            raise ValidationFailed("file is empty or has no header row")

        columns = {(name or "").strip().lower(): name for name in reader.fieldnames}
        missing = [c for c in REQUIRED_CSV_COLUMNS if c not in columns]
        if missing:
            raise ValidationFailed(
                f"missing required column(s): {', '.join(missing)}. "
                f"Expected header: {', '.join(REQUIRED_CSV_COLUMNS + OPTIONAL_CSV_COLUMNS)}"
            )

        tickers: list[str] = []
        quantities: list[float] = []
        cost_basis: list[float] = []
        has_cost = "cost_basis" in columns
        problems: list[str] = []

        for line_no, row in enumerate(reader, start=2):
            ticker = (row.get(columns["ticker"]) or "").strip()
            if not ticker:
                continue  # tolerate trailing blank lines
            try:
                qty = float((row.get(columns["quantity"]) or "").replace(",", ""))
            except ValueError:
                problems.append(f"line {line_no}: quantity is not a number")
                continue
            if qty < 0:
                problems.append(f"line {line_no}: negative quantity (short positions are not supported)")
                continue

            tickers.append(ticker)
            quantities.append(qty)

            if has_cost:
                raw_cost = (row.get(columns["cost_basis"]) or "").strip().replace(",", "")
                try:
                    cost_basis.append(float(raw_cost) if raw_cost else 0.0)
                except ValueError:
                    problems.append(f"line {line_no}: cost_basis is not a number")

        if problems:
            raise ValidationFailed("; ".join(problems))

        validated = PortfolioService.validate_tickers(tickers)
        return ParsedPortfolio(
            tickers=tuple(validated),
            quantities=tuple(quantities),
            cost_basis=tuple(cost_basis) if has_cost and cost_basis else None,
        )

    # -- persistence --------------------------------------------------------
    @staticmethod
    def create(
        db: Session,
        user_id: str,
        *,
        tickers: Sequence[str],
        holdings_ciphertext: str,
        cost_basis_ciphertext: str | None = None,
        name: str = "My Portfolio",
        keystore: KeystoreService | None = None,
    ) -> Portfolio:
        """Store an encrypted portfolio.

        The ciphertext is parsed -- not decrypted -- against the user's active
        public context, which catches a client that encrypted under the wrong
        key before the error surfaces three agents deep in the pipeline.

        Raises:
            ValidationFailed: on bad tickers, oversized or unparseable ciphertext.
            KeyNotFound: if the user has not registered a public context.

        Args:
            keystore: injected for tests; defaults to the process keystore.
        """
        validated = PortfolioService.validate_tickers(tickers)

        size = len(holdings_ciphertext.encode("ascii"))
        if size > settings.max_ciphertext_bytes:
            raise ValidationFailed(
                f"ciphertext is {size / 1e6:.1f} MB, limit is "
                f"{settings.max_ciphertext_bytes / 1e6:.0f} MB"
            )

        keystore = keystore or get_keystore()
        key = keystore.active_key(db, user_id)
        engine = keystore.engine_for_key(key)
        try:
            engine.load_vector(holdings_ciphertext)
            if cost_basis_ciphertext:
                engine.load_vector(cost_basis_ciphertext)
        except CiphertextError as exc:
            raise ValidationFailed(
                f"ciphertext does not parse under your registered key {key.fingerprint}: {exc}"
            ) from exc

        if len(validated) > key.slot_count:
            raise ValidationFailed(
                f"{len(validated)} assets exceeds the {key.slot_count} slots available at "
                f"N={key.poly_modulus_degree}; split the portfolio or use larger parameters"
            )

        db.query(Portfolio).filter(
            Portfolio.user_id == user_id, Portfolio.is_active.is_(True)
        ).update({"is_active": False}, synchronize_session=False)

        portfolio = Portfolio(
            user_id=user_id,
            encryption_key_id=key.id,
            name=name,
            holdings_ciphertext=holdings_ciphertext,
            cost_basis_ciphertext=cost_basis_ciphertext,
            ciphertext_bytes=size + len((cost_basis_ciphertext or "").encode("ascii")),
        )
        portfolio.tickers = validated
        db.add(portfolio)
        db.flush()
        logger.info(
            "stored portfolio %s for user %s: %d assets, %.2f MB ciphertext",
            portfolio.id, user_id, len(validated), portfolio.ciphertext_bytes / 1e6,
        )
        return portfolio

    @staticmethod
    def current(db: Session, user_id: str) -> Portfolio:
        """The user's active portfolio."""
        portfolio = (
            db.query(Portfolio)
            .filter(Portfolio.user_id == user_id, Portfolio.is_active.is_(True))
            .order_by(desc(Portfolio.created_at))
            .first()
        )
        if portfolio is None:
            raise PortfolioNotFound("no portfolio uploaded yet")
        return portfolio

    @staticmethod
    def get(db: Session, user_id: str, portfolio_id: str) -> Portfolio:
        """A specific portfolio, scoped to its owner."""
        portfolio = (
            db.query(Portfolio)
            .filter(Portfolio.id == portfolio_id, Portfolio.user_id == user_id)
            .one_or_none()
        )
        if portfolio is None:
            raise PortfolioNotFound(f"portfolio {portfolio_id} not found")
        return portfolio

    @staticmethod
    def history(db: Session, user_id: str, *, limit: int = 20) -> list[Portfolio]:
        """All of a user's portfolios, newest first."""
        return (
            db.query(Portfolio)
            .filter(Portfolio.user_id == user_id)
            .order_by(desc(Portfolio.created_at))
            .limit(limit)
            .all()
        )

    @staticmethod
    def delete(db: Session, user_id: str, portfolio_id: str) -> None:
        """Hard-delete a portfolio and its ciphertext."""
        portfolio = PortfolioService.get(db, user_id, portfolio_id)
        db.delete(portfolio)
        db.flush()

    # -- reference encryption path -----------------------------------------
    @staticmethod
    def encrypt_locally(engine: CKKSEngine, parsed: ParsedPortfolio) -> dict[str, str | list[str]]:
        """Encrypt a parsed portfolio with a *private* engine.

        Only meaningful on the client, or in tests. Included so the reference
        implementation of what the browser does is executable and testable in
        Python rather than existing only as TypeScript.
        """
        if not engine.is_private:
            raise PortfolioError("encrypt_locally needs a private engine; this is a client operation")
        out: dict[str, str | list[str]] = {
            "tickers": list(parsed.tickers),
            "holdings_ciphertext": engine.encrypt(parsed.quantities),
        }
        if parsed.cost_basis:
            out["cost_basis_ciphertext"] = engine.encrypt(parsed.cost_basis)
        return out

