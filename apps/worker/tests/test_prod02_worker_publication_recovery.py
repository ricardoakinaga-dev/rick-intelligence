from types import SimpleNamespace

import pytest

from external_ingestion import ExternalIngestionError, ExternalIngestionHandler, _recovery_metadata
from rick_jobs import JobResult, JobState, JobFailure, JobPublicationFacts, JobPublicationCancellation
from test_postgres_jobs import make_job, make_queue


def test_final_attempt_pre_ack_crash_recovers_committed_success():
    queue, connection = make_queue()
    queued = queue.enqueue(make_job(max_attempts=1), expected_version=0)
    running, lease = queue.claim(worker_id='worker-a', scope=queued.scope, expected_versions={}, now=104)[0]
    receipt = JobResult(document_id='winner', output_refs={}, completed_at=105)
    calls = []
    def recovery(job):
        calls.append(job)
        return receipt
    queue.publication_reconciler = recovery
    connection.database_now = 114
    assert queue.claim(worker_id='restarted', scope=queued.scope, expected_versions={}, now=114) == ()
    result = queue.get_for_workspace(queued.job_id, tenant_id=queued.tenant_id, workspace_id=queued.workspace_id)
    assert result.state is JobState.SUCCEEDED
    assert result.result.document_id == 'winner'
    assert result.attempt_count == result.max_attempts == 1
    assert connection.attempts[(str(queued.job_id), 1)]['state'] == 'SUCCEEDED'
    assert len(calls) == 1


def test_unavailable_final_outcome_remains_nonterminal_without_an_extra_attempt():
    queue, connection = make_queue()
    queued = queue.enqueue(make_job(max_attempts=1), expected_version=0)
    running, lease = queue.claim(worker_id='worker-a', scope=queued.scope, expected_versions={}, now=104)[0]
    calls = []
    def unavailable(job):
        calls.append(job)
        raise ExternalIngestionError('recovery_required')
    queue.publication_reconciler = unavailable
    for now in [114, 115, 116]:
        connection.database_now = now
        assert queue.claim(worker_id='restarted', scope=queued.scope, expected_versions={}, now=now) == ()
        row = connection.jobs[str(queued.job_id)]
        assert row['contract_state'] == 'RUNNING'
        assert row['attempts'] == 1
        assert row['version'] == running.version
    assert len(calls) == 3
    queue.publication_reconciler = lambda job: JobResult(document_id='winner', completed_at=116, output_refs={})
    connection.database_now = 117
    assert queue.claim(worker_id='restarted', scope=queued.scope, expected_versions={}, now=117) == ()
    assert connection.jobs[str(queued.job_id)]['contract_state'] == 'SUCCEEDED'


def test_worker_failure_after_commit_cannot_dead_letter_publication():
    queue, connection = make_queue()
    queued = queue.enqueue(make_job(max_attempts=1), expected_version=0)
    running, lease = queue.claim(worker_id='worker-a', scope=queued.scope, expected_versions={}, now=104)[0]
    queue.publication_reconciler = lambda job: JobResult(document_id='winner', completed_at=105, output_refs={})
    result = queue.fail(lease, JobFailure(code='handler_timeout', message='timeout', retryable=True, attempt=1, occurred_at=105),
                        now=105, expected_version=running.version)
    assert result.state is JobState.SUCCEEDED
    assert result.attempt_count == 1


def test_external_handler_unknown_commit_is_explicit_recovery(tmp_path):
    from test_external_ingestion import RECORD, Store
    class Ingestion:
        def ingest(self, path, **kwargs):
            return SimpleNamespace(status='verifying', metadata={'publication_outcome_unknown': True})
    handler = ExternalIngestionHandler(Ingestion(), Store(), temp_root=tmp_path)
    with pytest.raises(ExternalIngestionError) as caught:
        handler(RECORD)
    assert caught.value.code == 'recovery_required'


