"""Publication acknowledgement recovery: copied independent P0 probes and exhaustion cases."""
import asyncio,copy,hashlib,json,threading,time

from dataclasses import fields,asdict

from io import BytesIO

from pathlib import Path

import pytest

from rick_ingestion import IngestionService

from rick_ingestion.pipeline import _scoped_call

from rick_knowledge import Collection,Document,Chunk,InMemoryKnowledgeStore,SQLiteKnowledgeStore,document_id_for_content,legacy_document_id_for_content,content_checksum

from rick_retrieval import DeterministicHashEmbedding,InMemoryVectorStore,SQLiteVectorStore

from services.ingestion_service import IngestionApplicationService

from services.knowledge_service import KnowledgeApplicationService

@pytest.fixture(params=['memory','sqlite'])
def lab(request,tmp_path):
 k=InMemoryKnowledgeStore() if request.param=='memory' else SQLiteKnowledgeStore(tmp_path/'k.sqlite')
 v=InMemoryVectorStore() if request.param=='memory' else SQLiteVectorStore(tmp_path/'v.sqlite')
 p=tmp_path/'synthetic.txt';p.write_text('Independent synthetic invariant checking with enough words for multiple chunks. '*200)
 yield k,v,p,request.param
 for s in (k,v):
  if hasattr(s,'close'):s.close()

def service(k,v):return IngestionService(knowledge=k,vectors=v,embeddings=DeterministicHashEmbedding())

def state(k,v,d):return copy.deepcopy((k.get_document(d),k.get_chunks(d),v.all_points()))

@pytest.mark.parametrize('recovery_fault',[RuntimeError,asyncio.CancelledError])
def test_committed_ack_then_recovery_read_failure(lab,recovery_fault):
 k,v,p,kind=lab;armed=False;read_failed=False
 class Ack:
  def __getattr__(self,n):return getattr(k,n)
  def set_document_status(self,d,status,**kw):
   nonlocal armed
   result=_scoped_call(k.set_document_status,d,status,**kw)
   if status=='published':armed=True;raise RuntimeError('commit succeeded; acknowledgement lost')
   return result
  def get_document(self,d,**kw):
   nonlocal read_failed
   if armed and not read_failed:read_failed=True;raise recovery_fault('one recovery read fails')
   return k.get_document(d,**kw)
 s=service(Ack(),v);returned=None;escaped=None
 try:returned=s.ingest(p,job_id='double-fault',**SCOPE)
 except BaseException as e:escaped=type(e).__name__
 job=s.get_status('double-fault');doc,ch,pts=state(k,v,job.document_id)
 record('double_fault_'+kind+'_'+recovery_fault.__name__,{'escaped':escaped,'returned':getattr(returned,'status',None),'job':job.status,'document':doc.status,'chunks':len(ch),'points':len(pts),'pending':list(s._publication_pending)})
 assert doc.status=='published' and len(ch)==len(pts)>0
 assert escaped is None and returned.status==job.status==doc.status, 'AUD03-09 committed publication must have a coherent result after a transient recovery read fault'

