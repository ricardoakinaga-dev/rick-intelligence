"""Recovery boundary regressions; simulated queue SQL is not real PG evidence."""
import ast
from test_prod02_recovery_rework7 import install_historical_publication
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from canonical_queue import CanonicalIngestionQueueAdapter
from external_ingestion import ExternalIngestionHandler, ExternalIngestionError, _recovery_metadata
from rick_ingestion import IngestionService
from rick_ingestion.jobs import IngestionJob
from rick_jobs import JobState, JobFailure, JobResult
from rick_knowledge import InMemoryKnowledgeStore, SQLiteKnowledgeStore
from rick_knowledge.fencing import ATTEMPT_METADATA_KEY, OwnershipLostError
from rick_retrieval import InMemoryVectorStore, SQLiteVectorStore, DeterministicHashEmbedding
from services.postgres_ingestion import PostgresIngestionApplicationService
from test_postgres_jobs import make_job, make_queue

SCOPE = dict(tenant_id='t', workspace_id='w', collection_id='c')


class Crash(BaseException):
    pass


class CountingEmbedding(DeterministicHashEmbedding):
    calls = 0
    def embed(self, texts):
        self.calls += 1
        return super().embed(texts)


class NoReplay(DeterministicHashEmbedding):
    def embed(self, texts):
        pytest.fail('completed durable embedding batch replayed')


def svc(knowledge, vectors=None, embeddings=None):
    return IngestionService(knowledge=knowledge, vectors=vectors or InMemoryVectorStore(),
        embeddings=embeddings or DeterministicHashEmbedding())


@pytest.fixture(params=['memory', 'sqlite'])
def knowledge(request, tmp_path):
    store = InMemoryKnowledgeStore() if request.param == 'memory' else SQLiteKnowledgeStore(tmp_path/'knowledge.sqlite')
    yield store
    if hasattr(store, 'close'):
        store.close()


def source(tmp_path):
    path = tmp_path/'source.txt'
    path.write_text('Durable scoped recovery before publication intent. '*80)
    return path


def die_before_intent(knowledge, vectors, embedding, path, **kwargs):
    service = svc(knowledge, vectors, embedding)
    original = vectors.count_for_document
    def die(*a, **kw):
        raise Crash('after vectors before publication intent')
    vectors.count_for_document = die
    with pytest.raises(Crash):
        service.ingest(path, **SCOPE, job_id='resume', **kwargs)
    vectors.count_for_document = original
    assert knowledge.get_publication('resume', **SCOPE) is None
    return service.get_status('resume')


def test_F1_pre_intent_completed_parse_embed_survive_reconstruction(knowledge, tmp_path, monkeypatch):
    import rick_ingestion.pipeline as pipeline
    real_parse = pipeline.execute_parser
    parses = []
    def parse(*a, **kw):
        parses.append(1)
        return real_parse(*a, **kw)
    monkeypatch.setattr(pipeline, 'execute_parser', parse)
    vector = InMemoryVectorStore(); embedding = CountingEmbedding(); path = source(tmp_path)
    owner = die_before_intent(knowledge, vector, embedding, path,
        _recovery_metadata={'queue_attempt': 2, 'queue_created_at': 1., 'queue_started_at': 4.})
    before = knowledge.get_ingestion_checkpoint('resume', **SCOPE)
    assert before['attempt_id'] == owner.metadata['publication_attempt']
    assert before['document_id'] == owner.document_id
    assert before['job_snapshot']['attempt'] == 2
    assert len(before['artifacts']['vectors']) == len(before['artifacts']['plans']) > 0
    result = svc(knowledge, vector, NoReplay()).ingest(path, **SCOPE, job_id='resume')
    assert result.status == 'published' and len(parses) == embedding.calls == 1
    assert result.attempt == 2 and result.started_at == 4.
    assert result.metadata['publication_attempt'] == owner.metadata['publication_attempt']
    receipt = knowledge.get_publication('resume', **SCOPE)
    assert receipt['job_snapshot']['finished_at'] == result.finished_at
    assert knowledge.get_ingestion_checkpoint('resume', **SCOPE)['artifacts'] == {}
    assert svc(knowledge, vector, NoReplay()).ingest(path, **SCOPE, job_id='resume').finished_at == result.finished_at


