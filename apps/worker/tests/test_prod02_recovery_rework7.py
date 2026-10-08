"""Integration decision authority and raw legacy fixtures; local adapters only."""
from copy import deepcopy

import pytest

from rick_ingestion import IngestionService
from rick_ingestion.jobs import IngestionJob
from rick_knowledge import InMemoryKnowledgeStore, SQLiteKnowledgeStore
from rick_knowledge.fencing import OwnershipLostError
from rick_knowledge.publication import publication_snapshot
from rick_retrieval import DeterministicHashEmbedding, InMemoryVectorStore

SCOPE = dict(tenant_id='t', workspace_id='w', collection_id='c')


def install_historical_publication(store, job, outcome):
    """Explicit trusted raw installed data, never a NEW public decision.

    Test-only adapter write preserves supplied historical facts exactly.
    Public begin/resolve/snapshot still reject caller-provided finish facts.
    """
    attempt = job.metadata['publication_attempt']
    record = dict(job_id=job.job_id, tenant_id=job.tenant_id,
        workspace_id=job.workspace_id, collection_id=job.collection_id,
        document_id=job.document_id, attempt_id=attempt,
        document_attempt=job.metadata.get('published_document_attempt', attempt),
        outcome=outcome, cancel_requested=False, ready_count=0,
        job_snapshot=publication_snapshot(job))
    store._write_publication(record)
    return deepcopy(store.get_publication(job.job_id, tenant_id=job.tenant_id,
        workspace_id=job.workspace_id, collection_id=job.collection_id))


@pytest.fixture(params=['memory', 'sqlite'])
def knowledge(request, tmp_path):
    store = InMemoryKnowledgeStore() if request.param == 'memory' else SQLiteKnowledgeStore(tmp_path/'knowledge.sqlite')
    yield store
    if hasattr(store, 'close'):
        store.close()


def owner():
    return IngestionJob(**SCOPE, job_id='terminal7', document_id='doc',
        status='verifying', stage='verifying', created_at=10, started_at=20,
        metadata={'publication_attempt': 'token', 'queue_attempt': 1})


@pytest.mark.parametrize('outcome', ['failed', 'cancelled'])
def test_new_terminal_decision_uses_adapter_time_not_caller_or_poll(knowledge, monkeypatch, outcome):
    job = owner()
    knowledge.begin_ingestion_checkpoint(job)
    knowledge.save_ingestion_checkpoint(job, fingerprint={'fixture':'decision'}, artifacts={})
    knowledge.begin_publication(job)
    pending = knowledge.get_publication(job.job_id, **SCOPE)
    forged = deepcopy(pending)
    forged['job_snapshot']['finished_at'] = 999
    monkeypatch.setattr(knowledge, '_publication_commit_time', lambda: 30.)
    decision = knowledge.resolve_publication(forged, outcome)
    assert decision['job_snapshot']['finished_at'] == 30
    monkeypatch.setattr(knowledge, '_publication_commit_time', lambda: 999.)
    recovered = IngestionService(knowledge=knowledge, vectors=InMemoryVectorStore(),
        embeddings=DeterministicHashEmbedding()).recover_publication(job.job_id, **SCOPE)
    assert recovered.status == outcome and recovered.finished_at == 30
    checkpoint = knowledge.get_ingestion_checkpoint(job.job_id, **SCOPE)
    assert checkpoint['state'] == outcome and checkpoint['job_snapshot']['finished_at'] == 30
    assert knowledge.resolve_publication(forged, outcome)['job_snapshot']['finished_at'] == 30
    recovered.finished_at = 31
    with pytest.raises(OwnershipLostError):
        knowledge.finish_ingestion_checkpoint(recovered)
    assert knowledge.get_ingestion_checkpoint(job.job_id, **SCOPE) == checkpoint


@pytest.mark.parametrize('outcome', ['failed', 'cancelled'])
def test_installed_unknown_terminal_stays_unknown(knowledge, monkeypatch, outcome):
    job = owner()
    before = install_historical_publication(knowledge, job, outcome)
    monkeypatch.setattr(knowledge, '_publication_commit_time', lambda: 999.)
    assert knowledge.resolve_publication(before, outcome) == before
    result = IngestionService(knowledge=knowledge, vectors=InMemoryVectorStore(),
        embeddings=DeterministicHashEmbedding()).recover_publication(job.job_id, **SCOPE)
    assert result.status == outcome and result.finished_at is None
    assert knowledge.get_publication(job.job_id, **SCOPE) == before
    result.finished_at = 999
    with pytest.raises(OwnershipLostError):
        knowledge.save_publication_snapshot(result)
    assert knowledge.get_publication(job.job_id, **SCOPE) == before


