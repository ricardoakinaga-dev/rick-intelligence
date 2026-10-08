"""Receipt/journal authority and public time probes; fake queue is not PG evidence."""
from test_prod02_recovery_rework7 import install_historical_publication
from copy import deepcopy

import pytest

from canonical_queue import CanonicalIngestionQueueAdapter
from external_ingestion import ExternalIngestionHandler, ExternalIngestionError
from services.job_journal import SQLiteJobJournal
from services.postgres_ingestion import PostgresIngestionApplicationService
from rick_ingestion import IngestionService
from rick_ingestion.jobs import IngestionJob
from rick_jobs import JobState, JobResult, JobFailure
from rick_knowledge import InMemoryKnowledgeStore, SQLiteKnowledgeStore
from rick_knowledge.fencing import OwnershipLostError
from rick_retrieval import InMemoryVectorStore, DeterministicHashEmbedding
from test_postgres_jobs import make_job, make_queue

SCOPE = dict(tenant_id='t', workspace_id='w', collection_id='c')


@pytest.fixture(params=['memory', 'sqlite'])
def knowledge(request, tmp_path):
    store = InMemoryKnowledgeStore() if request.param == 'memory' else SQLiteKnowledgeStore(tmp_path/'knowledge.sqlite')
    yield store
    if hasattr(store, 'close'):
        store.close()


def service(store):
    return IngestionService(knowledge=store, vectors=InMemoryVectorStore(), embeddings=DeterministicHashEmbedding())


def owner():
    return IngestionJob(**SCOPE, job_id='authority', document_id='document', status='published',
        stage='published', attempt=1, created_at=10, started_at=20, finished_at=30,
        metadata={'publication_attempt': 'token', 'queue_attempt': 1})


def receipt(store, job):
    if job.finished_at is None:
        store.begin_publication(job)
        store.resolve_publication(store.get_publication(job.job_id, **SCOPE), 'committed')
    else:
        install_historical_publication(store, job, 'committed')
    return deepcopy(store.get_publication(job.job_id, **SCOPE))


def facts(job):
    return tuple(getattr(job, k) for k in ('attempt', 'created_at', 'started_at', 'finished_at'))


def test_R2_caller_and_cached_terminal_facts_cannot_replace_receipt(knowledge):
    original = owner()
    before = receipt(knowledge, original)
    caller = deepcopy(original)
    caller.attempt, caller.created_at, caller.started_at, caller.finished_at = 7, 111, 222, 333
    canonical = service(knowledge)
    result = canonical.recover_publication(original.job_id, **SCOPE, snapshot=caller)
    assert facts(result) == (1, 10, 20, 30)
    result.attempt, result.created_at, result.started_at, result.finished_at = 8, 444, 555, 666
    assert facts(canonical.recover_publication(original.job_id, **SCOPE)) == (1, 10, 20, 30)
    assert knowledge.get_publication(original.job_id, **SCOPE) == before


@pytest.mark.parametrize('field,value', [('attempt', 7), ('created_at', 111), ('started_at', 222), ('finished_at', 333)])
def test_R2_snapshot_writes_reject_divergent_terminal_facts(knowledge, field, value):
    job = owner()
    before = receipt(knowledge, job)
    setattr(job, field, value)
    with pytest.raises((ValueError, OwnershipLostError)):
        knowledge.save_publication_snapshot(job)
    assert knowledge.get_publication(job.job_id, **SCOPE) == before


@pytest.mark.parametrize('field,value', [('attempt', True), ('attempt', 1.5), ('attempt', 0),
    ('created_at', True), ('created_at', '10'), ('created_at', float('nan')),
    ('started_at', float('inf')), ('started_at', 9), ('finished_at', 19)])
def test_R2_snapshot_typed_counters_and_ordered_finite_times(knowledge, field, value):
    job = owner()
    setattr(job, field, value)
    with pytest.raises(ValueError):
        knowledge.begin_publication(job)
    assert knowledge.get_publication(job.job_id, **SCOPE) is None


def test_R2_document_attempt_and_queue_counter_relationship(knowledge):
    job = owner()
    job.metadata['published_document_attempt'] = 'other-document-owner'
    with pytest.raises((ValueError, OwnershipLostError)):
        knowledge.begin_publication(job, document_attempt='different-owner')
    job.metadata.pop('published_document_attempt')
    job.metadata['queue_attempt'] = 2
    with pytest.raises(ValueError):
        knowledge.begin_publication(job)


@pytest.mark.parametrize('status', ['published', 'failed', 'cancelled'])
def test_R3_late_same_attempt_verifying_cannot_reopen_terminal(status):
    journal = SQLiteJobJournal(':memory:')
    job = owner()
    job.status = job.stage = status
    try:
        journal.upsert(job)
        stale = deepcopy(job)
        stale.status = stale.stage = 'verifying'
        stale.finished_at = None
        stale.created_at = 111
        returned = journal.upsert(stale)
        assert (returned['status'], returned['created_at'], returned['started_at'], returned['finished_at']) == (status, 10, 20, 30)
        job.metadata['retirement_pending'] = False
        returned = journal.upsert(job, source_path=None)
        assert returned['finished_at'] == 30 and returned['metadata']['retirement_pending'] is False
    finally:
        journal.close()


