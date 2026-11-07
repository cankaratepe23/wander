"""Background worker: ``python -m app.worker``.

Runs as a second container from the same image. Claims jobs from the ``jobs`` table and
dispatches them to handlers by ``kind``. Everything slow (fetching posts, AI, geocoding) lives
here, so the capture endpoint can answer instantly.
"""

import logging
import signal
import time
from collections.abc import Callable
from typing import Any

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app import jobs
from app.config import get_settings
from app.db import make_engine, make_sessionmaker
from app.models import Capture

log = logging.getLogger("wander.worker")

Handler = Callable[[Session, dict[str, Any]], None]
HANDLERS: dict[str, Handler] = {}


def handler(kind: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn

    return register


@handler("enrich_capture")
def enrich_capture(db: Session, payload: dict[str, Any]) -> None:
    """Phase 0 placeholder. Phase 1 replaces this with the real pipeline (PLAN.md §4.2).

    Until then, captures are parked in 'needs_review' with an honest note, so nothing is lost
    and every one can be re-enriched once the pipeline exists.
    """
    capture = db.get(Capture, payload["capture_id"])
    if capture is None:
        log.warning("capture %s vanished before enrichment", payload["capture_id"])
        return
    capture.status = "needs_review"
    capture.error = "Saved. AI enrichment isn't built yet (Phase 1)."
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
