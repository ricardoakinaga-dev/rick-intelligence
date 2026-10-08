"""Adversarial recovery probes. Queue FakeConnection is control-flow evidence only."""
from copy import deepcopy
import pytest
from rick_ingestion import IngestionService
from rick_ingestion.jobs import IngestionJob
from rick_knowledge import InMemoryKnowledgeStore, SQLiteKnowledgeStore, Collection
from rick_knowledge.fencing import OwnershipLostError
from rick_retrieval import DeterministicHashEmbedding, InMemoryVectorStore, SQLiteVectorStore
from rick_jobs import JobResult, JobState
from external_ingestion import ExternalIngestionError, ExternalIngestionHandler
from test_postgres_jobs import make_queue, make_job

SCOPE = dict(tenant_id='t', workspace_id='w', collection_id='c')

@pytest.fixture(params=['memory', 'sqlite'])
def knowledge(request, tmp_path):
    store = InMemoryKnowledgeStore() if request.param == 'memory' else SQLiteKnowledgeStore(tmp_path/'knowledge.sqlite')
    yield store
    if hasattr(store, 'close'):
        store.close()

def service(store, vectors=None, embeddings=None):
    return IngestionService(knowledge=store, vectors=vectors or InMemoryVectorStore(), embeddings=embeddings or DeterministicHashEmbedding())

def source(tmp_path, text='Recovery completed work. '):
    path = tmp_path/'source.txt'; path.write_text(text*80); return path

class NoReplay(DeterministicHashEmbedding):
    def embed(self, texts):
        raise AssertionError('completed embeddings cannot be replayed')

def test_F1_committed_retirement_failure_has_durable_owner(knowledge, tmp_path):
    owner = service(knowledge); path=source(tmp_path)
    old=owner.ingest(path, **SCOPE); path.write_text('Changed canonical content. '*80)
    delete=owner.vectors.delete_document
    def fail_old(doc, col):
        if doc==old.document_id: raise RuntimeError('retirement failure')
        return delete(doc,col)
    owner.vectors.delete_document=fail_old
    new=owner.reindex(old.document_id,path,**SCOPE)
    assert new.status=='published'
    assert knowledge.get_document(new.document_id).status=='published'
    assert owner.vectors.count_for_document(new.document_id,'c')>0
    receipt=knowledge.get_publication(new.job_id,**SCOPE)
    assert receipt['outcome']=='committed'
    assert receipt['job_snapshot']['metadata']['retirement_pending'] is True
    assert owner.recover_publication(new.job_id,**SCOPE).status=='published'
    owner.vectors.delete_document=delete
    fresh=service(knowledge,owner.vectors,NoReplay())
    assert fresh.recover_publication(new.job_id,**SCOPE).status=='published'
    assert knowledge.get_document(old.document_id).status=='unpublished'
    assert knowledge.get_publication(new.job_id,**SCOPE)['job_snapshot']['metadata']['retirement_pending'] is False


def test_F3_snapshot_restores_attempt_timestamps_and_metadata(knowledge):
    job=IngestionJob(**SCOPE,job_id='metadata',document_id='doc',status='verifying',stage='verifying',
        attempt=7,created_at=10,started_at=11,metadata={'publication_attempt':'a'*32,'durability':'local-sqlite','restart_recovery':True})
    knowledge.begin_publication(job); knowledge.resolve_publication(knowledge.get_publication(job.job_id,**SCOPE),'committed')
    result=service(knowledge).recover_publication(job.job_id,**SCOPE,snapshot=job)
    assert (result.attempt,result.created_at,result.started_at)==(7,10,11)
    assert result.metadata['durability']=='local-sqlite' and result.metadata['restart_recovery']
    again=service(knowledge).recover_publication(job.job_id,**SCOPE)
    assert (again.attempt,again.created_at,again.started_at)==(7,10,11)