def test_R3_retry_requires_next_attempt_new_token_and_retryable_terminal():
    journal = SQLiteJobJournal(':memory:')
    job = owner()
    job.status = job.stage = 'failed'
    try:
        journal.upsert(job)
        retry = deepcopy(job)
        retry.status = retry.stage = 'queued'
        retry.started_at = retry.finished_at = None
        for number, token in [(1, 'new'), (3, 'new'), (2, 'token')]:
            retry.attempt = number
            retry.metadata['publication_attempt'] = token
            with pytest.raises(ValueError):
                journal.upsert(retry)
            assert journal.get(job.job_id)['finished_at'] == 30
        retry.attempt = 2
        retry.metadata['publication_attempt'] = 'new'
        assert journal.upsert(retry)['attempt'] == 2
        with pytest.raises(ValueError):
            journal.upsert(job)
    finally:
        journal.close()


@pytest.mark.parametrize('status', ['published', 'failed', 'cancelled'])
def test_R3_terminal_metadata_update_retains_all_terminal_facts(status):
    journal = SQLiteJobJournal(':memory:')
    job = owner()
    job.status = job.stage = status
    try:
        first = journal.upsert(job)
        job.created_at, job.started_at, job.finished_at = 111, 222, None
        job.document_id, job.progress, job.error_code = 'other', 0.1, 'storage_unavailable'
        job.cancel_requested = not first['cancel_requested']
        job.metadata['retirement_pending'] = False
        after = journal.upsert(job, source_path=None)
        for key in ('document_id','status','stage','progress','attempt','error_code','created_at','started_at','finished_at','cancel_requested'):
            assert after[key] == first[key]
        assert after['metadata']['retirement_pending'] is False
    finally:
        journal.close()


@pytest.mark.parametrize('attempt', [True, '1', 1.5, 0, 65])
def test_R3_invalid_caller_counter_cannot_pass_a_terminal_fence(attempt):
    journal = SQLiteJobJournal(':memory:')
    job = owner()
    try:
        before = journal.upsert(job)
        job.attempt = attempt
        with pytest.raises(ValueError): journal.upsert(job)
        assert journal.get(job.job_id) == before
    finally:
        journal.close()


def test_R2_no_start_is_invented_and_first_finish_is_persisted_once(knowledge):
    job = owner()
    job.started_at = job.finished_at = None
    receipt(knowledge, job)
    first = service(knowledge).recover_publication(job.job_id, **SCOPE)
    assert first.started_at is None and first.finished_at is not None
    saved = knowledge.get_publication(job.job_id, **SCOPE)
    assert saved['job_snapshot']['started_at'] is None
    assert saved['job_snapshot']['finished_at'] == first.finished_at
    second = service(knowledge).recover_publication(job.job_id, **SCOPE)
    assert facts(second) == facts(first)
    assert knowledge.get_publication(job.job_id, **SCOPE) == saved


@pytest.mark.parametrize('outcome', ['pending', 'committed'])
@pytest.mark.parametrize('change', ['token', 'document', 'scope'])
def test_R2_recovery_stale_identity_and_scope_do_not_weaken_receipt_fences(knowledge, change, outcome):
    job = owner()
    if outcome == 'pending':
        job.status = job.stage = 'verifying'
        job.finished_at = None
        knowledge.begin_publication(job)
        before = deepcopy(knowledge.get_publication(job.job_id, **SCOPE))
    else:
        before = receipt(knowledge, job)
    stale = deepcopy(job)
    if change == 'token': stale.metadata['publication_attempt'] = 'stale'
    if change == 'document': stale.document_id = 'stale'
    if change == 'scope': stale.tenant_id = 'foreign'
    if change == 'token' and outcome == 'committed':
        result = service(knowledge).recover_publication(job.job_id, **SCOPE, snapshot=stale)
        assert result.status == 'published' and facts(result) == facts(job)
        assert result.metadata['publication_attempt'] == 'token'
    else:
        with pytest.raises(OwnershipLostError): service(knowledge).recover_publication(job.job_id, **SCOPE, snapshot=stale)
    assert knowledge.get_publication(job.job_id, **SCOPE) == before


