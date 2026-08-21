"""Advisory pipeline request and response models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class InvestmentGoals(BaseModel):
    """What the Planning Agent needs before it can formulate constraints."""

    risk_tolerance: int = Field(ge=1, le=10, description="1 = capital preservation, 10 = maximum growth")
    horizon_years: float = Field(gt=0, le=60)
    max_holdings: int | None = Field(default=None, ge=1, le=200, description="Cardinality constraint")
    min_position_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    max_position_pct: float = Field(default=100.0, ge=0.0, le=100.0)
    liquidity_reserve_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    excluded_sectors: list[str] = Field(default_factory=list)
    esg_minimum: float | None = Field(default=None, ge=0.0, le=100.0)
    rebalancing: Literal["never", "quarterly", "annually"] = "annually"
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("max_position_pct")
    @classmethod
    def _bounds_ordered(cls, v: float, info) -> float:
        low = info.data.get("min_position_pct", 0.0)
        if v < low:
            raise ValueError("max_position_pct must be at least min_position_pct")
        return v


class AdvisoryRequest(BaseModel):
    portfolio_id: str | None = Field(default=None, description="Defaults to the active portfolio")
    goals: InvestmentGoals


class RefinementRequest(BaseModel):
    """Adjust an existing recommendation, e.g. 'exclude energy'."""

    instruction: str = Field(min_length=1, max_length=2000)
    goals: InvestmentGoals | None = None


class AdvisoryJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    stage: str
    progress: float
    portfolio_id: str
    parent_job_id: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    error_message: str | None = None

    @field_validator("status", "stage", mode="before")
    @classmethod
    def _enum_value(cls, v: object) -> object:
        return getattr(v, "value", v)


class AdvisoryResultOut(AdvisoryJobOut):
    """A finished job, including the encrypted recommendation.

    ``recommendation_ciphertext`` is encrypted under the user's key. The server
    produced it and cannot read it; the browser decrypts it for display.
    """

    recommendation_ciphertext: str | None = Field(default=None, repr=False)
    run_metadata: dict[str, Any] = Field(default_factory=dict)


class ChatTurnRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    thread_id: str | None = None


class ChatTurnResponse(BaseModel):
    thread_id: str
    turn_index: int
    assistant_response: str
    action_taken: str
    agent_name: str | None = None
    confidence: float | None = None
    job_id: str | None = Field(default=None, description="Set when the turn started an advisory run")
