"""V3 admission discriminators. Synthetic contracts confer no review authority.

Actual private file capture is exercised; all operation/publication effects are
bounded callbacks. No Docker, sockets, registry, provider or database calls.
"""
from __future__ import annotations
import argparse
import base64
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import pytest
import yaml
import assets
import contracts
import construction_contract as cc
import db_guard
import deploy
import publish_candidate as pub
from test_safety import (D, SOURCE, IMAGE, BUILDER, ROOT, archive, args, config, config_file,
                         manifest, migration_fixture, construction_fixture, construction_review)
from test_rework1 import rollback_fixture
from test_support import clean_scan


def rewrite(tmp_path, mutate, *, wrapped=False):
    path,_=archive(tmp_path,layout='wrapped' if wrapped else 'index',artifact=True)
    with tarfile.open(path) as tar:
        files={m.name:tar.extractfile(m).read() for m in tar.getmembers()}
    def obj(d):return json.loads(files['blobs/sha256/'+d['digest'].split(':')[1]])
    def put(value,descriptor):
        data=json.dumps(value,separators=(',',':')).encode();h=hashlib.sha256(data).hexdigest()
        files['blobs/sha256/'+h]=data
        d=copy.deepcopy(descriptor);d.update(digest='sha256:'+h,size=len(data));return d
    outer=json.loads(files['index.json']);root=obj(outer['manifests'][0]) if wrapped else outer
    mutate(root,obj,put,files,outer)
    if wrapped:
        d=put(root,outer['manifests'][0]);outer['manifests'][0]=d
        files['index.json']=json.dumps(outer,separators=(',',':')).encode();built=d['digest']
    else:
        files['index.json']=json.dumps(root,separators=(',',':')).encode()
        built='sha256:'+hashlib.sha256(files['index.json']).hexdigest()
    reachable = {'index.json','oci-layout'}
    def walk(descriptor):
        name='blobs/sha256/'+descriptor['digest'].split(':')[1]
        if name in reachable:return
        reachable.add(name)
        try:value=json.loads(files[name])
        except (ValueError,UnicodeError):return
        if isinstance(value,dict):
            for child in value.get('manifests',[])+value.get('layers',[]):walk(child)
            if isinstance(value.get('config'),dict) and 'digest' in value['config']:walk(value['config'])
    for descriptor in json.loads(files['index.json'])['manifests']:walk(descriptor)
    files={name:data for name,data in files.items() if name in reachable}
    with tarfile.open(path,'w') as tar:
        for name,data in files.items():
            m=tarfile.TarInfo(name);m.size=len(data);tar.addfile(m,io.BytesIO(data))
    return path,built


def admit(tmp_path,monkeypatch,mutate=None,**kw):
    monkeypatch.setattr(pub,'OUT',tmp_path)
    path,built=rewrite(tmp_path,mutate or (lambda *a:None),**kw)
    return pub.oci_evidence(path,built,image=IMAGE,source=SOURCE,builder=BUILDER,review=construction_review())


@pytest.mark.parametrize('attack',['arm64','second_amd64','no_platform','unknown_platform','nested_index',
                                 'duplicate','wrapper_sibling','disguised_runnable','unattached',
                                 'attestation_subject_size','unknown_layer','wrong_layer_subject','layer_corruption'])
