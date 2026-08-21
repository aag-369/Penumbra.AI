"""Shared state passed between agents.

Everything portfolio-shaped in here is a **ciphertext**. The type annotations
say ``str`` because that is what a base64 CKKS ciphertext is; the naming
convention (``*_ciphertext``) marks which fields the server cannot read.

A reviewer checking the privacy claim should be able to do it from this file
alone: any field without ``_ciphertext`` in its name is something the server
genuinely knows, and the list is short -- tickers, goals, constraints, and
solver telemetry.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Stage = Literal["queued", "planning", "risk", "qubo", "optimization", "execution", "done"]


class AdvisoryState(BaseModel):
    """Working state for one advisory run."""

    # -- identity -----------------------------------------------------------
    job_id: str
    user_id: str
    portfolio_id: str

    # -- inputs the server can read ----------------------------------------
    tickers: list[str] = Field(default_factory=list)
    goals: dict[str, Any] = Field(default_factory=dict)

    # -- inputs the server cannot read -------------------------------------
    holdings_ciphertext: str = Field(default="", repr=False)
    cost_basis_ciphertext: str | None = Field(default=None, repr=False)

    # -- planning agent -----------------------------------------------------
    planning_complete: bool = False
    clarifying_question: str | None = None
    structured_plan: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)

    # -- risk agent ---------------------------------------------------------
    #: Derived from public market history, so these are plaintext. See
    #: ``docs/SPEC_DEVIATIONS.md`` #3 for why encrypting them buys nothing.
    mean_returns: list[float] = Field(default_factory=list)
    covariance: list[list[float]] = Field(default_factory=list)
    #: Risk metrics computed over the user's encrypted weights.
    risk_metrics_ciphertext: dict[str, str] = Field(default_factory=dict, repr=False)

    # -- QUBO ---------------------------------------------------------------
    qubo: dict[str, Any] = Field(default_factory=dict)
    asset_mapping: dict[int, dict[str, Any]] = Field(default_factory=dict)
    obfuscation_applied: bool = False

    # -- optimisation -------------------------------------------------------
    solution_bits: list[int] = Field(default_factory=list)
    allocation_ciphertext: str | None = Field(default=None, repr=False)
    optimization_metadata: dict[str, Any] = Field(default_factory=dict)

    # -- execution ----------------------------------------------------------
    execution_plan: dict[str, Any] = Field(default_factory=dict)
    recommendation_ciphertext: str | None = Field(default=None, repr=False)

    # -- bookkeeping --------------------------------------------------------
    stage: Stage = "queued"
    progress: float = 0.0
    conversation_history: list[dict[str, str]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    def advance(self, stage: Stage, progress: float) -> None:
        """Move to a stage and record progress. Callers persist this to the job row."""
        self.stage = stage
        self.progress = max(0.0, min(1.0, progress))

    def redacted(self) -> dict[str, Any]:
        """State with every ciphertext elided -- safe to log or return in an error."""
        data = self.model_dump()
        for key in list(data):
            if key.endswith("_ciphertext"):
                value = data[key]
                data[key] = f"<{len(value)} chars>" if isinstance(value, str) and value else None
        return data