@pytest.mark.parametrize('outcome', ['failed', 'cancelled'])
def test_new_terminal_regressed_clock_does_not_use_poll(knowledge, monkeypatch, outcome):
    job = owner()
    knowledge.begin_publication(job)
    monkeypatch.setattr(knowledge, '_publication_commit_time', lambda: 19.)
    decision = knowledge.resolve_publication(knowledge.get_publication(job.job_id, **SCOPE), outcome)
    assert decision['job_snapshot']['finished_at'] is None
    monkeypatch.setattr(knowledge, '_publication_commit_time', lambda: 999.)
    result = IngestionService(knowledge=knowledge, vectors=InMemoryVectorStore(),
        embeddings=DeterministicHashEmbedding()).recover_publication(job.job_id, **SCOPE)
    assert result.finished_at is None


@pytest.mark.parametrize('outcome', ['failed', 'cancelled'])
def test_pending_checkpoint_cannot_bootstrap_caller_finish(knowledge, outcome):
    job = owner()
    knowledge.begin_ingestion_checkpoint(job)
    knowledge.begin_publication(job)
    before = deepcopy(knowledge.get_ingestion_checkpoint(job.job_id, **SCOPE))
    job.status = outcome
    job.finished_at = 999
    with pytest.raises(OwnershipLostError):
        knowledge.finish_ingestion_checkpoint(job)
    assert knowledge.get_ingestion_checkpoint(job.job_id, **SCOPE) == before
    assert knowledge.get_publication(job.job_id, **SCOPE)['outcome'] == 'pending'
    with pytest.raises(OwnershipLostError):
        knowledge.save_publication_snapshot(job)


@pytest.mark.parametrize('outcome', ['failed', 'cancelled'])
def test_sqlite_new_terminal_decision_rolls_back_time_with_outcome(tmp_path, monkeypatch, outcome):
    store = SQLiteKnowledgeStore(tmp_path/'rollback.sqlite')
    try:
        job = owner()
        store.begin_publication(job)
        before = store.get_publication(job.job_id, **SCOPE)
        original = store._write_publication
        def fail_after_write(record):
            original(record)
            raise RuntimeError('decision write lost')
        monkeypatch.setattr(store, '_write_publication', fail_after_write)
        with pytest.raises(RuntimeError):
            store.resolve_publication(before, outcome)
        assert store.get_publication(job.job_id, **SCOPE) == before
    finally:
        store.close()
    reopened = SQLiteKnowledgeStore(tmp_path/'rollback.sqlite')
    try:
        assert reopened.get_publication(job.job_id, **SCOPE) == before
    finally:
        reopened.close()


@pytest.mark.parametrize('outcome', ['failed', 'cancelled'])
def test_postgres_terminal_sql_uses_locked_adapter_clock(outcome):
    # SQL/connection evidence only; Parent owns actual PostgreSQL execution.
    from rick_knowledge import PostgresKnowledgeStore
    from test_prod02_recovery_rework6 import RecordingConnection
    local = InMemoryKnowledgeStore()
    job = owner()
    local.begin_publication(job)
    pending = local.get_publication(job.job_id, **SCOPE)
    guard, decision = RecordingConnection(), RecordingConnection()
    decision.receipt = deepcopy(pending)
    connections = iter([guard, decision])
    store = PostgresKnowledgeStore(lambda: next(connections))
    result = store.resolve_publication(pending, outcome)
    assert result['outcome'] == outcome and result['job_snapshot']['finished_at'] == decision.clock
    assert decision.commits == 1 and guard.commits == 0
    statements = [sql for sql, params in decision.calls]
    assert 'for update' in statements[0]
    assert any('extract(epoch from clock_timestamp())' in sql for sql in statements)


@pytest.mark.parametrize('duplicate', [False, True])
def test_normal_guard_projection_still_finalizes_completion_once(knowledge, tmp_path, duplicate):
    from contextlib import contextmanager
    events = []
    class Events:
        def emit(self, event):
            events.append(event)
    service = IngestionService(knowledge=knowledge, vectors=InMemoryVectorStore(),
        embeddings=DeterministicHashEmbedding(), events=Events())
    source = tmp_path/'source.txt'
    source.write_text('The committed publication must retain completion notification. ' * 20)
    if duplicate:
        assert service.ingest(source, **SCOPE).status == 'published'
    events.clear()
    @contextmanager
    def guard():
        yield
        job = service.get_status('normal7')
        receipt = knowledge.get_publication(job.job_id, **SCOPE)
        assert job.status == 'published' and job.finished_at == receipt['job_snapshot']['finished_at']
        assert service.cancel(job.job_id) is False
    result = service.ingest(source, **SCOPE, job_id='normal7', publication_guard=guard)
    assert result.status == 'published'
    assert sum(e['type'] == 'ingestion.completed' for e in events) == 1
    assert not any(e['type'] == 'ingestion.cancelled' for e in events)
    checkpoint = knowledge.get_ingestion_checkpoint(result.job_id, **SCOPE)
    assert checkpoint['state'] == 'committed' and checkpoint['artifacts'] == {}
    assert checkpoint['job_snapshot']['finished_at'] == result.finished_at
    assert knowledge.get_publication(result.job_id, **SCOPE)['job_snapshot']['finished_at'] == result.finished_at