def test_closed_published_inventory_rejects_every_uncovered_member(tmp_path,monkeypatch,attack):
    def mutate(root,obj,put,files,outer):
        app,att=root['manifests']
        if attack in {'arm64','second_amd64','no_platform','unknown_platform','unattached'}:
            data=obj(app);c=obj(data['config']);c['config']['Labels']['org.opencontainers.image.revision']='c'*40
            data['config']=put(c,data['config']);extra=put(data,app)
            if attack=='arm64':extra['platform']['architecture']='arm64'
            if attack=='no_platform':extra.pop('platform')
            if attack=='unknown_platform':extra['platform']={'os':'unknown','architecture':'unknown'}
            if attack=='unattached':extra['annotations']={'vnd.docker.reference.digest':app['digest']}
            root['manifests'].append(extra)
        elif attack=='nested_index':
            extra=put({'schemaVersion':2,'manifests':[app]},dict(app,mediaType='application/vnd.oci.image.index.v1+json'))
            root['manifests'].append(extra)
        elif attack=='duplicate':root['manifests'].append(copy.deepcopy(app))
        elif attack=='wrapper_sibling':outer['manifests'].append(copy.deepcopy(app))
        elif attack=='layer_corruption':
            d=obj(app)['layers'][0]['digest'];files['blobs/sha256/'+d.split(':')[1]]=b'x'*len(files['blobs/sha256/'+d.split(':')[1]])
        else:
            a=obj(att)
            if attack=='disguised_runnable':a['config']=obj(app)['config']
            if attack=='attestation_subject_size':a['subject']['size']+=1
            if attack=='unknown_layer':a['layers'].append(put({'TEST':'unknown'},dict(a['layers'][0],annotations={'in-toto.io/predicate-type':'https://example.org/unknown'})))
            if attack=='wrong_layer_subject':
                statement=obj(a['layers'][0]);statement['subject'][0]['digest']['sha256']='f'*64
                a['layers'][0]=put(statement,a['layers'][0])
            root['manifests'][1]=put(a,att)
    with pytest.raises(contracts.Refusal):admit(tmp_path,monkeypatch,mutate,wrapped=attack=='wrapper_sibling')
    assert not (tmp_path/'construction-binding.json').exists()
    assert not (tmp_path/'sbom.json').exists()


def test_single_runnable_and_strictly_attached_complete_evidence_are_healthy(tmp_path,monkeypatch):
    app=admit(tmp_path,monkeypatch)
    inventory=contracts.load(tmp_path/'oci-inventory.json');binding=contracts.load(tmp_path/'construction-binding.json')
    assert len(inventory['runnable'])==1 and inventory['runnable'][0]['digest']==app
    assert binding['parameters']==construction_fixture()[0]['parameters']
    assert binding['policy_sha256']==construction_review()[1]
    pub.scan_coverage(clean_scan(inventory['runnable'][0]['config_digest']),inventory)


@pytest.mark.parametrize('bad',['wrong_config','missing_id','blocked_high','blocked_critical'])
def test_scan_coverage_identity_and_blocked_findings_refused(tmp_path,monkeypatch,bad):
    admit(tmp_path,monkeypatch);inventory=contracts.load(tmp_path/'oci-inventory.json')
    report=clean_scan(inventory['runnable'][0]['config_digest'])
    if bad=='wrong_config':report['Metadata']['ImageID']='sha256:'+'f'*64
    if bad=='missing_id':report['Metadata'].pop('ImageID')
    if bad.startswith('blocked_'):report['Results'][0]['Vulnerabilities']=[{'VulnerabilityID':'TEST-ONLY','PkgName':'TEST ONLY libc','Severity':bad.removeprefix('blocked_').upper()}]
    with pytest.raises(contracts.Refusal):pub.scan_coverage(report,inventory)


@pytest.mark.parametrize('attack',['base_arg','extra_arg','missing_arg','material_hash','extra_material','missing_material',
    'recipe','embedded_dockerfile','mapping','incomplete_materials','local_hint_only','remote_context','source_digest','entrypoint'])
