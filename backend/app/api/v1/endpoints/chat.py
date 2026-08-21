"""Conversational advisory.

Both a REST endpoint and a WebSocket are provided. The WebSocket is what the
frontend uses -- an advisory turn can take a long time, and a socket lets the
server stream stage updates instead of leaving the client on a spinner.

The chatbot itself is Phase 2. The transport, persistence and authentication
around it work now.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from sqlalchemy import func

from ....database import SessionLocal
from ....models.agent_conversation import AgentConversation, MessageRole
from ....schemas.advisor_schema import ChatTurnRequest, ChatTurnResponse
from ....services.user_service import AuthError, UserService
from ..dependencies import CurrentUser, DbSession

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/turn", response_model=ChatTurnResponse)
def chat_turn(payload: ChatTurnRequest, current_user: CurrentUser, db: DbSession) -> ChatTurnResponse:
    """One conversational turn."""
    thread_id = payload.thread_id or _new_thread_id()
    turn_index = _next_turn_index(db, current_user.id, thread_id)

    db.add(
        AgentConversation(
            user_id=current_user.id,
            thread_id=thread_id,
            role=MessageRole.USER,
            content=payload.message,
            turn_index=turn_index,
        )
    )
    db.commit()

    # Phase 2: route through AdvisorChatbot.chat_turn and persist the reply.
    raise NotImplementedError("advisory chatbot is Phase 2")


@router.get("/threads/{thread_id}", response_model=list[dict])
def get_thread(thread_id: str, current_user: CurrentUser, db: DbSession) -> list[dict]:
    """Full history of one conversation thread."""
    turns = (
        db.query(AgentConversation)
        .filter(
            AgentConversation.user_id == current_user.id,
            AgentConversation.thread_id == thread_id,
        )
        .order_by(AgentConversation.turn_index)
        .all()
    )
    return [
        {
            "role": t.role.value,
            "content": t.content,
            "turn_index": t.turn_index,
            "agent_name": t.agent_name,
            "action_taken": t.action_taken,
            "created_at": t.created_at.isoformat(),
        }
        for t in turns
    ]


@router.websocket("/ws")
async def chat_websocket(websocket: WebSocket) -> None:
    """Streaming advisory chat.

    Authenticates from the first frame rather than a query parameter: URLs land
    in proxy logs and browser history, and a bearer token in a URL is a token
    that has been written to disk somewhere you do not control.

    Protocol::

        client -> {"type": "auth", "token": "<access token>"}
        server -> {"type": "ready", "user_id": "..."}
        client -> {"type": "message", "message": "...", "thread_id": "..."}
        server -> {"type": "stage", "stage": "risk", "progress": 0.4}
        server -> {"type": "reply", "content": "...", "action_taken": "..."}
    """
    await websocket.accept()
    db = SessionLocal()
    try:
        opening = await websocket.receive_json()
        if opening.get("type") != "auth" or not opening.get("token"):
            await websocket.send_json({"type": "error", "detail": "first frame must authenticate"})
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        try:
            user = UserService.resolve_token(db, opening["token"], "access")
        except AuthError as exc:
            await websocket.send_json({"type": "error", "detail": str(exc)})
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        await websocket.send_json({"type": "ready", "user_id": user.id})

        while True:
            frame = await websocket.receive_json()
            if frame.get("type") != "message":
                await websocket.send_json({"type": "error", "detail": "expected a message frame"})
                continue

            thread_id = frame.get("thread_id") or _new_thread_id()
            turn_index = _next_turn_index(db, user.id, thread_id)
            db.add(
                AgentConversation(
                    user_id=user.id,
                    thread_id=thread_id,
                    role=MessageRole.USER,
                    content=str(frame.get("message", ""))[:4000],
                    turn_index=turn_index,
                )
            )
            db.commit()

            # Phase 2: stream stage updates from the orchestrator, then the reply.
            await websocket.send_json(
                {
                    "type": "error",
                    "code": "not_implemented",
                    "detail": "the advisory chatbot is Phase 2; the transport layer is live",
                    "thread_id": thread_id,
                }
            )

    except WebSocketDisconnect:
        logger.info("chat websocket disconnected")
    except Exception:
        logger.exception("chat websocket failed")
        try:
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        except RuntimeError:
            pass
    finally:
        db.close()


def _new_thread_id() -> str:
    from ....models.base import new_uuid

    return new_uuid()


def _next_turn_index(db, user_id: str, thread_id: str) -> int:
    highest = (
        db.query(func.max(AgentConversation.turn_index))
        .filter(
            AgentConversation.user_id == user_id, AgentConversation.thread_id == thread_id
        )
        .scalar()
    )
    return 0 if highest is None else highest + 1
