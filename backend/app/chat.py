"""In-app chat (PLAN.md §4.4): Claude with the idea tools and web search, streamed to the browser.

A manual streaming loop rather than the tool runner, because every content block (thinking, tool
calls, web search results) is stored exactly as returned, so a conversation can be replayed to the
API later. Tool inputs stream eagerly, so each one is validated before it runs (app/tools.py).
"""

import json
import logging
from collections.abc import Iterator
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ai, tools
from app.config import Settings
from app.models import Conversation, Idea, Message, Place, User

log = logging.getLogger("wander.chat")

MAX_TOOL_ROUNDS = 12
WEB_SEARCH = {"type": "web_search_20260209", "name": "web_search", "max_uses": 5}

SYSTEM = f"""You are Wander's travel companion. Wander is a shared inbox of travel ideas that two people who travel
together save from TikTok, Instagram, WhatsApp, the web and their own notes. You help them refine those ideas and
decide where to go.

Use the tools to look at what they've actually saved before answering questions about it, and to make the
changes they ask for: fix a wrong place, add the restaurants from a list, merge duplicate places, shortlist an
idea. Make the changes directly when asked. Don't ask for confirmation for small edits, but never dismiss or
merge things they didn't ask about. Use web search for current facts such as seasons, opening times, travel
times and whether a plan fits in a number of days, and say briefly where the facts came from.

Keep answers short, warm and concrete: plain sentences or a few bullet points, no headings, and say "you both"
when something matters to both of them. Refer to ideas by their titles, not their ids.

{tools.family_note()}"""


def history(convo: Conversation) -> list[dict[str, Any]]:
    return [{"role": m.role, "content": m.content} for m in convo.messages]


def scope_note(db: Session, convo: Conversation) -> str | None:
    """Context for a conversation started from an idea, a place or a region."""
    if convo.scope == "idea" and convo.scope_id:
        idea = db.get(Idea, int(convo.scope_id))
        if idea:
            return "This chat is about this idea:\n" + json.dumps(
                tools.full(idea, db), ensure_ascii=False
            )
    if convo.scope == "place" and convo.scope_id:
        place = db.get(Place, int(convo.scope_id))
        if place:
            return f"This chat is about {place.name} ({place.region}, {place.country}), place_id {place.id}."
    if convo.scope == "region" and convo.scope_id:
        return f"This chat is about {convo.scope_id}."
    return None


def label_for(block: Any) -> str | None:
    if block.type == "tool_use":
        return tools.TOOLS.get(block.name, (None, None, "Working"))[2]
    if block.type == "server_tool_use" and block.name == "web_search":
        query = (getattr(block, "input", None) or {}).get("query")
        return f"Searching the web for “{query}”" if query else "Searching the web"
    return None


def dump(block: Any) -> dict[str, Any]:
    return block.model_dump(mode="json", exclude_none=True)


def respond(
    db: Session, settings: Settings, convo: Conversation, user: User, text: str
) -> Iterator[dict[str, Any]]:
    """Add the user's message, run Claude until it's done, and yield UI events along the way:
    {"type": "text", "text"}, {"type": "tool", "label"}, {"type": "changed"}, {"type": "error", "message"},
    and finally {"type": "done"}."""
    client = ai.client(settings)
    content: list[dict[str, Any]] = []
    if not convo.messages and (note := scope_note(db, convo)):
        content.append({"type": "text", "text": f"<context>\n{note}\n</context>"})
    content.append({"type": "text", "text": text})
    db.add(Message(conversation_id=convo.id, role="user", content=content, user_id=user.id))
    if not convo.title:
        convo.title = text.strip()[:80]
    db.commit()
    db.refresh(convo)

    system = f"{SYSTEM}\n\nThe person writing is {user.display_name}. Today is {date.today().isoformat()}."
    changed = False
    json_retries = 0
    rounds = 0
    while rounds < MAX_TOOL_ROUNDS:
        try:
            with client.messages.stream(
                model=settings.chat_model,
                max_tokens=8000,
                system=system,
                tools=[*tools.schemas(eager=True), WEB_SEARCH],
                messages=history(convo),
                cache_control={"type": "ephemeral"},
                output_config={"effort": settings.chat_effort},
            ) as stream:
                for event in stream:
                    if event.type == "text":
                        yield {"type": "text", "text": event.text}
                    elif event.type == "content_block_start" and (
                        label := label_for(event.content_block)
                    ):
                        yield {"type": "tool", "label": label}
                response = stream.get_final_message()
            json_retries = 0
        except ValueError:
            # Streamed tool input the SDK couldn't parse at all; re-issue the turn (bounded).
            json_retries += 1
            if json_retries > 2:
                yield {"type": "error", "message": "Claude's reply came back garbled. Try again."}
                break
            continue
        ai.log_usage(db, "chat", settings.chat_model, response.usage)
        db.add(
            Message(
                conversation_id=convo.id,
                role="assistant",
                content=[dump(b) for b in response.content],
            )
        )
        db.commit()
        db.refresh(convo)

        if response.stop_reason == "pause_turn":
            continue  # the server-side web search loop wants another round; resend as is
        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if response.stop_reason == "refusal" or not tool_uses:
            break
        if response.stop_reason == "max_tokens":
            yield {
                "type": "error",
                "message": "That answer got cut off. Ask again a bit more narrowly.",
            }
            break
        results = []
        for block in tool_uses:
            out, is_error = tools.run(db, user, settings, block.name, block.input)
            changed = changed or (block.name in tools.WRITES and not is_error)
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": out,
                    "is_error": is_error,
                }
            )
        db.add(Message(conversation_id=convo.id, role="user", content=results))
        db.commit()
        db.refresh(convo)
        rounds += 1
        if changed:
            yield {"type": "changed"}
    yield {"type": "done"}


def render(convo: Conversation) -> list[dict[str, Any]]:
    """Messages as the UI shows them: the person's words, Claude's text, and what Claude did."""
    out: list[dict[str, Any]] = []
    for m in convo.messages:
        if m.role == "user":
            texts = [
                b["text"]
                for b in m.content
                if b.get("type") == "text" and not b["text"].startswith("<context>")
            ]
            if texts:
                out.append({"role": "user", "text": "\n".join(texts), "id": m.id})
            continue
        steps, texts = [], []
        for b in m.content:
            if b.get("type") == "text":
                texts.append(b["text"])
            elif b.get("type") == "tool_use":
                steps.append(tools.TOOLS.get(b["name"], (None, None, "Working"))[2])
            elif b.get("type") == "server_tool_use" and b.get("name") == "web_search":
                steps.append("Searched the web")
        if out and out[-1]["role"] == "assistant":
            out[-1]["steps"] += steps
            out[-1]["text"] = "\n\n".join(t for t in [out[-1]["text"], *texts] if t)
        else:
            out.append(
                {"role": "assistant", "text": "\n\n".join(texts), "steps": steps, "id": m.id}
            )
    return out


def conversations(db: Session, scope: str | None, scope_id: str | None) -> list[Conversation]:
    q = select(Conversation).order_by(Conversation.created_at.desc())
    if scope:
        q = q.where(Conversation.scope == scope)
    if scope_id:
        q = q.where(Conversation.scope_id == scope_id)
    return list(db.scalars(q.limit(50)))