def test_F1_disk_handles_reopen_pre_intent_without_reparse(tmp_path, monkeypatch):
    import rick_ingestion.pipeline as pipeline
    kp=tmp_path/'disk.sqlite';vp=tmp_path/'vectors.sqlite';path=source(tmp_path)
    knowledge=SQLiteKnowledgeStore(kp);vectors=SQLiteVectorStore(vp);embedding=CountingEmbedding()
    owner=die_before_intent(knowledge,vectors,embedding,path)
    knowledge.close();vectors.close()
    knowledge=SQLiteKnowledgeStore(kp);vectors=SQLiteVectorStore(vp)
    monkeypatch.setattr(pipeline,'execute_parser',lambda *a,**kw: pytest.fail('disk checkpoint reparsed'))
    try:
        result=svc(knowledge,vectors,NoReplay()).ingest(path,**SCOPE,job_id='resume')
        assert result.status=='published' and result.attempt==1
        assert result.metadata['publication_attempt']==owner.metadata['publication_attempt']
        assert embedding.calls==1
    finally:
        knowledge.close();vectors.close()


@pytest.mark.parametrize('boundary', ['parsed', 'plans', 'first-batch'])
def test_F1_durable_individual_phases_and_batches_are_reused(knowledge,tmp_path,monkeypatch,boundary):
    import rick_ingestion.pipeline as pipeline
    from rick_ingestion.chunking import ChunkPlan
    from rick_knowledge import content_checksum
    real_parse=pipeline.execute_parser;parses=[]
    def parse(*a,**kw):
        parses.append(1);return real_parse(*a,**kw)
    monkeypatch.setattr(pipeline,'execute_parser',parse)
    class ManyChunks:
        def chunk(self,**kwargs):
            return [ChunkPlan(text=str(i),chunk_index=i,page_start=1,checksum=content_checksum(str(i))) for i in range(300)]
    original=knowledge.save_ingestion_checkpoint
    def crash(job,**kw):
        saved=original(job,**kw);art=saved['artifacts']
        if (boundary=='parsed' and 'parsed' in art or boundary=='plans' and 'plans' in art or
                boundary=='first-batch' and len(art.get('vectors',[]))==256):
            raise Crash('durable phase write before next phase')
        return saved
    knowledge.save_ingestion_checkpoint=crash
    embedding=CountingEmbedding();path=source(tmp_path);vectors=InMemoryVectorStore()
    service=svc(knowledge,vectors,embedding);service.chunker=ManyChunks()
    with pytest.raises(Crash): service.ingest(path,**SCOPE,job_id='phases')
    knowledge.save_ingestion_checkpoint=original
    class Remainder(CountingEmbedding):
        def embed(self,texts):
            if boundary=='first-batch': assert texts == [str(i) for i in range(256,300)]
            return super().embed(texts)
    remainder=Remainder();service=svc(knowledge,vectors,remainder);service.chunker=ManyChunks()
    result=service.ingest(path,**SCOPE,job_id='phases')
    assert result.status=='published' and result.attempt==1
    assert len(parses)==1
    assert embedding.calls+remainder.calls==2


@pytest.mark.parametrize('change',['content','model','document-owner'])
def test_F1_counts_cannot_authorize_checkpoint_reuse(knowledge,tmp_path,change):
    vectors=InMemoryVectorStore();path=source(tmp_path);embedding=CountingEmbedding()
    owner=die_before_intent(knowledge,vectors,embedding,path)
    checkpoint=deepcopy(knowledge.get_ingestion_checkpoint('resume',**SCOPE))
    if change=='content': path.write_text('Other source content. '*100)
    provider=NoReplay()
    if change=='model': provider.model='another-model'
    if change=='document-owner':
        doc=knowledge.get_document(owner.document_id)
        doc.metadata[ATTEMPT_METADATA_KEY]='successor'
        knowledge.upsert_document(doc)
    effects=deepcopy((knowledge.get_document(owner.document_id),vectors.all_points()))
    with pytest.raises(OwnershipLostError): svc(knowledge,vectors,provider).ingest(path,**SCOPE,job_id='resume')
    assert knowledge.get_ingestion_checkpoint('resume',**SCOPE)==checkpoint
    assert (knowledge.get_document(owner.document_id),vectors.all_points())==effects
    assert knowledge.get_publication('resume',**SCOPE) is None


