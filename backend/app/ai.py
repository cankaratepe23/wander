"""Shared Claude plumbing: the client, list prices, and per-call usage logging (PLAN.md §6)."""

import logging
from datetime import UTC, datetime
from typing import Any

import anthropic
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import AiUsage

log = logging.getLogger("wander.ai")

# USD per million tokens: (input, output). Cache reads cost 0.1x input, cache writes 1.25x.
PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
}
WEB_SEARCH_USD = 10.0 / 1000


class NotConfigured(RuntimeError):
    """Raised when a job needs Claude but no API key is set."""


def client(settings: Settings) -> anthropic.Anthropic:
    if not settings.ai_configured:
        raise NotConfigured("no Anthropic API key configured")
    # The SDK retries 429/5xx with backoff itself; the job queue retries anything beyond that.
    return anthropic.Anthropic(api_key=settings.anthropic_api_key, max_retries=3, timeout=120)


def cost(model: str, usage: Any, *, batch: bool = False) -> float:
    price_in, price_out = PRICES.get(model, PRICES["claude-opus-5-5"])
    tokens_in = getattr(usage, "input_tokens", 0) or 0
    tokens_out = getattr(usage, "output_tokens", 0) or 0
    read = getattr(usage, "cache_read_input_tokens", 0) or 0
    write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    usd = (
        tokens_in * price_in
        + read * price_in * 0.1
        + write * price_in * 1.25
        + tokens_out * price_out
    ) / 1e6
    searches = getattr(getattr(usage, "server_tool_use", None), "web_search_requests", 0) or 0
    usd += searches * WEB_SEARCH_USD
    return usd * (0.5 if batch else 1.0)


def log_usage(db: Session, task: str, model: str, usage: Any, *, batch: bool = False) -> AiUsage:
    """Record one call's usage. The caller commits."""
    row = AiUsage(
        task=task,
        model=model,
        input_tokens=getattr(usage, "input_tokens", 0) or 0,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
        cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
        web_searches=getattr(getattr(usage, "server_tool_use", None), "web_search_requests", 0)
        or 0,
        cost_usd=cost(model, usage, batch=batch),
        batch=batch,
    )
    db.add(row)
    log.info(
        "claude %s %s: in=%s out=%s cache_read=%s cache_write=%s $%.4f",
        task,
        model,
        row.input_tokens,
        row.output_tokens,
        row.cache_read_tokens,
        row.cache_write_tokens,
        row.cost_usd,
    )
    return row


def month_to_date(db: Session, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows = db.execute(
        select(AiUsage.task, func.count(AiUsage.id), func.sum(AiUsage.cost_usd))
        .where(AiUsage.created_at >= start)
        .group_by(AiUsage.task)
    ).all()
    by_task = {task: {"calls": n, "usd": round(usd or 0.0, 4)} for task, n, usd in rows}
    return {
        "month": start.strftime("%Y-%m"),
        "usd": round(sum(t["usd"] for t in by_task.values()), 4),
        "by_task": by_task,
    }
