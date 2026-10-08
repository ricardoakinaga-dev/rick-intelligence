"""Opt-in probe owning a synthetic disposable PostgreSQL container.

Lead coordinates the run with RICK_PROD02_DISPOSABLE_POSTGRES=1. No caller DSN,
existing container, migration checksum repair, or network image pull is used.
"""
from importlib.util import module_from_spec, spec_from_file_location
import json
import os
from pathlib import Path
import subprocess
import time
from uuid import uuid4

import pytest


def docker(*args):
    return subprocess.run(['docker', *args], capture_output=True, text=True, timeout=30)


@pytest.fixture
def owned_postgres(request):
    if os.environ.get('RICK_PROD02_DISPOSABLE_POSTGRES') != '1':
        pytest.skip('Lead must coordinate the owned disposable PostgreSQL probe')
    available = docker('info', '--format', '{{.ServerVersion}}')
    if available.returncode:
        pytest.skip('Docker socket unavailable; no existing database is used')
    image = 'postgres:16-alpine'
    if docker('image', 'inspect', image).returncode:
        pytest.skip('Disposable PostgreSQL image must be preloaded; pulling is disabled')
    owner = 'prod02-recovery-' + uuid4().hex
    password = uuid4().hex
    created = docker('run', '--detach', '--pull=never', '--name', owner,
        '--label', 'rick.test.owner=' + owner, '--label', 'rick.test.purpose=prod02-recovery',
        '--memory', '256m', '--cpus', '1', '-p', '127.0.0.1::5432',
        '-e', 'POSTGRES_PASSWORD=' + password, '-e', 'POSTGRES_DB=prod02', image)
    assert created.returncode == 0, 'could not create owned disposable PostgreSQL'
    container_id = created.stdout.strip()
    try:
        inspected = docker('inspect', container_id)
        assert inspected.returncode == 0
        info = json.loads(inspected.stdout)[0]
        assert info['Config']['Labels']['rick.test.owner'] == owner
        port = info['NetworkSettings']['Ports']['5432/tcp'][0]['HostPort']
        import psycopg
        from psycopg.rows import dict_row
        dsn = f'postgresql://postgres:{password}@127.0.0.1:{port}/prod02'
        def connect():
            return psycopg.connect(dsn, connect_timeout=2, row_factory=dict_row)
        connect.migration_dsn = dsn  # Owned test credential, in-memory handoff only.
        deadline = time.monotonic() + 30
        while True:
            try:
                with connect():
                    break
            except psycopg.OperationalError:
                if time.monotonic() >= deadline:
                    pytest.fail('owned disposable PostgreSQL did not become ready')
                time.sleep(.1)
        root = Path(__file__).resolve().parents[3]
        spec = spec_from_file_location('prod02_migrate', root / 'infrastructure/scripts/migrate.py')
        migration = module_from_spec(spec)
        spec.loader.exec_module(migration)
        prefix = getattr(request, 'param', None)
        if prefix is None:
            assert migration.apply(root / 'infrastructure/migrations', dsn) == 0
        else:
            # A real installed prefix, copied without altering any root SQL.
            import tempfile
            with tempfile.TemporaryDirectory(prefix='rick-pg-reviewed-prefix-') as directory:
                selected = Path(directory)
                for version, path, digest in migration.migration_files(root / 'infrastructure/migrations'):
                    if int(version) <= prefix:
                        (selected / path.name).write_bytes(path.read_bytes())
                repair = root / 'infrastructure/migrations' / migration.OPERATION_REPAIR_NAME
                (selected / repair.name).write_bytes(repair.read_bytes())
                assert migration.apply(selected, dsn) == 0
        yield connect
    finally:
        inspected = docker('inspect', container_id)
        if inspected.returncode == 0:
            info = json.loads(inspected.stdout)[0]
            assert info['Config']['Labels']['rick.test.owner'] == owner
            assert docker('rm', '--force', '--volumes', container_id).returncode == 0


def test_postgres_commit_restart_final_attempt_and_public_owner(owned_postgres, tmp_path):
    from rick_ingestion import IngestionService
    from rick_jobs import Job, JobState
    from rick_knowledge import Collection, PostgresKnowledgeStore
    from rick_retrieval import DeterministicHashEmbedding, InMemoryVectorStore
    from postgres_jobs import PostgresJobQueue, PostgresJobLeaseError
    from external_ingestion import ExternalIngestionHandler
    from canonical_queue import CanonicalIngestionQueueAdapter
    from services.postgres_ingestion import PostgresIngestionApplicationService

    connect = owned_postgres
    with connect() as conn:
        conn.execute("INSERT INTO rick_tenants (tenant_id, display_name) VALUES ('t','Synthetic')")
        conn.execute("INSERT INTO rick_users (user_id) VALUES ('u')")
        conn.execute("INSERT INTO rick_memberships (tenant_id,user_id,workspace_id,role) VALUES ('t','u','w','KNOWLEDGE_MANAGER')")
    scope = dict(tenant_id='t', workspace_id='w', collection_id='c')
    vectors = InMemoryVectorStore()
    source = tmp_path / 'guide.txt'
    source.write_text('Owned disposable publication recovery. ' * 80)
    knowledge = PostgresKnowledgeStore(connect, created_by='u')
    knowledge.ensure_collection(Collection(**scope, metadata={'created_by': 'u'}))
    queue = PostgresJobQueue(connect, max_attempts=1, lease_seconds=1)
    job = Job.create(job_id='job-restart', **scope, operation='ingest', idempotency_key='idem-restart',
                     payload={'object_key': 'uploads/guide'}, now=time.time(), max_attempts=1)
    queued = queue.enqueue(job, expected_version=0)
    running, stale_lease = queue.claim(worker_id='before', scope=job.scope, expected_versions={}, now=time.time())[0]
    canonical = IngestionService(knowledge=knowledge, vectors=vectors, embeddings=DeterministicHashEmbedding())
    from external_ingestion import _recovery_metadata
    published = canonical.ingest(source, **scope, job_id=str(job.job_id),
        _recovery_metadata=_recovery_metadata(running))
    assert published.status == 'published'
    assert knowledge.get_publication(str(job.job_id), **scope)['outcome'] == 'committed'
    before = vectors.all_points()
    class NoReplay(DeterministicHashEmbedding):
        def embed(self, texts):
            pytest.fail('publication recovery replayed embeddings')
    class Objects:
        def get(self, *args, **kwargs):
            pytest.fail('publication recovery hydrated source')
        def put(self, *args, **kwargs):
            pytest.fail('publication recovery overwrote source')
    restarted_knowledge = PostgresKnowledgeStore(connect, created_by='u')
    restarted = IngestionService(knowledge=restarted_knowledge, vectors=vectors, embeddings=NoReplay())
    handler = ExternalIngestionHandler(restarted, Objects(), temp_root=tmp_path / 'worker')
    restarted_queue = PostgresJobQueue(connect, publication_reconciler=handler.recover_job)
    time.sleep(1.1)
    assert restarted_queue.claim(worker_id='after', scope=job.scope, expected_versions={}, now=time.time()) == ()
    recovered = restarted_queue.get(str(job.job_id), **scope)
    assert recovered.state is JobState.SUCCEEDED
    assert recovered.attempt_count == recovered.max_attempts == 1
    assert recovered.result.document_id == published.document_id
    with pytest.raises(PostgresJobLeaseError):
        restarted_queue.heartbeat(stale_lease, now=time.time(), expected_version=running.version)
    public = PostgresIngestionApplicationService(queue=CanonicalIngestionQueueAdapter(restarted_queue),
        object_store=Objects(), knowledge=restarted_knowledge).get_status(str(job.job_id),
        tenant_id='t', workspace_id='w', allowed_collection_ids=['c'])
    assert public['status'] == 'published'
    assert public['document_id'] == published.document_id
    assert public['attempt'] == recovered.attempt_count
    assert public['started_at'] == recovered.attempts[-1].started_at == running.attempts[-1].started_at
    assert public['finished_at'] == recovered.attempts[-1].finished_at
    assert vectors.all_points() == before


