"""Completion decision discriminators: real local stores, controlled queue SQL.

PostgreSQL checks below observe emitted SQL/transaction ownership only. Parent
owns execution against actual PostgreSQL and its installed constraints.
"""
from copy import deepcopy
import json

import pytest

from external_ingestion import _recovery_metadata
from rick_ingestion.jobs import IngestionJob
from rick_jobs import JobState, JobScope, JobFailure
from postgres_jobs import PostgresJobQueue
from test_postgres_jobs import make_job
from rick_knowledge import InMemoryKnowledgeStore, SQLiteKnowledgeStore, PostgresKnowledgeStore, PostgresKnowledgeError
from rick_knowledge.fencing import OwnershipLostError
from rick_retrieval import InMemoryVectorStore
from test_prod02_recovery_rework4 import (
    SCOPE, Crash, NoProvider, handler, service, source,
)
from test_prod02_recovery_rework5 import RecoveryConnection


def running_queue(max_attempts=1, second=False):
    db = RecoveryConnection()
    queue = PostgresJobQueue(lambda: db, lease_seconds=10, backoff_seconds=0)
    job = queue.enqueue(make_job(scope=JobScope(**SCOPE), max_attempts=max_attempts), expected_version=0)
    running, lease = queue.claim(worker_id='first', scope=job.scope, expected_versions={}, now=104)[0]
    if second:
        queue.fail(lease, JobFailure('handler_timeout', 'timeout', True, 1, 105), now=105, expected_version=running.version)
        db.database_now = 106
        running, lease = queue.claim(worker_id='second', scope=job.scope, expected_versions={}, now=106)[0]
    return queue, db, running, lease


@pytest.fixture(params=['memory', 'sqlite'])
def knowledge(request, tmp_path):
    store = InMemoryKnowledgeStore() if request.param == 'memory' else SQLiteKnowledgeStore(tmp_path/'knowledge.sqlite')
    yield store
    if hasattr(store, 'close'):
        store.close()


def raw_historical_receipt(knowledge, record):
    """Installed old JSON, explicitly bypassing today's commit decision.

    A NEW resolve_publication(..., committed) is not a legacy-unknown fixture.
    This corrects that measurement without weakening the unknown assertions.
    """
    if isinstance(knowledge, InMemoryKnowledgeStore):
        knowledge._publications[tuple(record[k] for k in ('tenant_id', 'workspace_id', 'collection_id', 'job_id'))] = deepcopy(record)
    else:
        with knowledge._transaction():
            knowledge._connection.execute('UPDATE publication_receipts SET outcome=?, job_snapshot=? WHERE job_id=?',
                (record['outcome'], json.dumps(record['job_snapshot']), record['job_id']))


def publish(knowledge, tmp_path, monkeypatch, *, gap=False, second=False):
    import rick_ingestion.jobs as jobs
    monkeypatch.setattr(jobs.time, 'time', lambda: 110.)
    queue, db, running, lease = running_queue(2 if second else 1, second=second)
    vectors = InMemoryVectorStore()
    real_status = knowledge.set_document_status
    def lose_ack(document_id, status):
        real_status(document_id, status)
        if status == 'published':
            raise Crash('effect and receipt committed; no terminal checkpoint/snapshot')
    if gap:
        knowledge.set_document_status = lose_ack
    try:
        if gap:
            with pytest.raises(Crash):
                service(knowledge, vectors).ingest(source(tmp_path), **SCOPE,
                    job_id=str(running.job_id), _recovery_metadata=_recovery_metadata(running))
        else:
            result = service(knowledge, vectors).ingest(source(tmp_path), **SCOPE,
                job_id=str(running.job_id), _recovery_metadata=_recovery_metadata(running))
            assert result.finished_at == 110
    finally:
        knowledge.set_document_status = real_status
    return queue, db, running, vectors


