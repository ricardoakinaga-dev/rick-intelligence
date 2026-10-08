"""Bounded local adversarial regressions; no Docker, network or approval proof."""
from __future__ import annotations
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import pytest
import yaml
from test_safety import (HERE, ROOT, D, SOURCE, IMAGE, BUILDER, Cursor, Connection,
                         archive, args, config, config_file, manifest, construction_review)
import contracts
from test_support import cli_assets
import deploy
import db_guard
import publish_candidate
import buildx_binary

CATALOG=[('column','TEST_ONLY_table.TEST_ONLY_column','TEST ONLY schema metadata')]

class RollbackCursor(Cursor):
    def fetchall(self):
        if 'rollback_catalog' in self.last:return CATALOG
        return super().fetchall()

@pytest.mark.parametrize('attacked',['config','manifest'])
def test_cli_captured_inputs_cannot_be_replaced_before_effects(tmp_path,monkeypatch,attacked):
    values=config(tmp_path);values['LLM_MODEL']='reviewed-model'
    original_config=config_file(tmp_path,values)
    packet=manifest()
    original_manifest=tmp_path/'release.json';original_manifest.write_text(json.dumps(packet))
    original_manifest.chmod(0o600)
    expected_config=original_config.read_bytes();expected_manifest=original_manifest.read_bytes()
    monkeypatch.setattr(sys,'argv',['deploy.py','install','--config',str(original_config),
        '--manifest',str(original_manifest),'--trusted-config-sha256',hashlib.sha256(expected_config).hexdigest(),
        '--trusted-manifest-sha256',hashlib.sha256(expected_manifest).hexdigest(),
        *cli_assets(tmp_path,values,packet)])
    captured=[];capture=contracts.capture
    def attack(path,**kwargs):
        captured.append(path)
        data=capture(path,**kwargs)
        if attacked=='config' and path==original_config:
            original_config.write_bytes(data.replace(b'reviewed-model',b'unreviewed-model'))
        if attacked=='manifest' and path==original_manifest:
            other=copy.deepcopy(packet);other['source_revision']['value']='e'*40
            original_manifest.write_text(json.dumps(other))
        return data
    monkeypatch.setattr(deploy,'capture',attack)
    from infrastructure.docker import check_release
    validated=[]
    def validate(path,**kwargs):
        assert path!=original_manifest and path.read_bytes()==expected_manifest
        assert path.stat().st_mode & 0o077==0
        validated.append(path)
        return []
    monkeypatch.setattr(deploy,'release_errors',lambda args,folder:validate(args.manifest))
    monkeypatch.setattr(deploy,'verify',lambda *a:None)
    commands=[]
    def execute(argv,env=None):
        commands.append(argv)
        assert str(original_config) not in argv and str(original_manifest) not in argv
        assert env['LLM_MODEL']=='reviewed-model'
        if argv[:2]==['docker','compose']:
            path=Path(argv[argv.index('--env-file')+1])
            assert path!=original_config
            assert deploy.read_env(path)['LLM_MODEL']=='reviewed-model'
        return json.dumps({'pending':[],'database_state':'EXISTING'}) if 'db-preflight' in argv else ''
    operation=deploy.execute_operation
    def effects(a,conf,m,refs):
        assert conf==values and m==packet
        return operation(a,conf,m,refs,execute)
    monkeypatch.setattr(deploy,'execute_operation',effects)
    deploy.main()
    originals=[p for p in captured if p in {original_config,original_manifest}]
    assert originals==[original_config,original_manifest] and validated
    assert any('up' in c and 'api' in c for c in commands)

@pytest.mark.parametrize('kind',['symlink','fifo','public_config','writable_manifest'])
def test_secure_capture_refuses_nonregular_or_unprotected_files(tmp_path,kind):
    p=tmp_path/'input'
    private=kind=='public_config'
    if kind=='symlink':
        target=tmp_path/'target';target.write_text('x');p.symlink_to(target)
    elif kind=='fifo':os.mkfifo(p)
    else:
        p.write_text('x');p.chmod(0o644 if private else 0o666)
    with pytest.raises((contracts.Refusal,OSError)):
        contracts.capture(p,private=private)