def test_postgres_rework_ready_cleanup_cancel_fairness_and_identity_constraints(owned_postgres,tmp_path):
    """Real SQL evidence for F1–F7; uses only this fixture's owned disposable DB."""
    from copy import deepcopy
    from rick_ingestion import IngestionService
    from rick_ingestion.jobs import IngestionJob
    from rick_knowledge import Collection,PostgresKnowledgeStore
    from rick_knowledge.fencing import OwnershipLostError
    from rick_jobs import Job,JobResult,JobState,JobScope
    from rick_retrieval import DeterministicHashEmbedding,InMemoryVectorStore
    from postgres_jobs import PostgresJobQueue,PostgresJobLeaseError
    from external_ingestion import ExternalIngestionHandler,ExternalIngestionError
    from canonical_queue import CanonicalIngestionQueueAdapter
    from services.postgres_ingestion import PostgresIngestionApplicationService
    import psycopg
    connect=owned_postgres
    with connect() as conn:
        conn.execute("INSERT INTO rick_tenants (tenant_id,display_name) VALUES ('t','Synthetic')")
        conn.execute("INSERT INTO rick_users (user_id) VALUES ('u')")
        conn.execute("INSERT INTO rick_memberships (tenant_id,user_id,workspace_id,role) VALUES ('t','u','w','KNOWLEDGE_MANAGER')")
    scope=dict(tenant_id='t',workspace_id='w',collection_id='c')
    store=PostgresKnowledgeStore(connect,created_by='u');store.ensure_collection(Collection(**scope,metadata={'created_by':'u'}))
    vectors=InMemoryVectorStore();source=tmp_path/'ready.txt';source.write_text('Postgres durable ready intent. '*80)
    owner=IngestionService(knowledge=store,vectors=vectors,embeddings=DeterministicHashEmbedding())
    real=store.set_document_status
    def die(doc,status,**kw):
        if status=='published': raise SystemExit('before status commit')
        return real(doc,status,**kw)
    store.set_document_status=die
    with pytest.raises(SystemExit): owner.ingest(source,**scope,job_id='ready')
    job=owner.get_status('ready')
    authority=store.get_publication(job.job_id,**scope)['job_snapshot']
    job.attempt=7;job.created_at=10;job.started_at=11
    job.metadata.update(durability='postgres-s3',restart_recovery=True)
    with pytest.raises(OwnershipLostError): store.save_publication_snapshot(job)
    for key in ('attempt','created_at','started_at'): setattr(job,key,authority[key])
    store.save_publication_snapshot(job)
    before=deepcopy(vectors.all_points());source.unlink()
    class NoReplay(DeterministicHashEmbedding):
        def embed(self,texts): pytest.fail('completed embeddings replayed')
    store=PostgresKnowledgeStore(connect,created_by='u')
    recovered=IngestionService(knowledge=store,vectors=vectors,embeddings=NoReplay()).recover_publication('ready',**scope)
    assert recovered.status=='published' and vectors.all_points()==before
    assert (recovered.attempt,recovered.created_at,recovered.started_at)==tuple(authority[k] for k in ('attempt','created_at','started_at'))
    assert recovered.metadata['restart_recovery'] and recovered.metadata['durability']=='postgres-s3'
    source.write_text('Postgres replacement retirement. '*80)
    delete=vectors.delete_document
    def fail_old(doc,col):
        if doc==recovered.document_id: raise RuntimeError('retirement failed')
        return delete(doc,col)
    vectors.delete_document=fail_old
    owner=IngestionService(knowledge=store,vectors=vectors,embeddings=DeterministicHashEmbedding())
    replacement=owner.reindex(recovered.document_id,source,**scope,job_id='replace')
    assert replacement.status==store.get_document(replacement.document_id,tenant_id='t',workspace_id='w').status=='published'
    assert store.get_publication('replace',**scope)['job_snapshot']['metadata']['retirement_pending']
    vectors.delete_document=delete
    assert IngestionService(knowledge=PostgresKnowledgeStore(connect,created_by='u'),vectors=vectors,embeddings=NoReplay()).recover_publication('replace',**scope).status=='published'
    assert store.get_document(recovered.document_id,tenant_id='t',workspace_id='w').status=='unpublished'
    assert not store.get_publication('replace',**scope)['job_snapshot']['metadata']['retirement_pending']

    for outcome in ['failed','cancelled','committed']:
        terminal=IngestionJob(**scope,job_id='terminal-'+outcome,document_id='doc-'+outcome,metadata={'publication_attempt':'a'})
        store.begin_publication(terminal);store.resolve_publication(store.get_publication(terminal.job_id,**scope),outcome)
        store.begin_publication(terminal);assert store.get_publication(terminal.job_id,**scope)['outcome']==outcome
        terminal.metadata['publication_attempt']='b';terminal.attempt+=1
        if outcome=='failed': store.begin_publication(terminal)
        else:
            with pytest.raises(OwnershipLostError): store.begin_publication(terminal)
    identity_keys=['tenant_id','workspace_id','collection_id','job_id','document_id','attempt_id','document_attempt']
    for key in identity_keys:
        for blank in ['', '\t\n', '\u00a0\u2003']:
            values=dict(tenant_id='t',workspace_id='w',collection_id='c',job_id='invalid',document_id='d',attempt_id='a',document_attempt='a',outcome='pending')
            values[key]=blank
            with pytest.raises(psycopg.errors.CheckViolation):
                with connect() as conn:
                    conn.execute('INSERT INTO rick_publication_receipts ('+','.join(values)+') VALUES ('+','.join('%s' for _ in values)+')',tuple(values.values()))

    queue=PostgresJobQueue(connect,max_attempts=1,lease_seconds=3600)
    def enqueue_claim(name):
        item=Job.create(**scope,job_id=name,operation='ingest',idempotency_key='idem-'+name,payload={'object_key':'uploads/guide'},now=time.time(),max_attempts=1)
        queued=queue.enqueue(item,expected_version=0)
        return queue.claim(worker_id='old',scope=item.scope,expected_versions={},now=time.time())[0]
    running,lease=enqueue_claim('public-cancel')
    from external_ingestion import _recovery_metadata
    intent=IngestionJob(**scope,job_id='public-cancel',document_id='unknown-doc',
                        metadata=_recovery_metadata(running),attempt=running.attempt_count,
                        created_at=running.created_at,started_at=running.attempts[-1].started_at)
    store.begin_publication(intent)
    class Objects:
        def get(self,*a,**kw): pytest.fail('source replay')
        def put(self,*a,**kw): pytest.fail('source replay')
    handler=ExternalIngestionHandler(IngestionService(knowledge=store,vectors=vectors,embeddings=NoReplay()),Objects(),temp_root=tmp_path/'worker')
    queue.publication_reconciler=handler.recover_job
    app=PostgresIngestionApplicationService(queue=CanonicalIngestionQueueAdapter(queue),object_store=Objects(),knowledge=store)
    get=store.get_document
    def unknown(*a,**kw): raise RuntimeError('unavailable authority')
    store.get_document=unknown
    public=app.cancel('public-cancel',tenant_id='t',workspace_id='w',allowed_collection_ids=['c'])
    assert public['status']=='verifying' and public['cancel_requested'] and not public['cancelled']
    assert store.get_publication('public-cancel',**scope)['cancel_requested']
    store.get_document=get;handler.ingestion=IngestionService(knowledge=store,vectors=vectors,embeddings=NoReplay())
    public=app.get_status('public-cancel',tenant_id='t',workspace_id='w',allowed_collection_ids=['c'])
    terminal=queue.get('public-cancel',**scope)
    assert public['status']=='cancelled'
    assert public['started_at']==terminal.attempts[-1].started_at==running.attempts[-1].started_at
    assert public['finished_at']==terminal.attempts[-1].finished_at
    assert queue.get('public-cancel',**scope).attempt_count==1

    queue.publication_reconciler=None
    leases={}
    for i in range(121): leases[f'fair-{i:03}']=enqueue_claim(f'fair-{i:03}')
    with connect() as conn:
        conn.execute("UPDATE rick_ingestion_jobs SET lease_acquired_at=clock_timestamp()-INTERVAL '2 seconds', lease_until=clock_timestamp()-INTERVAL '1 second' WHERE job_id LIKE 'fair-%'")
        expired={r['job_id']:r['lease_until'] for r in conn.execute("SELECT job_id,lease_until FROM rick_ingestion_jobs WHERE job_id LIKE 'fair-%'")}
    calls=[]
    def reconcile(item):
        calls.append(str(item.job_id))
        if str(item.job_id)=='fair-120': return JobResult(document_id=replacement.document_id,completed_at=item.attempts[-1].started_at,output_refs={})
        raise ExternalIngestionError('recovery_required')
    for _ in range(3):
        queue=PostgresJobQueue(connect,publication_reconciler=reconcile)
        before=len(calls)
        assert queue.claim(worker_id='restart',scope=JobScope(**scope),expected_versions={},now=time.time())==()
        assert len(calls)-before<=100
    assert queue.get('fair-120',**scope).state is JobState.SUCCEEDED
    with connect() as conn:
        rows=list(conn.execute("SELECT job_id,lease_until,attempts FROM rick_ingestion_jobs WHERE job_id LIKE 'fair-%' AND contract_state='RUNNING'"))
    assert len(rows)==120 and all(r['attempts']==1 and r['lease_until']==expired[r['job_id']] for r in rows)
    original,stale=leases['fair-000']
    with pytest.raises(PostgresJobLeaseError): queue.heartbeat(stale,now=original.updated_at,expected_version=original.version)


