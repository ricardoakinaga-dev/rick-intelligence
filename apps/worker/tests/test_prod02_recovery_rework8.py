"""Local public queue/store matrix; SQL observations are not actual PG proof."""
import ast
import base64
import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Mapping
from types import SimpleNamespace

import pytest

from external_ingestion import _recovery_metadata
from postgres_jobs import PostgresJobQueue, PostgresJobError, PostgresJobLeaseError
from rick_jobs import JobResult, JobPublicationResult, JobPublicationFacts, JobScope, JobState
from rick_ingestion import IngestionService
from rick_ingestion.jobs import IngestionJob
from rick_knowledge import InMemoryKnowledgeStore, SQLiteKnowledgeStore
from rick_knowledge.fencing import OwnershipLostError
from rick_knowledge.publication import publication_snapshot
from rick_retrieval import InMemoryVectorStore, DeterministicHashEmbedding
from test_postgres_jobs import make_job
from test_prod02_recovery_rework5 import RecoveryConnection, RecoveryCursor
from test_prod02_recovery_rework4 import handler, NoProvider, source, Crash

SCOPE = dict(tenant_id='t', workspace_id='w', collection_id='c')


class GuardCursor(RecoveryCursor):
    """Observe the real mutation's DB-clock lease/deadline predicate locally."""
    def _update_job(self, compact, params):
        if "lease_until > clock_timestamp()" in compact:
            deadline = params[-1] if 'clock_timestamp() < to_timestamp(%s)' in compact else None
            guard_offset = -3 if deadline is not None else -2
            token = params[guard_offset+1] if deadline is not None else params[-1]
            worker = params[guard_offset]
            rows = [r for r in self.connection.jobs.values() if r.get('lease_owner') == token
                and r.get('lease_worker_id') == worker]
            if not rows or rows[0]['lease_until'] <= self.connection.database_now:
                return
            if deadline is not None:
                if self.connection.database_now >= deadline:
                    return
                # The older collaborator decodes a tail without deadline.
                params = params[:-1]
        super()._update_job(compact, params)


class GuardConnection(RecoveryConnection):
    def cursor(self):
        return GuardCursor(self)


def running(payload=None):
    db = GuardConnection()
    db.database_now = 20
    queue = PostgresJobQueue(lambda: db, lease_seconds=200)
    job = queue.enqueue(replace(make_job(scope=JobScope(**SCOPE),payload=payload), created_at=10, updated_at=10, available_at=10), expected_version=0)
    job, lease = queue.claim(worker_id='owner', scope=job.scope, expected_versions={}, now=20)[0]
    return queue, db, job, lease


def typed(job, finish):
    return JobPublicationResult(document_id='doc', completed_at=finish,
        facts=JobPublicationFacts(job_id=job.job_id, scope=job.scope, attempt=job.attempt_count,
            created_at=job.created_at, started_at=job.attempts[-1].started_at,
            attempt_id=_recovery_metadata(job)['publication_attempt']))


def translate(job, result):
    # Execute the actual frozen normal adapter, without constructing providers.
    path = Path(__file__).parents[2]/'api/src/services/external_composition.py'
    tree = ast.parse(path.read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_canonical_job_result')
    env = {'Mapping': Mapping, 'JobResult': JobResult}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), 'exec'), env)
    return env['_canonical_job_result'](job, result)


def assert_projection(db, before, result, finish):
    assert result.state is JobState.SUCCEEDED
    assert result.result.completed_at == result.attempts[-1].finished_at == finish
    assert result.created_at == before.created_at and result.attempt_count == before.attempt_count
    assert result.attempts[:-1] == before.attempts[:-1]
    assert result.attempts[-1].started_at == before.attempts[-1].started_at
    assert result.attempts[-1].worker_id == before.attempts[-1].worker_id
    assert result.version == before.version+1
    attempt_sql = [p for s,p in db.trace if 'insert into rick_ingestion_job_attempts' in s.lower()]
    assert attempt_sql[-1][5] == finish
    assert any('rick_ingestion_job_events' in s for s,p in db.trace)
    audits = [json.loads(p[-1]) for s,p in db.trace if 'insert into rick_audit_events' in s.lower()]
    assert audits[-1]['attempt_count'] == before.attempt_count
    assert audits[-1]['state'] == 'SUCCEEDED'
    assert audits[-1]['max_attempts'] == before.max_attempts


