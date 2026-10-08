"""Public recovery discriminators for I1-R1..R6; queue SQL uses a memory model.

No provider/network/PG behavior is claimed by these tests. Real PG belongs to
Parent. Crashes are BaseException injections with fresh service/handler owners.
"""
from test_prod02_recovery_rework7 import install_historical_publication
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from external_ingestion import ExternalIngestionHandler, ExternalIngestionError, _recovery_metadata
from postgres_jobs import PostgresJobLeaseError
from rick_ingestion import IngestionService
from rick_ingestion.chunking import ChunkPlan
from rick_ingestion.jobs import IngestionJob
from rick_jobs import JobContinuation, JobFailure, JobResult, JobScope, JobState
from rick_knowledge import InMemoryKnowledgeStore, SQLiteKnowledgeStore, content_checksum
from rick_knowledge.fencing import ATTEMPT_METADATA_KEY, OwnershipLostError
from rick_retrieval import InMemoryVectorStore, DeterministicHashEmbedding
from test_postgres_jobs import make_job, make_queue

SCOPE = dict(tenant_id='t', workspace_id='w', collection_id='c')

class Crash(BaseException):
    pass

class Embedding(DeterministicHashEmbedding):
    def __init__(self):
        super().__init__(); self.batches=[]
    def embed(self, texts):
        self.batches.append(len(texts));return super().embed(texts)

class NoProvider(DeterministicHashEmbedding):
    def embed(self, texts):
        pytest.fail('durable completed output triggered provider replay')

class ManyChunks:
    calls=0
    def chunk(self, **kwargs):
        type(self).calls+=1
        return [ChunkPlan(text=str(i),chunk_index=i,page_start=1,checksum=content_checksum(str(i))) for i in range(257)]

class NoObjects:
    def get(self, *args, **kwargs):pytest.fail('recovery hydrated source')

@pytest.fixture(params=['memory','sqlite'])
def knowledge(request, tmp_path):
    store = InMemoryKnowledgeStore() if request.param=='memory' else SQLiteKnowledgeStore(tmp_path/'knowledge.sqlite')
    yield store
    if hasattr(store,'close'):store.close()

def service(knowledge, vectors=None, embedding=None):
    return IngestionService(knowledge=knowledge,vectors=vectors if vectors is not None else InMemoryVectorStore(),
        embeddings=embedding if embedding is not None else DeterministicHashEmbedding())

def handler(knowledge, vectors, tmp_path, embedding=None):
    return ExternalIngestionHandler(service(knowledge,vectors,embedding),NoObjects(),temp_root=tmp_path/'worker')

def source(tmp_path, text='Recovery facts survive crashes. '):
    path=tmp_path/'source.txt';path.write_text(text*80);return path

def running_queue(max_attempts=2, second=False):
    queue,db=make_queue();job=queue.enqueue(make_job(scope=JobScope(**SCOPE),max_attempts=max_attempts),expected_version=0)
    running,lease=queue.claim(worker_id='before',scope=job.scope,expected_versions={},now=104)[0]
    if second:
        queue.fail(lease,JobFailure('handler_timeout','timeout',True,1,105),now=105,expected_version=running.version)
        db.database_now=106
        running,lease=queue.claim(worker_id='second',scope=job.scope,expected_versions={},now=106)[0]
    return queue,db,running,lease

def checkpoint_crash(knowledge,vectors,path,running=None):
    count=vectors.count_for_document
    vectors.count_for_document=lambda *a,**kw: (_ for _ in ()).throw(Crash('after indexing, before intent'))
    owner=service(knowledge,vectors)
    try:
        with pytest.raises(Crash):
            owner.ingest(path,**SCOPE,job_id=str(running.job_id) if running else 'job',
                _recovery_metadata=_recovery_metadata(running) if running else None)
    finally:vectors.count_for_document=count
    return owner.get_status(str(running.job_id) if running else 'job')