def test_async_api_committed_ack_recovery_read_failure(lab,tmp_path):
 k,v,p,kind=lab;armed=False;failed=False;terminal=threading.Event()
 class Ack:
  def __getattr__(self,n):return getattr(k,n)
  def set_document_status(self,d,status,**kw):
   nonlocal armed
   result=_scoped_call(k.set_document_status,d,status,**kw)
   if status=='published':armed=True;raise RuntimeError('commit acknowledgement lost')
   return result
  def get_document(self,d,**kw):
   nonlocal failed
   if armed and not failed:failed=True;raise RuntimeError('one recovery read fails')
   return k.get_document(d,**kw)
 class Events:
  def emit(self,e):
   if e.get('type') in ('worker.ingestion.failed','worker.ingestion.completed'):terminal.set()
 s=service(Ack(),v);app=IngestionApplicationService(s,staging_root=tmp_path/'staging',event_sink=Events())
 try:
  queued=app.submit_upload(BytesIO(p.read_bytes()),filename='synthetic.txt',**SCOPE)
  deadline=time.monotonic()+3
  while app._async_pending and time.monotonic()<deadline:time.sleep(.01)
  assert not app._async_pending,'bounded worker completion timed out'
  public=app.get_status(queued['job_id'],tenant_id='t',workspace_id='w',allowed_collection_ids=['c'])
  job=s.get_status(queued['job_id']);doc,ch,pts=state(k,v,job.document_id)
  record('api_double_fault_'+kind,{'public_status':public['status'],'package_status':job.status,'document_status':doc.status,'points':len(pts),'chunks':len(ch),'error_code':public.get('error_code')})
  assert public['status']==job.status==doc.status=='published','AUD03-09 API falsely reports failed while published document and vectors remain'
 finally:app.close(timeout=3)


SCOPE = dict(tenant_id="t", workspace_id="w", collection_id="c")


def record(name, data):
    print(json.dumps({"probe": name, **data}, default=str))


@pytest.mark.parametrize("committed", [True, False])
@pytest.mark.parametrize("signal", [RuntimeError, asyncio.CancelledError])
@pytest.mark.parametrize("caller", ["pipeline", "api"])
def test_unreadable_outcome_is_retained_and_explicitly_reconciled(lab, tmp_path, committed, signal, caller):
    k, v, path, kind = lab
    lost, reads = False, 0
    class Interrupted:
        def __getattr__(self, name):
            return getattr(k, name)
        def set_document_status(self, document_id, status, **kwargs):
            nonlocal lost
            if status == "published":
                if committed:
                    _scoped_call(k.set_document_status, document_id, status, **kwargs)
                lost = True
                raise RuntimeError("acknowledgement lost")
            return _scoped_call(k.set_document_status, document_id, status, **kwargs)
        def get_document(self, document_id, **kwargs):
            nonlocal reads
            if lost:
                reads += 1
                raise signal("recovery temporarily unavailable")
            return k.get_document(document_id, **kwargs)
    pipeline = service(Interrupted(), v)
    app = None
    try:
        if caller == "api":
            app = IngestionApplicationService(pipeline, staging_root=tmp_path / "staging")
            queued = app.submit_upload(BytesIO(path.read_bytes()), filename="synthetic.txt", **SCOPE)
            deadline = time.monotonic() + 3
            while app._async_pending and time.monotonic() < deadline:
                time.sleep(.01)
            assert app._async_pending == 0
            job = pipeline.get_status(queued["job_id"])
            public = app.get_status(job.job_id, tenant_id="t", workspace_id="w", allowed_collection_ids=["c"])
            assert public["status"] == "verifying" and public["error_code"] is None
            assert public["metadata"]["publication_outcome"] == "unknown"
            assert app._job_paths[job.job_id].is_file()
        else:
            job = pipeline.ingest(path, job_id="unknown", **SCOPE)
        assert reads == 3 and job.status == "verifying"
        assert job.metadata["publication_outcome_unknown"] is True
        before = state(k, v, job.document_id)
        assert len(before[1]) == len(before[2]) > 0
        assert before[0].status == ("published" if committed else "processing")
        assert pipeline.cancel(job.job_id) is True
        assert job.status == "verifying" and state(k, v, job.document_id) == before
        assert pipeline.reconcile_publication(job.job_id) is job
        assert reads == 6 and job.status == "verifying" and state(k, v, job.document_id) == before
        lost = False
        resolved = pipeline.reconcile_publication(job.job_id)
        document, chunks, points = state(k, v, job.document_id)
        if committed:
            assert resolved.status == document.status == "published"
            assert len(chunks) == len(points) > 0
        else:
            assert resolved.status == "cancelled" and document.status == "failed"
            assert chunks == points == []
        assert "publication_outcome_unknown" not in resolved.metadata
        assert job.job_id not in pipeline._publication_pending
        assert job.job_id not in pipeline._publication_recovery
        if app is not None:
            public = app.get_status(job.job_id, tenant_id="t", workspace_id="w", allowed_collection_ids=["c"])
            assert public["status"] == resolved.status
            assert "publication_outcome" not in public["metadata"]
        record("explicit_recovery", dict(adapter=kind, caller=caller, committed=committed,
               signal=signal.__name__, recovery_reads=reads, resolved=resolved.status, document=document.status))
    finally:
        if app is not None:
            app.close(timeout=3)