@pytest.mark.parametrize('denial',[None,'cancel','archive','missing-vectors','unavailable'])
def test_F4_ready_intent_before_status_commit_is_resumable_and_fenced(knowledge,tmp_path,denial):
    owner=service(knowledge); path=source(tmp_path); real=knowledge.set_document_status
    def die(doc,status,**kw):
        if status=='published': raise SystemExit('before status commit')
        return real(doc,status,**kw)
    knowledge.set_document_status=die
    with pytest.raises(SystemExit): owner.ingest(path,**SCOPE,job_id='ready')
    knowledge.set_document_status=real
    receipt=knowledge.get_publication('ready',**SCOPE); before=deepcopy(owner.vectors.all_points())
    job=owner.get_status('ready')
    if denial=='cancel': knowledge.request_publication_cancel(job)
    if denial=='archive': knowledge.upsert_collection(Collection(**SCOPE, status='archived'))
    if denial=='missing-vectors': owner.vectors.delete_document(job.document_id,'c')
    if denial=='unavailable':
        def unavailable(*a,**kw): raise RuntimeError('authority unavailable')
        knowledge.get_collection=unavailable
    fresh=service(knowledge,owner.vectors,NoReplay()); path.unlink()
    recovered=fresh.recover_publication('ready',**SCOPE)
    assert recovered.status==({None:'published','cancel':'cancelled','archive':'failed','missing-vectors':'verifying','unavailable':'verifying'}[denial])
    if denial is None:
        assert owner.vectors.all_points()==before
        assert fresh.ingest(path,**SCOPE,job_id='ready').status=='published'
    if denial in {'unavailable','missing-vectors'}: assert knowledge.get_publication('ready',**SCOPE)['outcome']=='pending'

@pytest.mark.parametrize('outcome',['failed','cancelled','committed'])
def test_F6_duplicate_begin_cannot_reopen_terminal_attempt(knowledge,outcome):
    job=IngestionJob(**SCOPE,job_id='terminal',document_id='doc',metadata={'publication_attempt':'a'})
    knowledge.begin_publication(job); knowledge.resolve_publication(knowledge.get_publication(job.job_id,**SCOPE),outcome)
    knowledge.begin_publication(job)
    assert knowledge.get_publication(job.job_id,**SCOPE)['outcome']==outcome
    other=deepcopy(job); other.metadata['publication_attempt']='b'; other.attempt=job.attempt+1
    if outcome!='failed':
        with pytest.raises(OwnershipLostError): knowledge.begin_publication(other)
    else:
        knowledge.begin_publication(other)
        assert knowledge.get_publication(job.job_id,**SCOPE)['attempt_id']=='b'

@pytest.mark.parametrize('field',['job_id','document_id','publication_attempt','document_attempt'])
@pytest.mark.parametrize('value',['','  ','\t\n'])
def test_F7_invalid_receipt_identities_rejected(knowledge,field,value):
    job=IngestionJob(**SCOPE,job_id='valid',document_id='doc',metadata={'publication_attempt':'a'})
    kw={}
    if field=='publication_attempt': job.metadata[field]=value
    elif field=='document_attempt': kw[field]=value
    else: setattr(job,field,value)
    with pytest.raises(ValueError): knowledge.begin_publication(job,**kw)


def test_F2_actual_public_cancel_stays_verifying_and_persists_request(tmp_path,knowledge,monkeypatch):
    monkeypatch.setattr(knowledge, '_publication_commit_time', lambda: 105.)
    from canonical_queue import CanonicalIngestionQueueAdapter
    from services.postgres_ingestion import PostgresIngestionApplicationService
    queue,connection=make_queue(); queued=queue.enqueue(make_job(max_attempts=1),expected_version=0)
    running,lease=queue.claim(worker_id='old',scope=queued.scope,expected_versions={},now=104)[0]
    scope=dict(tenant_id=queued.tenant_id,workspace_id=queued.workspace_id,collection_id=queued.collection_id)
    from external_ingestion import _recovery_metadata
    job=IngestionJob(**scope,job_id=str(queued.job_id),document_id='doc',
        created_at=running.created_at,started_at=running.attempts[-1].started_at,
        metadata=_recovery_metadata(running))
    knowledge.begin_publication(job)
    class Objects:
        def get(self,*a,**kw): raise AssertionError('recovery cannot hydrate source')
        def put(self,*a,**kw): raise AssertionError('recovery cannot rewrite source')
    objects=Objects()
    handler=ExternalIngestionHandler(service(knowledge),objects,temp_root=tmp_path/'worker')
    queue.publication_reconciler=handler.recover_job
    app=PostgresIngestionApplicationService(queue=CanonicalIngestionQueueAdapter(queue,clock=lambda:105),object_store=objects,knowledge=knowledge)
    get=knowledge.get_document
    def unavailable(*a,**kw): raise RuntimeError('unknown')
    knowledge.get_document=unavailable
    assert app.cancel(str(queued.job_id),**{k:scope[k] for k in ['tenant_id','workspace_id']},allowed_collection_ids=[]) is None
    assert not knowledge.get_publication(job.job_id,**scope)['cancel_requested']
    public=app.cancel(job.job_id,tenant_id=scope['tenant_id'],workspace_id=scope['workspace_id'],allowed_collection_ids=[scope['collection_id']])
    assert public['status']=='verifying'
    assert public['cancel_requested'] is True and public['cancelled'] is False
    assert public['started_at'] == running.attempts[-1].started_at and public['finished_at'] is None
    assert knowledge.get_publication(job.job_id,**scope)['cancel_requested']
    knowledge.get_document=get
    handler.ingestion=service(knowledge)
    public = app.get_status(job.job_id,tenant_id=scope['tenant_id'],workspace_id=scope['workspace_id'],allowed_collection_ids=[scope['collection_id']])
    cancelled = queue.get_for_workspace(queued.job_id,tenant_id=queued.tenant_id,workspace_id=queued.workspace_id)
    assert public['status']=='cancelled'
    assert public['started_at'] == cancelled.attempts[-1].started_at == running.attempts[-1].started_at
    assert public['finished_at'] == cancelled.attempts[-1].finished_at == 105
    assert connection.jobs[job.job_id]['attempts']==1