def test_F1_other_scope_has_no_checkpoint_authority(knowledge,tmp_path):
    vectors=InMemoryVectorStore();path=source(tmp_path);first=CountingEmbedding()
    owner=die_before_intent(knowledge,vectors,first,path)
    checkpoint=deepcopy(knowledge.get_ingestion_checkpoint('resume',**SCOPE))
    second=CountingEmbedding()
    foreign=svc(knowledge,vectors,second).ingest(path,tenant_id='foreign',workspace_id='w',collection_id='c',job_id='resume')
    assert foreign.status=='published' and second.calls>0
    assert foreign.document_id!=owner.document_id
    assert knowledge.get_ingestion_checkpoint('resume',**SCOPE)==checkpoint


def receipt_owner(store, outcome='committed', attempt=2):
    job=IngestionJob(**SCOPE,job_id='authority',document_id='document',attempt=attempt,
        created_at=1.,started_at=4.,finished_at=9. if outcome=='committed' else None,
        metadata={'publication_attempt':'owner','queue_attempt':attempt})
    if outcome == 'pending':
        store.begin_publication(job)
    else:
        install_historical_publication(store, job, outcome)
    return job


@pytest.mark.parametrize('projection',['caller','cache'])
def test_F2_committed_receipt_repairs_stale_attempt_tokens(knowledge,projection):
    job=receipt_owner(knowledge);before=deepcopy(knowledge.get_publication(job.job_id,**SCOPE))
    stale=deepcopy(job);stale.metadata['publication_attempt']='obsolete';stale.attempt=1
    stale.created_at,stale.started_at,stale.finished_at=100.,200.,300.
    service=svc(knowledge,embeddings=NoReplay())
    if projection=='cache': service._jobs[job.job_id]=stale
    result=service.recover_publication(job.job_id,**SCOPE,snapshot=stale if projection=='caller' else None)
    assert result.status=='published'
    assert (result.attempt,result.created_at,result.started_at,result.finished_at)==(2,1.,4.,9.)
    assert result.metadata['publication_attempt']=='owner'
    assert knowledge.get_publication(job.job_id,**SCOPE)==before


@pytest.mark.parametrize('projection',['caller','cache'])
@pytest.mark.parametrize('change',['token','document','scope'])
def test_F2_pending_attempt_and_scope_fences_are_retained(knowledge,projection,change):
    job=receipt_owner(knowledge,'pending');before=deepcopy(knowledge.get_publication(job.job_id,**SCOPE))
    stale=deepcopy(job)
    if change=='token': stale.metadata['publication_attempt']='obsolete'
    if change=='document': stale.document_id='other-document'
    if change=='scope': stale.tenant_id='foreign'
    service=svc(knowledge,embeddings=NoReplay())
    if projection=='cache': service._jobs[job.job_id]=stale
    with pytest.raises(OwnershipLostError):
        service.recover_publication(job.job_id,**SCOPE,snapshot=stale if projection=='caller' else None)
    assert knowledge.get_publication(job.job_id,**SCOPE)==before


def running_queue(attempt2=False):
    queue,connection=make_queue();queued=queue.enqueue(make_job(max_attempts=2),expected_version=0)
    running,lease=queue.claim(worker_id='first',scope=queued.scope,expected_versions={},now=104)[0]
    if attempt2:
        queue.fail(lease,JobFailure(code='handler_timeout',message='timeout',retryable=True,attempt=1,occurred_at=105),now=105,expected_version=running.version)
        connection.database_now=106
        running,lease=queue.claim(worker_id='second',scope=queued.scope,expected_versions={},now=106)[0]
    return queue,connection,running,lease


def worker(knowledge,tmp_path):
    class Objects:
        def get(self,*a,**kw): pytest.fail('public cancellation must not hydrate')
        def put(self,*a,**kw): pytest.fail('public cancellation must not write source')
    return ExternalIngestionHandler(svc(knowledge),Objects(),temp_root=tmp_path/'worker')


@pytest.mark.parametrize('attempt2',[False,True])
def test_F3_public_running_cancel_is_durable_before_intent(knowledge,tmp_path,attempt2):
    queue,connection,running,lease=running_queue(attempt2)
    handler=worker(knowledge,tmp_path);queue.publication_reconciler=handler.recover_job
    scope={k:getattr(running,k) for k in SCOPE}
    result=queue.cancel(running.job_id,**scope,now=107,expected_version=running.version)
    assert result.state is JobState.CANCELLED
    saved=knowledge.get_ingestion_checkpoint(str(running.job_id),**scope)
    expected=_recovery_metadata(CanonicalIngestionQueueAdapter._record(running))
    assert saved['cancel_requested'] is True
    assert saved['attempt_id']==expected['publication_attempt']
    assert saved['job_snapshot']['attempt']==running.attempt_count
    assert saved['job_snapshot']['started_at']==running.attempts[-1].started_at
    # Reconstruct service with retained durable store; cancellation reaches
    # actual ingestion before provider/effect work and no intent is fabricated.
    result=svc(knowledge,embeddings=NoReplay()).ingest(source(tmp_path),**scope,
        job_id=str(running.job_id),_recovery_metadata=expected)
    assert result.status=='cancelled' and result.attempt==running.attempt_count
    assert knowledge.get_publication(str(running.job_id),**scope) is None
    assert knowledge.get_ingestion_checkpoint(str(running.job_id),**scope)['state']=='cancelled'
    assert connection.jobs[str(running.job_id)]['attempts']==running.attempt_count
    assert result.started_at==running.attempts[-1].started_at