@pytest.mark.parametrize('poison',[False,True])
def test_R1_projection_cannot_authorize_retirement(knowledge,tmp_path,poison):
    vectors=InMemoryVectorStore();path=source(tmp_path)
    old=service(knowledge,vectors).ingest(path,**SCOPE,job_id='old')
    path.write_text('Separate new publication. '*80)
    new=service(knowledge,vectors).ingest(path,**SCOPE,job_id='new')
    before=deepcopy((knowledge.get_document(old.document_id),vectors.all_points(),knowledge.get_publication('new',**SCOPE)))
    stale=deepcopy(new);stale.metadata={'request_id':'diagnostic'}
    if poison:stale.metadata.update(retirement_pending=True,previous_document_id=old.document_id,
        previous_document_attempt=old.metadata['publication_attempt'],index_activation_required=False)
    recovered=service(knowledge,vectors,NoProvider()).recover_publication('new',**SCOPE,snapshot=stale)
    assert recovered.status=='published' and recovered.metadata['request_id']=='diagnostic'
    assert not recovered.metadata.get('retirement_pending')
    # Diagnostics may be persisted; effects and durable control facts do not change.
    assert (knowledge.get_document(old.document_id),vectors.all_points())==before[:2]
    receipt=knowledge.get_publication('new',**SCOPE)
    assert not receipt['job_snapshot']['metadata'].get('retirement_pending')
    assert receipt['job_snapshot']['finished_at']==before[2]['job_snapshot']['finished_at']


def test_R1_durable_retirement_is_recovered(knowledge,tmp_path):
    vectors=InMemoryVectorStore();path=source(tmp_path)
    old=service(knowledge,vectors).ingest(path,**SCOPE,job_id='old')
    path.write_text('Replacement durable directive. '*80)
    delete=vectors.delete_document
    vectors.delete_document=lambda *a,**kw: (_ for _ in ()).throw(RuntimeError('delete unavailable'))
    new=service(knowledge,vectors).reindex(old.document_id,path,**SCOPE,job_id='new')
    assert new.status=='published' and knowledge.get_publication('new',**SCOPE)['job_snapshot']['metadata']['retirement_pending']
    vectors.delete_document=delete
    result=service(knowledge,vectors,NoProvider()).recover_publication('new',**SCOPE)
    assert result.status=='published' and not result.metadata['retirement_pending']
    assert knowledge.get_document(old.document_id).status=='unpublished'
    assert vectors.count_for_document(old.document_id,'c')==0

@pytest.mark.parametrize('max_attempts',[1,2])
def test_R2_expiry_transfers_lease_retaining_partial_batches(knowledge,tmp_path,monkeypatch,max_attempts):
    import rick_ingestion.pipeline as pipeline
    queue,db,running,old_lease=running_queue(max_attempts)
    path=source(tmp_path);vectors=InMemoryVectorStore();embedding=Embedding();parses=[]
    parse=pipeline.execute_parser
    def counted(*a,**kw):parses.append(1);return parse(*a,**kw)
    monkeypatch.setattr(pipeline,'execute_parser',counted)
    ManyChunks.calls=0
    owner=service(knowledge,vectors,embedding);owner.chunker=ManyChunks()
    save=knowledge.save_ingestion_checkpoint
    def crash(job,**kw):
        cp=save(job,**kw)
        if len(cp['artifacts'].get('vectors',[]))==256:raise Crash('completed batch persisted')
        return cp
    knowledge.save_ingestion_checkpoint=crash
    with pytest.raises(Crash):owner.ingest(path,**SCOPE,job_id=str(running.job_id),_recovery_metadata=_recovery_metadata(running))
    knowledge.save_ingestion_checkpoint=save
    before=deepcopy(knowledge.get_ingestion_checkpoint(str(running.job_id),**SCOPE))
    recovered_handler=handler(knowledge,vectors,tmp_path)
    queue.publication_reconciler=recovered_handler.recover_job
    assert isinstance(recovered_handler.recover_job(running),JobContinuation)
    db.database_now=115
    resumed,new_lease=queue.claim(worker_id='after',scope=running.scope,expected_versions={},now=115)[0]
    assert resumed.state is JobState.RUNNING and resumed.attempts==running.attempts
    assert resumed.attempt_count==1 and new_lease.worker_id=='after'
    assert new_lease.token!=old_lease.token and resumed.version==running.version+1
    assert knowledge.get_ingestion_checkpoint(str(running.job_id),**SCOPE)==before
    with pytest.raises(PostgresJobLeaseError):queue.heartbeat(old_lease,now=115,expected_version=resumed.version)
    final_embedding=Embedding();fresh=service(knowledge,vectors,final_embedding);fresh.chunker=ManyChunks()
    result=fresh.ingest(path,**SCOPE,job_id=str(resumed.job_id),_recovery_metadata=_recovery_metadata(resumed))
    assert result.status=='published' and result.attempt==1
    assert result.metadata['publication_attempt']==before['attempt_id']
    assert parses==[1] and ManyChunks.calls==1 and embedding.batches==[256] and final_embedding.batches==[1]
    completed=queue.acknowledge(new_lease,JobResult(document_id=result.document_id,completed_at=result.finished_at),
        now=max(116,result.finished_at),expected_version=resumed.version)
    assert completed.state is JobState.SUCCEEDED and completed.attempt_count==1

