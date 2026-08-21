"""Shared response envelopes."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Message(BaseModel):
    """Simple acknowledgement."""

    message: str


class ErrorDetail(BaseModel):
    """Body of every non-2xx response.

    ``code`` is a stable machine-readable string; ``detail`` is for humans and
    is safe to display. Internal exception text never reaches either field --
    see :mod:`app.middleware.error_handling`.
    """

    code: str = Field(examples=["validation_failed"])
    detail: str
    context: dict[str, Any] | None = None


class Page(BaseModel):
    """Offset pagination envelope."""

    total: int
    skip: int
    limit: int