def test_public_production_status_recovers_restart_commit_without_handler_replay(tmp_path):
    from canonical_queue import CanonicalIngestionQueueAdapter
    from services.postgres_ingestion import PostgresIngestionApplicationService
    from rick_ingestion import IngestionService
    from rick_knowledge import SQLiteKnowledgeStore
    from rick_retrieval import InMemoryVectorStore, DeterministicHashEmbedding

    class Objects:
        def put(self, *args, **kwargs):
            raise AssertionError('recovery cannot rewrite source')
        def get(self, *args, **kwargs):
            raise AssertionError('recovery cannot hydrate source')
    queue, connection = make_queue()
    queued = queue.enqueue(make_job(max_attempts=1), expected_version=0)
    running, lease = queue.claim(worker_id='worker-a', scope=queued.scope, expected_versions={}, now=104)[0]
    knowledge = SQLiteKnowledgeStore(tmp_path / 'knowledge.sqlite')
    vectors = InMemoryVectorStore()
    source = tmp_path / 'guide.txt'
    source.write_text('Public production recovery authority. ' * 80)
    scope = dict(tenant_id=queued.tenant_id, workspace_id=queued.workspace_id, collection_id=queued.collection_id)
    try:
        canonical = IngestionService(knowledge=knowledge, vectors=vectors, embeddings=DeterministicHashEmbedding())
        published = canonical.ingest(source, **scope, job_id=str(queued.job_id),
            _recovery_metadata=_recovery_metadata(running))
        before = vectors.all_points()
        knowledge.close()
        knowledge = SQLiteKnowledgeStore(tmp_path / 'knowledge.sqlite')
        class NoReplay(DeterministicHashEmbedding):
            def embed(self, texts):
                raise AssertionError('recovery cannot replay embeddings')
        restarted = IngestionService(knowledge=knowledge, vectors=vectors, embeddings=NoReplay())
        handler = ExternalIngestionHandler(restarted, Objects(), temp_root=tmp_path / 'worker')
        # Exact composition contract for the Lead, for both API and worker queues.
        queue.publication_reconciler = handler.recover_job
        service = PostgresIngestionApplicationService(queue=CanonicalIngestionQueueAdapter(queue),
            object_store=Objects(), knowledge=knowledge)
        assert service.get_status(str(queued.job_id), tenant_id='foreign', workspace_id=queued.workspace_id,
                                  allowed_collection_ids=[queued.collection_id]) is None
        assert service.get_status(str(queued.job_id), tenant_id=queued.tenant_id, workspace_id=queued.workspace_id,
                                  allowed_collection_ids=[]) is None
        assert connection.jobs[str(queued.job_id)]['contract_state'] == 'RUNNING'
        public = service.get_status(str(queued.job_id), tenant_id=queued.tenant_id, workspace_id=queued.workspace_id,
                                    allowed_collection_ids=[queued.collection_id])
        assert public['status'] == 'published'
        assert public['document_id'] == published.document_id
        assert vectors.all_points() == before
        assert connection.jobs[str(queued.job_id)]['attempts'] == 1
        assert 'publication_attempt' not in public['metadata']
        assert restarted.get_status(str(queued.job_id)).status == 'published'
    finally:
        knowledge.close()


def test_runtime_unknown_outcome_does_not_fail_the_final_attempt():
    from test_runtime import FakeQueue, ManualClock, job, make_runtime
    clock = ManualClock()
    queue = FakeQueue([job(now=clock.value)])
    def unavailable(job, lease, *, cancelled):
        raise ExternalIngestionError('recovery_required')
    runtime = make_runtime(queue, clock, unavailable)
    try:
        result = runtime.run_once()
        assert result.failed == result.succeeded == 0
        assert result.lease_lost == 1
        assert queue.failures == queue.acknowledged == []
    finally:
        runtime.shutdown()


def test_committed_receipt_dominates_owner_cancellation():
    queue, connection = make_queue()
    queued = queue.enqueue(make_job(max_attempts=1), expected_version=0)
    running, lease = queue.claim(worker_id='worker-a', scope=queued.scope, expected_versions={}, now=104)[0]
    queue.publication_reconciler = lambda job: JobResult(document_id='winner', completed_at=105, output_refs={})
    result = queue.cancel_lease(lease, now=105, expected_version=running.version)
    assert result.state is JobState.SUCCEEDED


