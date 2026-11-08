"""Seasonal nudges (PLAN.md §4.5): once a month, a push about ideas that are in season soon.

"4 of your ideas are best in March–April: Cappadocia balloons, Japan sakura, … Plan one?" goes to an
ntfy topic (self-hosted or ntfy.sh) on the 1st of each month. Nothing is sent when nothing is in season.
"""

import calendar
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import jobs
from app.config import Settings
from app.models import Idea, Job

log = logging.getLogger("wander.nudges")

SEND_HOUR = 9
SEND_MINUTE = 7


def in_season(db: Session, today: datetime) -> tuple[list[Idea], tuple[int, int]]:
    """Ideas best this month or next, both hearted first, then newest."""
    m1 = today.month
    m2 = m1 % 12 + 1
    ideas = [
        i
        for i in db.scalars(
            select(Idea).where(Idea.status.in_(("someday", "shortlist")), Idea.reviewed.is_(True))
        )
        if {m1, m2} & set(i.best_months or [])
    ]
    ideas.sort(key=lambda i: (-len(i.hearts), -i.id))
    return ideas, (m1, m2)


def message(ideas: list[Idea], months: tuple[int, int]) -> tuple[str, str] | None:
    if not ideas:
        return None
    a, b = (calendar.month_name[m] for m in months)
    names = [i.title for i in ideas[:4]]
    more = f" and {len(ideas) - 4} more" if len(ideas) > 4 else ""
    count = f"{len(ideas)} of your ideas are" if len(ideas) > 1 else "One of your ideas is"
    return (f"In season: {a}–{b}", f"{count} best in {a}–{b}: {', '.join(names)}{more}. Plan one?")


def send(settings: Settings, title: str, body: str) -> bool:
    if not settings.ntfy_url:
        log.info("no ntfy URL configured; nudge not sent: %s", body)
        return False
    r = httpx.post(
        settings.ntfy_url,
        content=body.encode(),
        headers={"Title": title, "Tags": "world_map", "Click": "/#/globe"},
        timeout=15,
    )
    r.raise_for_status()
    return True


def next_send_time(now: datetime, tz: str) -> datetime:
    zone = ZoneInfo(tz)
    local = now.astimezone(zone)
    year, month = (local.year + (local.month == 12), local.month % 12 + 1)
    first = datetime(year, month, 1, SEND_HOUR, SEND_MINUTE, tzinfo=zone)
    return first.astimezone(ZoneInfo("UTC"))


def ensure_scheduled(db: Session, settings: Settings, now: datetime, tz: str) -> None:
    waiting = db.scalar(
        select(Job.id).where(Job.kind == "monthly_nudge", Job.status.in_(("queued", "running")))
    )
    if waiting is None:
        job = jobs.enqueue(db, "monthly_nudge", {}, max_attempts=3)
        job.run_after = next_send_time(now, tz)
        db.commit()


def run(db: Session, settings: Settings, now: datetime, tz: str) -> str | None:
    ideas, months = in_season(db, now.astimezone(ZoneInfo(tz)))
    msg = message(ideas, months)
    if msg:
        send(settings, *msg)
    return msg[1] if msg else None