@pytest.mark.parametrize('gap', [False, True])
@pytest.mark.parametrize('second', [False, True])
def test_committed_decision_survives_lost_ack(knowledge, tmp_path, monkeypatch, gap, second):
    queue, db, running, vectors = publish(knowledge, tmp_path, monkeypatch, gap=gap, second=second)
    receipt = deepcopy(knowledge.get_publication(str(running.job_id), **SCOPE))
    checkpoint = knowledge.get_ingestion_checkpoint(str(running.job_id), **SCOPE)
    assert receipt['outcome'] == 'committed'
    assert receipt['job_snapshot']['finished_at'] == 110
    assert receipt['job_snapshot']['attempt'] == running.attempt_count
    assert receipt['job_snapshot']['started_at'] == running.attempts[-1].started_at
    if gap:
        assert checkpoint['state'] == 'active' and checkpoint['job_snapshot']['finished_at'] is None
    if isinstance(knowledge, SQLiteKnowledgeStore):
        knowledge.close()
        knowledge = SQLiteKnowledgeStore(tmp_path/'knowledge.sqlite')
    import rick_ingestion.jobs as jobs
    monkeypatch.setattr(jobs.time, 'time', lambda: 210.)
    worker = handler(knowledge, vectors, tmp_path, NoProvider())
    queue.publication_reconciler = worker.recover_job
    recovered = queue.recover_publication(running.job_id, **SCOPE, now=210)
    assert recovered.state is JobState.SUCCEEDED
    assert recovered.result.completed_at == recovered.attempts[-1].finished_at == 110
    assert recovered.attempts[:-1] == running.attempts[:-1]
    assert worker.ingestion.get_status(str(running.job_id)).finished_at == 110
    assert knowledge.get_publication(str(running.job_id), **SCOPE)['job_snapshot']['finished_at'] == 110
    if isinstance(knowledge, SQLiteKnowledgeStore):
        knowledge.close()


def owner():
    return IngestionJob(job_id='decision', **SCOPE, document_id='doc',
        attempt=2, created_at=100, started_at=104,
        metadata={'publication_attempt': 'attempt-two', 'queue_attempt': 2})


def test_resolve_uses_adapter_clock_and_preserves_known_finish(knowledge, monkeypatch):
    import rick_ingestion.jobs as jobs
    monkeypatch.setattr(jobs.time, 'time', lambda: 110.)
    job = owner()
    knowledge.begin_publication(job, ready_count=3)
    receipt = knowledge.get_publication(job.job_id, **SCOPE)
    forged = deepcopy(receipt)
    forged['job_snapshot']['finished_at'] = 999
    committed = knowledge.resolve_publication(forged, 'committed')
    assert committed['job_snapshot']['finished_at'] == 110
    assert committed['ready_count'] == 3
    job.finished_at, job.status = 111, 'published'
    with pytest.raises(OwnershipLostError):
        knowledge.save_publication_snapshot(job)
    monkeypatch.setattr(jobs.time, 'time', lambda: 210.)
    assert knowledge.resolve_publication(forged, 'committed') == committed


def test_new_pending_cannot_import_caller_finish(knowledge):
    job = owner()
    job.finished_at = 109
    with pytest.raises(OwnershipLostError):
        knowledge.begin_publication(job)
    assert knowledge.get_publication(job.job_id, **SCOPE) is None


@pytest.mark.parametrize('outcome', ['committed', 'cancelled'])
def test_installed_unknown_finish_is_deferred_without_backfill(knowledge, tmp_path, outcome):
    queue, db, running, _ = running_queue(1)
    job = IngestionJob(job_id=str(running.job_id), **SCOPE, document_id='doc',
        attempt=1, created_at=running.created_at, started_at=104,
        metadata=_recovery_metadata(running))
    knowledge.begin_publication(job)
    receipt = knowledge.get_publication(job.job_id, **SCOPE)
    receipt['outcome'] = outcome
    raw_historical_receipt(knowledge, receipt)
    before = deepcopy(knowledge.get_publication(job.job_id, **SCOPE))
    worker = handler(knowledge, InMemoryVectorStore(), tmp_path, NoProvider())
    queue.publication_reconciler = worker.recover_job
    recovered = queue.recover_publication(running.job_id, **SCOPE, now=210)
    assert recovered.state is JobState.RUNNING
    assert db.jobs[job.job_id]['last_error_code'] == 'publication_finish_unknown'
    assert worker.ingestion.get_status(job.job_id).finished_at is None
    assert knowledge.get_publication(job.job_id, **SCOPE) == before
    job.finished_at, job.status = 210, 'published' if outcome == 'committed' else outcome
    with pytest.raises(OwnershipLostError):
        knowledge.save_publication_snapshot(job)
    assert knowledge.get_publication(job.job_id, **SCOPE) == before


