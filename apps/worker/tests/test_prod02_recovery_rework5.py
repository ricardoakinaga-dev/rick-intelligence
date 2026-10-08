"""Recovery v5 public-boundary discriminators; no real PostgreSQL/provider proof.

Full production methods execute over memory SQL collaborators and local stores.
Crashes use BaseException; they do not simulate a process kill or power loss.
"""
from test_prod02_recovery_rework7 import install_historical_publication
from copy import deepcopy
from dataclasses import replace

import pytest

from external_ingestion import _recovery_metadata
from postgres_jobs import PostgresJobQueue
from rick_jobs import JobContinuation, JobScope, JobState
from rick_ingestion.jobs import IngestionJob
from rick_knowledge import InMemoryKnowledgeStore, SQLiteKnowledgeStore
from rick_retrieval import InMemoryVectorStore
from test_postgres_jobs import FakeConnection, FakeCursor, make_job
from test_prod02_recovery_rework4 import (
    SCOPE, Crash, NoProvider, handler, running_queue, service, source,
)


class RecoveryCursor(FakeCursor):
    """Extend SQL memory model only for this lane's new column assignments."""
    def _update_job(self, compact, params):
        if 'set publication_recovery_at=' in compact and 'last_error_code=%s' in compact:
            reason, job_id, tenant, workspace, collection, version = params
            row = self.connection.jobs.get(str(job_id))
            if row and (row['tenant_id'], row['workspace_id'], row['collection_id'], row['version']) == (tenant, workspace, collection, version):
                row['publication_recovery_at'] = self.connection.database_now + 1
                row['last_error_code'] = reason
            return
        super()._update_job(compact, params)
        if self.rows and 'last_error_code=null' in compact:
            self.connection.jobs[str(self.rows[0]['job_id'])]['last_error_code'] = None
        if self.rows and 'publication_recovery_at=clock_timestamp()' in compact:
            row = self.connection.jobs[str(self.rows[0]['job_id'])]
            row['publication_recovery_at'] = self.connection.database_now
            self.rows[0]['publication_recovery_at'] = self.connection.database_now


class RecoveryConnection(FakeConnection):
    def cursor(self):
        return RecoveryCursor(self)


@pytest.fixture(params=['memory', 'sqlite'])
def knowledge(request, tmp_path):
    store = InMemoryKnowledgeStore() if request.param == 'memory' else SQLiteKnowledgeStore(tmp_path/'knowledge.sqlite')
    yield store
    if hasattr(store, 'close'):
        store.close()


def test_F1_repeated_continuation_crashes_do_not_starve_queued_or_continuation():
    db = RecoveryConnection()
    queue = PostgresJobQueue(lambda: db, lease_seconds=10)
    scope = JobScope(**SCOPE)
    originals = {}
    for name in ('continuation-a', 'continuation-b'):
        queued = queue.enqueue(make_job(scope=scope, job_id=name, key=name, max_attempts=1), expected_version=0)
        running, lease = queue.claim(worker_id='original', scope=scope, expected_versions={}, now=104)[0]
        originals[name] = (running, lease)
    queue.enqueue(make_job(scope=scope, job_id='healthy', key='healthy', max_attempts=1), expected_version=0)
    def reconcile(job):
        if str(job.job_id) == 'healthy':
            return None
        return JobContinuation(job_id=job.job_id, scope=scope, attempt=1,
            created_at=job.created_at, started_at=104, attempt_id='stable-business-token')
    queue.publication_reconciler = reconcile
    claims = []
    recovery_order = []
    for poll in range(5):
        db.database_now = 115 + 31*poll
        claimed = queue.claim(worker_id='replacement', scope=scope, expected_versions={}, now=db.database_now, limit=1)
        assert len(claimed) == 1
        job, lease = claimed[0]
        claims.append(str(job.job_id))
        if str(job.job_id) in originals:
            old, old_lease = originals[str(job.job_id)]
            assert job.attempts == old.attempts and job.attempt_count == job.max_attempts == 1
            assert lease.token != old_lease.token
            recovery_order.append(db.jobs[str(job.job_id)].get('publication_recovery_at'))
    assert {'continuation-a', 'continuation-b', 'healthy'} <= set(claims)
    assert all(value is not None for value in recovery_order)


