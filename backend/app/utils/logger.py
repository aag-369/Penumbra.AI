"""Logging setup."""

from __future__ import annotations

import logging
import sys

from ..config import settings

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def configure_logging(level: int | None = None) -> None:
    """Configure root logging once, at startup."""
    resolved = level if level is not None else (logging.DEBUG if settings.debug else logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(resolved)

    # SQLAlchemy's INFO level prints every statement, which on this API means
    # printing megabyte-long ciphertext parameters.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("multipart").setLevel(logging.WARNING)