def test_recovery_keeps_cancellation_pending_until_terminal_commit(lab):
    pipeline_knowledge, vectors, source, kind = lab
    unavailable = False
    class Interrupted:
        def __getattr__(self, name):
            return getattr(pipeline_knowledge, name)
        def set_document_status(self, document_id, status, **kwargs):
            nonlocal unavailable
            result = _scoped_call(pipeline_knowledge.set_document_status, document_id, status, **kwargs)
            if status == "published":
                unavailable = True
                raise RuntimeError("lost acknowledgement")
            return result
        def get_document(self, document_id, **kwargs):
            if unavailable:
                raise RuntimeError("unreadable outcome")
            return pipeline_knowledge.get_document(document_id, **kwargs)
    pipeline = service(Interrupted(), vectors)
    job = pipeline.ingest(source, job_id="cancel-at-resolution", **SCOPE)
    assert job.status == "verifying"
    unavailable = False
    real_lock = pipeline._lock
    cancelled = []
    class CancelOnResolution:
        def __enter__(self):
            real_lock.acquire()
            return self
        def __exit__(self, *_):
            real_lock.release()
            if (not cancelled and job.status == "verifying"
                    and not job.metadata.get("publication_outcome_unknown")):
                # Deterministically inject cancellation after recovery has
                # read the commit, before the job transitions to published.
                cancelled.append(None)
                cancelled[0] = pipeline.cancel(job.job_id)
    pipeline._lock = CancelOnResolution()
    result = pipeline.reconcile_publication(job.job_id)
    assert cancelled == [True]
    assert result.status == pipeline_knowledge.get_document(job.document_id).status == "published"
    assert job.job_id not in pipeline._publication_pending
    record("cancel_at_resolution", dict(adapter=kind, status=result.status))


