"""Backfill jobs (PLAN.md §4.6): imported items are read slowly, then understood in batches at half price.

1. ``create``: an import becomes captures, each with a ``prepare_import`` job, staggered so Instagram and
   TikTok are fetched at a polite pace (the throwaway account mustn't look like a scraper).
2. ``prepare_import``: gather signals for one capture (no Claude call), then make sure a submit is scheduled.
3. ``submit_batch``: send up to BATCH_SIZE prepared captures to the Message Batches API.
4. ``poll_batch``: wait for the batch to end, then file each result like a normal capture, into the review
   tray (ideas start unreviewed). Errors fall back to a normal, individual enrichment.
"""

import json
import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ai, enrich, jobs, understand
from app.config import Settings
from app.importers import Item
from app.models import Capture, Import, Job, Media, User, utcnow
from app.sources import detect_platform

log = logging.getLogger("wander.backfill")

BATCH_SIZE = 200
MAX_BATCH_BYTES = 200_000_000  # the API's limit is 256 MB, and carousels make requests large
PACE = {
    "instagram": timedelta(seconds=45),
    "tiktok": timedelta(seconds=6),
    "youtube": timedelta(seconds=6),
}
DEFAULT_PACE = timedelta(seconds=2)
POLL_EVERY = timedelta(minutes=10)


def create(db: Session, user: User, source: str, filename: str | None, items: list[Item]) -> Import:
    imp = Import(source=source, filename=filename, total=len(items), created_by=user.id)
    db.add(imp)
    db.flush()
    at = utcnow()
    for item in items:
        capture = Capture(
            user_id=user.id,
            kind="import",
            raw_text=item.text,
            url=item.url,
            source_app=f"import:{source}",
            import_id=imp.id,
        )
        db.add(capture)
        db.flush()
        job = jobs.enqueue(db, "prepare_import", {"capture_id": capture.id})
        job.run_after = at
        at += PACE.get(detect_platform(item.url), DEFAULT_PACE) if item.url else timedelta(0)
    db.commit()
    return imp


def ensure_submit(db: Session, delay: timedelta = timedelta(minutes=3)) -> None:
    """Schedule one submit_batch job, unless one is already waiting."""
    waiting = db.scalar(
        select(Job.id).where(Job.kind == "submit_batch", Job.status.in_(("queued", "running")))
    )
    if waiting is None:
        job = jobs.enqueue(db, "submit_batch", {})
        job.run_after = utcnow() + delay
        db.commit()


def prepare_import(
    db: Session, payload: dict, settings: Settings, deps: enrich.Deps | None = None
) -> None:
    capture = db.get(Capture, payload["capture_id"])
    if capture is None or capture.prepared_at is not None:
        return
    if enrich.prepare(db, capture, settings, deps) is None:
        return  # parked in Needs a look: nothing readable
    capture.status = "queued"
    capture.error = "Read; waiting for the next batch."
    capture.prepared_at = utcnow()
    db.commit()
    ensure_submit(db)


def submit_batch(db: Session, settings: Settings, client=None) -> str | None:
    pending = list(
        db.scalars(
            select(Capture)
            .where(
                Capture.prepared_at.is_not(None),
                Capture.batch_id.is_(None),
                Capture.status == "queued",
            )
            .order_by(Capture.id)
            .limit(BATCH_SIZE)
        )
    )
    if not pending:
        return None
    client = client or ai.client(settings)
    requests = []
    included: list[Capture] = []
    size = 0
    for capture in pending:
        media = db.scalar(select(Media).where(Media.capture_id == capture.id))
        signals = enrich.signals_from_media(capture, media, settings)
        images = enrich.images_for(capture, settings, signals)
        params = understand.params(settings, capture.raw_text, signals, images)
        size += len(json.dumps(params))
        if requests and size > MAX_BATCH_BYTES:
            break  # the rest go in the next batch, scheduled below
        requests.append({"custom_id": f"capture-{capture.id}", "params": params})
        included.append(capture)
    batch = client.messages.batches.create(requests=requests)
    for capture in included:
        capture.batch_id = batch.id
        capture.error = "Being read in a batch (usually within the hour)."
    poll = jobs.enqueue(db, "poll_batch", {"batch_id": batch.id}, max_attempts=10)
    poll.run_after = utcnow() + POLL_EVERY
    db.commit()
    log.info("submitted batch %s with %d captures", batch.id, len(included))
    more = db.scalar(
        select(Capture.id).where(
            Capture.prepared_at.is_not(None), Capture.batch_id.is_(None), Capture.status == "queued"
        )
    )
    if more:
        ensure_submit(db, delay=timedelta(0))
    return batch.id


class NotDone(Exception):  # noqa: N818
    pass


def poll_batch(
    db: Session, payload: dict, settings: Settings, client=None, deps: enrich.Deps | None = None
) -> None:
    client = client or ai.client(settings)
    batch_id = payload["batch_id"]
    batch = client.messages.batches.retrieve(batch_id)
    if batch.processing_status != "ended":
        raise NotDone(batch.processing_status)
    for entry in client.messages.batches.results(batch_id):
        try:
            capture = db.get(Capture, int(entry.custom_id.removeprefix("capture-")))
        except ValueError:
            continue
        if capture is None or capture.batch_id != batch_id:
            continue
        if entry.result.type != "succeeded":
            # Errored, canceled or expired: fall back to a normal, individual enrichment.
            capture.batch_id = None
            capture.prepared_at = None
            jobs.enqueue(db, "enrich_capture", {"capture_id": capture.id})
            db.commit()
            continue
        message = entry.result.message
        ai.log_usage(db, "import", settings.enrich_model, message.usage, batch=True)
        try:
            u = understand.parse(message)
        except ValueError as exc:
            enrich.park(db, capture, f"Couldn't understand this one ({exc}).")
            continue
        notes = list(
            (db.scalar(select(Media).where(Media.capture_id == capture.id)) or Media()).notes or []
        )
        enrich.apply(db, capture, settings, u, notes, deps, imported=True)
    log.info("batch %s filed", batch_id)


def progress(db: Session, imp: Import) -> dict:
    rows = list(db.scalars(select(Capture).where(Capture.import_id == imp.id)))
    counts: dict[str, int] = {}
    for c in rows:
        key = (
            c.status
            if c.status != "queued"
            else ("batched" if c.batch_id else "prepared" if c.prepared_at else "waiting")
        )
        counts[key] = counts.get(key, 0) + 1
    return {
        "id": imp.id,
        "source": imp.source,
        "filename": imp.filename,
        "total": imp.total,
        "counts": counts,
        "created_at": imp.created_at.isoformat(),
    }
