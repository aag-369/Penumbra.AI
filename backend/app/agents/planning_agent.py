"""Planning Agent -- turns a conversation into formal optimisation constraints.

Phase 2. Not implemented.

Scope
-----
The Planning Agent is the only agent that talks to the user directly. It runs a
multi-turn conversation to establish risk tolerance, horizon, cardinality,
position bounds, sector exclusions and liquidity needs, then emits a constraint
dictionary that :class:`~app.agents.risk_agent.RiskAgent` turns into QUBO
penalty terms.

Privacy note for the implementer
--------------------------------
This agent must never receive a ciphertext, and must never be given plaintext
holdings. It reasons about *goals*, which the user states in words, not about
positions. Keeping it on the plaintext side of the boundary is what makes it
safe to send its prompts to a third-party LLM API. The moment someone passes
portfolio numbers into a prompt here, the privacy claim is void -- which is why
:meth:`interpret_goals` takes only text and history.
"""

from __future__ import annotations

from typing import Any, Protocol


class LLMClient(Protocol):
    """Minimal interface the agents need from a language model."""

    async def complete(self, prompt: str, *, system: str | None = None, max_tokens: int = 4096) -> str:
        ...


class PlanningAgent:
    """Interprets investment goals. See module docstring for scope."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    async def interpret_goals(
        self, user_input: str, conversation_history: list[dict[str, str]]
    ) -> dict[str, Any]:
        """Continue the goal-elicitation conversation.

        Args:
            user_input: the user's latest message.
            conversation_history: prior turns as ``{"role", "content"}`` dicts.

        Returns:
            ``{"planning_complete": bool, "clarifying_question": str | None,
            "structured_plan": dict | None}``.
        """
        raise NotImplementedError("Phase 2: Planning Agent")

    async def generate_constraints(self, structured_plan: dict[str, Any]) -> dict[str, Any]:
        """Convert a structured plan into QUBO-ready constraints.

        Returns keys consumed by :class:`~app.optimization.qubo_builder.QUBOBuilder`:
        ``risk_aversion``, ``max_cardinality``, ``min_position``,
        ``max_position``, ``sector_limits``, ``liquidity_reserve``.
        """
        raise NotImplementedError("Phase 2: Planning Agent")