def test_provenance_must_equal_reviewed_inputs_not_shape_or_vcs_hint(tmp_path,monkeypatch,attack):
    def mutate(root,obj,put,*unused):
        att=root['manifests'][1];a=obj(att);layer=a['layers'][1];statement=obj(layer);p=statement['predicate']
        if attack=='base_arg':p['invocation']['parameters']['args']['build-arg:PYTHON_IMAGE']='docker.io/test-only/other@sha256:'+'f'*64
        if attack=='extra_arg':p['invocation']['parameters']['args']['build-arg:INJECTED']='yes'
        if attack=='missing_arg':p['invocation']['parameters']['args'].pop('build-arg:PYTHON_IMAGE')
        if attack=='material_hash':p['materials'][1]['digest']['sha256']='f'*64
        if attack=='extra_material':p['materials'].append({'uri':'pkg:docker/unknown','digest':{'sha256':'f'*64}})
        if attack=='missing_material':p['materials'].pop()
        if attack=='recipe':p['buildConfig']['llbDefinition'][0]['op']['Op']={'exec':{'meta':{'args':['sh','-c','TEST ONLY different recipe']}}}
        if attack=='embedded_dockerfile':p['metadata'][cc.META]['source']['infos'][0]['data']=base64.b64encode(b'FROM TEST ONLY other').decode()
        if attack=='mapping':p['metadata'][cc.META]['source']['locations']['step0']['locations'][0]['sourceIndex']=5
        if attack=='incomplete_materials':p['metadata']['completeness']['materials']=False
        if attack=='local_hint_only':p['invocation']['configSource']={'entryPoint':'api.Dockerfile'}
        if attack=='remote_context':p['invocation']['configSource']['uri']='https://github.com/evil/fork.git#'+SOURCE
        if attack=='source_digest':p['invocation']['configSource']['digest']['sha1']='c'*40
        if attack=='entrypoint':p['invocation']['configSource']['entryPoint']='infrastructure/docker/worker.Dockerfile'
        a['layers'][1]=put(statement,layer);root['manifests'][1]=put(a,att)
    with pytest.raises(contracts.Refusal):admit(tmp_path,monkeypatch,mutate)
    assert not (tmp_path/'provenance.json').exists()


def test_local_vcs_hint_has_no_authority_over_verified_remote_context(tmp_path,monkeypatch):
    def mutate(root,obj,put,*unused):
        a=obj(root['manifests'][1]);layer=a['layers'][1];statement=obj(layer)
        statement['predicate']['metadata'][cc.META]['vcs']={'source':'unverified client hint','revision':'unverified'}
        a['layers'][1]=put(statement,layer);root['manifests'][1]=put(a,root['manifests'][1])
    assert admit(tmp_path,monkeypatch,mutate)


@pytest.mark.parametrize('attack',['no_review','wrong_review_hash','different_review_bytes','different_dockerfile_bytes',
                                 'missing_recipe_hash','missing_base_mapping','unreviewed_local_sources','unknown_policy_key'])
def test_trusted_review_cannot_be_omitted_echoed_or_replaced(tmp_path,monkeypatch,attack):
    path,built=archive(tmp_path);monkeypatch.setattr(pub,'OUT',tmp_path)
    data,h,dfile=construction_review();p=json.loads(data)
    if attack=='no_review':review=None
    else:
        if attack=='wrong_review_hash':h='0'*64
        if attack=='different_review_bytes':data=data+b' '
        if attack=='different_dockerfile_bytes':dfile+=b'\n'
        if attack=='missing_recipe_hash':p.pop('build_config_sha256')
        if attack=='missing_base_mapping':p['base_materials'].pop('PYTHON_IMAGE')
        if attack=='unreviewed_local_sources':p['parameters']['locals']=['context']
        if attack=='unknown_policy_key':p['approved']=True
        if attack in {'missing_recipe_hash','missing_base_mapping','unreviewed_local_sources','unknown_policy_key'}:
            data=json.dumps(p).encode();h=hashlib.sha256(data).hexdigest()
        review=data,h,dfile
    with pytest.raises(contracts.Refusal):pub.oci_evidence(path,built,image=IMAGE,source=SOURCE,builder=BUILDER,review=review)