@pytest.mark.parametrize('conflict', ['start', 'count'])
def test_canonical_conflicts_remain_deferred(knowledge, tmp_path, monkeypatch, conflict):
    queue, db, running, vectors = publish(knowledge, tmp_path, monkeypatch, gap=True, second=True)
    if conflict == 'start':
        db.attempts[(str(running.job_id), 2)]['started_at'] += 1
        db.jobs[str(running.job_id)]['updated_at'] += 1
    else:
        db.jobs[str(running.job_id)].update(attempts=3, max_attempts=3, updated_at=120)
        db.attempts[(str(running.job_id), 2)].update(state='FAILED', finished_at=112,
            failure={'code': 'handler_timeout', 'message': 'timeout', 'retryable': True, 'attempt': 2, 'occurred_at': 112})
        db.attempts[(str(running.job_id), 3)] = dict(attempt_no=3, worker_id='later',
            state='RUNNING', started_at=120, finished_at=None, failure=None)
    before = deepcopy(db.attempts)
    receipt = deepcopy(knowledge.get_publication(str(running.job_id), **SCOPE))
    queue.publication_reconciler = handler(knowledge, vectors, tmp_path, NoProvider()).recover_job
    result = queue.recover_publication(running.job_id, **SCOPE, now=210)
    assert result.state is JobState.RUNNING
    assert db.jobs[str(running.job_id)]['last_error_code'] == 'publication_attempt_conflict'
    assert db.attempts == before
    assert knowledge.get_publication(str(running.job_id), **SCOPE) == receipt


def test_normal_finish_uses_decision_before_later_transition(knowledge, tmp_path, monkeypatch):
    import rick_ingestion.jobs as jobs
    monkeypatch.setattr(jobs.time, 'time', lambda: 110.)
    queue, db, running, lease = running_queue()
    real_status = knowledge.set_document_status
    def delayed_return(document_id, status):
        real_status(document_id, status)
        if status == 'published':
            monkeypatch.setattr(jobs.time, 'time', lambda: 120.)
    knowledge.set_document_status = delayed_return
    result = service(knowledge).ingest(source(tmp_path), **SCOPE, job_id=str(running.job_id),
        _recovery_metadata=_recovery_metadata(running))
    assert result.status == 'published' and result.finished_at == 110
    receipt = knowledge.get_publication(result.job_id, **SCOPE)
    checkpoint = knowledge.get_ingestion_checkpoint(result.job_id, **SCOPE)
    assert receipt['job_snapshot']['finished_at'] == checkpoint['job_snapshot']['finished_at'] == 110


def test_new_pending_recovery_consumes_decision_time(knowledge, tmp_path, monkeypatch):
    import rick_ingestion.jobs as jobs
    monkeypatch.setattr(jobs.time, 'time', lambda: 110.)
    queue, db, running, lease = running_queue()
    vectors = InMemoryVectorStore()
    real_status = knowledge.set_document_status
    def before_commit(document_id, status):
        if status == 'published':
            raise Crash('pending receipt before effect commit')
        real_status(document_id, status)
    knowledge.set_document_status = before_commit
    with pytest.raises(Crash):
        service(knowledge, vectors).ingest(source(tmp_path), **SCOPE, job_id=str(running.job_id),
            _recovery_metadata=_recovery_metadata(running))
    assert knowledge.get_publication(str(running.job_id), **SCOPE)['outcome'] == 'pending'
    monkeypatch.setattr(jobs.time, 'time', lambda: 150.)
    def commit_then_delay(document_id, status):
        real_status(document_id, status)
        monkeypatch.setattr(jobs.time, 'time', lambda: 160.)
    knowledge.set_document_status = commit_then_delay
    result = service(knowledge, vectors, NoProvider()).recover_publication(str(running.job_id), **SCOPE)
    assert result.status == 'published' and result.finished_at == 150
    assert knowledge.get_publication(str(running.job_id), **SCOPE)['job_snapshot']['finished_at'] == 150