@pytest.mark.parametrize('finish,now', [(30,100), (110,90)])
@pytest.mark.parametrize('normal', [False, True])
def test_normal_and_recovery_share_durable_finish(finish, now, normal):
    queue, db, job, lease = running()
    result = typed(job, finish)
    queue.publication_reconciler = lambda _: result
    db.database_now = now
    if normal:
        terminal = queue.acknowledge(lease, result, now=now, expected_version=job.version)
    else:
        terminal = queue.recover_publication(job.job_id, **SCOPE, now=now)
    assert_projection(db, job, terminal, finish)
    assert terminal.updated_at == max(now, finish)
    with pytest.raises(PostgresJobLeaseError):
        queue.acknowledge(lease, result, now=now, expected_version=terminal.version)


@pytest.mark.parametrize('field', ['job_id','scope','attempt','created_at','started_at','attempt_id'])
@pytest.mark.parametrize('normal', [False, True])
def test_identity_conflicts_preserve_history(field, normal):
    queue, db, job, lease = running()
    result = typed(job, 30)
    value = {'job_id':'other', 'scope':JobScope('other','w','c'), 'attempt':2,
        'created_at':11, 'started_at':21, 'attempt_id':'forged'}[field]
    result = replace(result, facts=replace(result.facts, **{field:value}))
    queue.publication_reconciler = lambda _: result
    before = deepcopy(db.attempts)
    terminal = (queue.acknowledge(lease, result, now=100, expected_version=job.version) if normal
        else queue.recover_publication(job.job_id, **SCOPE, now=100))
    assert terminal.state is JobState.RUNNING and terminal.version == job.version
    assert db.attempts == before
    assert db.jobs[str(job.job_id)]['last_error_code'] == 'publication_attempt_conflict'


def test_plain_generic_result_still_finishes_at_ack_clock():
    queue, db, job, lease = running()
    terminal = queue.acknowledge(lease, JobResult(completed_at=30), now=100, expected_version=job.version)
    assert terminal.result.completed_at == 30 and terminal.attempts[-1].finished_at == 100


@pytest.fixture(params=['memory','sqlite'])
def knowledge(request, tmp_path):
    store = InMemoryKnowledgeStore() if request.param == 'memory' else SQLiteKnowledgeStore(tmp_path/'legacy.sqlite')
    yield store
    if hasattr(store,'close'):
        store.close()


def raw_receipt(store, job_id):
    if isinstance(store, InMemoryKnowledgeStore):
        return deepcopy(store._publications[(SCOPE['tenant_id'],SCOPE['workspace_id'],SCOPE['collection_id'],job_id)])
    return tuple(store._connection.execute('SELECT * FROM publication_receipts WHERE job_id=?',(job_id,)).fetchone())


def legacy(store, job, finish=None, checkpoint_finish=30):
    owner = IngestionJob(job_id=str(job.job_id), **SCOPE, document_id='doc',
        created_at=job.created_at, started_at=job.attempts[-1].started_at,
        attempt=job.attempt_count, metadata=_recovery_metadata(job), status='published', finished_at=finish)
    receipt = dict(job_id=owner.job_id, **SCOPE, document_id='doc',
        attempt_id=owner.metadata['publication_attempt'],document_attempt=owner.metadata['publication_attempt'],
        outcome='committed',cancel_requested=False,ready_count=0,job_snapshot=publication_snapshot(owner))
    store._write_publication(receipt)
    owner.finished_at = checkpoint_finish
    checkpoint = dict(job_id=owner.job_id, **SCOPE, document_id='doc', attempt_id=owner.metadata['publication_attempt'],
        state='committed', cancel_requested=False, fingerprint=None, artifacts={},job_snapshot=publication_snapshot(owner))
    store._write_ingestion_checkpoint(checkpoint)
    return owner


def test_checkpoint_projects_finish_without_backfilling_raw_legacy_receipt(knowledge, tmp_path):
    queue, db, job, lease = running()
    owner = legacy(knowledge, job)
    before = raw_receipt(knowledge, owner.job_id)
    worker = handler(knowledge, InMemoryVectorStore(), tmp_path, NoProvider())
    queue.publication_reconciler = worker.recover_job
    terminal = queue.recover_publication(job.job_id, **SCOPE, now=100)
    assert_projection(db, job, terminal, 30)
    assert worker.ingestion.get_status(owner.job_id).finished_at == 30
    assert knowledge.get_publication(owner.job_id, **SCOPE)['job_snapshot']['finished_at'] is None
    after = raw_receipt(knowledge, owner.job_id)
    assert after == before
    (tmp_path/'raw-legacy-evidence.json').write_text(json.dumps({'adapter':type(knowledge).__name__, 'before':before, 'after':after, 'public_finish':30, 'canonical_finish':terminal.attempts[-1].finished_at},indent=2))
    owner.finished_at = 999
    with pytest.raises(OwnershipLostError):
        knowledge.save_publication_snapshot(owner)
    assert raw_receipt(knowledge, owner.job_id) == before