def test_F3_actual_attempt2_cancellation_never_marks_old_receipt(knowledge,tmp_path):
    queue,connection,running,lease=running_queue(True);assert running.attempt_count==2
    scope={k:getattr(running,k) for k in SCOPE};metadata=_recovery_metadata(running)
    old=IngestionJob(**scope,job_id=str(running.job_id),document_id='old-document',attempt=1,
        created_at=running.created_at,started_at=running.attempts[0].started_at,
        metadata={'publication_attempt':'old','queue_attempt':1})
    knowledge.begin_publication(old);before=deepcopy(knowledge.get_publication(old.job_id,**scope))
    handler=worker(knowledge,tmp_path);queue.publication_reconciler=handler.recover_job
    cancelled=queue.cancel(running.job_id,**scope,now=107,expected_version=running.version)
    assert cancelled.state is JobState.RUNNING
    assert knowledge.get_publication(old.job_id,**scope)==before
    saved=knowledge.get_ingestion_checkpoint(old.job_id,**scope)
    assert saved['attempt_id']==metadata['publication_attempt'] and saved['job_snapshot']['attempt']==2
    assert saved['cancel_requested']
    # Once the parent owner resolves the previous attempt, the current attempt
    # remains cancelled. There is no transfer of cancellation to old effects.
    knowledge.resolve_publication(before,'failed')
    result=svc(knowledge,embeddings=NoReplay()).ingest(source(tmp_path),**scope,
        job_id=old.job_id,_recovery_metadata=metadata)
    assert result.status=='cancelled' and result.attempt==2
    assert not knowledge.get_publication(old.job_id,**scope)['cancel_requested']


def test_F3_matching_committed_receipt_wins_public_cancel(knowledge,tmp_path):
    queue,connection,running,lease=running_queue();scope={k:getattr(running,k) for k in SCOPE}
    result=svc(knowledge).ingest(source(tmp_path),**scope,job_id=str(running.job_id),_recovery_metadata=_recovery_metadata(running))
    before=deepcopy(knowledge.get_publication(str(running.job_id),**scope))
    handler=worker(knowledge,tmp_path);queue.publication_reconciler=handler.recover_job
    cancelled=queue.cancel(running.job_id,**scope,now=105,expected_version=running.version)
    assert cancelled.state is JobState.SUCCEEDED
    assert cancelled.result.completed_at==pytest.approx(result.finished_at,abs=1e-6,rel=0)
    assert knowledge.get_publication(str(running.job_id),**scope)==before
    assert not before['cancel_requested']


def test_F4_exact_callback_and_converter_preserve_attempt_start_finish(tmp_path,monkeypatch):
    # Execute exact production bodies with local collaborators; this is not a
    # claim that full external composition or production construction ran.
    path=Path(__file__).resolve().parents[2]/'api/src/services/external_composition.py'
    tree=ast.parse(path.read_text())
    callback=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='canonical_ingestion_handler')
    converter=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_canonical_job_result')
    from collections.abc import Mapping
    env={'SimpleNamespace':SimpleNamespace,'JobResult':JobResult,'Mapping':Mapping,'time':SimpleNamespace(time=lambda:200.)}
    exec(compile(ast.Module(body=[converter,callback],type_ignores=[]),str(path),'exec'),env)
    import rick_ingestion.jobs as jobs
    monkeypatch.setattr(jobs.time,'time',lambda:100.)
    knowledge=InMemoryKnowledgeStore();service=svc(knowledge);file=source(tmp_path);captured=[]
    def handler(record,**kw):
        captured.append(_recovery_metadata(record))
        return service.ingest(file,**SCOPE,job_id=record.job_id,_recovery_metadata=_recovery_metadata(record))
    env['handler']=handler
    job=SimpleNamespace(job_id='callback',**SCOPE,attempt_count=2,
        attempts=(SimpleNamespace(started_at=2.),SimpleNamespace(started_at=4.)),created_at=1.,updated_at=90.,payload={})
    result=env['canonical_ingestion_handler'](job,SimpleNamespace(token='lease'),cancelled=lambda:False)
    assert captured[0]['queue_started_at']==4.
    receipt=knowledge.get_publication('callback',**SCOPE)
    assert receipt['job_snapshot']['attempt']==2 and receipt['job_snapshot']['started_at']==4.
    assert receipt['job_snapshot']['finished_at']==result.completed_at==100.
    assert env['_canonical_job_result'](job,{'status':'published','document_id':'doc','finished_at':8.}).completed_at==8.
    with pytest.raises(RuntimeError): env['_canonical_job_result'](job,{'status':'published','document_id':'doc'})