def test_clock_regression_commits_without_fabricating_finish(knowledge, tmp_path, monkeypatch):
    import rick_ingestion.jobs as jobs
    queue, db, running, vectors = publish(knowledge, tmp_path, monkeypatch, gap=True)
    receipt = knowledge.get_publication(str(running.job_id), **SCOPE)
    # A new pending decision with a regressed trusted clock. The raw rewrite
    # is test setup only; normal APIs cannot reopen this terminal receipt.
    receipt['outcome'] = 'pending'
    receipt['job_snapshot']['finished_at'] = None
    raw_historical_receipt(knowledge, receipt)
    monkeypatch.setattr(jobs.time, 'time', lambda: 103.)
    committed = knowledge.resolve_publication(receipt, 'committed')
    assert committed['outcome'] == 'committed' and committed['job_snapshot']['finished_at'] is None
    monkeypatch.setattr(jobs.time, 'time', lambda: 210.)
    queue.publication_reconciler = handler(knowledge, vectors, tmp_path, NoProvider()).recover_job
    result = queue.recover_publication(running.job_id, **SCOPE, now=210)
    assert result.state is JobState.RUNNING
    assert db.jobs[str(running.job_id)]['last_error_code'] == 'publication_finish_unknown'
    assert knowledge.get_publication(str(running.job_id), **SCOPE) == committed


def test_legacy_terminal_checkpoint_supplies_only_known_finish(knowledge, tmp_path, monkeypatch):
    queue, db, running, vectors = publish(knowledge, tmp_path, monkeypatch)
    receipt = knowledge.get_publication(str(running.job_id), **SCOPE)
    receipt['job_snapshot']['finished_at'] = None
    raw_historical_receipt(knowledge, receipt)
    queue.publication_reconciler = handler(knowledge, vectors, tmp_path, NoProvider()).recover_job
    result = queue.recover_publication(running.job_id, **SCOPE, now=210)
    assert result.state is JobState.SUCCEEDED and result.result.completed_at == 110
    assert result.attempts[-1].finished_at == 110
    # Installed history stays unknown; the matching checkpoint supplies only
    # the public/canonical projection, never a receipt backfill.
    assert knowledge.get_publication(str(running.job_id), **SCOPE)['job_snapshot']['finished_at'] is None


def test_sqlite_commit_receipt_failure_rolls_back_document(tmp_path, monkeypatch):
    knowledge = SQLiteKnowledgeStore(tmp_path/'knowledge.sqlite')
    queue, db, running, vectors = publish(knowledge, tmp_path, monkeypatch, gap=True)
    receipt = knowledge.get_publication(str(running.job_id), **SCOPE)
    knowledge.set_document_status(receipt['document_id'], 'processing')
    receipt['outcome'] = 'pending'
    receipt['job_snapshot']['finished_at'] = None
    raw_historical_receipt(knowledge, receipt)
    knowledge._connection.execute("CREATE TEMP TRIGGER reject_completion BEFORE UPDATE ON publication_receipts WHEN NEW.outcome='committed' BEGIN SELECT RAISE(ABORT, 'injected receipt failure'); END")
    with pytest.raises(Exception, match='injected receipt failure'):
        knowledge.set_document_status(receipt['document_id'], 'published')
    assert knowledge.get_document(receipt['document_id']).status == 'processing'
    assert knowledge.get_publication(str(running.job_id), **SCOPE) == receipt
    knowledge.close()


@pytest.mark.parametrize('second', [False, True])
def test_lost_ack_exception_with_unavailable_read_preserves_committed_time(knowledge, tmp_path, monkeypatch, second):
    import rick_ingestion.jobs as jobs
    monkeypatch.setattr(jobs.time, 'time', lambda: 110.)
    queue, db, running, _ = running_queue(2 if second else 1, second=second)
    vectors = InMemoryVectorStore()
    real_status, real_get = knowledge.set_document_status, knowledge.get_publication
    unavailable = False
    def commit_lose_ack(document_id, status):
        nonlocal unavailable
        real_status(document_id, status)
        if status == 'published':
            unavailable = True
            raise RuntimeError('lost commit acknowledgement')
    def read(*args, **kwargs):
        if unavailable:
            raise RuntimeError('receipt read temporarily unavailable')
        return real_get(*args, **kwargs)
    knowledge.set_document_status, knowledge.get_publication = commit_lose_ack, read
    result = service(knowledge, vectors).ingest(source(tmp_path), **SCOPE,
        job_id=str(running.job_id), _recovery_metadata=_recovery_metadata(running))
    assert result.status == 'verifying' and result.metadata['publication_outcome_unknown']
    receipt = real_get(str(running.job_id), **SCOPE)
    assert receipt['outcome'] == 'committed' and receipt['job_snapshot']['finished_at'] == 110
    checkpoint = knowledge.get_ingestion_checkpoint(str(running.job_id), **SCOPE)
    assert checkpoint['state'] == 'active' and checkpoint['job_snapshot']['finished_at'] is None
    unavailable = False
    knowledge.set_document_status = real_status
    monkeypatch.setattr(jobs.time, 'time', lambda: 210.)
    queue.publication_reconciler = handler(knowledge, vectors, tmp_path, NoProvider()).recover_job
    recovered = queue.recover_publication(running.job_id, **SCOPE, now=210)
    assert recovered.state is JobState.SUCCEEDED
    assert recovered.result.completed_at == recovered.attempts[-1].finished_at == 110
    assert recovered.attempts[:-1] == running.attempts[:-1]