@pytest.mark.parametrize('drift',['attempt','scope','start','created','content','owner'])
def test_R2_continuation_and_output_reuse_are_fenced(knowledge,tmp_path,drift):
    queue,db,running,lease=running_queue(1);vectors=InMemoryVectorStore();path=source(tmp_path)
    original=checkpoint_crash(knowledge,vectors,path,running)
    before=deepcopy(knowledge.get_ingestion_checkpoint(str(running.job_id),**SCOPE))
    worker=handler(knowledge,vectors,tmp_path,NoProvider())
    if drift in {'attempt','scope','start','created'}:
        fake=SimpleNamespace(job_id=str(running.job_id),**SCOPE,attempt_count=running.attempt_count,
            created_at=running.created_at,started_at=running.attempts[-1].started_at,payload={})
        if drift=='attempt':fake.attempt_count+=1
        if drift=='scope':fake.tenant_id='foreign'
        if drift=='start':fake.started_at+=1
        if drift=='created':fake.created_at-=1
        if drift in {'attempt','start','created'}:
            with pytest.raises(ExternalIngestionError) as caught:worker.recover_job(fake)
            assert caught.value.code=='recovery_required'
        elif drift=='scope':assert worker.recover_job(fake) is None
    else:
        queue.publication_reconciler=worker.recover_job;db.database_now=115
        resumed,_=queue.claim(worker_id='after',scope=running.scope,expected_versions={},now=115)[0]
        if drift=='content':path.write_text('Different checksum. '*80)
        else:
            doc=knowledge.get_document(original.document_id);doc.metadata[ATTEMPT_METADATA_KEY]='successor';knowledge.upsert_document(doc)
        effects=deepcopy((knowledge.get_document(original.document_id),vectors.all_points()))
        with pytest.raises(OwnershipLostError):service(knowledge,vectors,NoProvider()).ingest(path,**SCOPE,
            job_id=str(resumed.job_id),_recovery_metadata=_recovery_metadata(resumed))
        assert (knowledge.get_document(original.document_id),vectors.all_points())==effects
    assert knowledge.get_ingestion_checkpoint(str(running.job_id),**SCOPE)==before

@pytest.mark.parametrize('old_receipt',[False,True])
def test_R3_current_document_cancel_outranks_old_failed_receipt(knowledge,tmp_path,old_receipt):
    queue,db,running,lease=running_queue(second=old_receipt);vectors=InMemoryVectorStore()
    old=None
    if old_receipt:
        first=IngestionJob(**SCOPE,job_id=str(running.job_id),document_id='older',attempt=1,
            created_at=running.created_at,started_at=104,finished_at=105,
            metadata={'publication_attempt':'old','queue_attempt':1})
        install_historical_publication(knowledge, first, 'failed')
        old=deepcopy(knowledge.get_publication(first.job_id,**SCOPE))
    owner=checkpoint_crash(knowledge,vectors,source(tmp_path),running)
    assert owner.document_id is not None
    worker=handler(knowledge,vectors,tmp_path,NoProvider())
    worker.request_publication_cancel(running)
    for _ in range(3):
        with pytest.raises(ExternalIngestionError) as caught:handler(knowledge,vectors,tmp_path,NoProvider()).recover_job(running)
        assert caught.value.code=='cancelled'
    cp=knowledge.get_ingestion_checkpoint(str(running.job_id),**SCOPE)
    assert cp['state']=='cancelled' and cp['document_id']==owner.document_id
    assert vectors.all_points()==[] and knowledge.get_document(owner.document_id).status!='published'
    assert knowledge.get_publication(str(running.job_id),**SCOPE)==old

