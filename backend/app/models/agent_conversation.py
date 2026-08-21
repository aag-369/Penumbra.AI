"""Multi-turn advisory chat history."""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING

from sqlalchemy import Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from .base import Timestamped, UUIDPrimaryKey

if TYPE_CHECKING:
    from .user import User


class MessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class AgentConversation(UUIDPrimaryKey, Timestamped, Base):
    __tablename__ = "agent_conversations"

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    thread_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    advisory_job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("advisory_jobs.id", ondelete="SET NULL")
    )

    role: Mapped[MessageRole] = mapped_column(
        Enum(MessageRole, native_enum=False, length=16), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)

    #: Which agent produced the turn, and what it decided to do.
    agent_name: Mapped[str | None] = mapped_column(String(64))
    action_taken: Mapped[str | None] = mapped_column(String(64))
    confidence: Mapped[float | None] = mapped_column(Float)
    token_count: Mapped[int | None] = mapped_column(Integer)

    user: Mapped["User"] = relationship(back_populates="conversations")

    def __repr__(self) -> str:
        return f"<AgentConversation {self.thread_id}#{self.turn_index} {self.role.value}>"