def canonical():
    spec=importlib.util.spec_from_file_location('vps_rework_canonical',ROOT/'infrastructure/scripts/migrate.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def rollback_fixture(tmp_path, *, target_version=8, retained_version=9):
    """Actual SQL bytes; synthetic review record explicitly grants no authority."""
    module=canonical()
    older=tmp_path/f'older-image{target_version}';older.mkdir()
    retained=tmp_path/f'actual-schema{retained_version}';retained.mkdir()
    artifacts={}
    for p in sorted((ROOT/'infrastructure/migrations').iterdir()):
        if p.name.endswith(('.sql','.sql.inc')) and int(p.name[:4]) <= retained_version:
            data=p.read_bytes();(retained/p.name).write_bytes(data)
            artifacts[p.name]=hashlib.sha256(data).hexdigest()
            if int(p.name[:4]) <= target_version:(older/p.name).write_bytes(data)
    rows=module.migration_files(retained)
    assert [v for v,_,_ in rows]==[f'{i:04d}' for i in range(1,retained_version+1)]
    history=[(v,h,module.APPLICATION) for v,_,h in rows]
    policy={'schema':'rick.vps.rollback-policy/v1','authorization':'RETAIN_SCHEMA_IMAGE_ROLLBACK',
            'target_source_sha':SOURCE,'target_images':contracts.images(manifest()),
            'retained_source_sha':'c'*40,'retained_artifacts':artifacts,
            'compatibility':{'status':'PASS','evidence':'TEST ONLY: simulated independently reviewed compatibility',
                'target_schema_version':f'{target_version:04d}','retained_schema_version':f'{retained_version:04d}'},
            'observed':{'schema':'rick.vps.rollback-preflight/v1','read_only':True,'database_state':'EXISTING',
                'history':[{'version':v,'sha256':h} for v,h,_ in history], 'pending':[],
                'relation_count':42,'retained_source_sha':'c'*40,
                'schema_catalog_sha256':db_guard.catalog_digest(CATALOG)}}
    values=config(tmp_path)
    policy['deployment']={k:values[k] for k in ('VPS_PROJECT','POSTGRES_DB','POSTGRES_VOLUME','REDIS_VOLUME',
                            'QDRANT_VOLUME','OBJECT_VOLUME','CADDY_VOLUME')}
    evidence={k:policy[k] for k in ('target_source_sha','retained_source_sha','retained_artifacts','target_images')}
    evidence.update(schema='rick.vps.schema-compatibility/v1',decision='RETAIN_SCHEMA_IMAGE_ROLLBACK',
        target_schema_version=f'{target_version:04d}',retained_schema_version=f'{retained_version:04d}',reviewer='TEST ONLY simulated reviewer',
        analysis='TEST ONLY simulated reviewed comparison for regression; this is not compatibility approval.')
    data=json.dumps(evidence).encode();evidence_path=tmp_path/'compatibility.json';evidence_path.write_bytes(data)
    policy['compatibility']['evidence_sha256']=hashlib.sha256(data).hexdigest()
    return module,older,retained,history,policy,values

def test_olderimage8_actualschema9_only_reviewed_rollback_path(tmp_path):
    module,older,retained,history,policy,values=rollback_fixture(tmp_path)
    db_guard.validate_rollback_inputs(policy,values,manifest())
    cursor=RollbackCursor(42,history)
    result=db_guard.inspect_database(Connection(cursor),module,older,
                                     rollback_policy=policy,retained_directory=retained,
                                     compatibility_evidence=tmp_path/'compatibility.json')
    assert result==policy['observed'] and result['pending']==[]
    assert all(not any(verb in sql for verb in ('CREATE ','INSERT ','ALTER ','UPDATE ','DELETE ')) for sql in cursor.sql)
    # Same newer history still fails the canonical install/upgrade path.
    with pytest.raises(RuntimeError,match='unknown version'):
        db_guard.inspect_database(Connection(Cursor(42,history)),module,older)

def test_retained_schema_inventory_collection_uses_strict_current_image_history(tmp_path):
    module,older,retained,history,policy,_=rollback_fixture(tmp_path)
    # Collection never supplies compatibility authorization and only knows SQL
    # carried by this current image, unlike the older rollback target.
    observed=db_guard.inspect_database(Connection(RollbackCursor(42,history)),module,retained,
                                       retained_source_sha=policy['retained_source_sha'])
    assert observed==policy['observed']
    with pytest.raises(RuntimeError,match='unknown version'):
        db_guard.inspect_database(Connection(RollbackCursor(42,history)),module,older,
                                  retained_source_sha=policy['retained_source_sha'])

@pytest.mark.parametrize('bad',['checksum','unknown','gap','application','artifact','policy_missing',
                               'policy_checksum','compatibility_missing','provenance_missing','inventory',
                               'target_image','deployment','target_schema','retained_schema','old_sql','pending',
                               'evidence_bytes','evidence_missing','evidence_target','schema_definition'])
def test_rollback_never_accepts_arbitrary_history_or_unreviewed_evidence(tmp_path,bad):
    module,older,retained,history,policy,values=rollback_fixture(tmp_path)
    if bad=='checksum':history[-1]=('0009','f'*64,module.APPLICATION)
    if bad=='unknown':history.append(('0010','f'*64,module.APPLICATION))
    if bad=='gap':history.pop(7)
    if bad=='application':history[-1]=('0009',history[-1][1],'other-app')
    if bad=='artifact':
        p=next(retained.glob('0009_*.sql'));p.write_bytes(p.read_bytes()+b'\n-- adversarial change')
    if bad=='policy_missing':policy['authorization']=''
    if bad=='policy_checksum':
        with pytest.raises(contracts.Refusal):contracts.parse(json.dumps(policy).encode(),'0'*64)
        return
    if bad=='compatibility_missing':policy['compatibility'].pop('evidence')
    if bad=='provenance_missing':policy.pop('retained_source_sha')
    if bad=='inventory':policy['observed']['relation_count']=43
    if bad=='schema_definition':policy['observed']['schema_catalog_sha256']='f'*64
    if bad=='target_image':policy['target_images']['api']='ghcr.io/evil/image@sha256:'+D
    if bad=='deployment':policy['deployment']['POSTGRES_VOLUME']='another-volume'
    if bad=='target_schema':policy['compatibility']['target_schema_version']='0007'
    if bad=='retained_schema':policy['compatibility']['retained_schema_version']='0010'
    if bad=='old_sql':
        p=next(older.glob('0008_*.sql'));p.write_bytes(p.read_bytes()+b'\n-- adversarial change')
    if bad=='pending':history.pop()
    if bad=='evidence_bytes':(tmp_path/'compatibility.json').write_text('{}')
    if bad=='evidence_target':
        p=tmp_path/'compatibility.json';e=json.loads(p.read_text());e['target_schema_version']='0007'
        p.write_text(json.dumps(e));policy['compatibility']['evidence_sha256']=contracts.digest(p)
    with pytest.raises((contracts.Refusal,RuntimeError,ValueError)):
        db_guard.validate_rollback_inputs(policy,values,manifest())
        db_guard.inspect_database(Connection(RollbackCursor(42,history)),module,older,
                                  rollback_policy=policy,retained_directory=retained,
                                  compatibility_evidence=None if bad=='evidence_missing' else tmp_path/'compatibility.json')

def test_rollback_operation_uses_separate_inventory_before_start(tmp_path,monkeypatch):
    _,_,_,_,policy,values=rollback_fixture(tmp_path)
    packet=manifest();packet['rollout']={'rollback':{'migration_compatibility':'PASS','evidence':'TEST ONLY'}}
    a=args(tmp_path,'rollback');a.rollback_policy=tmp_path/'policy.json'
    a.rollback_policy.write_text(json.dumps(policy));a.rollback_policy.chmod(0o600);a.rollback_policy_sha256=contracts.digest(a.rollback_policy)
    calls=[];monkeypatch.setattr(deploy,'verify',lambda *a:None)
    def execute(argv,env=None):
        calls.append(argv)
        if 'db-rollback-preflight' in argv:return json.dumps(policy['observed'])
        return ''
    deploy.execute_operation(a,values,packet,contracts.images(packet),execute)
    assert not any('db-preflight' in c or 'db-migrate' in c for c in calls)
    check=next(i for i,c in enumerate(calls) if 'db-rollback-preflight' in c)
    start=next(i for i,c in enumerate(calls) if 'up' in c and 'api' in c)
    assert check < start

@pytest.mark.parametrize('attacked',['policy','evidence','sql'])
def test_cli_rollback_effects_use_only_captured_reviewed_inputs(tmp_path,monkeypatch,attacked):
    module,older,retained,history,policy,values=rollback_fixture(tmp_path)
    for p in retained.iterdir():p.chmod(0o600)
    evidence=tmp_path/'compatibility.json';evidence.chmod(0o600)
    policy_path=tmp_path/'policy.json';policy_path.write_text(json.dumps(policy));policy_path.chmod(0o600)
    packet=manifest();packet['rollout']={'rollback':{'migration_compatibility':'PASS','evidence':'TEST ONLY'}}
    m=tmp_path/'release.json';m.write_text(json.dumps(packet));m.chmod(0o600)
    conf=config_file(tmp_path,values)
    monkeypatch.setattr(sys,'argv',['deploy.py','rollback','--config',str(conf),'--manifest',str(m),
        '--trusted-config-sha256',contracts.digest(conf),'--trusted-manifest-sha256',contracts.digest(m),
        '--rollback-policy',str(policy_path),'--rollback-policy-sha256',contracts.digest(policy_path),
        '--rollback-evidence',str(evidence),'--retained-migrations',str(retained),
        *cli_assets(tmp_path,values,packet)])
    target={'policy':policy_path,'evidence':evidence,'sql':next(retained.glob('0009_*.sql'))}[attacked]
    captured=[];capture=contracts.capture
    def attack(path,**kwargs):
        data=capture(path,**kwargs);captured.append(path)
        if path==target:path.write_bytes(b'UNREVIEWED REPLACEMENT')
        return data
    monkeypatch.setattr(deploy,'capture',attack)
    from infrastructure.docker import check_release
    monkeypatch.setattr(deploy,'release_errors',lambda *a,**k:[])
    monkeypatch.setattr(deploy,'verify',lambda *a:None)
    calls=[]
    def execute(argv,env=None):
        calls.append(argv)
        if 'db-rollback-preflight' in argv:
            p=contracts.load(Path(env['VPS_ROLLBACK_POLICY_FILE']),env['VPS_ROLLBACK_POLICY_SHA256'])
            observed=db_guard.inspect_database(Connection(RollbackCursor(42,history)),module,older,
                rollback_policy=p,retained_directory=Path(env['VPS_RETAINED_MIGRATIONS']),
                compatibility_evidence=Path(env['VPS_ROLLBACK_EVIDENCE_FILE']))
            assert observed==policy['observed']
            return json.dumps(observed)
        return ''
    operation=deploy.execute_operation
    monkeypatch.setattr(deploy,'execute_operation',lambda a,c,m,r:operation(a,c,m,r,execute))
    deploy.main()
    assert captured.count(target)==1
    assert any('up' in c and 'api' in c for c in calls)
    assert not any('db-migrate' in c for c in calls)

def test_handoff_reflects_current_source_and_preserves_real_unknowns():
    document=(ROOT/'docs/operations/vps-github-images.md').read_text()
    assert 'only accepts legacy' not in document
    assert 'if not self.locker_base_url.strip() and not self.redis_url.strip():' in (ROOT/'apps/api/src/core/config.py').read_text()
    for term in ('IdP','costs','backup/restore','release approval','No production PASS','independent review'):
        assert term in document

@pytest.mark.parametrize('version',['','latest','v0.25','0.25.0','v01.25.0','v0.25.0-rc1','https://evil/bin'])
def test_buildx_refuses_mutable_or_invalid_version(version):
    with pytest.raises(contracts.Refusal):buildx_binary.inputs(version,D)

@pytest.mark.parametrize('failure',['checksum','empty','version'])
def test_buildx_checksum_checked_before_any_execution(tmp_path,failure):
    data=b'TEST ONLY synthetic Buildx bytes'
    h=hashlib.sha256(data).hexdigest()
    calls=[]
    def run(argv):
        calls.append(argv)
        return 'github.com/docker/buildx v0.24.0 '+SOURCE
    with pytest.raises(contracts.Refusal):
        buildx_binary.install('v0.25.0',D if failure=='checksum' else h,tmp_path,
                              download=lambda url:b'' if failure=='empty' else data,run=run)
    assert bool(calls)==(failure=='version')

def test_reviewed_buildx_binary_records_actual_bytes_and_version(tmp_path):
    data=b'TEST ONLY synthetic executable bytes';h=hashlib.sha256(data).hexdigest()
    def run(argv):
        assert Path(argv[0]).read_bytes()==data
        return 'github.com/docker/buildx v0.25.0 '+SOURCE
    record=buildx_binary.install('v0.25.0',h,tmp_path,download=lambda url:data,run=run)
    assert record['sha256']==h and record['version']=='v0.25.0'

@pytest.mark.parametrize('layout',['wrapped','index','application'])
@pytest.mark.parametrize('artifact',[False,True])
def test_buildkit_named_metadata_application_digest_distinct_from_index(tmp_path,monkeypatch,layout,artifact):
    monkeypatch.setattr(publish_candidate,'OUT',tmp_path)
    path,d=archive(tmp_path,layout=layout,artifact=artifact)
    app=publish_candidate.oci_evidence(path,d,image=IMAGE,source=SOURCE,builder=BUILDER,review=construction_review())
    assert (app==d)==(layout=='application')

@pytest.mark.parametrize('layout',['index','application'])
@pytest.mark.parametrize('bad',['name','subject_digest','empty','source','revision','dockerfile','builder',
                               'materials','build_steps','packages','config_revision','platform','attachment','directory'])
def test_well_hashed_unrelated_or_empty_oci_metadata_refused(tmp_path,monkeypatch,layout,bad):
    monkeypatch.setattr(publish_candidate,'OUT',tmp_path)
    path,d=archive(tmp_path,layout=layout,bad=bad)
    with pytest.raises(contracts.Refusal):
        publish_candidate.oci_evidence(path,d,image=IMAGE,source=SOURCE,builder=BUILDER,review=construction_review())
    assert not (tmp_path/'sbom.json').exists() and not (tmp_path/'provenance.json').exists()

def test_workflow_requires_reviewed_buildx_and_names_oci_target():
    job=yaml.safe_load((ROOT/'.github/workflows/publish-images.yml').read_text())['jobs']['candidate']
    assert job['env']['BUILDX_VERSION']=='${{ vars.RICK_BUILDX_VERSION }}'
    assert job['env']['BUILDX_SHA256']=='${{ vars.RICK_BUILDX_SHA256 }}'
    steps=job['steps']
    install=next(i for i,s in enumerate(steps) if s.get('run')=='python3 infrastructure/vps/buildx_binary.py')
    create=next(i for i,s in enumerate(steps) if 'docker buildx create' in s.get('run',''))
    build=next(i for i,s in enumerate(steps) if s.get('id')=='build')
    assert install < create < build
    assert 'name=ghcr.io/' in steps[build]['with']['outputs']
    assert 'version=v0.2,builder-id=' in steps[build]['with']['provenance']
    assert 'buildx_binary' in (HERE/'publish_candidate.py').read_text()


def test_image9_schema10_rollback_requires_reviewed_forward_schema(tmp_path):
    module,older,retained,history,policy,values=rollback_fixture(tmp_path,target_version=9,retained_version=10)
    db_guard.validate_rollback_inputs(policy,values,manifest())
    result=db_guard.inspect_database(Connection(RollbackCursor(42,history)),module,older,
        rollback_policy=policy,retained_directory=retained,compatibility_evidence=tmp_path/'compatibility.json')
    assert result==policy['observed'] and result['pending']==[]
    with pytest.raises(RuntimeError,match='unknown version'):
        db_guard.inspect_database(Connection(Cursor(42,history)),module,older)
