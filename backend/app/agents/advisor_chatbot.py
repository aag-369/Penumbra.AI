"""Conversational front end over the agent pipeline.

Phase 2. Not implemented.

Classifies each user turn into one of: a new advisory request, a goal
refinement, a risk adjustment, or a question about an existing recommendation --
and routes accordingly. Only the last of these can be answered without re-running
the pipeline.

Same constraint as the Planning Agent: prompts sent to an external LLM must
never contain portfolio quantities. The chatbot may reference the *user's own*
decrypted view only if that decryption happened in the browser and the user
chose to paste it back, which is their prerogative and not something the server
should arrange.
"""

from __future__ import annotations

from typing import Any, Literal

from .planning_agent import LLMClient

Intent = Literal["new_advisory", "goal_refinement", "risk_adjustment", "question"]


class AdvisorChatbot:
    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    async def classify_intent(self, message: str, history: list[dict[str, str]]) -> Intent:
        """Route a user turn."""
        raise NotImplementedError("Phase 2: Advisor Chatbot")

    async def chat_turn(
        self, message: str, user_id: str, thread_id: str, history: list[dict[str, str]]
    ) -> dict[str, Any]:
        """Handle one turn.

        Returns ``{"assistant_response": str, "action_taken": str,
        "confidence": float, "job_id": str | None}``.
        """
        raise NotImplementedError("Phase 2: Advisor Chatbot")