def committed(knowledge, tmp_path, monkeypatch, *, window=False):
    import rick_ingestion.jobs as jobs
    monkeypatch.setattr(jobs.time, 'time', lambda: 110.)
    db = RecoveryConnection()
    queue = PostgresJobQueue(lambda: db, lease_seconds=10)
    queued = queue.enqueue(make_job(scope=JobScope(**SCOPE), max_attempts=1), expected_version=0)
    running, lease = queue.claim(worker_id='original', scope=queued.scope, expected_versions={}, now=104)[0]
    vectors = InMemoryVectorStore()
    save = knowledge.save_publication_snapshot
    if window:
        knowledge.save_publication_snapshot = lambda _: (_ for _ in ()).throw(Crash('after terminal checkpoint before receipt snapshot'))
        with pytest.raises(Crash):
            service(knowledge, vectors).ingest(source(tmp_path), **SCOPE,
                job_id=str(running.job_id), _recovery_metadata=_recovery_metadata(running))
        knowledge.save_publication_snapshot = save
    else:
        service(knowledge, vectors).ingest(source(tmp_path), **SCOPE,
            job_id=str(running.job_id), _recovery_metadata=_recovery_metadata(running))
    monkeypatch.setattr(jobs.time, 'time', lambda: 210.)
    queue.publication_reconciler = handler(knowledge, vectors, tmp_path, NoProvider()).recover_job
    return queue, db, running, vectors


@pytest.mark.parametrize('window', [False, True])
def test_F2_durable_finish_survives_checkpoint_receipt_window(knowledge, tmp_path, monkeypatch, window):
    queue, db, running, vectors = committed(knowledge, tmp_path, monkeypatch, window=window)
    checkpoint = deepcopy(knowledge.get_ingestion_checkpoint(str(running.job_id), **SCOPE))
    assert checkpoint['job_snapshot']['finished_at'] == 110
    recovered = queue.recover_publication(running.job_id, **SCOPE, now=210)
    assert recovered.state is JobState.SUCCEEDED
    assert recovered.result.completed_at == recovered.attempts[-1].finished_at == 110
    assert knowledge.get_ingestion_checkpoint(str(running.job_id), **SCOPE) == checkpoint


def test_F2_durable_cancellation_finish_is_carried_to_queue(knowledge, tmp_path, monkeypatch):
    queue, db, running, lease = running_queue(1)
    owner = IngestionJob(job_id=str(running.job_id), **SCOPE, attempt=1,
        created_at=running.created_at, started_at=104, finished_at=110,
        status='cancelled', cancel_requested=True, metadata=_recovery_metadata(running))
    knowledge.begin_ingestion_checkpoint(owner)
    knowledge.request_ingestion_cancel(owner)
    knowledge.finish_ingestion_checkpoint(owner)
    before = deepcopy(knowledge.get_ingestion_checkpoint(str(running.job_id), **SCOPE))
    queue.publication_reconciler = handler(knowledge, InMemoryVectorStore(), tmp_path, NoProvider()).recover_job
    recovered = queue.recover_publication(running.job_id, **SCOPE, now=210)
    assert recovered.state is JobState.CANCELLED
    assert recovered.attempts[-1].finished_at == 110
    assert knowledge.get_ingestion_checkpoint(str(running.job_id), **SCOPE) == before


@pytest.mark.parametrize('start', [104, 105, 111])
def test_F3_receipt_start_conflict_preserves_canonical_identity(knowledge, tmp_path, monkeypatch, start):
    queue, db, running, vectors = committed(knowledge, tmp_path, monkeypatch)
    db.attempts[(str(running.job_id), 1)]['started_at'] = start
    db.jobs[str(running.job_id)]['updated_at'] = max(start, 104)
    before = deepcopy(knowledge.get_publication(str(running.job_id), **SCOPE))
    attempts_before = deepcopy(db.attempts)
    recovered = queue.recover_publication(running.job_id, **SCOPE, now=210)
    assert recovered.attempt_count == 1 and recovered.attempts[-1].started_at == start
    if start == 104:
        assert recovered.state is JobState.SUCCEEDED
        assert recovered.attempts[-1].finished_at == 110
    else:
        assert recovered.state is JobState.RUNNING
        assert db.jobs[str(running.job_id)]['last_error_code'] == 'publication_attempt_conflict'
        assert db.attempts == attempts_before
    assert knowledge.get_publication(str(running.job_id), **SCOPE) == before