def test_matching_mapping_hash_cannot_substitute_other_dockerfile():
    policy,recipe,mapping=construction_fixture()
    mapping['infos'][0]['data']=base64.b64encode(b'TEST ONLY unreviewed Dockerfile').decode()
    policy['source_mapping_sha256']=cc.canonical_sha256(mapping)
    predicate={'invocation':{'configSource':policy['context'],'parameters':policy['parameters']},
        'materials':policy['materials'],'buildConfig':recipe,'metadata':{
            'completeness':{'parameters':True,'materials':True},cc.META:{'source':mapping}}}
    with pytest.raises(contracts.Refusal,match='hash mismatch'):cc.verify_recipe(predicate,policy)


def finish_plan(tmp_path,monkeypatch,plan):
    a=args(tmp_path,'migrate');p=tmp_path/'plan.json';p.write_text(json.dumps(plan));p.chmod(0o600)
    a.plan=p;a.plan_sha256=contracts.digest(p);a.manifest=tmp_path/'release.json'
    a.manifest.write_text(json.dumps(manifest()))
    from infrastructure.docker import check_release
    monkeypatch.setattr(deploy,'release_errors',lambda *a,**kw:[])
    calls=[];snapshots=[]
    def snapshot(name,data):
        path=tmp_path/name;path.write_bytes(data);path.chmod(0o600);snapshots.append(path);return path
    monkeypatch.setattr(deploy,'execute_operation',lambda *a:calls.append(a))
    return a,calls,snapshots,lambda:deploy.finish(a,config(tmp_path),manifest(),contracts.images(manifest()),snapshot,str(tmp_path))


@pytest.mark.parametrize('existing',[False,True])
def test_complete_migration_plan_authorized_before_effect_boundary(tmp_path,monkeypatch,existing):
    plan=migration_fixture(existing);a,calls,snapshots,invoke=finish_plan(tmp_path,monkeypatch,plan)
    invoke();assert len(calls)==1 and snapshots
    db_guard.authorize(plan,copy.deepcopy(plan['observed']))
    changed=copy.deepcopy(plan['observed']);changed['pending'][0]['sha256']='f'*64
    with pytest.raises(contracts.Refusal,match='inventory changed'):db_guard.authorize(plan,changed)


PLAN_ATTACKS=['only_schema_auth','missing_maintenance','missing_backup','missing_compatibility','missing_observed',
    'wrong_auth','unknown_key','observation_string','observation_missing_schema','observation_missing_readonly',
    'observation_missing_state','observation_missing_history','observation_missing_pending','not_readonly','bad_state',
    'history_string','pending_string','row_missing_checksum','bad_checksum','duplicate_version','gap','empty_pending',
    'no_existing_history','no_maintenance','integer_maintenance','blank_backup','integer_backup','no_compatibility',
    'integer_compatibility','empty_with_history','empty_without_decisions']