@pytest.mark.parametrize('mutation',['correct','id','text','vector','zero','chunk','successor','stale','foreign'])
def test_R4_pending_requires_exact_durable_points(knowledge,tmp_path,mutation):
    vectors=InMemoryVectorStore();path=source(tmp_path);owner=service(knowledge,vectors)
    set_status=knowledge.set_document_status
    def crash(doc,status,**kw):
        if status=='published':raise Crash('intent persisted, commit not executed')
        return set_status(doc,status,**kw)
    knowledge.set_document_status=crash
    with pytest.raises(Crash):owner.ingest(path,**SCOPE,job_id='pending')
    knowledge.set_document_status=set_status
    job=owner.get_status('pending');receipt=deepcopy(knowledge.get_publication('pending',**SCOPE))
    points=deepcopy(vectors.all_points());assert points
    if mutation in {'id','text','vector','zero'}:
        vectors.delete_document(job.document_id,'c')
        if mutation!='zero':
            if mutation=='id':points[0]['point_id']='wrong-id'
            if mutation=='text':points[0]['payload']['text']='wrong text'
            if mutation=='vector':points[0]['vector']=[0.0]*len(points[0]['vector'])
            vectors.upsert_points(points)
    if mutation=='chunk':
        chunks=knowledge.get_chunks(job.document_id);chunks[0].text='changed persisted text';knowledge.replace_document_chunks(job.document_id,chunks)
    if mutation=='successor':
        doc=knowledge.get_document(job.document_id);doc.metadata[ATTEMPT_METADATA_KEY]='successor';knowledge.upsert_document(doc)
    projection=deepcopy(job)
    if mutation=='stale':projection.metadata['publication_attempt']='stale'
    if mutation=='foreign':projection.tenant_id='foreign'
    effects=deepcopy((knowledge.get_document(job.document_id),vectors.all_points()))
    recovered=service(knowledge,vectors,NoProvider())
    if mutation in {'stale','foreign'}:
        with pytest.raises(OwnershipLostError):recovered.recover_publication('pending',**SCOPE,snapshot=projection)
    else:
        result=recovered.recover_publication('pending',**SCOPE,snapshot=projection)
        assert result.status==('published' if mutation=='correct' else 'failed' if mutation=='successor' else 'verifying')
    if mutation!='correct':assert (knowledge.get_document(job.document_id),vectors.all_points())==effects
    current=knowledge.get_publication('pending',**SCOPE)
    assert current['outcome']==('committed' if mutation=='correct' else 'failed' if mutation=='successor' else 'pending')
    if mutation not in {'correct','successor'}:assert current==receipt

@pytest.mark.parametrize('committed',[True,False])
def test_R5_receipt_commit_repairs_stale_callback_counter(knowledge,tmp_path,committed):
    vectors=InMemoryVectorStore();path=source(tmp_path)
    job=service(knowledge,vectors).ingest(path,**SCOPE,job_id='callback') if committed else checkpoint_crash(knowledge,vectors,path)
    before=deepcopy(knowledge.get_publication(job.job_id,**SCOPE))
    fake=SimpleNamespace(job_id=job.job_id,**SCOPE,attempt_count=9,created_at=job.created_at,
        started_at=job.started_at,payload={})
    worker=handler(knowledge,vectors,tmp_path,NoProvider())
    if committed:
        result=worker.recover_job(fake)
        assert isinstance(result,JobResult) and result.document_id==job.document_id and result.completed_at==job.finished_at
    else:
        with pytest.raises(ExternalIngestionError) as caught:worker.recover_job(fake)
        assert caught.value.code=='recovery_required'
    assert knowledge.get_publication(job.job_id,**SCOPE)==before

@pytest.mark.parametrize('poll',[115,200])
def test_R6_poll_clock_does_not_change_attempt_finish(tmp_path,poll):
    queue,db,running,lease=running_queue(1)
    from rick_jobs import JobPublicationResult, JobPublicationFacts
    authority=JobPublicationResult(document_id='winner',completed_at=110,
        facts=JobPublicationFacts(job_id=running.job_id,scope=running.scope,
            attempt=running.attempt_count,created_at=running.created_at,
            started_at=running.attempts[-1].started_at,
            attempt_id=_recovery_metadata(running)['publication_attempt']))
    queue.publication_reconciler=lambda _:authority
    result=queue.recover_publication(running.job_id,**SCOPE,now=poll)
    assert result.state is JobState.SUCCEEDED and result.result.completed_at==110
    assert result.attempts[-1].finished_at==110 and result.attempts[-1].started_at==104
    assert result.updated_at==poll
    again=queue.recover_publication(running.job_id,**SCOPE,now=poll+20)
    assert again==result

@pytest.mark.parametrize('finish',[103,116])
def test_R6_completion_outside_attempt_lifetime_is_rejected(finish):
    _,_,running,_=running_queue(1)
    with pytest.raises(ValueError):
        running.finish_attempt(JobState.SUCCEEDED,now=115,
            result=JobResult(document_id='winner',completed_at=finish),finished_at=finish)