def test_postgres_actual_attempt_two_ack_loss_snapshot_authority_and_public_times(owned_postgres, tmp_path):
    """Opt-in SQL boundary; leaf collection skips this without touching Docker."""
    from base64 import urlsafe_b64encode
    from copy import deepcopy
    import hashlib
    from rick_ingestion import IngestionService
    from rick_ingestion.jobs import IngestionJob
    from rick_jobs import Job, JobState, JobFailure
    from rick_knowledge import Collection, PostgresKnowledgeStore
    from rick_knowledge.fencing import OwnershipLostError
    from rick_retrieval import DeterministicHashEmbedding, InMemoryVectorStore
    from postgres_jobs import PostgresJobQueue, PostgresJobLeaseError
    from external_ingestion import ExternalIngestionHandler, ExternalIngestionError
    from canonical_queue import CanonicalIngestionQueueAdapter
    from services.postgres_ingestion import PostgresIngestionApplicationService

    connect = owned_postgres
    with connect() as conn:
        conn.execute("INSERT INTO rick_tenants (tenant_id, display_name) VALUES ('t','Synthetic')")
        conn.execute("INSERT INTO rick_users (user_id) VALUES ('u')")
        conn.execute("INSERT INTO rick_memberships (tenant_id,user_id,workspace_id,role) VALUES ('t','u','w','KNOWLEDGE_MANAGER')")
    scope = dict(tenant_id='t', workspace_id='w', collection_id='c')
    store = PostgresKnowledgeStore(connect, created_by='u')
    store.ensure_collection(Collection(**scope, metadata={'created_by': 'u'}))
    vectors = InMemoryVectorStore()
    data = b'PostgreSQL attempt two publication. ' * 80
    class Objects:
        available = False
        def get(self, *a, **kw):
            if not self.available:
                raise RuntimeError('before durable receipt')
            return data
        def put(self, *a, **kw):
            pytest.fail('recovery must not rewrite source')
    objects = Objects()
    queue = PostgresJobQueue(connect, max_attempts=2, lease_seconds=3600, backoff_seconds=0)
    item = Job.create(**scope, job_id='second-attempt', operation='ingest', idempotency_key='idem-second',
        payload={'object_key':'uploads/guide', 'filename_ref':urlsafe_b64encode(b'guide.txt').decode(),
                 'checksum':'sha256:' + hashlib.sha256(data).hexdigest()}, now=time.time(), max_attempts=2)
    queue.enqueue(item, expected_version=0)
    first, first_lease = queue.claim(worker_id='first', scope=item.scope, expected_versions={}, now=time.time())[0]
    canonical = IngestionService(knowledge=store, vectors=vectors, embeddings=DeterministicHashEmbedding())
    handler = ExternalIngestionHandler(canonical, objects, temp_root=tmp_path/'worker')
    with pytest.raises(ExternalIngestionError): handler(CanonicalIngestionQueueAdapter._record(first))
    assert store.get_publication(str(item.job_id), **scope) is None
    failed_at = time.time()
    queue.fail(first_lease, JobFailure(code='handler_timeout', message='timeout', retryable=True,
        attempt=1, occurred_at=failed_at), now=failed_at, expected_version=first.version)
    second, second_lease = queue.claim(worker_id='second', scope=item.scope, expected_versions={}, now=time.time())[0]
    assert second.attempt_count == 2
    objects.available = True
    real_status, real_get = store.set_document_status, store.get_publication
    unavailable = False
    def commit_lose_ack(doc, status, **kw):
        nonlocal unavailable
        real_status(doc, status, **kw)
        if status == 'published':
            unavailable = True
            raise RuntimeError('lost commit acknowledgement')
    def read(*a, **kw):
        if unavailable:
            raise RuntimeError('authority temporarily unavailable')
        return real_get(*a, **kw)
    store.set_document_status, store.get_publication = commit_lose_ack, read
    with pytest.raises(ExternalIngestionError) as error: handler(CanonicalIngestionQueueAdapter._record(second))
    assert error.value.code == 'recovery_required'
    unavailable = False
    saved = real_get(str(item.job_id), **scope)
    assert saved['outcome'] == 'committed'
    assert saved['job_snapshot']['attempt'] == saved['job_snapshot']['metadata']['queue_attempt'] == 2
    assert saved['job_snapshot']['created_at'] == second.created_at
    assert saved['job_snapshot']['started_at'] == second.attempts[-1].started_at
    objects.available = False
    class NoReplay(DeterministicHashEmbedding):
        def embed(self, texts): pytest.fail('committed recovery must not replay embeddings')
    fresh_store = PostgresKnowledgeStore(connect, created_by='u')
    handler.ingestion = IngestionService(knowledge=fresh_store, vectors=vectors, embeddings=NoReplay())
    restarted_queue = PostgresJobQueue(connect, publication_reconciler=handler.recover_job)
    app = PostgresIngestionApplicationService(queue=CanonicalIngestionQueueAdapter(restarted_queue), object_store=objects, knowledge=fresh_store)
    public = app.get_status(str(item.job_id), tenant_id='t', workspace_id='w', allowed_collection_ids=['c'])
    terminal = restarted_queue.get(str(item.job_id), **scope)
    assert terminal.state is JobState.SUCCEEDED and public['attempt'] == terminal.attempt_count == 2
    assert terminal.attempts[0] == second.attempts[0]
    assert public['started_at'] == terminal.attempts[-1].started_at == second.attempts[-1].started_at
    assert public['finished_at'] == terminal.attempts[-1].finished_at
    with pytest.raises(PostgresJobLeaseError):
        restarted_queue.heartbeat(second_lease, now=time.time(), expected_version=second.version)
    before = fresh_store.get_publication(str(item.job_id), **scope)
    authoritative = before['job_snapshot']
    divergent = IngestionJob(**scope, job_id=str(item.job_id), document_id=before['document_id'], status='published', stage='published', **deepcopy(authoritative))
    divergent.attempt = 7
    divergent.created_at, divergent.started_at, divergent.finished_at = 10, 20, 30
    with pytest.raises((ValueError, OwnershipLostError)): fresh_store.save_publication_snapshot(divergent)
    result = IngestionService(knowledge=fresh_store, vectors=vectors, embeddings=NoReplay()).recover_publication(str(item.job_id), **scope, snapshot=divergent)
    assert tuple(getattr(result,k) for k in ('attempt','created_at','started_at','finished_at')) == tuple(authoritative[k] for k in ('attempt','created_at','started_at','finished_at'))
    assert fresh_store.get_publication(str(item.job_id), **scope) == before
    invalid = IngestionJob(**scope, job_id='invalid-counter', document_id='doc', attempt=True, metadata={'publication_attempt':'invalid'})
    with pytest.raises(ValueError): fresh_store.begin_publication(invalid)
    invalid.attempt, invalid.created_at = 1, float('nan')
    with pytest.raises(ValueError): fresh_store.begin_publication(invalid)
    assert fresh_store.get_publication(invalid.job_id, **scope) is None


def test_postgres_pre_intent_outputs_reconstruct_without_provider_replay(owned_postgres,tmp_path,monkeypatch):
    """Parent opt-in: actual PG checkpoints, retained hermetic vector store."""
    from rick_knowledge import PostgresKnowledgeStore
    from rick_retrieval import InMemoryVectorStore, DeterministicHashEmbedding
    from rick_ingestion import IngestionService
    import rick_ingestion.pipeline as pipeline
    connect=owned_postgres
    with connect() as conn:
        conn.execute("INSERT INTO rick_tenants (tenant_id,display_name) VALUES ('t','Synthetic')")
        conn.execute("INSERT INTO rick_users (user_id) VALUES ('u')")
        conn.execute("INSERT INTO rick_memberships (tenant_id,user_id,workspace_id,role) VALUES ('t','u','w','KNOWLEDGE_MANAGER')")
    scope=dict(tenant_id='t',workspace_id='w',collection_id='c')
    knowledge=PostgresKnowledgeStore(connect,created_by='u');vectors=InMemoryVectorStore()
    class Counting(DeterministicHashEmbedding):
        calls=0
        def embed(self,texts):
            self.calls+=1;return super().embed(texts)
    embedding=Counting();source=tmp_path/'source.txt';source.write_text('PG pre-intent phase recovery. '*80)
    original=vectors.count_for_document
    def crash(*a,**kw): raise SystemExit('pre-intent crash')
    vectors.count_for_document=crash
    canonical=IngestionService(knowledge=knowledge,vectors=vectors,embeddings=embedding)
    with pytest.raises(SystemExit): canonical.ingest(source,**scope,job_id='pre-intent',
        _recovery_metadata={'queue_attempt':2,'queue_created_at':1.,'queue_started_at':4.})
    assert knowledge.get_publication('pre-intent',**scope) is None
    saved=knowledge.get_ingestion_checkpoint('pre-intent',**scope)
    assert len(saved['artifacts']['vectors'])>0 and saved['job_snapshot']['attempt']==2
    vectors.count_for_document=original
    monkeypatch.setattr(pipeline,'execute_parser',lambda *a,**kw:pytest.fail('PG durable parse replay'))
    class NoReplay(DeterministicHashEmbedding):
        def embed(self,texts): pytest.fail('PG durable embedding replay')
    restarted=IngestionService(knowledge=PostgresKnowledgeStore(connect,created_by='u'),vectors=vectors,embeddings=NoReplay())
    result=restarted.ingest(source,**scope,job_id='pre-intent')
    assert result.status=='published' and result.attempt==2 and result.started_at==4.
    assert embedding.calls==1
    assert knowledge.get_publication('pre-intent',**scope)['job_snapshot']['finished_at']==result.finished_at
    assert knowledge.get_ingestion_checkpoint('pre-intent',**scope)['artifacts']=={}