def test_F3_pre_intent_crash_cancel_recovery_cleans_owned_effects_without_source(knowledge,tmp_path):
    path=source(tmp_path);vectors=InMemoryVectorStore();owner=die_before_intent(knowledge,vectors,CountingEmbedding(),path)
    before=knowledge.get_ingestion_checkpoint(owner.job_id,**SCOPE)
    knowledge.request_ingestion_cancel(owner);path.unlink()
    result=svc(knowledge,vectors,NoReplay()).recover_publication(owner.job_id,**SCOPE)
    assert result.status=='cancelled' and result.attempt==owner.attempt
    assert vectors.all_points()==[]
    assert knowledge.get_document(owner.document_id).status!='published'
    assert knowledge.get_ingestion_checkpoint(owner.job_id,**SCOPE)['state']=='cancelled'
    assert knowledge.get_publication(owner.job_id,**SCOPE) is None
    assert svc(knowledge,vectors,NoReplay()).recover_publication(owner.job_id,**SCOPE).finished_at==result.finished_at
    assert result.started_at==before['job_snapshot']['started_at']


@pytest.mark.parametrize('duplicate',[False,True])
def test_F3_cancel_between_gate_check_and_intent_fences_commit(knowledge,tmp_path,duplicate):
    path=source(tmp_path);vectors=InMemoryVectorStore()
    if duplicate:
        assert svc(knowledge,vectors).ingest(path,**SCOPE,job_id='prior').status=='published'
    original=knowledge.begin_publication
    def race(job,**kw):
        knowledge.request_ingestion_cancel(job)
        original(job,**kw)
    knowledge.begin_publication=race
    result=svc(knowledge,vectors).ingest(path,**SCOPE,job_id='race')
    assert result.status=='cancelled'
    receipt=knowledge.get_publication('race',**SCOPE)
    assert receipt['outcome']=='cancelled' and receipt['cancel_requested']
    if duplicate:
        assert knowledge.get_document(result.document_id).status=='published'
        assert vectors.all_points()
    else:
        assert knowledge.get_document(result.document_id).status!='published'
        assert vectors.all_points()==[]


def test_F3_public_view_uses_current_checkpoint_not_older_receipt(knowledge,tmp_path):
    queue,connection,running,lease=running_queue(True);scope={k:getattr(running,k) for k in SCOPE}
    old=IngestionJob(**scope,job_id=str(running.job_id),document_id='old',attempt=1,
        created_at=running.created_at,started_at=running.attempts[0].started_at,
        metadata={'publication_attempt':'old','queue_attempt':1})
    knowledge.begin_publication(old)
    handler=worker(knowledge,tmp_path);queue.publication_reconciler=handler.recover_job
    app=PostgresIngestionApplicationService(queue=CanonicalIngestionQueueAdapter(queue,clock=lambda:107),object_store=handler.object_store,knowledge=knowledge)
    public=app.cancel(old.job_id,tenant_id=scope['tenant_id'],workspace_id=scope['workspace_id'],allowed_collection_ids=[scope['collection_id']])
    assert public['status']=='verifying' and public['cancel_requested'] and public['attempt']==2
    assert public['started_at']==running.attempts[-1].started_at
    assert not knowledge.get_publication(old.job_id,**scope)['cancel_requested']


