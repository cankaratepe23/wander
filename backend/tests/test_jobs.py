from datetime import timedelta

import pytest

from app import jobs
from app.db import make_engine, make_sessionmaker
from app.migrate import upgrade_to_head
from app.models import Job, utcnow


@pytest.fixture
def factory(tmp_path):
    db_path = tmp_path / "wander.db"
    upgrade_to_head(db_path)
    return make_sessionmaker(make_engine(db_path))


def test_claim_returns_oldest_due_job_once(factory):
    with factory() as db:
        jobs.enqueue(db, "a", {"n": 1})
        jobs.enqueue(db, "b", {"n": 2})
        db.commit()
        first = jobs.claim_next(db)
        second = jobs.claim_next(db)
        third = jobs.claim_next(db)
    assert (first.kind, first.payload, first.attempts) == ("a", {"n": 1}, 1)
    assert second.kind == "b"
    assert third is None


def test_failure_backs_off_then_gives_up(factory):
    with factory() as db:
        jobs.enqueue(db, "flaky", {}, max_attempts=2)
        db.commit()
        now = utcnow()
        job = jobs.claim_next(db, now=now)
        assert jobs.fail(db, job.id, "boom", now=now) == "queued"
        assert jobs.claim_next(db, now=now) is None  # not due yet: backing off
        later = now + timedelta(minutes=5)
        job = jobs.claim_next(db, now=later)
        assert job.attempts == 2
        assert jobs.fail(db, job.id, "boom again", now=later) == "failed"
        assert db.get(Job, job.id).last_error == "boom again"


def test_stale_running_job_is_requeued(factory):
    with factory() as db:
        jobs.enqueue(db, "slow", {})
        db.commit()
        now = utcnow()
        job = jobs.claim_next(db, now=now)
        assert jobs.requeue_stale(db, now=now) == 0
        assert jobs.requeue_stale(db, now=now + timedelta(hours=1)) == 1
        again = jobs.claim_next(db, now=now + timedelta(hours=1))
        assert again.id == job.id