def test_postgres_attempt2_cancel_persists_before_intent_and_preserves_attempt1(owned_postgres,tmp_path):
    """Parent opt-in: actual queue row locks plus actual PG checkpoint writes."""
    from rick_jobs import Job, JobFailure, JobState
    from rick_knowledge import Collection, PostgresKnowledgeStore
    from rick_ingestion import IngestionService
    from rick_ingestion.jobs import IngestionJob
    from rick_retrieval import InMemoryVectorStore, DeterministicHashEmbedding
    from postgres_jobs import PostgresJobQueue
    from external_ingestion import ExternalIngestionHandler, _recovery_metadata
    from copy import deepcopy
    connect=owned_postgres
    with connect() as conn:
        conn.execute("INSERT INTO rick_tenants (tenant_id,display_name) VALUES ('t','Synthetic')")
        conn.execute("INSERT INTO rick_users (user_id) VALUES ('u')")
        conn.execute("INSERT INTO rick_memberships (tenant_id,user_id,workspace_id,role) VALUES ('t','u','w','KNOWLEDGE_MANAGER')")
    scope=dict(tenant_id='t',workspace_id='w',collection_id='c')
    knowledge=PostgresKnowledgeStore(connect,created_by='u')
    knowledge.ensure_collection(Collection(**scope,metadata={'created_by':'u'}))
    queue=PostgresJobQueue(connect,max_attempts=2,backoff_seconds=0)
    queued=queue.enqueue(Job.create(job_id='cancel-two',**scope,operation='ingest',idempotency_key='cancel-two',
        payload={'object_key':'uploads/cancel-two'},now=time.time(),max_attempts=2),expected_version=0)
    running,lease=queue.claim(worker_id='first',scope=queued.scope,expected_versions={},now=time.time())[0]
    now=time.time()
    queue.fail(lease,JobFailure(code='handler_timeout',message='timeout',retryable=True,attempt=1,occurred_at=now),now=now,expected_version=running.version)
    running,lease=queue.claim(worker_id='second',scope=queued.scope,expected_versions={},now=time.time())[0]
    assert running.attempt_count==2
    old=IngestionJob(job_id=str(running.job_id),**scope,document_id='old',attempt=1,
        created_at=running.created_at,started_at=running.attempts[0].started_at,
        metadata={'publication_attempt':'old','queue_attempt':1})
    knowledge.begin_publication(old);before=deepcopy(knowledge.get_publication(old.job_id,**scope))
    class Objects:
        def get(self,*a,**kw): pytest.fail('cancellation cannot hydrate')
    handler=ExternalIngestionHandler(IngestionService(knowledge=knowledge,vectors=InMemoryVectorStore(),embeddings=DeterministicHashEmbedding()),Objects(),temp_root=tmp_path/'worker')
    queue.publication_reconciler=handler.recover_job
    cancelled=queue.cancel(running.job_id,**scope,now=time.time(),expected_version=running.version)
    assert cancelled.state is JobState.RUNNING
    assert knowledge.get_publication(old.job_id,**scope)==before
    checkpoint=PostgresKnowledgeStore(connect,created_by='u').get_ingestion_checkpoint(old.job_id,**scope)
    assert checkpoint['attempt_id']==_recovery_metadata(running)['publication_attempt']
    assert checkpoint['job_snapshot']['attempt']==2 and checkpoint['cancel_requested']
    knowledge.resolve_publication(before,'failed')
    source=tmp_path/'source.txt';source.write_text('Cancelled current second attempt. '*80)
    result=handler.ingestion.ingest(source,**scope,job_id=old.job_id,_recovery_metadata=_recovery_metadata(running))
    assert result.status=='cancelled' and result.attempt==2
    assert not knowledge.get_publication(old.job_id,**scope)['cancel_requested']


@pytest.mark.parametrize("max_attempts", [1, 2])
def test_postgres_checkpoint_expiry_transfers_lease_without_replaying_completed_outputs(
    owned_postgres, tmp_path, monkeypatch, max_attempts,
):
    """Actual PG scheduling/storage; vectors and object bytes are memory collaborators."""
    from copy import deepcopy
    from hashlib import sha256
    from rick_ingestion import IngestionService
    from rick_jobs import Job, JobState
    from rick_knowledge import Collection, PostgresKnowledgeStore
    from rick_retrieval import DeterministicHashEmbedding, InMemoryVectorStore
    from external_ingestion import ExternalIngestionHandler, _recovery_metadata
    from canonical_queue import CanonicalIngestionQueueAdapter
    from postgres_jobs import PostgresJobQueue, PostgresJobLeaseError
    import rick_ingestion.pipeline as pipeline

    connect = owned_postgres
    with connect() as conn:
        conn.execute("INSERT INTO rick_tenants (tenant_id,display_name) VALUES ('t','Synthetic')")
        conn.execute("INSERT INTO rick_users (user_id) VALUES ('u')")
        conn.execute("INSERT INTO rick_memberships (tenant_id,user_id,workspace_id,role) VALUES ('t','u','w','KNOWLEDGE_MANAGER')")
    scope = dict(tenant_id='t', workspace_id='w', collection_id='c')
    knowledge = PostgresKnowledgeStore(connect, created_by='u')
    knowledge.ensure_collection(Collection(**scope, metadata={'created_by':'u'}))
    data = b'Actual PostgreSQL pre-intent expiry recovery. ' * 80
    class Objects:
        def get(self, *args, **kwargs): return data
    class Counting(DeterministicHashEmbedding):
        calls = 0
        def embed(self, texts):
            self.calls += 1
            return super().embed(texts)
    embeddings = Counting()
    vectors = InMemoryVectorStore()
    job = Job.create(job_id='expiry-checkpoint', **scope, operation='ingest',
        idempotency_key='expiry-checkpoint', payload={'object_key':'uploads/expiry',
        'filename_ref':'ZXhwaXJ5LnR4dA==', 'checksum':'sha256:'+sha256(data).hexdigest()},
        now=time.time(), max_attempts=max_attempts)
    queue = PostgresJobQueue(connect, max_attempts=max_attempts, lease_seconds=1)
    queue.enqueue(job, expected_version=0)
    original, old_lease = queue.claim(worker_id='before', scope=job.scope,
        expected_versions={}, now=time.time())[0]
    ingestion = IngestionService(knowledge=knowledge, vectors=vectors, embeddings=embeddings)
    handler = ExternalIngestionHandler(ingestion, Objects(), created_by='u', temp_root=tmp_path/'before')
    def die(*args, **kwargs): raise SystemExit('before publication intent')
    monkeypatch.setattr(knowledge, 'begin_publication', die)
    with pytest.raises(SystemExit): handler(CanonicalIngestionQueueAdapter._record(original))
    checkpoint = knowledge.get_ingestion_checkpoint(str(job.job_id), **scope)
    assert knowledge.get_publication(str(job.job_id), **scope) is None
    assert checkpoint['document_id'] and checkpoint['state'] == 'active'
    assert checkpoint['artifacts']['vectors'] and embeddings.calls == 1
    before = deepcopy(checkpoint['artifacts'])
    class NoReplay(DeterministicHashEmbedding):
        def embed(self, texts): pytest.fail('lease continuation replayed completed embeddings')
    restarted_knowledge = PostgresKnowledgeStore(connect, created_by='u')
    restarted = IngestionService(knowledge=restarted_knowledge, vectors=vectors, embeddings=NoReplay())
    resumed_handler = ExternalIngestionHandler(restarted, Objects(), created_by='u', temp_root=tmp_path/'after')
    resumed_queue = PostgresJobQueue(connect, lease_seconds=30,
        publication_reconciler=resumed_handler.recover_job)
    time.sleep(1.1)
    resumed, new_lease = resumed_queue.claim(worker_id='after', scope=job.scope,
        expected_versions={}, now=time.time())[0]
    assert resumed.state is JobState.RUNNING
    assert resumed.attempt_count == original.attempt_count == 1
    assert resumed.max_attempts == max_attempts
    assert resumed.created_at == original.created_at
    assert resumed.attempts[-1].started_at == original.attempts[-1].started_at
    assert resumed.version == original.version + 1
    assert new_lease.token != old_lease.token and str(new_lease.worker_id) == 'after'
    assert _recovery_metadata(resumed)['publication_attempt'] == checkpoint['attempt_id']
    assert restarted_knowledge.get_ingestion_checkpoint(str(job.job_id), **scope)['artifacts'] == before
    with pytest.raises(PostgresJobLeaseError):
        resumed_queue.heartbeat(old_lease, expected_version=original.version, now=time.time())
    with pytest.raises(PostgresJobLeaseError):
        resumed_queue.heartbeat(old_lease, expected_version=resumed.version, now=time.time())
    monkeypatch.setattr(pipeline, 'execute_parser', lambda *a, **kw: pytest.fail('lease continuation replayed completed parsing'))
    published = resumed_handler(CanonicalIngestionQueueAdapter._record(resumed))
    assert published.status == 'published' and published.attempt == 1
    recovered = resumed_queue.recover_publication(str(job.job_id), **scope, now=time.time()+100)
    assert recovered.state is JobState.SUCCEEDED and recovered.attempt_count == 1
    from math import floor
    # The queue normalizes both attempt and result to PostgreSQL microseconds.
    # The publication receipt retains the original finish; polling is separate.
    expected_finish = floor(published.finished_at * 1_000_000) / 1_000_000
    assert recovered.attempts[-1].finished_at == recovered.result.completed_at == expected_finish
    assert restarted_knowledge.get_publication(str(job.job_id), **scope)['job_snapshot']['finished_at'] == published.finished_at
    assert recovered.updated_at > recovered.attempts[-1].finished_at
    assert restarted_knowledge.get_ingestion_checkpoint(str(job.job_id), **scope)['artifacts'] == {}
    with pytest.raises(PostgresJobLeaseError):
        resumed_queue.heartbeat(new_lease, expected_version=resumed.version, now=time.time())


