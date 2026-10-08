"""Authorization and private-admission controls; no real-PG/race/DAC claim.

Driver callbacks model a lock-time observation, not PostgreSQL concurrency.
Native tools and separate-UID DAC remain the Parent's verification boundary.
"""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
import contracts
import db_guard
import publication_capture as capture
import publish_candidate as pub
import publish_guard
from test_rework5 import candidate
from test_rework7 import PublicTools

ROOT = Path(__file__).absolute().parents[3]
SPEC = importlib.util.spec_from_file_location('migration_rework8', ROOT/'infrastructure/scripts/migrate.py')
migrate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migrate)


class ModelCursor:
    def __init__(self, history, relations, *, on_lock=None, fail_sql=None):
        self.history = list(history); self.relations = copy.deepcopy(relations)
        self.sql = []; self.last = ''; self.on_lock = on_lock; self.fail_sql = fail_sql
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def execute(self, sql, args=()):
        self.sql.append(sql); self.last = sql
        if 'pg_advisory_xact_lock' in sql and self.on_lock: self.on_lock()
        if sql == self.fail_sql: raise RuntimeError('modeled pending SQL failure')
        if sql.startswith('INSERT INTO rick_schema_migrations'):
            self.history.append(args)
    def fetchone(self):
        if 'transaction_read_only' in self.last: return ('on',)
        if 'current_schema()' in self.last: return ('public',)
        if 'count(*)' in self.last: return (len(self.relations),)
        if 'to_regclass' in self.last: return (bool(self.history),)
        raise AssertionError(self.last)
    def fetchall(self):
        if 'migration_authorization_relations' in self.last: return copy.deepcopy(self.relations)
        return list(self.history)


class ModelConnection:
    def __init__(self, cursor):
        self.c = cursor; self.rollback = False; self.before = list(cursor.history)
    def __enter__(self): return self
    def __exit__(self, exc, *args):
        self.rollback = exc is not None
        if self.rollback: self.c.history[:] = self.before
    def cursor(self): return self.c


@pytest.fixture
def migration_model(tmp_path, monkeypatch):
    # Three synthetic SQL files are controls only; installed SQL is never edited.
    directory = tmp_path/'control-migrations'; directory.mkdir()
    for i in range(1,4): (directory/f'{i:04d}_control.sql').write_text(f'SELECT {i};')
    return directory, migrate.migration_files(directory)


def observation(rows, history=(), relations=()):
    applied = {r[0] for r in history}
    return {'schema':'rick.vps.preflight/v1','read_only':True,
            'database_state':'EXISTING' if relations else 'EMPTY',
            'relation_count':len(relations),'relations':copy.deepcopy(list(relations)),
            'history':[{'version':v,'sha256':h} for v,h,_ in history],
            'pending':[{'version':v,'sha256':h} for v,_,h in rows if v not in applied]}


def plan_bytes(observed):
    existing = observed['database_state']=='EXISTING'
    return json.dumps({'schema':'rick.vps.migration-plan/v1','authorization':'APPLY_REVIEWED_SQL',
                       'observed':observed,'maintenance_window':existing,
                       'verified_backup_id':'TEST ONLY reviewed backup' if existing else '',
                       'backward_compatible':True},sort_keys=True).encode()


def driver(monkeypatch, cursor):
    conn = ModelConnection(cursor)
    class DriverError(Exception): pass
    monkeypatch.setitem(sys.modules,'psycopg',SimpleNamespace(connect=lambda *a,**k:conn,Error=DriverError))
    return conn


def assert_no_effects(cursor):
    assert not any(sql.lstrip().startswith(('CREATE','ALTER','DO ','INSERT','UPDATE','DELETE')) for sql in cursor.sql)
    assert not any(sql in {'SELECT 1;','SELECT 2;','SELECT 3;'} for sql in cursor.sql)


def test_unchanged_empty_authorization_applies(migration_model, monkeypatch):
    directory, rows = migration_model
    cursor = ModelCursor([],[]); conn = driver(monkeypatch,cursor)
    assert migrate.apply(directory,'TEST ONLY DSN',authorization=plan_bytes(observation(rows)))==0
    assert [r[0] for r in cursor.history]==['0001','0002','0003']
    assert cursor.sql[0]=='SET TRANSACTION ISOLATION LEVEL READ COMMITTED'
    assert 'pg_advisory_xact_lock' in cursor.sql[1]
    first_ddl = next(i for i,sql in enumerate(cursor.sql) if sql.lstrip().startswith('CREATE'))
    assert any('migration_authorization_relations' in sql for sql in cursor.sql[:first_ddl])
    assert not conn.rollback