@pytest.mark.parametrize("committed", [True, False])
@pytest.mark.parametrize("package_first", [True, False])
def test_service_reconciliation_registers_source_journal_and_refresh(lab, tmp_path, committed, package_first):
    from services.job_journal import JobJournal
    knowledge, vectors, source, kind = lab
    unreadable = False
    writes_available = False
    refreshes = []
    class LostAcknowledgement:
        def __getattr__(self, name):
            return getattr(knowledge, name)
        def set_document_status(self, document_id, status, **kwargs):
            nonlocal unreadable
            if status == "published":
                if committed or writes_available:
                    result = _scoped_call(knowledge.set_document_status, document_id, status, **kwargs)
                if not writes_available:
                    unreadable = True
                    raise RuntimeError("publication acknowledgement lost")
                return result
            return _scoped_call(knowledge.set_document_status, document_id, status, **kwargs)
        def get_document(self, document_id, **kwargs):
            if unreadable:
                raise RuntimeError("every recovery read fails")
            return knowledge.get_document(document_id, **kwargs)
    pipeline = service(LostAcknowledgement(), vectors)
    journal = JobJournal(tmp_path / "journal.sqlite")
    app = IngestionApplicationService(pipeline, staging_root=tmp_path / "staging",
        job_journal=journal, refresh_callback=lambda: refreshes.append(True))
    scope = dict(tenant_id="t", workspace_id="w", allowed_collection_ids=["c"])
    try:
        queued = app.submit_upload(BytesIO(source.read_bytes()), filename="reviewed-source.txt", **SCOPE)
        deadline = time.monotonic() + 3
        while app._async_pending and time.monotonic() < deadline:
            time.sleep(.01)
        assert app._async_pending == 0
        job_id = queued["job_id"]
        job = pipeline.get_status(job_id)
        path = app._job_paths[job_id]
        initial = copy.deepcopy(journal.get(job_id))
        assert initial["status"] == "verifying" and path.is_file()
        assert job.document_id not in app._document_paths and refreshes == []
        # Scoped denial must not execute reconciliation or change source ownership.
        assert app.reconcile_publication(job_id, **{**scope, "tenant_id": "foreign"}) is None
        still_unknown = app.reconcile_publication(job_id, **scope)
        assert still_unknown["status"] == "verifying"
        assert still_unknown["metadata"]["publication_outcome"] == "unknown"
        assert path.is_file() and refreshes == []
        unreadable = False
        if not committed:
            before = state(knowledge, vectors, job.document_id)
            still_pending = app.reconcile_publication(job_id, **scope)
            assert still_pending["status"] == "verifying"
            assert path.is_file() and refreshes == []
            assert state(knowledge, vectors, job.document_id) == before
            unreadable = False
        # A ready durable intent can finish once writes recover; loss of an
        # acknowledgement alone cannot authorize destructive failure cleanup.
        writes_available = True
        if package_first:
            pipeline.reconcile_publication(job_id)
            assert app.get_status(job_id, **scope)["status"] == "published"
            assert job.document_id not in app._document_paths
        resolved = app.reconcile_publication(job_id, **scope)
        public = app.get_status(job_id, **scope)
        durable_job = journal.get(job_id)
        assert resolved["status"] == public["status"] == durable_job["status"] == "published"
        assert "publication_outcome" not in public["metadata"]
        assert app._document_paths[job.document_id] == path and app._stored_path(job.document_id) == path
        assert app._document_filenames[job.document_id] == "reviewed-source.txt"
        assert durable_job["source_path"] == str(path) and durable_job["display_filename"] == "reviewed-source.txt"
        assert path.is_file() and refreshes == [True]
        assert app.reconcile_publication(job_id, **scope)["status"] == "published"
        assert refreshes == [True], "registration/refresh must be idempotent"
        record("api_lifecycle_reconciled", dict(adapter=kind, committed=committed,
            package_first=package_first, public=public["status"], journal=durable_job["status"],
            source_retained=path.is_file(), refreshes=len(refreshes)))
    finally:
        app.close(timeout=3)
        journal.close()


def test_definitive_prepublication_failure_cleans_source_and_journal(lab, tmp_path):
    from services.job_journal import JobJournal
    knowledge, vectors, source, kind = lab
    pipeline = service(knowledge, vectors)

    class StartFailure:
        def emit(self, event):
            if event["type"] == "ingestion.start":
                raise RuntimeError("definitive failure before processing")

    pipeline.events = StartFailure()
    refreshes = []
    journal = JobJournal(tmp_path / "failed-journal.sqlite")
    staging = tmp_path / "failed-staging"
    app = IngestionApplicationService(pipeline, staging_root=staging,
        job_journal=journal, refresh_callback=lambda: refreshes.append(True))
    try:
        queued = app.submit_upload(BytesIO(source.read_bytes()), filename="failed-source.txt", **SCOPE)
        deadline = time.monotonic() + 3
        while app._async_pending and time.monotonic() < deadline:
            time.sleep(.01)
        assert app._async_pending == 0
        job_id = queued["job_id"]
        public = app.get_status(job_id, tenant_id="t", workspace_id="w", allowed_collection_ids=["c"])
        durable = journal.get(job_id)
        assert public["status"] == durable["status"] == "failed"
        assert durable["source_path"] is None
        assert job_id not in app._job_paths
        assert not any(path.is_file() for path in staging.rglob('*'))
        assert vectors.all_points() == [] and refreshes == []
    finally:
        app.close(timeout=3)
        journal.close()