@pytest.mark.parametrize('attack',PLAN_ATTACKS)
def test_malformed_or_unauthorized_plan_never_reaches_effect_boundary(tmp_path,monkeypatch,attack):
    plan=migration_fixture();o=plan['observed']
    if attack=='only_schema_auth':plan={k:plan[k] for k in ('schema','authorization')}
    if attack.startswith('missing_'):plan.pop({'maintenance':'maintenance_window','backup':'verified_backup_id','compatibility':'backward_compatible','observed':'observed'}[attack.removeprefix('missing_')])
    if attack=='wrong_auth':plan['authorization']='DO_NOT_APPLY'
    if attack=='unknown_key':plan['approved']=True
    if attack=='observation_string':plan['observed']='TEST ONLY'
    if attack.startswith('observation_missing_'):o.pop({'readonly':'read_only','state':'database_state'}.get(attack.removeprefix('observation_missing_'),attack.removeprefix('observation_missing_')))
    if attack=='not_readonly':o['read_only']=False
    if attack=='bad_state':o['database_state']='UNKNOWN'
    if attack=='history_string':o['history']='TEST ONLY'
    if attack=='pending_string':o['pending']='TEST ONLY'
    if attack=='row_missing_checksum':o['pending'][0].pop('sha256')
    if attack=='bad_checksum':o['pending'][0]['sha256']='not-a-hash'
    if attack=='duplicate_version':o['pending'][0]['version']='0007'
    if attack=='gap':o['pending'][0]['version']='0009'
    if attack=='empty_pending':o['pending']=[]
    if attack=='no_existing_history':o['history']=[]
    if attack=='no_maintenance':plan['maintenance_window']=False
    if attack=='integer_maintenance':plan['maintenance_window']=1
    if attack=='blank_backup':plan['verified_backup_id']='  '
    if attack=='integer_backup':plan['verified_backup_id']=1
    if attack=='no_compatibility':plan['backward_compatible']=False
    if attack=='integer_compatibility':plan['backward_compatible']=1
    if attack=='empty_with_history':o['database_state']='EMPTY'
    if attack=='empty_without_decisions':plan=migration_fixture(False);plan.pop('maintenance_window')
    a,calls,snapshots,invoke=finish_plan(tmp_path,monkeypatch,plan)
    with pytest.raises(contracts.Refusal):invoke()
    assert calls==[] and snapshots==[]


def test_direct_migrate_boundary_also_denies_incomplete_plan_before_any_callbacks(tmp_path,monkeypatch):
    a=args(tmp_path,'migrate');a.plan=tmp_path/'plan';a.plan.write_text('{}');a.plan.chmod(0o600);a.plan_sha256=contracts.digest(a.plan)
    calls=[]
    with pytest.raises(contracts.Refusal):deploy.execute_operation(a,config(tmp_path),manifest(),contracts.images(manifest()),lambda *a:calls.append(a))
    assert calls==[]


@pytest.mark.parametrize('site',['finish','stage'])
@pytest.mark.parametrize('attack',['public','hardlink'])
def test_both_retained_sql_capture_sites_refuse_real_unprotected_inputs(tmp_path,monkeypatch,site,attack):
    _,_,retained,_,policy,values=rollback_fixture(tmp_path)
    for p in retained.iterdir():p.chmod(0o600)
    evidence=tmp_path/'compatibility.json';evidence.chmod(0o600)
    p=tmp_path/'policy.json';p.write_text(json.dumps(policy));p.chmod(0o600)
    sql=next(retained.glob('0009_*.sql'))
    # Healthy exact bytes, own UID and sole link pass the real policy first.
    assert contracts.capture(sql,private=True)==sql.read_bytes()
    if attack=='public':sql.chmod(0o644)
    else:os.link(sql,tmp_path/'retained-hardlink')
    a=args(tmp_path,'rollback');a.rollback_policy=p;a.rollback_policy_sha256=contracts.digest(p)
    a.rollback_evidence=evidence;a.retained_migrations=retained
    packet=manifest();packet['rollout']={'rollback':{'migration_compatibility':'PASS','evidence':'TEST ONLY'}}
    calls=[]
    if site=='stage':
        with pytest.raises(contracts.Refusal):
            with assets.stage(a,values,packet):calls.append('admitted')
    else:
        a.manifest=tmp_path/'release';a.manifest.write_text(json.dumps(packet))
        from infrastructure.docker import check_release
        monkeypatch.setattr(deploy,'release_errors',lambda *a,**kw:[])
        monkeypatch.setattr(deploy,'execute_operation',lambda *a:calls.append('admitted'))
        snapdir=tmp_path/'snapshots';snapdir.mkdir(mode=0o700)
        def snapshot(name,data):
            q=snapdir/name;q.write_bytes(data);q.chmod(0o600);return q
        with pytest.raises(contracts.Refusal):deploy.finish(a,values,packet,contracts.images(packet),snapshot,str(snapdir))
    assert calls==[]