def test_changed_empty_to_valid_prefix_refused_before_any_ddl(migration_model, monkeypatch):
    directory, rows = migration_model
    history = [(rows[0][0],rows[0][2],migrate.APPLICATION)]
    assert migrate.validate_history(rows,history)=={'0001':rows[0][2]}
    cursor = ModelCursor(history,[['public','rick_schema_migrations','r']])
    conn = driver(monkeypatch,cursor)
    with pytest.raises(RuntimeError,match='inventory changed under migration lock'):
        migrate.apply(directory,'TEST ONLY DSN',authorization=plan_bytes(observation(rows)))
    assert_no_effects(cursor); assert conn.rollback and cursor.history==history


@pytest.mark.parametrize('attack',['checksum','gap','unknown','application'])
def test_invalid_locked_prefix_refused_without_bookkeeping(migration_model, monkeypatch, attack):
    directory,rows = migration_model
    row = ('0001',rows[0][2],migrate.APPLICATION)
    if attack=='checksum': row=('0001','f'*64,migrate.APPLICATION)
    if attack=='gap': row=('0002',rows[1][2],migrate.APPLICATION)
    if attack=='unknown': row=('9999','f'*64,migrate.APPLICATION)
    if attack=='application': row=('0001',rows[0][2],'other')
    cursor=ModelCursor([row],[['public','rick_schema_migrations','r']]); conn=driver(monkeypatch,cursor)
    with pytest.raises(RuntimeError): migrate.apply(directory,'TEST ONLY DSN',authorization=plan_bytes(observation(rows)))
    assert_no_effects(cursor); assert conn.rollback


def test_locked_sql_inventory_drift_refused(migration_model, monkeypatch):
    directory,rows=migration_model
    def replace_sql(): rows[1][1].write_text('SELECT 999;')
    cursor=ModelCursor([],[],on_lock=replace_sql);driver(monkeypatch,cursor)
    with pytest.raises(RuntimeError,match='SQL inventory changed'):
        migrate.apply(directory,'TEST ONLY DSN',authorization=plan_bytes(observation(rows)))
    assert_no_effects(cursor)


@pytest.mark.parametrize('attack',['renamed_relation','same_state_prefix','checksum','legacy_repair'])
def test_changed_existing_authorization_refused_before_effects(monkeypatch, attack):
    rows=migrate.migration_files(ROOT/'infrastructure/migrations')
    history=[(v,h,migrate.APPLICATION) for v,_,h in rows[:9]]
    relations=[['public','rick_documents','r'],['public','rick_schema_migrations','r']]
    approved=plan_bytes(observation(rows,history,relations))
    if attack=='renamed_relation': relations[0][1]='other_documents'
    if attack=='same_state_prefix': history=history[:8]
    if attack=='checksum': history[8]=('0009','f'*64,migrate.APPLICATION)
    if attack=='legacy_repair': history[3]=('0004',migrate.JOBS_CONTRACT_ORIGINAL,migrate.APPLICATION)
    cursor=ModelCursor(history,relations);conn=driver(monkeypatch,cursor)
    with pytest.raises(RuntimeError): migrate.apply(ROOT/'infrastructure/migrations','TEST ONLY DSN',authorization=approved)
    assert_no_effects(cursor);assert conn.rollback


@pytest.mark.parametrize('noop',[False,True])
def test_unchanged_existing_and_complete_noop_authorization(monkeypatch, noop):
    directory=ROOT/'infrastructure/migrations';rows=migrate.migration_files(directory)
    history=[(v,h,migrate.APPLICATION) for v,_,h in rows[:10 if noop else 9]]
    relations=[['public','rick_documents','r'],['public','rick_schema_migrations','r']]
    approved=plan_bytes(observation(rows,history,relations))
    db_guard.validate_migration_plan(json.loads(approved),allow_noop=noop)
    cursor=ModelCursor(history,relations);driver(monkeypatch,cursor)
    # This callback is outside the lock-authorization claim; Parent verifies
    # installed function/trigger semantics with real PostgreSQL.
    monkeypatch.setattr(migrate,'verify_jobs_rewrite',lambda *a:None)
    assert migrate.apply(directory,'TEST ONLY DSN',authorization=approved)==0
    if noop:
        assert cursor.history==history
        assert not any(path.read_text() in cursor.sql for _,path,_ in rows)
    else: assert rows[-1][1].read_text() in cursor.sql


