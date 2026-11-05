import itertools

import pytest
from sqlalchemy import select

from app.models import AuditLog, JobStatus
from app.state_machine import TRANSITIONS, InvalidTransition, transition

ALLOWED = [(a, b) for a, targets in TRANSITIONS.items() for b in targets]
FORBIDDEN = [
    (a, b) for a, b in itertools.product(JobStatus, JobStatus) if b not in TRANSITIONS[a]
]


@pytest.mark.parametrize("src,dst", ALLOWED, ids=lambda s: s.value)
def test_allowed_transition_updates_status_and_audits_once(db, make_job, src, dst):
    job = make_job(src.value)
    transition(db, job, dst, actor="test", event="TEST_MOVE", payload={"n": 1})
    db.commit()

    db.refresh(job)
    assert job.status == dst.value
    rows = db.scalars(select(AuditLog)).all()
    assert len(rows) == 1
    assert (rows[0].from_status, rows[0].to_status) == (src.value, dst.value)
    assert rows[0].job_id == job.id


@pytest.mark.parametrize("src,dst", FORBIDDEN, ids=lambda s: s.value)
def test_forbidden_transition_raises_and_changes_nothing(db, make_job, src, dst):
    job = make_job(src.value)
    with pytest.raises(InvalidTransition):
        transition(db, job, dst, actor="test", event="TEST_MOVE")
    db.rollback()

    db.refresh(job)
    assert job.status == src.value
    assert db.scalars(select(AuditLog)).all() == []


def test_full_happy_path(db, make_job):
    job = make_job()
    for dst in [
        JobStatus.AUTHORIZED, JobStatus.SUBMITTED, JobStatus.VERIFIED,
        JobStatus.RELEASED, JobStatus.CAPTURED, JobStatus.PAID_OUT,
    ]:
        transition(db, job, dst, actor="test", event=f"TO_{dst.value}")
    db.commit()
    assert job.status == "PAID_OUT"
    assert len(db.scalars(select(AuditLog)).all()) == 6