def test_postgres_current_document_checkpoint_cancel_survives_older_failed_receipt(
    owned_postgres, tmp_path, monkeypatch,
):
    """Actual current checkpoint cancellation remains terminal on repeated polls."""
    from copy import deepcopy
    from hashlib import sha256
    from rick_ingestion import IngestionService
    from rick_ingestion.jobs import IngestionJob
    from rick_jobs import Job, JobState, JobFailure
    from rick_knowledge import Collection, PostgresKnowledgeStore
    from rick_retrieval import DeterministicHashEmbedding, InMemoryVectorStore
    from external_ingestion import ExternalIngestionHandler, _recovery_metadata
    from canonical_queue import CanonicalIngestionQueueAdapter
    from postgres_jobs import PostgresJobQueue

    connect = owned_postgres
    with connect() as conn:
        conn.execute("INSERT INTO rick_tenants (tenant_id,display_name) VALUES ('t','Synthetic')")
        conn.execute("INSERT INTO rick_users (user_id) VALUES ('u')")
        conn.execute("INSERT INTO rick_memberships (tenant_id,user_id,workspace_id,role) VALUES ('t','u','w','KNOWLEDGE_MANAGER')")
    scope = dict(tenant_id='t', workspace_id='w', collection_id='c')
    knowledge = PostgresKnowledgeStore(connect, created_by='u')
    knowledge.ensure_collection(Collection(**scope, metadata={'created_by':'u'}))
    data = b'Document-bearing cancellation after previous failed receipt. ' * 80
    class Objects:
        def get(self, *args, **kwargs): return data
    vectors = InMemoryVectorStore()
    job = Job.create(job_id='document-cancel-two', **scope, operation='ingest',
        idempotency_key='document-cancel-two', payload={'object_key':'uploads/cancel',
        'filename_ref':'Y2FuY2VsLnR4dA==','checksum':'sha256:'+sha256(data).hexdigest()},
        now=time.time(), max_attempts=2)
    queue = PostgresJobQueue(connect, max_attempts=2, backoff_seconds=0, lease_seconds=30)
    queue.enqueue(job, expected_version=0)
    first, first_lease = queue.claim(worker_id='first', scope=job.scope,
        expected_versions={}, now=time.time())[0]
    old = IngestionJob(job_id=str(job.job_id), **scope, document_id='old',
        attempt=1, created_at=first.created_at, started_at=first.attempts[-1].started_at,
        metadata=_recovery_metadata(first))
    knowledge.begin_publication(old)
    knowledge.resolve_publication(knowledge.get_publication(str(job.job_id), **scope),'failed')
    previous = deepcopy(knowledge.get_publication(str(job.job_id), **scope))
    failed_at = time.time()
    queue.fail(first_lease, JobFailure(code='handler_timeout', message='timeout', retryable=True,
        attempt=1, occurred_at=failed_at), now=failed_at, expected_version=first.version)
    current, lease = queue.claim(worker_id='second', scope=job.scope,
        expected_versions={}, now=time.time())[0]
    assert current.attempt_count == 2
    ingestion = IngestionService(knowledge=knowledge, vectors=vectors, embeddings=DeterministicHashEmbedding())
    handler = ExternalIngestionHandler(ingestion, Objects(), created_by='u', temp_root=tmp_path/'before')
    def die(*args, **kwargs): raise SystemExit('before current publication intent')
    monkeypatch.setattr(knowledge,'begin_publication',die)
    with pytest.raises(SystemExit): handler(CanonicalIngestionQueueAdapter._record(current))
    checkpoint = knowledge.get_ingestion_checkpoint(str(job.job_id), **scope)
    assert checkpoint['document_id'] and checkpoint['job_snapshot']['attempt'] == 2
    restarted_knowledge = PostgresKnowledgeStore(connect,created_by='u')
    handler.ingestion = IngestionService(knowledge=restarted_knowledge,vectors=vectors,embeddings=DeterministicHashEmbedding())
    queue.publication_reconciler = handler.recover_job
    requested = queue.cancel(str(job.job_id), **scope, now=time.time(), expected_version=current.version)
    assert requested.state is JobState.CANCELLED
    assert restarted_knowledge.get_ingestion_checkpoint(str(job.job_id), **scope)['cancel_requested']
    for _ in range(3):
        recovered = queue.recover_publication(str(job.job_id), **scope, now=time.time())
        assert recovered.state is JobState.CANCELLED and recovered.attempt_count == 2
        assert restarted_knowledge.get_publication(str(job.job_id), **scope) == previous
    assert restarted_knowledge.get_ingestion_checkpoint(str(job.job_id), **scope)['state'] == 'cancelled'
    assert restarted_knowledge.get_document(checkpoint['document_id'], tenant_id='t',workspace_id='w').status != 'published'


def _pg_rework5_fixture(connect, tmp_path, *, max_attempts=1, lease_seconds=1):
    """Owned PG facts; object bytes/vectors/embeddings remain memory collaborators."""
    from base64 import b64encode
    from hashlib import sha256
    from rick_ingestion import IngestionService
    from rick_jobs import Job
    from rick_knowledge import Collection, PostgresKnowledgeStore
    from rick_retrieval import DeterministicHashEmbedding, InMemoryVectorStore
    from external_ingestion import ExternalIngestionHandler
    from postgres_jobs import PostgresJobQueue
    with connect() as conn:
        conn.execute("INSERT INTO rick_tenants (tenant_id,display_name) VALUES ('t','Synthetic')")
        conn.execute("INSERT INTO rick_users (user_id) VALUES ('u')")
        conn.execute("INSERT INTO rick_memberships (tenant_id,user_id,workspace_id,role) VALUES ('t','u','w','KNOWLEDGE_MANAGER')")
    scope = dict(tenant_id='t', workspace_id='w', collection_id='c')
    knowledge = PostgresKnowledgeStore(connect, created_by='u')
    knowledge.ensure_collection(Collection(**scope, metadata={'created_by':'u'}))
    vectors = InMemoryVectorStore()
    objects = {}
    class Objects:
        def get(self, object_scope, key, *args, **kwargs): return objects[key]
    def create_job(name):
        key = 'uploads/' + name
        data = (name + ' owned PostgreSQL recovery discriminator. ').encode() * 80
        objects[key] = data
        return Job.create(job_id=name, **scope, operation='ingest', idempotency_key=name,
            payload={'object_key':key,'filename_ref':b64encode((name+'.txt').encode()).decode(),
                     'checksum':'sha256:'+sha256(data).hexdigest()},
            now=time.time(), max_attempts=max_attempts)
    def handler(store, name):
        return ExternalIngestionHandler(IngestionService(knowledge=store,vectors=vectors,
            embeddings=DeterministicHashEmbedding()),Objects(),created_by='u',temp_root=tmp_path/name)
    queue = PostgresJobQueue(connect, max_attempts=max_attempts, lease_seconds=lease_seconds)
    return scope, knowledge, vectors, queue, create_job, handler