def test_F1_new_canonical_attempt_does_not_reuse_previous_attempt_batches(knowledge,tmp_path):
    path=source(tmp_path);vectors=InMemoryVectorStore();first=CountingEmbedding()
    owner=die_before_intent(knowledge,vectors,first,path,_recovery_metadata={
        'publication_attempt':'first','queue_attempt':1,'queue_created_at':1.,'queue_started_at':2.})
    old=deepcopy(knowledge.get_ingestion_checkpoint(owner.job_id,**SCOPE))
    second=CountingEmbedding()
    result=svc(knowledge,vectors,second).ingest(path,**SCOPE,job_id=owner.job_id,
        _recovery_metadata={'publication_attempt':'second','queue_attempt':2,'queue_created_at':1.,'queue_started_at':4.})
    assert result.status=='published' and result.attempt==2 and result.started_at==4.
    assert first.calls==second.calls==1
    assert result.metadata['publication_attempt']=='second'
    # A stale provider completion cannot overwrite the new attempt checkpoint.
    before=deepcopy(knowledge.get_ingestion_checkpoint(owner.job_id,**SCOPE))
    with pytest.raises(OwnershipLostError):
        knowledge.save_ingestion_checkpoint(owner,fingerprint=old['fingerprint'],artifacts=old['artifacts'])
    assert knowledge.get_ingestion_checkpoint(owner.job_id,**SCOPE)==before
    assert knowledge.get_publication(owner.job_id,**SCOPE)['attempt_id']=='second'


@pytest.mark.parametrize('change',['document','tenant','job'])
def test_F2_committed_cached_or_caller_scope_cannot_cross_identity(knowledge,change):
    owner=receipt_owner(knowledge);before=deepcopy(knowledge.get_publication(owner.job_id,**SCOPE))
    stale=deepcopy(owner)
    if change=='document': stale.document_id='other'
    if change=='tenant': stale.tenant_id='other'
    if change=='job': stale.job_id='other'
    with pytest.raises(OwnershipLostError): svc(knowledge).recover_publication(owner.job_id,**SCOPE,snapshot=stale)
    if change!='job':
        service=svc(knowledge);service._jobs[owner.job_id]=stale
        with pytest.raises(OwnershipLostError): service.recover_publication(owner.job_id,**SCOPE)
    assert knowledge.get_publication(owner.job_id,**SCOPE)==before


def test_F1_ready_receipt_recovery_releases_checkpoint_outputs(knowledge,tmp_path):
    path=source(tmp_path);vectors=InMemoryVectorStore();original=knowledge.set_document_status
    def die(doc,status):
        if status=='published': raise Crash('ready receipt before publication')
        return original(doc,status)
    knowledge.set_document_status=die
    with pytest.raises(Crash): svc(knowledge,vectors).ingest(path,**SCOPE,job_id='ready')
    assert knowledge.get_ingestion_checkpoint('ready',**SCOPE)['artifacts']['vectors']
    knowledge.set_document_status=original;path.unlink()
    result=svc(knowledge,vectors,NoReplay()).recover_publication('ready',**SCOPE)
    assert result.status=='published'
    saved=knowledge.get_ingestion_checkpoint('ready',**SCOPE)
    assert saved['state']=='committed' and saved['artifacts']=={}
    assert saved['job_snapshot']['finished_at']==result.finished_at


def test_F1_second_attempt_checkpoint_supersedes_older_failed_receipt(knowledge,tmp_path):
    first=IngestionJob(**SCOPE,job_id='resume',document_id='first',attempt=1,
        created_at=1.,started_at=2.,finished_at=3.,metadata={'publication_attempt':'first'})
    install_historical_publication(knowledge, first, 'failed')
    path=source(tmp_path);vectors=InMemoryVectorStore();embedding=CountingEmbedding()
    # Actual ingest advances to attempt two after its receipt-backed first failure.
    real=vectors.count_for_document
    vectors.count_for_document=lambda *a,**kw: (_ for _ in ()).throw(Crash('attempt two before intent'))
    service=svc(knowledge,vectors,embedding)
    with pytest.raises(Crash): service.ingest(path,**SCOPE,job_id='resume')
    assert service.get_status('resume').attempt==2
    saved=knowledge.get_ingestion_checkpoint('resume',**SCOPE)
    assert saved['job_snapshot']['attempt']==2 and knowledge.get_publication('resume',**SCOPE)['attempt_id']=='first'
    vectors.count_for_document=real
    result=svc(knowledge,vectors,NoReplay()).ingest(path,**SCOPE,job_id='resume')
    assert result.status=='published' and result.attempt==2 and embedding.calls==1
    assert result.metadata['publication_attempt']==saved['attempt_id']
    assert result.started_at==saved['job_snapshot']['started_at']
