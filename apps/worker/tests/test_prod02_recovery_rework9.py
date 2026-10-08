"""Generic recovery clock parity; SQL collaborators do not prove live PG behavior."""
from copy import deepcopy

import pytest

from postgres_jobs import PostgresJobError
from rick_jobs import (
    JobFailure, JobPublicationCancellation, JobResult, JobState, JobValidationError,
)
from test_prod02_recovery_rework8 import (
    SCOPE, knowledge, legacy, raw_receipt, running, typed,
)
from test_prod02_recovery_rework4 import NoProvider, handler
from rick_retrieval import InMemoryVectorStore


def complete(queue, job, lease, result, now, normal):
    queue.publication_reconciler = lambda _: result
    if normal:
        return queue.acknowledge(lease, result, now=now, expected_version=job.version)
    return queue.recover_publication(job.job_id, **SCOPE, now=now)


def assert_deferred(db, job, before, reason):
    row, attempts = before
    current = db.jobs[str(job.job_id)]
    assert db.attempts == attempts
    assert {k: v for k, v in current.items()
            if k not in {'last_error_code', 'publication_recovery_at'}} == {
                k: v for k, v in row.items()
                if k not in {'last_error_code', 'publication_recovery_at'}}
    assert current['last_error_code'] == reason
    assert current['publication_recovery_at'] == db.database_now + 1


@pytest.mark.parametrize('normal', [False, True], ids=['recovery', 'normal'])
@pytest.mark.parametrize('finish,now,valid', [
    (30, 25, False), (30, 100, True), (30, 30, True),
    (20, 100, True), (19, 100, False), (30, 19, False),
    (20, 19, False),
])
def test_generic_completion_obeys_ordinary_transition_clock(normal, finish, now, valid):
    queue, db, job, lease = running()
    result = JobResult(document_id='doc', completed_at=finish)
    db.database_now = 25  # Independent database lease/scheduling clock.
    before = deepcopy((db.jobs[str(job.job_id)], db.attempts))
    if not valid and normal:
        with pytest.raises(PostgresJobError) as caught:
            complete(queue, job, lease, result, now, normal)
        assert caught.value.code == 'invalid_transition'
        assert (db.jobs[str(job.job_id)], db.attempts) == before
        return
    terminal = complete(queue, job, lease, result, now, normal)
    if not valid:
        assert terminal == job
        assert_deferred(db, job, before, 'publication_attempt_conflict')
        return
    assert terminal.state is JobState.SUCCEEDED
    assert terminal.result == result
    assert terminal.result.completed_at == finish
    assert terminal.updated_at == terminal.attempts[-1].finished_at == now
    assert terminal.attempts[:-1] == job.attempts[:-1]
    assert terminal.attempts[-1].started_at == job.attempts[-1].started_at
    assert terminal.attempts[-1].worker_id == job.attempts[-1].worker_id
    assert terminal.version == job.version + 1
    writes = [p for s, p in db.trace if 'insert into rick_ingestion_job_attempts' in s.lower()]
    assert writes[-1][5] == now


@pytest.mark.parametrize('normal', [False, True], ids=['recovery', 'normal'])
def test_generic_unknown_timestamp_uses_frozen_ordinary_contract(normal):
    queue, db, job, lease = running()
    before = deepcopy((db.jobs[str(job.job_id)], db.attempts))
    # This frozen JobResult contract rejects None at construction, before either
    # public queue path. Do not fabricate a typed unknown-history receipt.
    with pytest.raises(JobValidationError):
        complete(queue, job, lease, JobResult(completed_at=None), 100, normal)
    assert (db.jobs[str(job.job_id)], db.attempts) == before


@pytest.mark.parametrize('finish,now', [(30, 100), (110, 90), (30, 19)])
@pytest.mark.parametrize('cancel', [False, True])
def test_validated_publication_retains_separate_clocks(finish, now, cancel):
    queue, db, job, lease = running()
    result = typed(job, finish)
    if cancel:
        result = JobPublicationCancellation(result.facts, finish)
    terminal = complete(queue, job, lease, result, now, False)
    assert terminal.state is (JobState.CANCELLED if cancel else JobState.SUCCEEDED)
    assert terminal.attempts[-1].finished_at == finish
    assert terminal.updated_at == max(now, job.updated_at, finish)
    assert terminal.attempts[:-1] == job.attempts[:-1]


def test_typed_unknown_cancellation_stays_deferred():
    queue, db, job, lease = running()
    result = JobPublicationCancellation(typed(job, 30).facts, None)
    before = deepcopy((db.jobs[str(job.job_id)], db.attempts))
    terminal = complete(queue, job, lease, result, 100, False)
    assert terminal == job
    assert_deferred(db, job, before, 'publication_finish_unknown')


@pytest.mark.parametrize('normal', [False, True], ids=['recovery', 'normal'])
def test_generic_past_completion_preserves_prior_attempt(normal):
    queue, db, job, lease = running()
    queued = queue.fail(lease, JobFailure(code='handler_timeout', message='timeout',
        retryable=True, attempt=1, occurred_at=35), now=35, expected_version=job.version)
    db.database_now = max(40, queued.available_at)
    job, lease = queue.claim(worker_id='later', scope=queued.scope,
        expected_versions={}, now=db.database_now)[0]
    prior = deepcopy(db.attempts[(str(job.job_id), 1)])
    terminal = complete(queue, job, lease,
        JobResult(completed_at=job.attempts[-1].started_at + 1), 100, normal)
    assert terminal.attempt_count == 2
    assert terminal.attempts[-1].finished_at == 100
    assert terminal.attempts[:-1] == job.attempts[:-1]
    assert db.attempts[(str(job.job_id), 1)] == prior


def test_invalid_generic_poll_then_valid_poll_preserves_attempt_budget():
    queue, db, job, lease = running()
    result = JobResult(completed_at=30)
    before = deepcopy((db.jobs[str(job.job_id)], db.attempts))
    for now in (25, 26):
        terminal = complete(queue, job, lease, result, now, False)
        assert terminal == job
        assert_deferred(db, job, before, 'publication_attempt_conflict')
    terminal = complete(queue, job, lease, result, 100, False)
    assert terminal.state is JobState.SUCCEEDED
    assert terminal.attempts[-1].finished_at == 100
    assert terminal.attempt_count == job.attempt_count
    assert terminal.version == job.version + 1


@pytest.mark.parametrize('known', [False, True])
def test_historical_receipt_remains_immutable(knowledge, tmp_path, known):
    queue, db, job, lease = running()
    owner = legacy(knowledge, job, checkpoint_finish=30 if known else None)
    before = raw_receipt(knowledge, owner.job_id)
    attempts = deepcopy(db.attempts)
    worker = handler(knowledge, InMemoryVectorStore(), tmp_path, NoProvider())
    queue.publication_reconciler = worker.recover_job
    terminal = queue.recover_publication(job.job_id, **SCOPE, now=100)
    assert raw_receipt(knowledge, owner.job_id) == before
    if known:
        assert terminal.state is JobState.SUCCEEDED
        assert terminal.attempts[-1].finished_at == 30
    else:
        assert terminal == job and db.attempts == attempts
        assert db.jobs[str(job.job_id)]['last_error_code'] == 'publication_finish_unknown'
