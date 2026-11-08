"""Chat and hotspot endpoints. Replies stream as Server-Sent Events."""

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import ai, chat, hotspots
from app.auth import current_user, get_db
from app.models import Conversation, User

router = APIRouter(prefix="/api")


@router.get("/hotspots")
def list_hotspots(
    level: Literal["country", "region", "city"] = "country",
    limit: int = 20,
    _user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    return hotspots.load_and_rank(db, level, limit=max(1, min(limit, 50)))


class ConversationIn(BaseModel):
    scope: Literal["idea", "place", "region", "global"] = "global"
    scope_id: str | None = None


def convo_out(c: Conversation) -> dict:
    return {
        "id": c.id,
        "scope": c.scope,
        "scope_id": c.scope_id,
        "title": c.title,
        "created_at": c.created_at.isoformat(),
    }


@router.get("/conversations")
def list_conversations(
    scope: str | None = None,
    scope_id: str | None = None,
    _u: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    return [convo_out(c) for c in chat.conversations(db, scope, scope_id)]


@router.post("/conversations", status_code=status.HTTP_201_CREATED)
def create_conversation(
    body: ConversationIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    c = Conversation(scope=body.scope, scope_id=body.scope_id, created_by=user.id)
    db.add(c)
    db.commit()
    return convo_out(c)


@router.get("/conversations/{cid}")
def get_conversation(
    cid: int, _u: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    c = db.get(Conversation, cid)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such conversation")
    return {**convo_out(c), "messages": chat.render(c)}


class MessageIn(BaseModel):
    text: str


@router.post("/conversations/{cid}/messages")
def send_message(
    cid: int, body: MessageIn, request: Request, user: User = Depends(current_user)
) -> StreamingResponse:
    settings = request.app.state.settings
    if not body.text.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "empty message")
    if not settings.ai_configured:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Claude isn't connected yet")
    factory = request.app.state.sessionmaker
    user_id = user.id

    def events():
        # Its own session: the request's session is closed before a streamed body finishes.
        with factory() as db:
            convo = db.get(Conversation, cid)
            if convo is None:
                yield sse({"type": "error", "message": "no such conversation"})
                return
            me = db.get(User, user_id)
            try:
                for event in chat.respond(db, settings, convo, me, body.text.strip()):
                    yield sse(event)
            except ai.NotConfigured:
                yield sse({"type": "error", "message": "Claude isn't connected yet."})
            except Exception as exc:  # noqa: BLE001 - report, don't drop the stream
                chat.log.exception("chat failed")
                yield sse(
                    {
                        "type": "error",
                        "message": f"Something went wrong ({type(exc).__name__}). Try again.",
                    }
                )
                yield sse({"type": "done"})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