@pytest.mark.parametrize('wrong',['number','scope','start','created'])
def test_R2_queue_rejects_counterfeit_continuation_facts(knowledge,tmp_path,wrong):
    queue,db,running,lease=running_queue(1);vectors=InMemoryVectorStore()
    checkpoint_crash(knowledge,vectors,source(tmp_path),running)
    cp=handler(knowledge,vectors,tmp_path).recover_job(running)
    changes={'number':dict(attempt=2),'scope':dict(scope=JobScope('foreign','w','c')),
        'start':dict(started_at=105),'created':dict(created_at=99)}
    queue.publication_reconciler=lambda _:replace(cp,**changes[wrong])
    db.database_now=115
    assert queue.claim(worker_id='new',scope=running.scope,expected_versions={},now=115)==()
    assert db.jobs[str(running.job_id)]['contract_state']=='RUNNING'
    assert db.jobs[str(running.job_id)]['version']==running.version
    assert db.jobs[str(running.job_id)]['attempts']==1


def test_R2_returning_former_writer_cannot_truncate_completed_outputs(knowledge,tmp_path):
    vectors=InMemoryVectorStore();owner=checkpoint_crash(knowledge,vectors,source(tmp_path))
    before=deepcopy(knowledge.get_ingestion_checkpoint(owner.job_id,**SCOPE))
    for artifacts in ({},dict(before['artifacts'],vectors=[]),dict(before['artifacts'],parsed={'text':'changed','pages':[]})):
        with pytest.raises(OwnershipLostError):knowledge.save_ingestion_checkpoint(owner,
            fingerprint=before['fingerprint'],artifacts=artifacts)
        assert knowledge.get_ingestion_checkpoint(owner.job_id,**SCOPE)==before

@pytest.mark.parametrize('moment',['before-index','partial-index','pre-intent'])
def test_R2_complete_effect_manifest_resumes_after_expiry(knowledge,tmp_path,moment):
    queue,db,running,lease=running_queue(1);vectors=InMemoryVectorStore();path=source(tmp_path)
    owner=service(knowledge,vectors);upsert=vectors.upsert_points;count=vectors.count_for_document
    def interrupted(points):
        if moment=='partial-index':upsert(points[:1])
        raise Crash('manifest persisted before index acknowledgement')
    if moment=='pre-intent':vectors.count_for_document=lambda *a,**kw: (_ for _ in ()).throw(Crash('pre-intent'))
    else:vectors.upsert_points=interrupted
    with pytest.raises(Crash):owner.ingest(path,**SCOPE,job_id=str(running.job_id),_recovery_metadata=_recovery_metadata(running))
    vectors.upsert_points=upsert;vectors.count_for_document=count
    checkpoint=deepcopy(knowledge.get_ingestion_checkpoint(str(running.job_id),**SCOPE))
    assert checkpoint['artifacts']['point_manifest']
    queue.publication_reconciler=handler(knowledge,vectors,tmp_path,NoProvider()).recover_job;db.database_now=115
    resumed,_=queue.claim(worker_id='new',scope=running.scope,expected_versions={},now=115)[0]
    result=service(knowledge,vectors,NoProvider()).ingest(path,**SCOPE,job_id=str(resumed.job_id),_recovery_metadata=_recovery_metadata(resumed))
    assert result.status=='published' and result.attempt==1
    assert knowledge.get_publication(str(resumed.job_id),**SCOPE)['outcome']=='committed'

@pytest.mark.parametrize('sparse_wrong',[False,True])
def test_R4_normalized_effect_vectors_are_bound_including_sparse(knowledge,tmp_path,sparse_wrong):
    class NormalizedVectors(InMemoryVectorStore):
        def plan_upsert_batches(self, points):
            normalized=deepcopy(points)
            for p in normalized:
                p['payload']['index_version']='normalized-test-v1'
                p['sparse_vector']={'indices':[3], 'values':[0.1]}
            return (normalized,)
    vectors=NormalizedVectors();owner=service(knowledge,vectors);set_status=knowledge.set_document_status
    def crash(doc,status,**kw):
        if status=='published':raise Crash('after intent')
        return set_status(doc,status,**kw)
    knowledge.set_document_status=crash
    with pytest.raises(Crash):owner.ingest(source(tmp_path),**SCOPE,job_id='normalized')
    knowledge.set_document_status=set_status
    points=deepcopy(vectors.all_points())
    if sparse_wrong:
        points[0]['sparse_vector']['values']=[0.2]
        vectors.upsert_points(points)
    result=service(knowledge,vectors,NoProvider()).recover_publication('normalized',**SCOPE)
    assert result.status==('verifying' if sparse_wrong else 'published')
    assert knowledge.get_publication('normalized',**SCOPE)['outcome']==('pending' if sparse_wrong else 'committed')


