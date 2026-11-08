"""Background worker: ``python -m app.worker``.

Runs as a second container from the same image. Claims jobs from the ``jobs`` table and
dispatches them to handlers by ``kind``. Everything slow (fetching posts, AI, geocoding) lives
here, so the capture endpoint can answer instantly.
"""

import logging
import signal
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app import ai, backfill, backup, deep, enrich, jobs, nudges
from app.config import get_settings
from app.db import make_engine, make_sessionmaker
from app.models import Capture, utcnow

log = logging.getLogger("wander.worker")

Handler = Callable[[Session, dict[str, Any]], None]
HANDLERS: dict[str, Handler] = {}


def handler(kind: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn

    return register


class Defer(Exception):  # noqa: N818 - it's a signal, not an error
    """Raised by a handler to try again later without using up an attempt."""

    def __init__(self, reason: str, delay: timedelta = timedelta(minutes=30)) -> None:
        super().__init__(reason)
        self.delay = delay


OUT_OF_CREDIT = "Saved. Claude is out of credit, so this will be filed once credit is back."


def wait_for_credit() -> Defer:
    return Defer("Anthropic spend limit reached or credit ran out", ai.CREDIT_PAUSE)


@handler("enrich_capture")
def enrich_capture(db: Session, payload: dict[str, Any]) -> None:
    """Run the enrichment pipeline (app/enrich.py) for one capture."""
    capture = db.get(Capture, payload["capture_id"])
    if capture is None:
        log.warning("capture %s vanished before enrichment", payload["capture_id"])
        return
    settings = get_settings()
    if not settings.ai_configured:
        capture.status = "queued"
        capture.error = "Saved. It will be filed once Claude is connected."
        db.commit()
        raise Defer("no Anthropic API key configured")
    if ai.credit_paused():
        capture.status = "queued"
        capture.error = OUT_OF_CREDIT
        db.commit()
        raise wait_for_credit()
    try:
        enrich.run(
            db, capture, settings, enrich.Deps(deepen=deep.deepen if settings.deep_parse else None)
        )
    except Exception as exc:
        db.rollback()
        capture = db.get(Capture, payload["capture_id"])
        if capture is not None and capture.status == "processing":
            capture.status = "queued"  # the job retries; show it as waiting, not stuck
            if ai.out_of_credit(exc):
                capture.error = OUT_OF_CREDIT
            db.commit()
        if ai.out_of_credit(exc):
            ai.pause_for_credit()
            raise wait_for_credit() from exc
        raise


@handler("prepare_import")
def prepare_import(db: Session, payload: dict[str, Any]) -> None:
    settings = get_settings()
    backfill.prepare_import(
        db, payload, settings, enrich.Deps(deepen=None)
    )  # no video downloads in bulk


@handler("submit_batch")
def submit_batch(db: Session, payload: dict[str, Any]) -> None:
    if ai.credit_paused():
        raise wait_for_credit()
    try:
        backfill.submit_batch(db, get_settings())
    except ai.NotConfigured as exc:
        raise Defer("no Anthropic API key configured") from exc
    except Exception as exc:
        if ai.out_of_credit(exc):
            ai.pause_for_credit()
            raise wait_for_credit() from exc
        raise


@handler("poll_batch")
def poll_batch(db: Session, payload: dict[str, Any]) -> None:
    try:
        backfill.poll_batch(db, payload, get_settings())
    except backfill.NotDone as exc:
        raise Defer(f"batch still {exc}", backfill.POLL_EVERY) from exc
    except ai.NotConfigured as exc:
        raise Defer("no Anthropic API key configured") from exc
    except Exception as exc:
        if ai.out_of_credit(exc):
            raise wait_for_credit() from exc
        raise


@handler("monthly_nudge")
def monthly_nudge(db: Session, payload: dict[str, Any]) -> None:
    settings = get_settings()
    now = utcnow()
    sent = nudges.run(db, settings, now, settings.tz)
    log.info("monthly nudge: %s", sent or "nothing in season")
    # Schedule next month's directly: this job is still "running", so ensure_scheduled would skip it.
    job = jobs.enqueue(db, "monthly_nudge", {}, max_attempts=3)
    job.run_after = nudges.next_send_time(now + timedelta(days=2), settings.tz)
    db.commit()


@handler("nightly_backup")
def nightly_backup(db: Session, payload: dict[str, Any]) -> None:
    settings = get_settings()
    now = utcnow()
    backup.backup(settings, now)
    job = jobs.enqueue(db, "nightly_backup", {}, max_attempts=3)
    job.run_after = backup.next_run(now + timedelta(hours=1), settings.tz)
    db.commit()


def run_one(factory: sessionmaker[Session]) -> bool:
    """Claim and run a single job. Returns True if a job was run."""
    with factory() as db:
        job = jobs.claim_next(db)
    if job is None:
        return False

    fn = HANDLERS.get(job.kind)
    with factory() as db:
        if fn is None:
            jobs.fail(db, job.id, f"no handler for job kind {job.kind!r}")
            log.error("job %s: unknown kind %r", job.id, job.kind)
            return True
        try:
            fn(db, job.payload)
        except Defer as d:
            db.rollback()
            jobs.defer(db, job.id, d.delay, str(d))
            log.info("job %s (%s) deferred: %s", job.id, job.kind, d)
        except Exception as exc:  # noqa: BLE001 - any handler failure is retried
            db.rollback()
            new_status = jobs.fail(db, job.id, f"{type(exc).__name__}: {exc}")
            log.exception("job %s (%s) failed, now %s", job.id, job.kind, new_status)
        else:
            jobs.complete(db, job.id)
            log.info("job %s (%s) done", job.id, job.kind)
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    factory = make_sessionmaker(make_engine(settings.db_path))

    stopping = False

    def _stop(signum, _frame):  # noqa: ANN001
        nonlocal stopping
        log.info("signal %s received, finishing the current job and exiting", signum)
        stopping = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    log.info("worker started, polling every %.1fs", settings.worker_poll_seconds)
    try:
        with factory() as db:
            nudges.ensure_scheduled(db, settings, utcnow(), settings.tz)
            backup.ensure_scheduled(db, utcnow(), settings.tz)
    except OperationalError:
        pass  # the API hasn't migrated yet; the next start will schedule it
    last_stale_check = 0.0
    while not stopping:
        try:
            if time.monotonic() - last_stale_check > 60:
                with factory() as db:
                    if n := jobs.requeue_stale(db):
                        log.warning("requeued %d stale job(s)", n)
                last_stale_check = time.monotonic()
            if not run_one(factory):
                time.sleep(settings.worker_poll_seconds)
        except OperationalError as exc:
            # Typically the API hasn't run migrations yet on first start, or a long write lock.
            log.warning("database not ready (%s); retrying shortly", exc.orig)
            time.sleep(5)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