def test_known_receipt_conflicting_checkpoint_is_refused(knowledge):
    queue, db, job, lease = running()
    owner = legacy(knowledge, job, finish=29, checkpoint_finish=30)
    before = raw_receipt(knowledge, owner.job_id)
    service = IngestionService(knowledge=knowledge,vectors=InMemoryVectorStore(),embeddings=DeterministicHashEmbedding())
    with pytest.raises(OwnershipLostError):
        service.recover_publication(owner.job_id, **SCOPE)
    assert raw_receipt(knowledge, owner.job_id) == before


def test_frozen_normal_translation_uses_scoped_authority(knowledge, tmp_path):
    queue, db, job, lease = running(payload={'object_key':'objects/raw.txt', 'checksum':'sha256:'+'0'*64,'filename_ref':base64.urlsafe_b64encode(b'raw.txt').decode()})
    legacy(knowledge, job, finish=30, checkpoint_finish=30)
    worker = handler(knowledge, InMemoryVectorStore(), tmp_path, NoProvider())
    business = worker(SimpleNamespace(job_id=str(job.job_id), **SCOPE,payload=job.payload,
        attempt_count=job.attempt_count,created_at=job.created_at,started_at=job.attempts[-1].started_at))
    generic = translate(job, business)
    queue.publication_reconciler = worker.recover_job
    terminal = queue.acknowledge(lease, generic, now=100, expected_version=job.version)
    assert_projection(db, job, terminal, 30)


@pytest.mark.parametrize('finish,now', [(30,100),(110,90)])
def test_actual_normal_handler_and_frozen_callback(knowledge, tmp_path, monkeypatch, finish, now):
    path = source(tmp_path)
    data = path.read_bytes()
    queue, db, job, lease = running(payload={'object_key':'objects/source.txt',
        'checksum':'sha256:'+hashlib.sha256(data).hexdigest(),'filename_ref':base64.urlsafe_b64encode(b'source.txt').decode()})
    vectors = InMemoryVectorStore()
    worker = handler(knowledge, vectors, tmp_path)
    class LocalObjects:
        def get(self,*args,**kwargs):
            return data
    worker.object_store = LocalObjects()
    real_service = worker.ingestion
    monkeypatch.setattr(knowledge, '_publication_commit_time', lambda: float(finish))
    tree = ast.parse((Path(__file__).parents[2]/'api/src/services/external_composition.py').read_text())
    callback = next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name == 'canonical_ingestion_handler')
    converter = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name == '_canonical_job_result')
    # Actual callback/handler/public ingest with deterministic providers and
    # local object bytes; full composition construction is not run.
    env = {'SimpleNamespace':SimpleNamespace,'Mapping':Mapping,'JobResult':JobResult,'handler':worker}
    exec(compile(ast.Module(body=[converter,callback],type_ignores=[]),'<frozen callback>','exec'),env)
    result = env['canonical_ingestion_handler'](job,lease,cancelled=lambda:False)
    queue.publication_reconciler = worker.recover_job
    db.database_now = now
    terminal = queue.acknowledge(lease,result,now=now,expected_version=job.version)
    assert_projection(db,job,terminal,finish)
    assert real_service.get_status(str(job.job_id)).finished_at == finish


def test_after_ack_commit_crash_and_stale_lease_preserve_finish():
    queue, db, job, lease = running()
    result = typed(job,30)
    queue.publication_reconciler = lambda _: result
    def crash(point):
        if point == 'after_commit':
            raise Crash('ack committed before return')
    queue._fault_injector = crash
    with pytest.raises(Crash):
        queue.acknowledge(lease,result,now=100,expected_version=job.version)
    before = deepcopy(db.attempts)
    queue._fault_injector = None
    terminal = queue.recover_publication(job.job_id, **SCOPE,now=120)
    assert_projection(db,job,terminal,30)
    assert db.attempts == before
    with pytest.raises(PostgresJobLeaseError):
        queue.acknowledge(lease,result,now=120,expected_version=terminal.version)
    assert db.attempts == before


