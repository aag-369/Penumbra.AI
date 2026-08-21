"""Agent orchestration.

Phase 2. Not implemented.

The pipeline is a linear state machine over :class:`~app.agents.state.AdvisoryState`::

    queued -> planning -> risk -> qubo -> optimization -> execution -> done

LangGraph is the intended implementation (``StateGraph(AdvisoryState)`` with one
node per agent). It is not a dependency yet, because pinning a framework before
the agents exist tends to shape the agents around the framework.

Two things the implementer must preserve:

* **The state object carries ciphertexts, and no node may decrypt them.** The
  server-side engine physically cannot -- :meth:`CKKSEngine.decrypt` raises on a
  public engine -- so the guarantee is enforced by construction rather than by
  discipline. Do not introduce a code path that loads a private engine here.
* **Progress must be persisted on every transition.** A run takes minutes; a
  client polling ``GET /advisor/jobs/{id}`` needs to see the stage advance, and
  a crashed run needs to leave a diagnosable row rather than a job stuck at
  "pending".
"""

from __future__ import annotations

from typing import Any

from .execution_agent import ExecutionAgent
from .planning_agent import PlanningAgent
from .risk_agent import RiskAgent
from .state import AdvisoryState


class AdvisoryOrchestrator:
    """Coordinates Planning -> Risk -> Execution."""

    def __init__(
        self, planning: PlanningAgent, risk: RiskAgent, execution: ExecutionAgent
    ) -> None:
        self.planning = planning
        self.risk = risk
        self.execution = execution

    async def run(self, state: AdvisoryState, *, on_progress=None) -> AdvisoryState:
        """Run the full pipeline.

        Args:
            state: initial state, with ciphertexts and goals populated.
            on_progress: optional ``(stage, progress) -> None`` callback, used
                by the job runner to persist progress to the database.
        """
        raise NotImplementedError("Phase 2: Advisory Orchestrator")

    async def refine(self, state: AdvisoryState, instruction: str) -> AdvisoryState:
        """Re-run from the planning stage with an additional instruction."""
        raise NotImplementedError("Phase 2: Advisory Orchestrator")


def build_default_orchestrator(*_args: Any, **_kwargs: Any) -> AdvisoryOrchestrator:
    """Factory wired up in Phase 2."""
    raise NotImplementedError("Phase 2: Advisory Orchestrator")