def test_postgres_repeated_continuation_crash_does_not_starve_other_work(owned_postgres,tmp_path,monkeypatch):
    """Real DB-clock lease expiries; injected executor crashes retain checkpoints."""
    from copy import deepcopy
    from rick_jobs import JobResult, JobState
    from rick_knowledge import PostgresKnowledgeStore
    from canonical_queue import CanonicalIngestionQueueAdapter
    from postgres_jobs import PostgresJobQueue, PostgresJobLeaseError
    scope,knowledge,vectors,queue,create_job,make_handler = _pg_rework5_fixture(owned_postgres,tmp_path)
    jobs = [create_job(name) for name in ('continuation-a','continuation-b')]
    for job in jobs: queue.enqueue(job,expected_version=0)
    initial = queue.claim(worker_id='before',scope=jobs[0].scope,expected_versions={},limit=2,now=time.time())
    assert len(initial) == 2
    source_handler = make_handler(knowledge,'before')
    def die(*args,**kwargs): raise SystemExit('crash before publication intent')
    with monkeypatch.context() as fault:
        fault.setattr(knowledge,'begin_publication',die)
        for running,_ in initial:
            with pytest.raises(SystemExit): source_handler(CanonicalIngestionQueueAdapter._record(running))
    artifacts = {str(job.job_id):deepcopy(knowledge.get_ingestion_checkpoint(str(job.job_id),**scope)['artifacts']) for job in jobs}
    fresh = create_job('healthy-queued')
    queue.enqueue(fresh,expected_version=0)
    restarted_store = PostgresKnowledgeStore(owned_postgres,created_by='u')
    recovery_handler = make_handler(restarted_store,'after')
    resumed_queue = PostgresJobQueue(owned_postgres,max_attempts=1,lease_seconds=1,
        publication_reconciler=recovery_handler.recover_job)
    seen = []
    for poll in range(6):
        time.sleep(1.1)
        claimed = resumed_queue.claim(worker_id='after-'+str(poll),scope=fresh.scope,
            expected_versions={},limit=1,now=time.time())
        if not claimed: continue
        assert len(claimed) == 1
        running,lease = claimed[0]
        name = str(running.job_id);seen.append(name)
        if name == 'healthy-queued':
            published = recovery_handler(CanonicalIngestionQueueAdapter._record(running))
            assert published.status == 'published'
            resumed_queue.acknowledge(lease,JobResult(document_id=published.document_id,
                completed_at=published.finished_at),now=time.time(),expected_version=running.version)
        else:
            assert running.attempt_count == running.max_attempts == 1
            assert restarted_store.get_ingestion_checkpoint(name,**scope)['artifacts'] == artifacts[name]
            # Execution dies here. The next poll waits for actual PostgreSQL expiry.
    assert {'continuation-a','continuation-b','healthy-queued'} <= set(seen), seen
    assert resumed_queue.get('healthy-queued',**scope).state is JobState.SUCCEEDED
    for original,old_lease in initial:
        with pytest.raises(PostgresJobLeaseError):
            resumed_queue.heartbeat(old_lease,expected_version=original.version,now=time.time())


@pytest.mark.parametrize('terminal',['published','cancelled'])
def test_postgres_terminal_checkpoint_finish_survives_receipt_or_callback_gap(owned_postgres,tmp_path,monkeypatch,terminal):
    """Injected commit gap, fresh owners and real PG rollback; no process-kill claim."""
    from math import floor
    from types import SimpleNamespace
    from rick_jobs import JobState
    from rick_knowledge import PostgresKnowledgeStore
    from canonical_queue import CanonicalIngestionQueueAdapter
    from postgres_jobs import PostgresJobQueue, PostgresJobLeaseError
    import rick_ingestion.jobs as ingestion_jobs
    scope,knowledge,vectors,queue,create_job,make_handler = _pg_rework5_fixture(owned_postgres,tmp_path)
    job = create_job('terminal-checkpoint-'+terminal)
    queue.enqueue(job,expected_version=0)
    running,lease = queue.claim(worker_id='before',scope=job.scope,expected_versions={},now=time.time())[0]
    handler = make_handler(knowledge,'before')
    def die(*args,**kwargs): raise SystemExit('terminal persisted before canonical callback')
    if terminal == 'published':
        with monkeypatch.context() as fault:
            fault.setattr(knowledge,'save_publication_snapshot',die)
            with pytest.raises(SystemExit): handler(CanonicalIngestionQueueAdapter._record(running))
        receipt = knowledge.get_publication(str(job.job_id),**scope)
        assert receipt['outcome'] == 'committed' and receipt['job_snapshot']['finished_at'] is not None
        assert receipt['job_snapshot']['started_at'] == running.attempts[-1].started_at
    else:
        with monkeypatch.context() as fault:
            fault.setattr(knowledge,'begin_publication',die)
            with pytest.raises(SystemExit): handler(CanonicalIngestionQueueAdapter._record(running))
        queue.publication_reconciler = handler.recover_job
        persist = queue._persist
        def crash_before_canonical_cancel(cursor,next_job,*args,**kwargs):
            if next_job.state is JobState.CANCELLED: die()
            return persist(cursor,next_job,*args,**kwargs)
        with monkeypatch.context() as fault:
            fault.setattr(queue,'_persist',crash_before_canonical_cancel)
            with pytest.raises(SystemExit):
                queue.cancel(str(job.job_id),**scope,now=time.time(),expected_version=running.version)
    checkpoint = knowledge.get_ingestion_checkpoint(str(job.job_id),**scope)
    original_finish = checkpoint['job_snapshot']['finished_at']
    assert checkpoint['state'] == ('committed' if terminal == 'published' else 'cancelled')
    assert original_finish is not None
    if terminal == 'published':
        assert receipt['job_snapshot']['finished_at'] == original_finish
    assert queue.get(str(job.job_id),**scope).state is JobState.RUNNING
    expected_finish = floor(original_finish*1_000_000)/1_000_000
    restarted_store = PostgresKnowledgeStore(owned_postgres,created_by='u')
    restarted_handler = make_handler(restarted_store,'after')
    restarted_queue = PostgresJobQueue(owned_postgres,publication_reconciler=restarted_handler.recover_job)
    # Only the ingestion transition clock is replaced; DB clock and sleeps remain real.
    monkeypatch.setattr(ingestion_jobs,'time',SimpleNamespace(time=lambda:original_finish+100))
    recovered = restarted_queue.recover_publication(str(job.job_id),**scope,now=original_finish+100)
    assert recovered.state is (JobState.SUCCEEDED if terminal == 'published' else JobState.CANCELLED)
    assert recovered.attempts[-1].finished_at == expected_finish
    assert recovered.attempt_count == 1 and recovered.attempts[-1].started_at == running.attempts[-1].started_at
    assert recovered.updated_at > original_finish
    if terminal == 'published':
        assert recovered.result.completed_at == expected_finish
        assert restarted_store.get_publication(str(job.job_id),**scope)['job_snapshot']['finished_at'] == original_finish
    else:
        assert restarted_store.get_publication(str(job.job_id),**scope) is None
    with pytest.raises(PostgresJobLeaseError):
        restarted_queue.heartbeat(lease,expected_version=running.version,now=time.time())


def test_postgres_earlier_journal_receipt_cannot_rewrite_canonical_attempt_identity(owned_postgres,tmp_path):
    """A deliberate legacy-journal/canonical conflict must defer, never alter history."""
    from copy import deepcopy
    from math import floor
    from rick_ingestion import IngestionService
    from rick_jobs import Job, JobState
    from rick_knowledge import PostgresKnowledgeStore
    from rick_retrieval import DeterministicHashEmbedding
    from external_ingestion import _recovery_metadata
    from postgres_jobs import PostgresJobQueue
    scope,knowledge,vectors,queue,create_job,make_handler = _pg_rework5_fixture(owned_postgres,tmp_path)
    template = create_job('journal-canonical-conflict')
    born = floor(time.time()*1_000_000)/1_000_000
    job = Job.create(job_id=template.job_id,**scope,operation='ingest',idempotency_key=template.idempotency_key,
        payload=template.payload,now=born,max_attempts=1)
    journal_owner = job.transition(JobState.QUEUED,now=born).start_attempt(worker_id='journal-before',now=born)
    source = tmp_path/'journal.txt';source.write_text('Earlier journal publication. '*80)
    service = IngestionService(knowledge=knowledge,vectors=vectors,embeddings=DeterministicHashEmbedding())
    published = service.ingest(source,**scope,job_id=str(job.job_id),
        _recovery_metadata=_recovery_metadata(journal_owner))
    assert published.status == 'published'
    receipt = deepcopy(knowledge.get_publication(str(job.job_id),**scope))
    points = deepcopy(vectors.all_points())
    queue.enqueue(job,expected_version=0)
    running,lease = queue.claim(worker_id='canonical-after',scope=job.scope,expected_versions={},now=time.time())[0]
    assert running.attempts[-1].started_at > published.finished_at
    owner = make_handler(PostgresKnowledgeStore(owned_postgres,created_by='u'),'after')
    recovery_queue = PostgresJobQueue(owned_postgres,publication_reconciler=owner.recover_job)
    for _ in range(2):
        recovered = recovery_queue.recover_publication(str(job.job_id),**scope,now=time.time())
        assert recovered.state is JobState.RUNNING
        assert recovered.attempts == running.attempts and recovered.version == running.version
        with owned_postgres() as conn:
            row = conn.execute('SELECT last_error_code FROM rick_ingestion_jobs WHERE job_id=%s',(str(job.job_id),)).fetchone()
            assert row['last_error_code'] == 'publication_attempt_conflict'
        assert knowledge.get_publication(str(job.job_id),**scope) == receipt
        assert vectors.all_points() == points


