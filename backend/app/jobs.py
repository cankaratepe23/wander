"""A small durable job queue on top of the ``jobs`` table.

One worker process claims jobs one at a time. SQLite serialises writes, so the
UPDATE ... RETURNING claim is atomic without row locks. Failed jobs retry with exponential
backoff; jobs left ``running`` by a crashed worker are requeued after a timeout.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text, update
from sqlalchemy.orm import Session

from app.models import Job, utcnow

STALE_AFTER = timedelta(minutes=15)
BACKOFF_BASE = timedelta(seconds=30)
BACKOFF_MAX = timedelta(hours=6)


@dataclass(frozen=True)
class ClaimedJob:
    id: int
    kind: str
    payload: dict[str, Any]
    attempts: int


def enqueue(db: Session, kind: str, payload: dict[str, Any], *, max_attempts: int = 5) -> Job:
    """Add a job to the session. The caller commits, so the job lands atomically with its data."""
    job = Job(kind=kind, payload=payload, max_attempts=max_attempts)
    db.add(job)
    return job


def _as_db_time(value: datetime) -> str:
    # Must match SQLAlchemy's SQLite DateTime storage format, so string comparison is time order.
    return value.strftime("%Y-%m-%d %H:%M:%S.%f")


def claim_next(db: Session, *, now: datetime | None = None) -> ClaimedJob | None:
    now = now or utcnow()
    row = db.execute(
        text(
            """
            UPDATE jobs
               SET status = 'running', attempts = attempts + 1, locked_at = :now
             WHERE id = (SELECT id FROM jobs
                          WHERE status = 'queued' AND run_after <= :now
                          ORDER BY run_after, id
                          LIMIT 1)
            RETURNING id, kind, payload, attempts
            """
        ),
        {"now": _as_db_time(now)},
    ).one_or_none()
    db.commit()
    if row is None:
        return None
    # Raw SQL bypasses the ORM's JSON type, so decode the stored text here.
    payload = json.loads(row.payload) if isinstance(row.payload, str) else row.payload
    return ClaimedJob(id=row.id, kind=row.kind, payload=payload or {}, attempts=row.attempts)


def complete(db: Session, job_id: int) -> None:
    db.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(status="done", finished_at=utcnow(), locked_at=None, last_error=None)
    )
    db.commit()


def fail(db: Session, job_id: int, error: str, *, now: datetime | None = None) -> str:
    """Record a failure. Returns the job's new status: 'queued' (will retry) or 'failed'."""
    now = now or utcnow()
    job = db.get(Job, job_id, populate_existing=True)
    if job is None:
        return "failed"
    job.last_error = error[:4000]
    job.locked_at = None
    if job.attempts >= job.max_attempts:
        job.status = "failed"
        job.finished_at = now
    else:
        delay = min(BACKOFF_BASE * (2 ** (job.attempts - 1)), BACKOFF_MAX)
        job.status = "queued"
        job.run_after = now + delay
    db.commit()
    return job.status


def defer(
    db: Session, job_id: int, delay: timedelta, reason: str, *, now: datetime | None = None
) -> None:
    """Put a job back without counting the attempt, e.g. while no API key is configured."""
    now = now or utcnow()
    job = db.get(Job, job_id, populate_existing=True)
    if job is None:
        return
    job.status = "queued"
    job.attempts = max(0, job.attempts - 1)
    job.run_after = now + delay
    job.locked_at = None
    job.last_error = reason[:4000]
    db.commit()


def requeue_stale(db: Session, *, now: datetime | None = None) -> int:
    """Put jobs a crashed worker left 'running' back in the queue."""
    now = now or utcnow()
    result = db.execute(
        update(Job)
        .where(Job.status == "running", Job.locked_at < now - STALE_AFTER)
        .values(status="queued", locked_at=None)
    )
    db.commit()
    return result.rowcount or 0