def test_modeled_pending_failure_exits_transaction(migration_model, monkeypatch):
    directory,rows=migration_model
    cursor=ModelCursor([],[],fail_sql='SELECT 2;');conn=driver(monkeypatch,cursor)
    with pytest.raises(RuntimeError,match='pending SQL failure'):
        migrate.apply(directory,'TEST ONLY DSN',authorization=plan_bytes(observation(rows)))
    assert conn.rollback and cursor.history==[]


def test_guard_main_hands_exact_immutable_plan_to_runner(migration_model, monkeypatch):
    directory,rows=migration_model;observed=observation(rows);plan=json.loads(plan_bytes(observed)); received=[]
    monkeypatch.setattr(db_guard,'runner',lambda:SimpleNamespace(apply=lambda *a,**k:received.append(k['authorization']) or 0))
    monkeypatch.setattr(db_guard,'inspect_database',lambda *a,**k:copy.deepcopy(observed))
    monkeypatch.setattr(db_guard,'load',lambda *a:copy.deepcopy(plan))
    driver(monkeypatch,ModelCursor([],[]))
    monkeypatch.setattr(sys,'argv',['db_guard.py','apply'])
    monkeypatch.setenv('RICK_PREFLIGHT_DATABASE_DSN','postgresql://readonly:TEST@postgres/rick')
    monkeypatch.setenv('RICK_MIGRATION_DATABASE_DSN','postgresql://migrator:TEST@postgres/rick')
    monkeypatch.setenv('VPS_PLAN_SHA256','a'*64)
    assert db_guard.main()==0
    assert type(received[0]) is bytes and json.loads(received[0])==plan
    plan['observed']['pending'].clear()
    assert json.loads(received[0])['observed']['pending']==observed['pending']


@pytest.mark.parametrize('mode',[0o600,0o644])
def test_original_authority_permission_gate(tmp_path, monkeypatch, mode):
    from test_rework6 import modeled_root_ancestors
    modeled_root_ancestors(monkeypatch)
    p=tmp_path/'authority.json';p.write_bytes(b'{}');p.chmod(mode)
    with capture.PublicationCapture({}) as captured:
        if mode==0o600:
            assert captured.retain('authority.json',p,private=True).read()==b'{}'
        else:
            with pytest.raises(contracts.Refusal,match='private'):captured.retain('authority.json',p,private=True)
        assert p.stat().st_mode & 0o777==mode


@pytest.mark.parametrize('name',['image.tar','reviewed.Dockerfile'])
def test_readable_non_authority_sources_remain_compatible(tmp_path,monkeypatch,name):
    from test_rework6 import modeled_root_ancestors
    modeled_root_ancestors(monkeypatch)
    p=tmp_path/name;p.write_bytes(b'TEST ONLY');p.chmod(0o644)
    with capture.PublicationCapture({}) as captured:
        assert captured.retain(name,p).read()==b'TEST ONLY'


def test_tool_output_private_from_creation_under_permissive_umask(tmp_path,monkeypatch):
    from test_rework6 import modeled_root_ancestors
    modeled_root_ancestors(monkeypatch)
    original=tmp_path/'image.tar';original.write_bytes(b'TEST ONLY')
    old=os.umask(0o022)
    try:
        with capture.PublicationCapture({}) as captured:
            captured.retain('image.tar',original)
            identity=captured.prepare_output('scan.json');p=captured.outputs/'scan.json'
            assert p.stat().st_mode & 0o777==0o600
            p.write_bytes(b'{}')
            assert captured.retain_output('scan.json',identity).read()==b'{}'
            captured.export('scan.json',tmp_path/'scan.json')
            assert (tmp_path/'scan.json').stat().st_mode & 0o777==0o600
    finally:os.umask(old)


@pytest.mark.parametrize('attack',['shared','replace'])
def test_tool_output_privacy_or_identity_drift_refused(monkeypatch,attack):
    from test_rework6 import modeled_root_ancestors
    modeled_root_ancestors(monkeypatch)
    with capture.PublicationCapture({}) as captured:
        identity=captured.prepare_output('scan.json');p=captured.outputs/'scan.json';p.write_bytes(b'{}')
        if attack=='shared':p.chmod(0o644)
        else:p.rename(p.with_name('previous.json'));p.write_bytes(b'{}');p.chmod(0o600)
        with pytest.raises(contracts.Refusal):captured.retain_output('scan.json',identity)