@pytest.mark.parametrize('known', [False, True])
def test_projection_and_later_document_mutation_cannot_supply_finish(knowledge, tmp_path, monkeypatch, known):
    queue, db, running, vectors = publish(knowledge, tmp_path, monkeypatch, gap=True)
    receipt = knowledge.get_publication(str(running.job_id), **SCOPE)
    if not known:
        receipt['job_snapshot']['finished_at'] = None
        raw_historical_receipt(knowledge, receipt)
    knowledge.set_document_status(receipt['document_id'], 'unpublished')
    forged = IngestionJob(job_id=str(running.job_id), **SCOPE, document_id=receipt['document_id'],
        status='published', attempt=running.attempt_count, created_at=running.created_at,
        started_at=running.attempts[-1].started_at, finished_at=999,
        metadata={**receipt['job_snapshot']['metadata'], 'finished_at': 999, 'completion_time': 999})
    recovered = service(knowledge, vectors, NoProvider()).recover_publication(str(running.job_id), **SCOPE, snapshot=forged)
    assert recovered.status == 'published'
    assert recovered.finished_at == (110 if known else None)
    assert knowledge.get_document(receipt['document_id']).status == 'unpublished'
    assert knowledge.get_publication(str(running.job_id), **SCOPE)['job_snapshot']['finished_at'] == (110 if known else None)


def test_conflicting_terminal_checkpoint_is_not_rewritten(knowledge, tmp_path, monkeypatch):
    queue, db, running, vectors = publish(knowledge, tmp_path, monkeypatch)
    checkpoint = knowledge.get_ingestion_checkpoint(str(running.job_id), **SCOPE)
    checkpoint['job_snapshot']['finished_at'] = 111
    knowledge._write_ingestion_checkpoint(checkpoint)
    receipt = deepcopy(knowledge.get_publication(str(running.job_id), **SCOPE))
    queue.publication_reconciler = handler(knowledge, vectors, tmp_path, NoProvider()).recover_job
    recovered = queue.recover_publication(running.job_id, **SCOPE, now=210)
    assert recovered.state is JobState.RUNNING
    assert knowledge.get_ingestion_checkpoint(str(running.job_id), **SCOPE) == checkpoint
    assert knowledge.get_publication(str(running.job_id), **SCOPE) == receipt


def test_acknowledged_commit_with_unavailable_finish_read_does_not_project_clock(knowledge, tmp_path, monkeypatch):
    import rick_ingestion.jobs as jobs
    monkeypatch.setattr(jobs.time, 'time', lambda: 110.)
    queue, db, running, _ = running_queue()
    real_status, real_get = knowledge.set_document_status, knowledge.get_publication
    unavailable = False
    def commit(document_id, status):
        nonlocal unavailable
        real_status(document_id, status)
        if status == 'published':
            unavailable = True
            monkeypatch.setattr(jobs.time, 'time', lambda: 120.)
    def read(*args, **kwargs):
        if unavailable:
            raise RuntimeError('completion read temporarily unavailable')
        return real_get(*args, **kwargs)
    knowledge.set_document_status, knowledge.get_publication = commit, read
    vectors = InMemoryVectorStore()
    ingestion = service(knowledge, vectors)
    with pytest.raises(RuntimeError):
        ingestion.ingest(source(tmp_path), **SCOPE, job_id=str(running.job_id),
            _recovery_metadata=_recovery_metadata(running))
    cached = ingestion.get_status(str(running.job_id))
    assert cached.status == 'verifying' and cached.finished_at is None
    assert real_get(str(running.job_id), **SCOPE)['job_snapshot']['finished_at'] == 110
    unavailable = False
    recovered = service(knowledge, vectors, NoProvider()).recover_publication(str(running.job_id), **SCOPE)
    assert recovered.status == 'published' and recovered.finished_at == 110