def test_R4_legacy_cardinality_only_intent_cannot_commit(knowledge,tmp_path):
    vectors=InMemoryVectorStore();job=checkpoint_crash(knowledge,vectors,source(tmp_path))
    knowledge.begin_publication(job,ready_count=len(knowledge.get_chunks(job.document_id)))
    # Remove the new effect authorization only from the pre-intent fixture via
    # its retained pre-manifest copy. Real store writes cannot truncate it.
    current=knowledge.get_ingestion_checkpoint
    def legacy(*a,**kw):
        cp=current(*a,**kw)
        if cp:cp['artifacts'].pop('point_manifest',None)
        return cp
    knowledge.get_ingestion_checkpoint=legacy
    result=service(knowledge,vectors,NoProvider()).recover_publication(job.job_id,**SCOPE)
    assert result.status=='verifying'
    assert knowledge.get_publication(job.job_id,**SCOPE)['outcome']=='pending'

@pytest.mark.parametrize('moment',['batch','index','intent'])
def test_R2_external_owner_lease_loss_preserves_work_for_expiry(knowledge,tmp_path,moment):
    import hashlib
    data=b'External execution durable recovery. '*80
    class Objects:
        calls=0
        def get(self,*a,**kw):self.calls+=1;return data
    objects=Objects();queue,db=make_queue()
    job=queue.enqueue(make_job(scope=JobScope(**SCOPE),max_attempts=1,payload={
        'object_key':'uploads/source','object_source_id':'job-1','filename_ref':'c291cmNlLnR4dA==',
        'checksum':'sha256:'+hashlib.sha256(data).hexdigest()}),expected_version=0)
    running,lease=queue.claim(worker_id='before',scope=job.scope,expected_versions={},now=104)[0]
    vectors=InMemoryVectorStore();embedding=Embedding();owner=service(knowledge,vectors,embedding)
    lost=[False];save=knowledge.save_ingestion_checkpoint;upsert=vectors.upsert_points;begin=knowledge.begin_publication
    def lose_after_save(job,**kw):
        cp=save(job,**kw)
        if moment=='batch' and cp['artifacts'].get('vectors'):lost[0]=True
        return cp
    def lose_after_index(points):
        result=upsert(points)
        if moment=='index':lost[0]=True
        return result
    def lose_after_intent(job,**kw):
        begin(job,**kw)
        if moment=='intent':lost[0]=True;raise ExternalIngestionError('lock_unavailable')
    knowledge.save_ingestion_checkpoint=lose_after_save;vectors.upsert_points=lose_after_index;knowledge.begin_publication=lose_after_intent
    worker=ExternalIngestionHandler(owner,objects,temp_root=tmp_path/'external-before')
    with pytest.raises(OwnershipLostError):worker(running,lease_lost_check=lambda:lost[0])
    knowledge.save_ingestion_checkpoint=save;vectors.upsert_points=upsert;knowledge.begin_publication=begin
    checkpoint=deepcopy(knowledge.get_ingestion_checkpoint(str(running.job_id),**SCOPE))
    assert checkpoint['state']=='active' and checkpoint['artifacts']['vectors'] and not checkpoint['cancel_requested']
    assert list((tmp_path/'external-before').iterdir())==[]
    after=ExternalIngestionHandler(service(knowledge,vectors,NoProvider()),objects,temp_root=tmp_path/'external-after')
    queue.publication_reconciler=after.recover_job;db.database_now=115
    claimed=queue.claim(worker_id='after',scope=running.scope,expected_versions={},now=115)
    if moment=='intent':
        assert claimed==()
        final=queue.get_for_workspace(job.job_id,tenant_id='t',workspace_id='w')
        assert final.state is JobState.SUCCEEDED and final.attempt_count==1
    else:
        resumed,_=claimed[0]
        result=after(resumed,lease_lost_check=lambda:False)
        assert result.status=='published' and result.attempt==1
        assert result.metadata['publication_attempt']==checkpoint['attempt_id']
    assert embedding.batches and objects.calls==(1 if moment=='intent' else 2)
    assert knowledge.get_publication(str(running.job_id),**SCOPE)['outcome']=='committed'