def test_F5_more_than_100_unknown_jobs_do_not_starve_later_commit_or_revive_lease():
    from postgres_jobs import PostgresJobQueue,PostgresJobLeaseError
    queue,connection=make_queue(); leases={}; scope=make_job().scope
    for i in range(121):
        queued=queue.enqueue(make_job(job_id=f'job-{i:03}',key=f'idem-{i:03}',max_attempts=1),expected_version=0)
        running,lease=queue.claim(worker_id='old',scope=scope,expected_versions={},now=104)[0]; leases[str(queued.job_id)]=(running,lease)
    calls=[]
    def recovery(job):
        calls.append(str(job.job_id))
        if str(job.job_id)=='job-120': return JobResult(document_id='winner',completed_at=115,output_refs={})
        raise ExternalIngestionError('recovery_required')
    queue.publication_reconciler=recovery
    for now in [114,115,116]:
        connection.database_now=now; prior=len(calls)
        assert queue.claim(worker_id='new',scope=scope,expected_versions={},now=now)==()
        assert len(calls)-prior<=100
        queue=PostgresJobQueue(lambda:connection,lease_seconds=10,publication_reconciler=recovery)
    assert connection.jobs['job-120']['contract_state']=='SUCCEEDED'
    row=connection.jobs['job-000']; running,lease=leases['job-000']
    assert row['attempts']==1 and row['lease_until']==lease.expires_at
    with pytest.raises(PostgresJobLeaseError): queue.heartbeat(lease,now=105,expected_version=running.version)

@pytest.mark.parametrize('column',['tenant_id','workspace_id','collection_id','job_id','document_id','attempt_id','document_attempt'])
@pytest.mark.parametrize('blank',['','\t\n','\u00a0\u2003'])
def test_F7_sqlite_raw_sql_identity_constraints(tmp_path,column,blank):
    import sqlite3
    db=SQLiteKnowledgeStore(tmp_path/'constraints.sqlite')
    values=dict(tenant_id='t',workspace_id='w',collection_id='c',job_id='j',document_id='d',attempt_id='a',document_attempt='a',outcome='pending')
    values[column]=blank
    try:
        with pytest.raises(sqlite3.IntegrityError):
            with db._transaction():
                db._connection.execute('INSERT INTO publication_receipts ('+','.join(values)+') VALUES ('+','.join('?' for _ in values)+')',tuple(values.values()))
    finally: db.close()


def test_F4_disk_reopen_preserves_ready_work_and_finished_timestamp(tmp_path,monkeypatch):
    import rick_ingestion.pipeline as pipeline
    db=SQLiteKnowledgeStore(tmp_path/'ready.sqlite'); vec=SQLiteVectorStore(tmp_path/'points.sqlite')
    owner=service(db,vec); path=source(tmp_path); real=db.set_document_status
    def die(doc,status,**kw):
        if status=='published': raise SystemExit('before commit')
        return real(doc,status,**kw)
    db.set_document_status=die
    with pytest.raises(SystemExit): owner.ingest(path,**SCOPE,job_id='disk-ready')
    job=owner.get_status('disk-ready'); before=deepcopy(vec.all_points())
    db.close();vec.close();path.unlink()
    db=SQLiteKnowledgeStore(tmp_path/'ready.sqlite');vec=SQLiteVectorStore(tmp_path/'points.sqlite')
    def no_parser(*a,**kw): raise AssertionError('completed parser cannot be replayed')
    monkeypatch.setattr(pipeline,'execute_parser',no_parser)
    try:
        fresh=service(db,vec,NoReplay()); result=fresh.recover_publication('disk-ready',**SCOPE)
        assert result.status=='published' and vec.all_points()==before
        assert (result.attempt,result.created_at,result.started_at)==(job.attempt,job.created_at,job.started_at)
        completed=result.finished_at
        again=service(db,vec,NoReplay()).recover_publication('disk-ready',**SCOPE)
        assert again.finished_at==completed
    finally: db.close();vec.close()