class RecordingCursor:
    def __init__(self, connection):
        self.connection, self.rows = connection, []
    def execute(self, query, params=()):
        compact = ' '.join(query.lower().split())
        self.connection.calls.append((compact, params))
        self.rows = []
        if compact.startswith('select status from rick_documents'):
            self.rows = [{'status': 'processing'}]
        elif compact.startswith('select receipt.cancel_requested'):
            self.rows = [{'cancel_requested': False}]
        elif compact.startswith('select attempt_id from rick_publication_receipts'):
            self.rows = [{'attempt_id': self.connection.receipt['attempt_id']}]
        elif compact.startswith('select tenant_id, workspace_id, collection_id, job_id,'):
            self.rows = [deepcopy(self.connection.receipt)]
        elif compact.startswith('select extract(epoch'):
            self.rows = [{'finished_at': self.connection.clock}]
        elif compact.startswith('insert into rick_publication_receipts'):
            keys = ('tenant_id', 'workspace_id', 'collection_id', 'job_id', 'document_id',
                'attempt_id', 'document_attempt', 'outcome', 'cancel_requested', 'ready_count', 'job_snapshot')
            self.connection.receipt = dict(zip(keys, params))
            self.connection.receipt['job_snapshot'] = json.loads(params[-1])
        if 'update rick_publication_receipts as receipt' in compact and self.connection.fail_receipt:
            raise RuntimeError('injected SQL execution failure')
    def fetchone(self):
        return self.rows.pop(0) if self.rows else None
    def fetchall(self):
        rows, self.rows = self.rows, []
        return rows
    def close(self):
        pass


class RecordingConnection:
    def __init__(self, *, fail_receipt=False):
        self.calls, self.commits, self.rollbacks = [], 0, 0
        self.fail_receipt, self.clock, self.receipt = fail_receipt, 110., None
    def cursor(self):
        return RecordingCursor(self)
    def commit(self):
        self.commits += 1
    def rollback(self):
        self.rollbacks += 1
    def close(self):
        pass


@pytest.mark.parametrize('fail_receipt', [False, True])
def test_postgres_actual_writer_emits_atomic_scoped_completion(fail_receipt):
    # Two independent connections, as required by the public guard contract.
    # This records production SQL and commit/rollback; it does NOT execute SQL.
    guard = RecordingConnection()
    decision = RecordingConnection(fail_receipt=fail_receipt)
    connections = iter([guard, decision])
    store = PostgresKnowledgeStore(lambda: next(connections))
    if fail_receipt:
        with pytest.raises(PostgresKnowledgeError):
            store.set_document_status('doc', 'published', tenant_id='t', workspace_id='w')
        assert decision.commits == 0 and decision.rollbacks == 1
    else:
        store.set_document_status('doc', 'published', tenant_id='t', workspace_id='w')
        assert decision.commits == 1 and decision.rollbacks == 0
    statements = [sql for sql, params in decision.calls]
    assert any('update rick_documents' in sql for sql in statements)
    receipt_sql = next(sql for sql in statements if 'update rick_publication_receipts as receipt' in sql)
    assert 'clock_timestamp()' in receipt_sql and 'job_snapshot=case' in receipt_sql
    assert "receipt.outcome='pending'" in receipt_sql
    assert "receipt.job_snapshot->>'finished_at' is not null then receipt.job_snapshot" in receipt_sql
    assert "jsonb_set(receipt.job_snapshot, '{finished_at}'" in receipt_sql
    assert 'decision.finished_at >= coalesce' in receipt_sql
    for key in ('tenant_id', 'workspace_id', 'collection_id'):
        assert f'receipt.{key}=document.{key}' in receipt_sql
    assert "receipt.document_attempt=document.metadata->>'_ingestion_attempt'" in receipt_sql


def test_postgres_generic_decision_samples_db_time_in_locked_transaction():
    job = owner()
    local = InMemoryKnowledgeStore()
    local.begin_publication(job)
    receipt = local.get_publication(job.job_id, **SCOPE)
    guard, decision = RecordingConnection(), RecordingConnection()
    decision.receipt = deepcopy(receipt)
    connections = iter([guard, decision])
    store = PostgresKnowledgeStore(lambda: next(connections))
    result = store.resolve_publication(receipt, 'committed')
    assert result['job_snapshot']['finished_at'] == decision.clock
    assert decision.commits == 1 and guard.commits == 0
    statements = [sql for sql, params in decision.calls]
    assert 'for update' in statements[0]
    assert any('extract(epoch from clock_timestamp())' in sql for sql in statements)