@pytest.mark.parametrize('later_start', [107, 120])
def test_F3_later_attempt_is_preserved_and_deferred_with_reason(knowledge, tmp_path, monkeypatch, later_start):
    queue, db, running, vectors = committed(knowledge, tmp_path, monkeypatch)
    # Legitimate later history cannot be erased by an older committed receipt.
    db.jobs[str(running.job_id)]['max_attempts'] = 2
    db.jobs[str(running.job_id)]['attempts'] = 2
    db.jobs[str(running.job_id)]['updated_at'] = later_start
    db.attempts[(str(running.job_id), 1)].update(state='FAILED', finished_at=106,
        failure={'code':'handler_timeout','message':'timeout','retryable':True,'attempt':1,'occurred_at':106})
    db.attempts[(str(running.job_id), 2)] = dict(attempt_no=2, worker_id='later', state='RUNNING', started_at=later_start, finished_at=None, failure=None)
    before = deepcopy(db.attempts)
    receipt = deepcopy(knowledge.get_publication(str(running.job_id), **SCOPE))
    for poll in (210, 220):
        recovered = queue.recover_publication(running.job_id, **SCOPE, now=poll)
        assert recovered.state is JobState.RUNNING and recovered.attempt_count == 2
        assert db.jobs[str(running.job_id)]['last_error_code'] == 'publication_attempt_conflict'
    assert db.attempts == before
    assert knowledge.get_publication(str(running.job_id), **SCOPE) == receipt


@pytest.mark.parametrize('outcome', ['committed', 'cancelled'])
def test_F2_unknown_historical_finish_stays_unknown(knowledge, tmp_path, outcome):
    db = RecoveryConnection()
    queue = PostgresJobQueue(lambda: db, lease_seconds=10)
    queued = queue.enqueue(make_job(scope=JobScope(**SCOPE), max_attempts=1), expected_version=0)
    running, lease = queue.claim(worker_id='original', scope=queued.scope, expected_versions={}, now=104)[0]
    owner = IngestionJob(job_id=str(running.job_id), **SCOPE, attempt=1,
        document_id='doc' if outcome == 'committed' else None,
        created_at=100, started_at=104, finished_at=None,
        status='published' if outcome == 'committed' else 'cancelled',
        cancel_requested=outcome == 'cancelled', metadata=_recovery_metadata(running))
    knowledge.begin_ingestion_checkpoint(owner)
    knowledge.save_ingestion_checkpoint(owner, fingerprint={'fixture': 'terminal'}, artifacts={})
    if outcome == 'cancelled':
        knowledge.request_ingestion_cancel(owner)
    else:
        install_historical_publication(knowledge, owner, 'committed')
    knowledge.finish_ingestion_checkpoint(owner)
    checkpoint = deepcopy(knowledge.get_ingestion_checkpoint(owner.job_id, **SCOPE))
    receipt = deepcopy(knowledge.get_publication(owner.job_id, **SCOPE))
    worker = handler(knowledge, InMemoryVectorStore(), tmp_path, NoProvider())
    queue.publication_reconciler = worker.recover_job
    recovered = queue.recover_publication(running.job_id, **SCOPE, now=210)
    assert recovered.state is JobState.RUNNING
    assert db.jobs[owner.job_id]['last_error_code'] == 'publication_finish_unknown'
    assert knowledge.get_ingestion_checkpoint(owner.job_id, **SCOPE) == checkpoint
    assert knowledge.get_publication(owner.job_id, **SCOPE) == receipt
    assert worker.ingestion.get_status(owner.job_id).finished_at is None


def test_F2_mismatched_terminal_checkpoint_cannot_supply_receipt_finish(knowledge, tmp_path, monkeypatch):
    queue, db, running, vectors = committed(knowledge, tmp_path, monkeypatch, window=True)
    getter = knowledge.get_ingestion_checkpoint
    before = deepcopy(knowledge.get_publication(str(running.job_id), **SCOPE))
    def wrong(*args, **kwargs):
        checkpoint = deepcopy(getter(*args, **kwargs))
        checkpoint['job_snapshot']['started_at'] += 1
        return checkpoint
    knowledge.get_ingestion_checkpoint = wrong
    recovered = queue.recover_publication(running.job_id, **SCOPE, now=210)
    assert recovered.state is JobState.RUNNING
    assert knowledge.get_publication(str(running.job_id), **SCOPE) == before