def test_F6_retry_count_advances_without_reopening_cancelled_winner(knowledge,tmp_path):
    job=IngestionJob(**SCOPE,job_id='retry',document_id='old',attempt=3,created_at=10,metadata={'publication_attempt':'a'})
    knowledge.begin_publication(job);knowledge.resolve_publication(knowledge.get_publication('retry',**SCOPE),'failed')
    owner=service(knowledge); result=owner.ingest(source(tmp_path),**SCOPE,job_id='retry')
    assert result.status=='published' and result.attempt==4 and result.created_at==10
    before=deepcopy(owner.vectors.all_points())
    assert owner.ingest(tmp_path/'missing',**SCOPE,job_id='retry').status=='published'
    assert owner.vectors.all_points()==before
    cancelled=IngestionJob(**SCOPE,job_id='cancelled',document_id='cancelled-doc',attempt=8,metadata={'publication_attempt':'b'})
    knowledge.begin_publication(cancelled);knowledge.resolve_publication(knowledge.get_publication('cancelled',**SCOPE),'cancelled')
    assert service(knowledge,embeddings=NoReplay()).ingest(tmp_path/'missing',**SCOPE,job_id='cancelled').status=='cancelled'
    assert knowledge.get_publication('cancelled',**SCOPE)['attempt_id']=='b'


def test_F1_public_published_poll_resumes_receipt_cleanup_without_queue_attempt_mutation(knowledge,tmp_path):
    from canonical_queue import CanonicalIngestionQueueAdapter
    from services.postgres_ingestion import PostgresIngestionApplicationService
    from rick_jobs import JobScope
    queue,conn=make_queue(); scope=JobScope(**SCOPE)
    queued=queue.enqueue(make_job(scope=scope,max_attempts=1),expected_version=0)
    running,lease=queue.claim(worker_id='old',scope=scope,expected_versions={},now=104)[0]
    owner=service(knowledge);path=source(tmp_path);old=owner.ingest(path,**SCOPE)
    path.write_text('New cleanup publication. '*80);delete=owner.vectors.delete_document
    def fail(doc,col):
        if doc==old.document_id: raise RuntimeError('retirement failed')
        return delete(doc,col)
    owner.vectors.delete_document=fail
    new=owner.reindex(old.document_id,path,**SCOPE,job_id=str(queued.job_id))
    assert new.status=='published' and new.metadata['retirement_pending']
    winner=queue.acknowledge(lease,JobResult(document_id=new.document_id,completed_at=105,output_refs={}),now=105,expected_version=running.version)
    class Objects:
        def get(self,*a,**kw): raise AssertionError('replay')
        def put(self,*a,**kw): raise AssertionError('replay')
    owner.vectors.delete_document=delete
    handler=ExternalIngestionHandler(service(knowledge,owner.vectors,NoReplay()),Objects(),temp_root=tmp_path/'worker')
    queue.publication_reconciler=handler.recover_job
    app=PostgresIngestionApplicationService(queue=CanonicalIngestionQueueAdapter(queue,clock=lambda:106),knowledge=knowledge,object_store=Objects())
    assert app.get_status(new.job_id,tenant_id='t',workspace_id='w',allowed_collection_ids=['c'])['status']=='published'
    assert knowledge.get_document(old.document_id).status=='unpublished'
    assert knowledge.get_publication(new.job_id,**SCOPE)['job_snapshot']['metadata']['retirement_pending'] is False
    assert queue.get_for_workspace(new.job_id,tenant_id='t',workspace_id='w')==winner