def test_durable_cancel_receipt_terminalizes_without_a_retry():
    queue, connection = make_queue()
    queued = queue.enqueue(make_job(max_attempts=2), expected_version=0)
    running, lease = queue.claim(worker_id='worker-a', scope=queued.scope, expected_versions={}, now=104)[0]
    def cancelled(job):
        error = ExternalIngestionError('cancelled')
        error.publication_cancellation = JobPublicationCancellation(
            facts=JobPublicationFacts(job_id=job.job_id, scope=job.scope,
                attempt=job.attempt_count, created_at=job.created_at,
                started_at=job.attempts[-1].started_at,
                attempt_id=_recovery_metadata(job)['publication_attempt']),
            completed_at=105.)
        raise error
    queue.publication_reconciler = cancelled
    connection.database_now = 114
    assert queue.claim(worker_id='restarted', scope=queued.scope, expected_versions={}, now=114) == ()
    assert connection.jobs[str(queued.job_id)]['contract_state'] == 'CANCELLED'
    assert connection.jobs[str(queued.job_id)]['attempts'] == 1


def test_public_unknown_is_nonterminal_and_owner_cancellation_is_durable(tmp_path):
    from canonical_queue import CanonicalIngestionQueueAdapter
    from services.postgres_ingestion import PostgresIngestionApplicationService
    from rick_ingestion import IngestionService
    from rick_ingestion.jobs import IngestionJob
    from rick_knowledge import SQLiteKnowledgeStore
    from rick_retrieval import InMemoryVectorStore, DeterministicHashEmbedding
    class Objects:
        def put(self, *args, **kwargs):
            raise AssertionError('must not write source')
        def get(self, *args, **kwargs):
            raise AssertionError('must not read source')
    knowledge = SQLiteKnowledgeStore(tmp_path / 'pending.sqlite')
    queue, connection = make_queue()
    queued = queue.enqueue(make_job(max_attempts=1), expected_version=0)
    running, lease = queue.claim(worker_id='worker-a', scope=queued.scope, expected_versions={}, now=104)[0]
    scope = dict(tenant_id=queued.tenant_id, workspace_id=queued.workspace_id, collection_id=queued.collection_id)
    from external_ingestion import _recovery_metadata
    intent = IngestionJob(**scope, job_id=str(queued.job_id), document_id='doc',
        created_at=running.created_at, started_at=running.attempts[-1].started_at,
        metadata=_recovery_metadata(running))
    knowledge.begin_publication(intent)
    canonical = IngestionService(knowledge=knowledge, vectors=InMemoryVectorStore(), embeddings=DeterministicHashEmbedding())
    handler = ExternalIngestionHandler(canonical, Objects(), temp_root=tmp_path / 'worker')
    queue.publication_reconciler = handler.recover_job
    service = PostgresIngestionApplicationService(queue=CanonicalIngestionQueueAdapter(queue), object_store=Objects(), knowledge=knowledge)
    original_get = knowledge.get_document
    def unreadable(*args, **kwargs):
        raise RuntimeError('authority temporarily unavailable')
    knowledge.get_document = unreadable
    try:
        public = service.get_status(str(queued.job_id), tenant_id=queued.tenant_id, workspace_id=queued.workspace_id,
                                    allowed_collection_ids=[queued.collection_id])
        assert public['status'] == public['stage'] == 'verifying'
        assert public['recovery_required'] is True
        assert public['metadata']['publication_outcome'] == 'unknown'
        assert public['error_code'] is None and public['finished_at'] is None
        assert connection.jobs[str(queued.job_id)]['contract_state'] == 'RUNNING'
        assert queue.cancel_lease(lease, now=105, expected_version=running.version).state is JobState.RUNNING
        assert knowledge.get_publication(str(queued.job_id), **scope)['cancel_requested']
        knowledge.get_document = original_get
        # Discard local cancellation state and reconcile from the receipt.
        handler.ingestion = IngestionService(knowledge=knowledge, vectors=InMemoryVectorStore(), embeddings=DeterministicHashEmbedding())
        result = queue.recover_publication(str(queued.job_id), **scope, now=106)
        assert result.state is JobState.CANCELLED
        assert result.attempt_count == 1
    finally:
        knowledge.close()