def test_public_quality_shared_input_refused_before_scan(candidate, monkeypatch):
    from test_rework6 import modeled_root_ancestors
    modeled_root_ancestors(monkeypatch)
    path=candidate/'quality.json';path.chmod(0o644);effects=[]
    monkeypatch.setattr(pub,'command',lambda *a:effects.append(a))
    with pytest.raises(contracts.Refusal,match='private'):pub.main()
    assert effects==[] and path.stat().st_mode & 0o777==0o644


def test_public_generated_evidence_private_and_predicate_exact(candidate,monkeypatch):
    from test_rework6 import modeled_root_ancestors
    modeled_root_ancestors(monkeypatch);tools=PublicTools(candidate,monkeypatch)
    old=os.umask(0o022)
    try:pub.main()
    finally:os.umask(old)
    for name in ['scan.json','registry.digest','predicate.json','candidate.json','signature.bundle.json',
                 'attestation.bundle.json','signature-verification.json','attestation-verification.jsonl']:
        assert (candidate/name).stat().st_mode & 0o777==0o600
    assert tools.predicate['scan_sha256']==hashlib.sha256((candidate/'scan.json').read_bytes()).hexdigest()
    assert json.loads((candidate/'predicate.json').read_bytes())==tools.predicate


def test_quality_producer_exclusive_private_creation(tmp_path, monkeypatch):
    from test_support import admission_fixture
    import admission
    import buildx_binary
    record=admission_fixture()['quality'];source=record['head_sha']
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('SOURCE_SHA',source);monkeypatch.setenv('QUALITY_RUN_ID',str(record['run_id']))
    monkeypatch.setenv('GITHUB_REPOSITORY',contracts.REPO);monkeypatch.setenv('GITHUB_REF','refs/heads/main')
    for key in publish_guard.INPUTS:monkeypatch.setenv(key,'docker.io/test/producer@sha256:'+'a'*64)
    monkeypatch.setattr(admission,'environment_tools',lambda:None)
    monkeypatch.setattr(buildx_binary,'inputs',lambda *a:None)
    run=dict(record);run['head_repository']={'full_name':contracts.REPO};run['html_url']=record['run_url']
    def api(path):
        if path=='branches/main':return {'commit':{'sha':source}}
        if '/jobs?' in path:return {'jobs':[{'name':name,'conclusion':'success'} for name in publish_guard.REQUIRED_JOBS]}
        return run
    monkeypatch.setattr(publish_guard,'api',api)
    old=os.umask(0o022)
    try:publish_guard.main()
    finally:os.umask(old)
    path=tmp_path/'publication/quality.json'
    assert path.stat().st_mode & 0o777==0o600
    before=path.read_bytes();path.chmod(0o644)
    with pytest.raises(FileExistsError):publish_guard.main()
    assert path.read_bytes()==before and path.stat().st_mode & 0o777==0o644


def test_public_shared_scanner_output_refused_before_auth(candidate,monkeypatch):
    from test_rework6 import modeled_root_ancestors
    modeled_root_ancestors(monkeypatch);tools=PublicTools(candidate,monkeypatch)
    original=tools.command
    def command(argv):
        result=original(argv)
        if argv[0]=='docker' and 'image' in argv:(tools.outputs/'scan.json').chmod(0o644)
        return result
    monkeypatch.setattr(pub,'command',command)
    with pytest.raises(contracts.Refusal,match='private'):pub.main()
    assert tools.events==['admission','scan']


@pytest.mark.parametrize('attack',['mutable','missing_backup','maintenance_drift','compatibility_drift'])
def test_runner_requires_immutable_complete_authorization(migration_model,monkeypatch,attack):
    directory,rows=migration_model;approved=plan_bytes(observation(rows))
    if attack=='mutable':approved=json.loads(approved)
    else:
        plan=json.loads(approved)
        if attack=='missing_backup':plan.pop('verified_backup_id')
        if attack=='maintenance_drift':plan['maintenance_window']=True
        if attack=='compatibility_drift':plan['backward_compatible']=False
        approved=json.dumps(plan).encode()
    cursor=ModelCursor([],[]);driver(monkeypatch,cursor)
    with pytest.raises(RuntimeError):migrate.apply(directory,'TEST ONLY DSN',authorization=approved)
    assert cursor.sql==[]


def test_readonly_and_locked_observations_have_identical_contract(migration_model):
    directory,rows=migration_model
    readonly=db_guard.inspect_database(ModelConnection(ModelCursor([],[])),migrate,directory)
    locked=migrate.locked_observation(ModelCursor([],[]),rows)
    assert readonly==locked==observation(rows)