@pytest.mark.parametrize('attack',['mismatch','wrong_user','missing_user','external_host','wrong_port','invalid_port',
                                 'empty_port','wrong_db','no_db','query','fragment','bad_percent','invalid_utf8'])
def test_redis_identity_and_decoded_password_refused_before_effects(tmp_path,monkeypatch,attack):
    values=config(tmp_path)
    variants={'mismatch':'rediss://default:different@redis/0','wrong_user':'rediss://other:example@redis/0',
        'missing_user':'rediss://:example@redis/0','external_host':'rediss://default:example@external/0',
        'wrong_port':'rediss://default:example@redis:6380/0','invalid_port':'rediss://default:example@redis:notaport/0',
        'empty_port':'rediss://default:example@redis:/0','wrong_db':'rediss://default:example@redis/1',
        'no_db':'rediss://default:example@redis','query':'rediss://default:example@redis/0?x=y',
        'fragment':'rediss://default:example@redis/0#x','bad_percent':'rediss://default:exam%ple@redis/0',
        'invalid_utf8':'rediss://default:%ff@redis/0'}
    values['RICK_REDIS_URL']=variants[attack];calls=[]
    with pytest.raises(contracts.Refusal):deploy.execute_operation(args(tmp_path),values,manifest(),contracts.images(manifest()),lambda *a:calls.append(a))
    assert calls==[]


@pytest.mark.parametrize('url,password',[('rediss://default:example@redis/0','example'),
    ('rediss://default:example@redis:6379/0','example'),('rediss://default:exam%70le@redis/0','example'),
    ('rediss://default:TEST%3AONLY%40password@redis/0','TEST:ONLY@password')])
def test_redis_percent_decoded_matching_password_and_closed_endpoint_are_healthy(tmp_path,url,password):
    values=config(tmp_path);values.update(RICK_REDIS_URL=url,REDIS_PASSWORD=password)
    assert deploy.parse_env(config_file(tmp_path,values).read_bytes())==values


def test_workflow_remote_context_and_review_inputs_precede_builder():
    job=yaml.safe_load((ROOT/'.github/workflows/publish-images.yml').read_text())['jobs']['candidate']
    steps=job['steps'];check=next(i for i,s in enumerate(steps) if s.get('run')=='python3 infrastructure/vps/construction_contract.py')
    create=next(i for i,s in enumerate(steps) if 'docker buildx create' in s.get('run',''))
    build=next(s for s in steps if s.get('id')=='build')
    assert check<create
    assert build['with']['context']=='https://github.com/'+contracts.REPO+'.git#${{ inputs.source_sha }}'
    assert job['env']['CONSTRUCTION_POLICY_SHA256']=='${{ vars[matrix.policy_hash_var] }}'
    assert {s['service'] for s in job['strategy']['matrix']['include']}==set(contracts.SERVICES)
    assert not any('approved' in s.get('run','').lower() for s in steps)


@pytest.mark.skipif(os.lstat('/tmp').st_uid not in {0,os.geteuid()},
                   reason='NOT_RUN: fresh child process sees unmapped host ancestor owner; Parent mapped-root CLI required')