@pytest.mark.parametrize('field',['job_id','document_id','publication_attempt','document_attempt'])
@pytest.mark.parametrize('blank',['',' \t\n','\u00a0\u2003'])
def test_F7_postgres_adapter_rejects_invalid_identity_before_any_sql(field,blank):
    from rick_knowledge import PostgresKnowledgeStore
    def no_sql(): raise AssertionError('invalid identity must be rejected before SQL')
    db=PostgresKnowledgeStore(no_sql)
    job=IngestionJob(**SCOPE,job_id='valid',document_id='doc',metadata={'publication_attempt':'a'});kwargs={}
    if field=='publication_attempt': job.metadata[field]=blank
    elif field=='document_attempt': kwargs[field]=blank
    else: setattr(job,field,blank)
    with pytest.raises(ValueError): db.begin_publication(job,**kwargs)

@pytest.mark.parametrize('denial',['cancel','archive','unavailable'])
def test_F4_pending_dedup_intent_obeys_current_fence_without_erasing_prior_winner(knowledge,tmp_path,denial):
    owner=service(knowledge);prior=owner.ingest(source(tmp_path),**SCOPE)
    record=knowledge.get_publication(prior.job_id,**SCOPE)
    job=IngestionJob(**SCOPE,job_id='dedup-pending',document_id=prior.document_id,status='verifying',stage='verifying',metadata={'publication_attempt':'new','deduplicated':True})
    knowledge.begin_publication(job,document_attempt=record['document_attempt'])
    before=deepcopy((knowledge.get_document(prior.document_id),owner.vectors.all_points()))
    if denial=='cancel': knowledge.request_publication_cancel(job)
    if denial=='archive': knowledge.upsert_collection(Collection(**SCOPE,status='archived'))
    if denial=='unavailable':
        def unknown(*a,**kw): raise RuntimeError('catalog unknown')
        knowledge.get_collection=unknown
    result=service(knowledge,owner.vectors,NoReplay()).recover_publication(job.job_id,**SCOPE)
    assert result.status=={'cancel':'cancelled','archive':'failed','unavailable':'verifying'}[denial]
    assert (knowledge.get_document(prior.document_id),owner.vectors.all_points())==before


def test_F4_same_live_owner_unknown_ready_ack_uses_durable_resume(knowledge,tmp_path):
    owner=service(knowledge);real=knowledge.set_document_status;get=knowledge.get_document
    blocked=False
    def unknown(*a,**kw):
        if blocked: raise RuntimeError('authority unavailable')
        return get(*a,**kw)
    def before_commit(doc,status,**kw):
        nonlocal blocked
        if status=='published':
            blocked=True
            raise RuntimeError('precommit acknowledgement uncertain')
        return real(doc,status,**kw)
    knowledge.get_document=unknown;knowledge.set_document_status=before_commit
    job=owner.ingest(source(tmp_path),**SCOPE,job_id='live-ready')
    assert job.status=='verifying' and job.metadata['publication_outcome_unknown']
    before=deepcopy(owner.vectors.all_points())
    blocked=False;knowledge.set_document_status=real;owner.embeddings=NoReplay()
    resumed=owner.reconcile_publication(job.job_id)
    assert resumed.status=='published' and owner.vectors.all_points()==before
    assert knowledge.get_publication(job.job_id,**SCOPE)['outcome']=='committed'


def test_F1_committed_authority_repairs_stale_failed_cache(knowledge,tmp_path):
    owner=service(knowledge);job=owner.ingest(source(tmp_path),**SCOPE)
    before=deepcopy((knowledge.get_document(job.document_id),owner.vectors.all_points()))
    job.status=job.stage='failed';job.error_code='storage_unavailable'
    result=owner.recover_publication(job.job_id,**SCOPE)
    assert result.status=='published' and result.error_code is None
    assert (knowledge.get_document(job.document_id),owner.vectors.all_points())==before


@pytest.mark.parametrize('retry_count',[1,3])
def test_F6_reordered_retry_cannot_reset_or_skip_attempt_accounting(knowledge,retry_count):
    original=IngestionJob(**SCOPE,job_id='count-fence',document_id='doc',attempt=1,metadata={'publication_attempt':'a'})
    knowledge.begin_publication(original);knowledge.resolve_publication(knowledge.get_publication(original.job_id,**SCOPE),'failed')
    replay=deepcopy(original);replay.metadata['publication_attempt']='b';replay.attempt=retry_count
    with pytest.raises(OwnershipLostError): knowledge.begin_publication(replay)
    assert knowledge.get_publication(original.job_id,**SCOPE)['outcome']=='failed'