@pytest.mark.parametrize('guard',['expired','deadline','version','late_expiry'])
def test_live_guards_still_refuse_typed_completion(guard):
    queue, db, job, lease = running()
    result = typed(job,110)
    queue.publication_reconciler = lambda _: result
    before = deepcopy(db.attempts)
    now, deadline, version = 90,None,job.version
    if guard == 'expired':
        db.database_now = lease.expires_at+1
    elif guard == 'deadline':
        deadline = 89
    elif guard == 'version':
        version -= 1
    else:
        # Expiry after lock, before conditional persistence.
        queue._fault_injector = lambda _: setattr(db,'database_now',lease.expires_at+1)
    with pytest.raises(PostgresJobError):
        queue.acknowledge(lease,result,now=now,expected_version=version,deadline=deadline)
    assert db.attempts == before


@pytest.mark.parametrize('authority', [None, 'generic'])
def test_plain_generic_with_untyped_reconciler_retains_legacy_behavior(authority):
    queue, db, job, lease = running()
    result = JobResult(completed_at=30)
    queue.publication_reconciler = lambda _: result if authority == 'generic' else None
    terminal = queue.acknowledge(lease,result,now=100,expected_version=job.version)
    assert terminal.result.completed_at == 30 and terminal.attempts[-1].finished_at == 100


@pytest.mark.parametrize('field',['document_id','completed_at','output_refs'])
def test_normal_generic_result_cannot_replace_typed_authority(field):
    queue, db, job, lease = running()
    result = typed(job,30)
    queue.publication_reconciler = lambda _: result
    changed = dict(document_id='doc',completed_at=30,output_refs={})
    changed[field] = {'document_id':'other','completed_at':999,'output_refs':{'object_key':'value'}}[field]
    before = deepcopy(db.attempts)
    terminal = queue.acknowledge(lease,JobResult(**changed),now=100,expected_version=job.version)
    assert terminal.state is JobState.RUNNING and db.attempts == before
    assert db.jobs[str(job.job_id)]['last_error_code'] == 'publication_attempt_conflict'


@pytest.mark.parametrize('field',['attempt','created_at','started_at','document_id','attempt_id'])
def test_mismatching_checkpoint_cannot_supply_unknown_receipt_finish(knowledge,tmp_path,field):
    queue, db, job, lease = running()
    owner = legacy(knowledge,job)
    checkpoint = knowledge.get_ingestion_checkpoint(owner.job_id, **SCOPE)
    if field in {'attempt','created_at','started_at'}:
        checkpoint['job_snapshot'][field] += 1
        if field == 'attempt':
            checkpoint['job_snapshot']['metadata']['queue_attempt'] += 1
    elif field == 'document_id':
        checkpoint[field] = 'other'
    else:
        checkpoint['attempt_id'] = 'other'
        checkpoint['job_snapshot']['metadata']['publication_attempt'] = 'other'
    knowledge._write_ingestion_checkpoint(checkpoint)
    before = raw_receipt(knowledge,owner.job_id)
    attempts = deepcopy(db.attempts)
    worker = handler(knowledge,InMemoryVectorStore(),tmp_path,NoProvider())
    queue.publication_reconciler = worker.recover_job
    terminal = queue.recover_publication(job.job_id, **SCOPE,now=100)
    assert terminal.state is JobState.RUNNING and db.attempts == attempts
    assert raw_receipt(knowledge,owner.job_id) == before


@pytest.mark.parametrize('guard',['valid_future_projection','late_deadline'])
def test_projection_clock_does_not_replace_database_deadline(guard):
    queue,db,job,lease = running()
    result = typed(job,110)
    db.database_now = 90
    before = deepcopy(db.attempts)
    if guard == 'late_deadline':
        queue._fault_injector = lambda point: setattr(db,'database_now',101) if point == 'in_transaction' else None
        with pytest.raises(PostgresJobLeaseError):
            queue.acknowledge(lease,result,now=90,deadline=100,expected_version=job.version)
        assert db.attempts == before
    else:
        terminal = queue.acknowledge(lease,result,now=90,deadline=100,expected_version=job.version)
        assert_projection(db,job,terminal,110)
        assert terminal.updated_at == 110