def test_offline_executable_archive_contract_in_protected_snapshot(tmp_path):
    # Execute the public CLI in a separate fresh Python process, using only
    # owned installer copies and reviewed byte fixtures. No build invocation.
    installer=tmp_path/'installer'
    for name in ('contracts.py','construction_contract.py','publish_candidate.py'):
        p=installer/'infrastructure/vps'/name;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes((ROOT/'infrastructure/vps'/name).read_bytes());p.chmod(0o600)
    dfile=installer/'infrastructure/docker/api.Dockerfile';dfile.parent.mkdir(parents=True)
    dfile.write_bytes(construction_review()[2]);dfile.chmod(0o600)
    data,h,_=construction_review();policy=tmp_path/'TEST_ONLY_policy.json';policy.write_bytes(data);policy.chmod(0o600)
    path,built=archive(tmp_path,layout='index')
    env={'PATH':'/usr/bin:/bin','HOME':str(tmp_path),'PYTHONDONTWRITEBYTECODE':'1','LANG':'C.UTF-8'}
    cmd=[sys.executable,'-B',str(installer/'infrastructure/vps/construction_contract.py'),
         '--policy',str(policy),'--trusted-policy-sha256',h,'--service','api','--source',SOURCE,
         '--archive',str(path),'--built-digest',built,'--builder',BUILDER,'--output',str(tmp_path/'evidence')]
    result=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr
    assert (tmp_path/'evidence/construction-binding.json').is_file()
    bad=list(cmd);bad[bad.index('--trusted-policy-sha256')+1]='0'*64
    result=subprocess.run(bad,env=env,capture_output=True,text=True,timeout=20)
    assert result.returncode==2 and 'refused' in result.stderr


@pytest.mark.parametrize('site',['finish','stage'])
def test_sql_owner_policy_negative_is_explicitly_unit_evidence(tmp_path,monkeypatch,site):
    # Real owner stat + synthetic trusted-caller UID: tests owner policy, not
    # actual cross-UID DAC. Parent's multi-UID proof remains separate authority.
    sql=tmp_path/'0001_test.sql';sql.write_bytes(b'-- TEST ONLY');sql.chmod(0o600)
    real_uid=os.geteuid();assert real_uid!=0
    with monkeypatch.context() as m:
        from types import SimpleNamespace
        original=contracts.os.fstat
        def foreign_leaf(fd):
            info=original(fd)
            if (info.st_dev,info.st_ino)==(sql.stat().st_dev,sql.stat().st_ino):
                fields={name:getattr(info,name) for name in dir(info) if name.startswith('st_')}
                fields['st_uid']=real_uid+1234;return SimpleNamespace(**fields)
            return info
        m.setattr(contracts.os,'fstat',foreign_leaf)
        with pytest.raises(contracts.Refusal,match='trusted sole owner'):contracts.capture(sql,private=True)
    # Both call sites must select this same private policy; AST connects it.
    import ast
    module=deploy if site=='finish' else assets
    tree=ast.parse(Path(module.__file__).read_bytes())
    calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)
           and n.func.id=='capture' and n.args and isinstance(n.args[0],ast.BinOp)
           and ((isinstance(n.args[0].left,ast.Name) and n.args[0].left.id=='original')
                or (isinstance(n.args[0].left,ast.Attribute) and n.args[0].left.attr=='retained_migrations'))]
    assert calls and all(any(k.arg=='private' and isinstance(k.value,ast.Constant) and k.value.value is True
                             for k in n.keywords) for n in calls)


def test_existing_inventory_drift_stops_apply_and_retains_bundle(tmp_path,monkeypatch):
    a=args(tmp_path,'migrate');plan=migration_fixture()
    a.plan=tmp_path/'plan';a.plan.write_text(json.dumps(plan));a.plan.chmod(0o600);a.plan_sha256=contracts.digest(a.plan)
    calls=[];mounts=[]
    observed=copy.deepcopy(plan['observed']);observed['pending'][0]['sha256']='f'*64
    monkeypatch.setattr(deploy,'verify',lambda *a:None)
    def execute(argv,env=None):
        calls.append(argv)
        if argv[:2]==['docker','compose']:
            p=Path(argv[argv.index('-f')+1]);mounts.append(p)
        return json.dumps(observed) if 'db-preflight' in argv else ''
    with pytest.raises(contracts.Refusal,match='inventory changed'):
        deploy.execute_operation(a,config(tmp_path),manifest(),contracts.images(manifest()),execute)
    assert not any('stop' in c or 'up' in c for c in calls)
    assert not any('db-migrate' in c for c in calls)
    assert mounts and all(p.exists() for p in mounts) and a.plan.exists()
    assert contracts.digest(a.plan)==a.plan_sha256