@pytest.mark.parametrize('state', ['queued', 'running', 'published', 'failed', 'cancelled', 'cancelled-before-attempt'])
def test_R4_public_projection_preserves_current_attempt_facts(state):
    job = make_job(now=10)
    job = job.transition(JobState.QUEUED, now=11)
    if state == 'cancelled-before-attempt':
        job = job.transition(JobState.CANCELLED, now=20)
    elif state != 'queued':
        job = job.start_attempt(worker_id='worker', now=12)
        if state == 'published':
            job = job.finish_attempt(JobState.SUCCEEDED, now=20, result=JobResult(document_id='winner', completed_at=20))
        elif state == 'failed':
            job = job.finish_attempt(JobState.FAILED, now=20,
                failure=JobFailure(code='handler_timeout', message='timeout', retryable=True, attempt=1, occurred_at=20))
        elif state == 'cancelled':
            job = job.finish_attempt(JobState.CANCELLED, now=20)
    record = CanonicalIngestionQueueAdapter._record(job)
    app = object.__new__(PostgresIngestionApplicationService)
    public = app._public_job(record)
    assert public['created_at'] == 10
    assert public['started_at'] == (12 if job.attempts else None)
    assert public['finished_at'] == (20 if state in {'published', 'failed', 'cancelled', 'cancelled-before-attempt'} else None)
    assert public['attempt'] == job.attempt_count


def test_R1_actual_second_attempt_after_pre_receipt_failure_ack_loss(tmp_path, knowledge):
    """Canonical facade → actual handler → receipt → reconstructed queue/API."""
    import hashlib
    queue, connection = make_queue()
    from base64 import urlsafe_b64encode
    payload = {'object_key': 'uploads/guide', 'filename_ref': urlsafe_b64encode(b'guide.txt').decode(),
        'checksum': 'sha256:' + hashlib.sha256(b'Recovery attempt two. ' * 80).hexdigest()}
    queued = queue.enqueue(make_job(max_attempts=2, payload=payload), expected_version=0)
    running, first_lease = queue.claim(worker_id='first', scope=queued.scope, expected_versions={}, now=104)[0]
    scope = dict(tenant_id=queued.tenant_id, workspace_id=queued.workspace_id, collection_id=queued.collection_id)
    class Objects:
        fail = True
        def get(self, *a, **kw):
            if self.fail:
                raise RuntimeError('before receipt')
            return b'Recovery attempt two. ' * 80
        def put(self, *a, **kw):
            pytest.fail('source must not be rewritten')
    objects = Objects()
    canonical = service(knowledge)
    handler = ExternalIngestionHandler(canonical, objects, temp_root=tmp_path/'worker')
    with pytest.raises(ExternalIngestionError):
        handler(CanonicalIngestionQueueAdapter._record(running))
    assert knowledge.get_publication(str(queued.job_id), **scope) is None
    queue.fail(first_lease, JobFailure(code='handler_timeout', message='timeout', retryable=True,
        attempt=1, occurred_at=105), now=105, expected_version=running.version)
    connection.database_now = 106
    running, second_lease = queue.claim(worker_id='second', scope=queued.scope, expected_versions={}, now=106)[0]
    assert running.attempt_count == 2
    objects.fail = False
    real_status = knowledge.set_document_status
    real_get = knowledge.get_publication
    unavailable = False
    def lose_ack(doc, status):
        nonlocal unavailable
        real_status(doc, status)
        if status == 'published':
            unavailable = True
            raise RuntimeError('committed but acknowledgement lost')
    def read(*a, **kw):
        if unavailable:
            raise RuntimeError('authority unavailable')
        return real_get(*a, **kw)
    knowledge.set_document_status = lose_ack
    knowledge.get_publication = read
    with pytest.raises(ExternalIngestionError) as error:
        handler(CanonicalIngestionQueueAdapter._record(running))
    assert error.value.code == 'recovery_required'
    unavailable = False
    saved = real_get(str(queued.job_id), **scope)
    assert saved['outcome'] == 'committed'
    assert saved['job_snapshot']['attempt'] == saved['job_snapshot']['metadata']['queue_attempt'] == 2
    assert saved['job_snapshot']['created_at'] == running.created_at
    assert saved['job_snapshot']['started_at'] == running.attempts[-1].started_at
    class NoReplay(DeterministicHashEmbedding):
        def embed(self, texts):
            pytest.fail('committed recovery cannot replay embeddings')
    objects.fail = True
    handler.ingestion = IngestionService(knowledge=knowledge, vectors=canonical.vectors, embeddings=NoReplay())
    # Restore queue object without source replay; fake persistence is scoped control-flow evidence.
    from postgres_jobs import PostgresJobQueue, PostgresJobLeaseError
    restarted_queue = PostgresJobQueue(lambda: connection, publication_reconciler=handler.recover_job)
    app = PostgresIngestionApplicationService(queue=CanonicalIngestionQueueAdapter(restarted_queue), object_store=objects, knowledge=knowledge)
    public = app.get_status(str(queued.job_id), tenant_id=queued.tenant_id,
        workspace_id=queued.workspace_id, allowed_collection_ids=[queued.collection_id])
    terminal = restarted_queue.get(str(queued.job_id), **scope)
    assert terminal.state is JobState.SUCCEEDED and terminal.attempt_count == 2
    assert public['attempt'] == 2 and public['started_at'] == running.attempts[-1].started_at
    assert public['finished_at'] == terminal.attempts[-1].finished_at
    assert terminal.attempts[0] == running.attempts[0]
    with pytest.raises(PostgresJobLeaseError):
        restarted_queue.heartbeat(second_lease, now=107, expected_version=running.version)
