"""Nightly SQLite backups (PLAN.md §5.3).

SQLite's online backup API copies a consistent snapshot even while the API and worker are writing, so
a filesystem snapshot of the data volume always contains at least one clean database file. The last
KEEP copies are kept under ``<data>/backups``.
"""

import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import jobs
from app.config import Settings
from app.models import Job

log = logging.getLogger("wander.backup")

KEEP = 7
AT_HOUR, AT_MINUTE = 3, 17


def backup(settings: Settings, now: datetime) -> Path:
    folder = settings.data_dir / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"wander-{now.strftime('%Y-%m-%d')}.db"
    tmp = target.with_suffix(".db.part")
    src = sqlite3.connect(settings.db_path)
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    tmp.replace(target)
    for old in sorted(folder.glob("wander-*.db"))[:-KEEP]:
        old.unlink(missing_ok=True)
    log.info("backed up the database to %s", target)
    return target


def next_run(now: datetime, tz: str) -> datetime:
    zone = ZoneInfo(tz)
    local = now.astimezone(zone)
    at = local.replace(hour=AT_HOUR, minute=AT_MINUTE, second=0, microsecond=0)
    if at <= local:
        at += timedelta(days=1)
    return at.astimezone(ZoneInfo("UTC"))


def ensure_scheduled(db: Session, now: datetime, tz: str) -> None:
    waiting = db.scalar(
        select(Job.id).where(Job.kind == "nightly_backup", Job.status.in_(("queued", "running")))
    )
    if waiting is None:
        job = jobs.enqueue(db, "nightly_backup", {}, max_attempts=3)
        job.run_after = next_run(now, tz)
        db.commit()