@pytest.mark.parametrize('outcome', ['committed', 'cancelled'])
def test_postgres_installed_unknown_terminal_finish_is_never_backfilled(owned_postgres, tmp_path, monkeypatch, outcome):
    """Raw legacy JSON is a fixture, never a new adapter decision or caller fact."""
    from copy import deepcopy
    from rick_ingestion.jobs import IngestionJob
    from rick_jobs import JobState
    from canonical_queue import CanonicalIngestionQueueAdapter
    from postgres_jobs import PostgresJobQueue, PostgresJobLeaseError
    from rick_knowledge import PostgresKnowledgeStore
    scope, store, vectors, queue, create_job, make_handler = _pg_rework5_fixture(owned_postgres, tmp_path)
    job = create_job('raw-unknown-' + outcome)
    queue.enqueue(job, expected_version=0)
    running, lease = queue.claim(worker_id='before', scope=job.scope, expected_versions={}, now=time.time())[0]
    handler = make_handler(store, 'before')
    def die(*args, **kwargs): raise SystemExit('simulated crash at durable boundary')
    if outcome == 'committed':
        publish = store.set_document_status
        def lose_ack(document_id, status, *args, **kwargs):
            publish(document_id, status, *args, **kwargs)
            if status == 'published': die()
        with monkeypatch.context() as fault:
            fault.setattr(store, 'set_document_status', lose_ack)
            with pytest.raises(SystemExit): handler(CanonicalIngestionQueueAdapter._record(running))
    else:
        with monkeypatch.context() as fault:
            fault.setattr(store, 'begin_publication', die)
            with pytest.raises(SystemExit): handler(CanonicalIngestionQueueAdapter._record(running))
        checkpoint = store.get_ingestion_checkpoint(str(job.job_id), **scope)
        saved = checkpoint['job_snapshot']
        intent = IngestionJob(job_id=str(job.job_id), **scope, document_id=checkpoint['document_id'],
            attempt=saved['attempt'], created_at=saved['created_at'], started_at=saved['started_at'],
            finished_at=None, status='verifying', metadata=deepcopy(saved['metadata']))
        store.begin_publication(intent)
    # Simulate installed pre-fix JSON directly in this UUID-owned disposable DB.
    # No production API is permitted to manufacture this missing historical fact.
    with owned_postgres() as connection:
        connection.execute("""UPDATE rick_publication_receipts
            SET outcome=%s, cancel_requested=%s,
                job_snapshot=jsonb_set(job_snapshot,'{finished_at}','null'::jsonb)
            WHERE job_id=%s""", (outcome, outcome == 'cancelled', str(job.job_id)))
    # The installed checkpoint is terminal too: an active checkpoint could
    # legitimately be finalized/cleaned during recovery, so it is not this fixture.
    legacy_checkpoint = deepcopy(store.get_ingestion_checkpoint(str(job.job_id), **scope))
    legacy_checkpoint.update(state=outcome, artifacts={}, cancel_requested=outcome == 'cancelled',
        job_snapshot=deepcopy(store.get_publication(str(job.job_id), **scope)['job_snapshot']))
    with owned_postgres() as connection:
        connection.execute('UPDATE rick_ingestion_checkpoints SET record=%s::jsonb WHERE job_id=%s',
            (json.dumps(legacy_checkpoint), str(job.job_id)))
    receipt = deepcopy(store.get_publication(str(job.job_id), **scope))
    checkpoint = deepcopy(store.get_ingestion_checkpoint(str(job.job_id), **scope))
    points = deepcopy(vectors.all_points())
    assert receipt['job_snapshot']['finished_at'] is None
    # Lease expiry is authorized by PostgreSQL wall time, not the caller poll.
    time.sleep(1.1)
    restarted = PostgresKnowledgeStore(owned_postgres, created_by='u')
    recovery = PostgresJobQueue(owned_postgres, publication_reconciler=make_handler(restarted, 'after').recover_job)
    for poll in (time.time() + 100, time.time() + 200):
        recovered = recovery.recover_publication(str(job.job_id), **scope, now=poll)
        assert recovered.state is JobState.RUNNING
        assert recovered.attempt_count == 1 and recovered.attempts == running.attempts
        with owned_postgres() as connection:
            row = connection.execute('SELECT last_error_code FROM rick_ingestion_jobs WHERE job_id=%s', (str(job.job_id),)).fetchone()
        assert row['last_error_code'] == 'publication_finish_unknown'
        assert restarted.get_publication(str(job.job_id), **scope) == receipt
        assert restarted.get_ingestion_checkpoint(str(job.job_id), **scope) == checkpoint
        assert vectors.all_points() == points
    with pytest.raises(PostgresJobLeaseError):
        recovery.heartbeat(lease, expected_version=running.version, now=time.time())


def test_postgres_document_and_completion_decision_roll_back_together(owned_postgres, tmp_path, monkeypatch):
    """Execute the real direct writer SQL, abort after both updates, then retry."""
    from canonical_queue import CanonicalIngestionQueueAdapter
    scope, store, vectors, queue, create_job, make_handler = _pg_rework5_fixture(owned_postgres, tmp_path)
    job = create_job('atomic-completion-rollback')
    queue.enqueue(job, expected_version=0)
    running, lease = queue.claim(worker_id='before', scope=job.scope, expected_versions={}, now=time.time())[0]
    publish = store.set_document_status
    def before_commit(document_id, status, *args, **kwargs):
        if status == 'published': raise SystemExit('before document transaction')
        return publish(document_id, status, *args, **kwargs)
    with monkeypatch.context() as fault:
        fault.setattr(store, 'set_document_status', before_commit)
        with pytest.raises(SystemExit): make_handler(store, 'before')(CanonicalIngestionQueueAdapter._record(running))
    receipt = store.get_publication(str(job.job_id), **scope)
    assert receipt['outcome'] == 'pending' and receipt['job_snapshot']['finished_at'] is None
    document_id = receipt['document_id']
    from rick_knowledge import PostgresKnowledgeError
    execute = store._execute
    injected = []
    def abort_after_receipt(cursor, sql, params=()):
        result = execute(cursor, sql, params)
        if "UPDATE rick_publication_receipts AS receipt" in sql and "SET outcome='committed'" in sql:
            injected.append(True)
            raise RuntimeError('abort real transaction after completion decision')
        return result
    with monkeypatch.context() as fault:
        fault.setattr(store, '_execute', abort_after_receipt)
        with pytest.raises(PostgresKnowledgeError, match='storage_unavailable'):
            store.set_document_status(document_id, 'published', tenant_id='t', workspace_id='w')
    assert injected == [True]
    assert store.get_document(document_id, tenant_id='t', workspace_id='w').status == 'processing'
    assert store.get_publication(str(job.job_id), **scope) == receipt
    store.set_document_status(document_id, 'published', tenant_id='t', workspace_id='w')
    decided = store.get_publication(str(job.job_id), **scope)
    assert decided['outcome'] == 'committed'
    assert decided['job_snapshot']['finished_at'] >= running.attempts[-1].started_at
    assert store.get_document(document_id, tenant_id='t', workspace_id='w').status == 'published'


@pytest.mark.parametrize('ack_clock', ['later', 'behind_decision'])
def test_postgres_normal_ack_preserves_durable_publication_finish(owned_postgres, tmp_path, ack_clock):
    """Normal acknowledgment and recovery must persist the same business finish."""
    from copy import deepcopy
    from math import floor
    from canonical_queue import CanonicalIngestionQueueAdapter
    from rick_jobs import JobState, JobResult
    from services.external_composition import _canonical_job_result
    # This exercises normal acknowledgment, not expiry. Keep the one-second
    # lease in the independent expiry controls, and allow parser/DB work here.
    scope, store, vectors, queue, create_job, make_handler = _pg_rework5_fixture(
        owned_postgres, tmp_path, lease_seconds=30)
    job = create_job('normal-ack-' + ack_clock)
    queue.enqueue(job, expected_version=0)
    running, lease = queue.claim(worker_id='publisher', scope=job.scope, expected_versions={}, now=time.time())[0]
    handler = make_handler(store, 'publisher')
    queue.publication_reconciler = handler.recover_job
    normal_result = handler(CanonicalIngestionQueueAdapter._record(running))
    result = _canonical_job_result(running, normal_result)
    assert isinstance(result, JobResult)
    receipt = deepcopy(store.get_publication(str(job.job_id), **scope))
    finished = receipt['job_snapshot']['finished_at']
    assert finished == result.completed_at and finished >= running.attempts[-1].started_at
    observed = finished + 100 if ack_clock == 'later' else (running.attempts[-1].started_at + finished) / 2
    succeeded = queue.acknowledge(lease, result, now=observed, expected_version=running.version)
    expected_finish = floor(finished * 1_000_000) / 1_000_000
    assert succeeded.state is JobState.SUCCEEDED
    assert succeeded.attempt_count == 1
    assert succeeded.attempts[-1].started_at == running.attempts[-1].started_at
    assert succeeded.attempts[-1].finished_at == expected_finish
    assert succeeded.result.completed_at == expected_finish
    assert succeeded.updated_at >= max(observed, expected_finish)
    persisted = queue.get(str(job.job_id), **scope)
    assert persisted.attempts == succeeded.attempts
    assert persisted.as_dict()['result'] == succeeded.as_dict()['result']
    assert store.get_publication(str(job.job_id), **scope) == receipt


def test_postgres_matching_checkpoint_finish_does_not_backfill_historical_receipt(owned_postgres, tmp_path, monkeypatch):
    """Checkpoint owns known projection time; old receipt JSON stays unchanged."""
    from copy import deepcopy
    from math import floor
    from canonical_queue import CanonicalIngestionQueueAdapter
    from rick_jobs import JobState
    from rick_knowledge import PostgresKnowledgeStore
    from postgres_jobs import PostgresJobQueue
    scope, store, vectors, queue, create_job, make_handler = _pg_rework5_fixture(owned_postgres, tmp_path)
    job = create_job('known-checkpoint-old-receipt')
    queue.enqueue(job, expected_version=0)
    running, lease = queue.claim(worker_id='before', scope=job.scope, expected_versions={}, now=time.time())[0]
    def die(*args, **kwargs): raise SystemExit('after terminal checkpoint before receipt snapshot')
    with monkeypatch.context() as fault:
        fault.setattr(store, 'save_publication_snapshot', die)
        with pytest.raises(SystemExit): make_handler(store, 'before')(CanonicalIngestionQueueAdapter._record(running))
    checkpoint = deepcopy(store.get_ingestion_checkpoint(str(job.job_id), **scope))
    finished = checkpoint['job_snapshot']['finished_at']
    assert checkpoint['state'] == 'committed' and finished is not None
    # Only this test-owned historical receipt lacks the old completion fact.
    with owned_postgres() as connection:
        connection.execute("""UPDATE rick_publication_receipts
            SET job_snapshot=jsonb_set(job_snapshot,'{finished_at}','null'::jsonb)
            WHERE job_id=%s""", (str(job.job_id),))
    receipt = deepcopy(store.get_publication(str(job.job_id), **scope))
    points = deepcopy(vectors.all_points())
    restarted = PostgresKnowledgeStore(owned_postgres, created_by='u')
    owner = make_handler(restarted, 'after')
    recovery = PostgresJobQueue(owned_postgres, publication_reconciler=owner.recover_job)
    for poll in (finished + 100, finished + 200):
        recovered = recovery.recover_publication(str(job.job_id), **scope, now=poll)
        expected_finish = floor(finished * 1_000_000) / 1_000_000
        assert recovered.state is JobState.SUCCEEDED
        assert recovered.attempt_count == 1 and recovered.attempts[-1].started_at == running.attempts[-1].started_at
        assert recovered.attempts[-1].finished_at == recovered.result.completed_at == expected_finish
        assert restarted.get_publication(str(job.job_id), **scope) == receipt
        assert restarted.get_publication(str(job.job_id), **scope)['job_snapshot']['finished_at'] is None
        assert restarted.get_ingestion_checkpoint(str(job.job_id), **scope) == checkpoint
        assert vectors.all_points() == points


@pytest.mark.parametrize('mode', ['acknowledge', 'recover'])
@pytest.mark.parametrize('clock', ['before_result', 'after_result', 'before_attempt'])
def test_postgres_generic_result_retains_ordinary_transition_clock(owned_postgres, tmp_path, mode, clock):
    """Plain callbacks cannot acquire typed publication authority in real SQL."""
    from math import floor
    from rick_jobs import JobResult, JobState
    from postgres_jobs import PostgresJobError
    scope, store, vectors, queue, create_job, make_handler = _pg_rework5_fixture(owned_postgres, tmp_path)
    job = create_job('generic-clock-' + mode + '-' + clock)
    queue.enqueue(job, expected_version=0)
    running, lease = queue.claim(worker_id='generic', scope=job.scope, expected_versions={}, now=time.time())[0]
    started = running.attempts[-1].started_at
    result = JobResult(completed_at=started + .05)
    observed = started + {'before_result': .02, 'after_result': .20, 'before_attempt': -.02}[clock]
    queue.publication_reconciler = lambda candidate: result
    if mode == 'acknowledge' and clock != 'after_result':
        with pytest.raises(PostgresJobError) as error:
            queue.acknowledge(lease, result, now=observed, expected_version=running.version)
        assert error.value.code == 'invalid_transition'
        terminal = queue.get(str(job.job_id), **scope)
    else:
        terminal = (queue.acknowledge(lease, result, now=observed, expected_version=running.version)
                    if mode == 'acknowledge' else queue.recover_publication(str(job.job_id), **scope, now=observed))
    if clock == 'after_result':
        assert terminal.state is JobState.SUCCEEDED
        assert terminal.result.completed_at == floor(result.completed_at * 1_000_000) / 1_000_000
        assert terminal.attempts[-1].finished_at == floor(observed * 1_000_000) / 1_000_000
        assert terminal.attempts[-1].started_at == started
        assert terminal.attempt_count == running.attempt_count
    else:
        assert terminal.state is JobState.RUNNING and terminal.version == running.version
        assert terminal.attempts == running.attempts and terminal.updated_at == running.updated_at
        assert terminal.result is None and terminal.created_at == running.created_at
    persisted = queue.get(str(job.job_id), **scope)
    assert persisted.as_dict() == terminal.as_dict()
    assert store.get_publication(str(job.job_id), **scope) is None
    assert not vectors.all_points()


@pytest.mark.parametrize('owned_postgres', [9], indirect=True)
@pytest.mark.parametrize('advance_history', [False, True])
def test_postgres_migration_revalidates_authorization_after_waiting_for_lock(
    owned_postgres, tmp_path, monkeypatch, advance_history,
):
    """A real concurrent migration must invalidate the previously reviewed plan."""
    import threading
    import psycopg
    from psycopg.rows import tuple_row
    root = Path(__file__).resolve().parents[3]
    monkeypatch.syspath_prepend(str(root / 'infrastructure/vps'))
    spec = spec_from_file_location('prod02_locked_migrate', root / 'infrastructure/scripts/migrate.py')
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    directory = root / 'infrastructure/migrations'
    rows = migration.migration_files(directory)
    with owned_postgres() as connection:
        dsn = owned_postgres.migration_dsn  # info.dsn intentionally omits password.
        connection.execute('SET TRANSACTION READ ONLY')
        with connection.cursor(row_factory=tuple_row) as cursor:
            observed = migration.locked_observation(cursor, rows)
    assert observed['history'][-1]['version'] == '0009'
    assert [p['version'] for p in observed['pending']] == ['0010']
    plan = dict(schema='rick.vps.migration-plan/v1', authorization='APPLY_REVIEWED_SQL',
                observed=observed, maintenance_window=True,
                verified_backup_id='synthetic-owned-test-backup', backward_compatible=True)
    authorization = json.dumps(plan, sort_keys=True).encode()
    original_connect = psycopg.connect
    trace, outcomes, backend = [], [], []
    reached = threading.Event()

    class CursorTrace:
        def __init__(self, inner): self.inner = inner
        def __enter__(self): self.inner.__enter__(); return self
        def __exit__(self, *args): return self.inner.__exit__(*args)
        def __getattr__(self, name): return getattr(self.inner, name)
        def execute(self, sql, *args, **kwargs):
            trace.append(str(sql))
            if 'pg_advisory_xact_lock' in str(sql): reached.set()
            return self.inner.execute(sql, *args, **kwargs)

    class ConnectionTrace:
        def __init__(self, inner): self.inner = inner; backend.append(inner.info.backend_pid)
        def __enter__(self): self.inner.__enter__(); return self
        def __exit__(self, *args): return self.inner.__exit__(*args)
        def cursor(self, *args, **kwargs): return CursorTrace(self.inner.cursor(*args, **kwargs))

    def traced_connect(*args, **kwargs): return ConnectionTrace(original_connect(*args, **kwargs))
    def execute_authorized():
        try: outcomes.append(('ok', migration.apply(directory, dsn, authorization=authorization)))
        except Exception as error: outcomes.append(('error', type(error).__name__, str(error)))

    # Own the same advisory lock before starting the authorized runner.
    holder = owned_postgres()
    holder.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ('rick-intelligence:migrations',))
    monkeypatch.setattr(psycopg, 'connect', traced_connect)
    thread = threading.Thread(target=execute_authorized, daemon=True)
    thread.start()
    try:
        assert reached.wait(5), 'runner did not attempt the migration lock'
        waiting = False
        end = time.monotonic() + 5
        while time.monotonic() < end:
            holder.execute('SELECT pg_stat_clear_snapshot()')
            row = holder.execute('SELECT wait_event_type, wait_event FROM pg_stat_activity WHERE pid=%s', (backend[0],)).fetchone()
            if row and row['wait_event_type'] == 'Lock' and str(row['wait_event']).lower() == 'advisory':
                waiting = True; break
            time.sleep(.02)
        assert waiting, 'real PostgreSQL runner was not observed waiting for the advisory lock'
        if advance_history:
            # The competing authorized migration completes the exact pending SQL.
            version, path, digest = rows[-1]
            assert version == '0010'
            holder.execute(path.read_text())
            holder.execute('INSERT INTO rick_schema_migrations(version,checksum,application) VALUES(%s,%s,%s)',
                           (version, digest, migration.APPLICATION))
        holder.commit()
    finally:
        holder.close()
        thread.join(timeout=10)
    assert not thread.is_alive(), 'owned runner did not finish after lock release'
    if advance_history:
        assert outcomes == [('error', 'RuntimeError', 'database inventory changed under migration lock')]
        assert not any(s.lstrip().upper().startswith(('CREATE', 'ALTER', 'INSERT', 'DROP', 'DO ')) for s in trace)
    else:
        assert outcomes == [('ok', 0)]
        assert any('INSERT INTO rick_schema_migrations' in s for s in trace)
    with original_connect(dsn) as connection:
        history = connection.execute('SELECT version,checksum,application FROM rick_schema_migrations ORDER BY version').fetchall()
    assert history == [(version, digest, migration.APPLICATION) for version, path, digest in rows]
