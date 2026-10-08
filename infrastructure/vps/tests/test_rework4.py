"""V4 executable boundary discriminators; all authorities are synthetic inputs.

Callbacks replace every external effect. Staging unit tests in a one-UID
sandbox model installer authorization only; real separated-UID DAC is separate.
"""
from __future__ import annotations
import base64
import copy
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import pytest
import admission
import assets
import contracts
import db_guard
import deploy
import fresh_inventory
import publish_candidate as pub
import trusted_code
from test_safety import (SOURCE,D,IMAGE,BUILDER,ROOT,archive,construction_review,config,args,manifest,migration_fixture,signed)
from test_support import admission_fixture,clean_scan

REAL_INSTALLER_OWNER = assets.installer_owner


def test_closed_executable_imports_and_policy_survive_live_repository_replacement(tmp_path):
    a=args(tmp_path);packet,files,_=a.captured_assets
    folder=tmp_path/'checker';folder.mkdir(mode=0o700)
    for name in ('infrastructure/docker/check_release.py','scripts/state_of_art/json_boundary.py',
                 'infrastructure/docker/rollout-policy.json'):
        (assets.ROOT/name).write_bytes(b'raise RuntimeError("UNAUTHENTICATED")')
    a.manifest=tmp_path/'manifest';a.manifest.write_bytes(b'{}')
    errors=trusted_code.release_errors(a,folder)
    assert errors and any('schema' in error for error in errors)
    assert (folder/'infrastructure/docker/rollout-policy.json').read_bytes()==files['infrastructure/docker/rollout-policy.json']
    loaded=trusted_code.modules(packet,files,folder)
    assert loaded['json_boundary'].loads_json(b'{"test":1}')=={'test':1}
    with pytest.raises(json.JSONDecodeError):loaded['json_boundary'].loads_json(b'{"test":1,"test":2}')
    with pytest.raises(json.JSONDecodeError):loaded['json_boundary'].loads_json(b'{"test":NaN}')


@pytest.mark.parametrize('path',['infrastructure/docker/check_release.py','scripts/state_of_art/json_boundary.py',
    'infrastructure/docker/rollout-policy.json','infrastructure/vps/db_guard.py','infrastructure/vps/admission.py'])
def test_captured_executable_or_policy_drift_refused_before_execution(tmp_path,path):
    a=args(tmp_path);packet,files,_=a.captured_assets
    files=dict(files);files[path]+=b'\nraise RuntimeError("TEST ONLY mutated authority")\n'
    with pytest.raises(contracts.Refusal,match='hash mismatch'):trusted_code.modules(packet,files,tmp_path)


@pytest.mark.parametrize('private',[False,True])
@pytest.mark.parametrize('attack',['hardlink','owner','group_parent','foreign_parent','world_parent','leaf_symlink'])
def test_all_capture_roles_require_solelink_owner_and_protected_ancestors(tmp_path,monkeypatch,private,attack):
    parent=tmp_path/'parent';parent.mkdir(mode=0o700)
    path=parent/'input';path.write_bytes(b'TEST ONLY input');path.chmod(0o600)
    assert contracts.capture(path,private=private)==b'TEST ONLY input'
    if attack=='hardlink':os.link(path,tmp_path/'other-link')
    elif attack=='owner':monkeypatch.setattr(contracts.os,'geteuid',lambda:os.getuid()+54321)
    elif attack=='group_parent':parent.chmod(0o770)
    elif attack=='world_parent':parent.chmod(0o777)
    elif attack=='foreign_parent':
        original=contracts.os.fstat
        def fstat(fd):
            info=original(fd)
            if (info.st_dev,info.st_ino)==(parent.stat().st_dev,parent.stat().st_ino):
                values=list(info);values[4]=os.getuid()+54321;return os.stat_result(values)
            return info
        monkeypatch.setattr(contracts.os,'fstat',fstat)
    else:
        path.rename(parent/'original');path.symlink_to(parent/'original')
    with pytest.raises(contracts.Refusal):contracts.capture(path,private=private)


def test_real_installer_authority_requires_distinct_nonroot_operation_reader(monkeypatch):
    with monkeypatch.context() as m:
        m.setattr(assets.os,'geteuid',lambda:0)
        assert REAL_INSTALLER_OWNER((20002,20002),(20003,20003))==0
        assert REAL_INSTALLER_OWNER((20002,20002),(0,0))==0
        with pytest.raises(contracts.Refusal):REAL_INSTALLER_OWNER((0,20002),(20003,20003))
    with monkeypatch.context() as m:
        m.setattr(assets.os,'geteuid',lambda:1000)
        with pytest.raises(contracts.Refusal,match='root installer'):REAL_INSTALLER_OWNER((1000,1000),(1000,1000))


@pytest.mark.parametrize('attack',['leaf_replace','chmod','hardlink','parent_replace','append'])
def test_retained_component_binding_checked_before_every_effect(tmp_path,monkeypatch,attack):
    a=args(tmp_path);values=config(tmp_path);calls=[]
    monkeypatch.setattr(deploy,'verify',lambda *a:None)
    def execute(argv,env=None):
        calls.append(argv)
        if len(calls)==1:
            leaf=Path(argv[argv.index('-f')+1]).parent/'db_guard.py'
            if attack=='leaf_replace':
                leaf.rename(leaf.with_suffix('.old'));leaf.write_bytes(b'UNREVIEWED')
            elif attack=='chmod':leaf.chmod(0o640)
            elif attack=='append':
                leaf.chmod(0o640);leaf.write_bytes(leaf.read_bytes()+b'UNREVIEWED')
            elif attack=='hardlink':os.link(leaf,leaf.with_suffix('.link'))
            else:
                parent=leaf.parent;parent.rename(parent.with_name('old-vps'));parent.mkdir()
        return ''
    with pytest.raises(contracts.Refusal,match='snapshot'):deploy.execute_operation(a,values,manifest(),contracts.images(manifest()),execute)
    assert len(calls)==1 and not any('up' in c or 'stop' in c for c in calls)


def migrate_args(tmp_path):
    a=args(tmp_path,'migrate');plan=migration_fixture()
    a.plan=tmp_path/'plan';a.plan.write_text(json.dumps(plan));a.plan.chmod(0o600);a.plan_sha256=contracts.digest(a.plan)
    return a,plan


@pytest.mark.parametrize('drift',['none','initial','quiescent','unavailable'])
def test_current_inventory_admission_and_quiescent_recheck_order(tmp_path,monkeypatch,drift):
    a,plan=migrate_args(tmp_path);calls=[];observations=[]
    monkeypatch.setattr(deploy,'verify',lambda *a:None)
    def execute(argv,env=None):
        calls.append(argv)
        if 'db-preflight' in argv:
            if drift=='unavailable':raise contracts.Refusal('TEST ONLY readonly observation unavailable')
            observed=copy.deepcopy(plan['observed']);observations.append(len(calls)-1)
            if (drift=='initial' and len(observations)==1) or (drift=='quiescent' and len(observations)==2):
                observed['pending'][0]['sha256']='f'*64
            return json.dumps(observed)
        return ''
    invoke=lambda:deploy.execute_operation(a,config(tmp_path),manifest(),contracts.images(manifest()),execute)
    if drift=='none':invoke()
    else:
        with pytest.raises(contracts.Refusal):invoke()
    if drift in {'initial','unavailable'}:assert not any('stop' in c or 'up' in c or 'db-migrate' in c for c in calls)
    else:
        stop=next(i for i,c in enumerate(calls) if 'stop' in c)
        stores=next(i for i,c in enumerate(calls) if 'up' in c)
        assert observations[0]<stop<stores<observations[1]
        if drift=='none':assert observations[1]<next(i for i,c in enumerate(calls) if 'db-migrate' in c)
        else:assert not any('db-migrate' in c for c in calls)


def fresh_packet(a, values):
    volumes=[{'Name':values[key],'Driver':'local','Labels':{'TEST ONLY':'reviewed-empty'}} for key in fresh_inventory.VOLUMES]
    return {'schema':'rick.vps.fresh-inventory/v1','authorization':'CREATE_REVIEWED_EMPTY_DATABASE',
        'source_sha':SOURCE,'config_sha256':a.captured_assets[0]['config_sha256'],
        'deployment':{key:values[key] for key in fresh_inventory.DEPLOYMENT},'database_state':'ABSENT',
        'absence_evidence':{'reference':'TEST ONLY independently reviewed offline empty volumes','sha256':D},
        'observed':{'volumes':volumes,'containers':[]}}


@pytest.mark.parametrize('attack',['none','wrong_volume','container','unauthorized','wrong_hash','source'])
def test_fresh_absence_is_explicit_authority_plus_current_readonly_inventory(tmp_path,monkeypatch,attack):
    a=args(tmp_path,'migrate');values=config(tmp_path);plan=migration_fixture(False)
    a.plan=tmp_path/'plan';a.plan.write_text(json.dumps(plan));a.plan.chmod(0o600);a.plan_sha256=contracts.digest(a.plan)
    packet=fresh_packet(a,values)
    if attack=='unauthorized':packet['authorization']='OBSERVED'
    if attack=='source':packet['source_sha']='f'*40
    a.fresh_inventory=tmp_path/'fresh';a.fresh_inventory.write_text(json.dumps(packet));a.fresh_inventory.chmod(0o600)
    a.trusted_fresh_inventory_sha256=contracts.digest(a.fresh_inventory) if attack!='wrong_hash' else '0'*64
    monkeypatch.setattr(deploy,'verify',lambda *a:None);calls=[]
    def execute(argv,env=None):
        calls.append(argv)
        if argv[:3]==['docker','volume','inspect']:
            volumes=copy.deepcopy(packet['observed']['volumes'])
            if attack=='wrong_volume':volumes[0]['Labels']={'TEST ONLY':'changed'}
            return json.dumps(volumes)
        if 'ps' in argv:return json.dumps([] if attack!='container' else [{'TEST ONLY':'existing writer'}])
        return json.dumps(plan['observed']) if 'db-preflight' in argv else ''
    invoke=lambda:deploy.execute_operation(a,values,manifest(),contracts.images(manifest()),execute)
    if attack=='none':
        invoke();assert any('db-migrate' in c for c in calls)
        assert not any('stop' in c for c in calls)
        inspect=next(i for i,c in enumerate(calls) if c[:3]==['docker','volume','inspect'])
        assert inspect<next(i for i,c in enumerate(calls) if 'up' in c)
    else:
        with pytest.raises(contracts.Refusal):invoke()
        assert not any('stop' in c or 'up' in c or 'db-migrate' in c for c in calls)


@pytest.mark.parametrize('attack',['none','subject_name','subject_extra','construction','quality','tool_policy',
    'recipe','tool_identity','tool_image','quality_attempt','quality_source','quality_jobs','buildx','coverage','scan_policy','no_authority'])
def test_candidate_independent_identities_cannot_be_omitted_or_echoed(tmp_path,attack):
    policy=admission_fixture();envelope=signed();s=json.loads(base64.b64decode(envelope['payload']));p=s['predicate']
    if attack=='subject_name':s['subject'][0]['name']='ghcr.io/evil/other'
    if attack=='subject_extra':s['subject'].append(copy.deepcopy(s['subject'][0]))
    if attack in {'construction','quality','tool_policy'}:p.pop({'tool_policy':'tool_policy_sha256'}.get(attack,attack))
    if attack=='recipe':p['construction']['build_config_sha256']='f'*64
    if attack=='tool_identity':p['tool_policy_sha256']='f'*64
    if attack=='tool_image':p['configured_build_tools']['TRIVY_IMAGE']='docker.io/evil/scanner@sha256:'+D
    if attack=='quality_attempt':p['quality']['run_attempt']=2
    if attack=='quality_source':p['quality']['head_sha']='f'*40
    if attack=='quality_jobs':p['quality']['job_conclusions'][next(iter(p['quality']['job_conclusions']))]='skipped'
    if attack=='buildx':p['buildx_binary']['sha256']='f'*64
    if attack=='coverage':p['scan_coverage']=[]
    if attack=='scan_policy':p['scan_requirements']['language_types']=[]
    if attack=='no_authority':policy=None
    envelope['payload']=base64.b64encode(json.dumps(s).encode()).decode()
    invoke=lambda:deploy.attestations(json.dumps(envelope),SOURCE,manifest()['images'][0]['image_ref'],policy)
    if attack=='none':invoke()
    else:
        with pytest.raises(contracts.Refusal):invoke()


def test_complete_independent_policy_validation(tmp_path):
    a=args(tmp_path);data=json.dumps(admission_fixture()).encode()
    result=admission.deployment_policy(data,assets.sha(data),manifest(),a.captured_assets[1])
    assert result['source_sha']==SOURCE
    with pytest.raises(contracts.Refusal):admission.deployment_policy(data,'f'*64,manifest(),a.captured_assets[1])


@pytest.mark.parametrize('attack',['unknown','unreferenced_hash','unreferenced_manifest','symlink','hardlink','bad_layout',
    'missing_layout','extra_directory','too_many','too_large','archive_bound','trailer'])
def test_oci_archive_closure_covers_every_member_and_bound(tmp_path,monkeypatch,attack):
    path,built=archive(tmp_path);monkeypatch.setattr(pub,'OUT',tmp_path)
    # Healthy archive must pass first; remove output to detect refusal writes.
    pub.oci_evidence(path,built,image=IMAGE,source=SOURCE,builder=BUILDER,review=construction_review())
    for name in ('sbom.json','provenance.json','construction-binding.json','oci-inventory.json'):(tmp_path/name).unlink()
    with tarfile.open(path) as tar:entries=[(copy.copy(m),tar.extractfile(m).read()) for m in tar]
    if attack=='bad_layout':entries=[(m,b'{"imageLayoutVersion":"999"}' if m.name=='oci-layout' else d) for m,d in entries]
    if attack=='missing_layout':entries=[(m,d) for m,d in entries if m.name!='oci-layout']
    if attack in {'unknown','unreferenced_hash','unreferenced_manifest','symlink','hardlink','extra_directory'}:
        import hashlib
        content=b'{"schemaVersion":2,"config":{},"layers":[]}'
        name=('unknown' if attack=='unknown' else 'extraneous-dir' if attack=='extra_directory' else
              'blobs/sha256/'+('f'*64 if attack=='unreferenced_hash' else hashlib.sha256(content).hexdigest()))
        m=tarfile.TarInfo(name)
        if attack=='symlink':m.type=tarfile.SYMTYPE;m.linkname='index.json'
        if attack=='hardlink':m.type=tarfile.LNKTYPE;m.linkname='index.json'
        if attack=='extra_directory':m.type=tarfile.DIRTYPE
        entries.append((m,content if m.isfile() else b''))
    with tarfile.open(path,'w') as tar:
        for m,data in entries:m.size=len(data);tar.addfile(m,io.BytesIO(data) if m.isfile() else None)
    if attack=='too_many':monkeypatch.setattr(pub,'MAX_MEMBERS',len(entries)-1)
    if attack=='too_large':monkeypatch.setattr(pub,'MAX_MEMBER_BYTES',1)
    if attack=='archive_bound':monkeypatch.setattr(pub,'MAX_ARCHIVE_BYTES',path.stat().st_size-1)
    if attack=='trailer':
        with path.open('ab') as stream:stream.write(b'UNINVENTORIED TRAILER')
    with pytest.raises(contracts.Refusal):pub.oci_evidence(path,built,image=IMAGE,source=SOURCE,builder=BUILDER,review=construction_review())
    assert not (tmp_path/'sbom.json').exists()


@pytest.mark.parametrize('attack',['none','empty','missing','unsupported_schema','unsupported_os','no_os','no_application',
    'empty_packages','missing_packages','unsupported_analysis','wrong_config','high','unknown_severity','invalid_vulnerabilities'])
def test_substantive_scan_coverage_distinguishes_clean_from_unknown(attack):
    report=clean_scan('sha256:'+D);inventory={'runnable':[{'config_digest':'sha256:'+D}]}
    if attack=='empty':report['Results']=[]
    if attack=='missing':report.pop('Results')
    if attack=='unsupported_schema':report['SchemaVersion']=3
    if attack=='unsupported_os':report['Metadata']['OS']['Family']='TEST ONLY unknown'
    if attack=='no_os':report['Results']=report['Results'][1:]
    if attack=='no_application':report['Results']=report['Results'][:1]
    if attack=='empty_packages':report['Results'][0]['Packages']=[]
    if attack=='missing_packages':report['Results'][0].pop('Packages')
    if attack=='unsupported_analysis':report['Results'][0]['Class']='secret'
    if attack=='wrong_config':report['Metadata']['ImageID']='sha256:'+'f'*64
    if attack in {'high','unknown_severity'}:report['Results'][0]['Vulnerabilities']=[{
        'VulnerabilityID':'TEST-ONLY','PkgName':'TEST ONLY libc','Severity':'HIGH' if attack=='high' else 'UNKNOWN'}]
    if attack=='invalid_vulnerabilities':report['Results'][0]['Vulnerabilities']={}
    invoke=lambda:pub.scan_coverage(report,inventory,{'os_family':'debian','language_types':['python-pkg']})
    if attack=='none':assert invoke()=={'os_family':'debian','language_types':['python-pkg']}
    else:
        with pytest.raises(contracts.Refusal):invoke()


@pytest.mark.parametrize('key',['RICK_EXTERNAL_DATABASE_DSN','RICK_PREFLIGHT_DATABASE_DSN','RICK_MIGRATION_DATABASE_DSN'])
@pytest.mark.parametrize('port',['','5432','5433','abc','65536','empty'])
def test_every_vps_database_role_is_fixed_to_postgres5432(tmp_path,key,port):
    values=config(tmp_path);endpoint=values[key].replace('@postgres/', '@postgres'+('' if port=='' else ':' if port=='empty' else ':'+port)+'/')
    values[key]=endpoint;data=('\n'.join(k+'='+v for k,v in values.items())+'\n').encode()
    if port in {'','5432'}:assert deploy.parse_env(data)==values
    else:
        with pytest.raises(contracts.Refusal):deploy.parse_env(data)


def test_direct_database_job_refuses_wrong_port_before_driver_import(monkeypatch):
    monkeypatch.setenv('RICK_PREFLIGHT_DATABASE_DSN','postgresql://readonly:TESTONLY@postgres:5433/rick')
    monkeypatch.setattr(sys,'argv',['db_guard.py','inspect'])
    with pytest.raises(contracts.Refusal,match='5432'):db_guard.main()


def test_captured_release_checker_accepts_complete_candidate_and_refuses_unclosed_policy(tmp_path):
    a=args(tmp_path)
    packet=json.loads((ROOT/'infrastructure/docker/release-manifest.json').read_bytes())
    packet.update(status='CANDIDATE',source_revision={'value':SOURCE,'status':'CAPTURED'})
    packet['build']['status']='PASS'
    for base in packet['base_images']:
        base.update(ref='docker.io/test-only/base@sha256:'+D,status='CAPTURED')
    for image in packet['images']:
        ref=f'ghcr.io/{contracts.REPO}-{image["service"]}@sha256:{D}'
        image.update(build_status='PASS',image_ref=ref,digest='sha256:'+D,digest_status='PASS')
        image['scan'].update(status='PASS',report='TEST ONLY scan',sbom='TEST ONLY sbom',critical=0,high=0)
        image['signature'].update(status='PASS',bundle='TEST ONLY signature',identity=contracts.IDENTITY,issuer=contracts.ISSUER)
    packet['rollout']['canary']={'status':'PASS','evidence':'TEST ONLY reviewed canary'}
    packet['rollout']['rollback']={'status':'PASS','evidence':'TEST ONLY reviewed rollback',
        'previous_release_digest':'sha256:'+D,'migration_compatibility':'PASS'}
    a.manifest=tmp_path/'complete-candidate';a.manifest.write_text(json.dumps(packet));a.manifest.chmod(0o600)
    folder=tmp_path/'healthy';folder.mkdir(mode=0o700)
    assert trusted_code.release_errors(a,folder)==[]
    packet['policy_file']='uncaptured.json';a.manifest.write_text(json.dumps(packet))
    folder=tmp_path/'negative';folder.mkdir(mode=0o700)
    errors=trusted_code.release_errors(a,folder)
    assert errors and any('uncaptured policy' in error for error in errors)


@pytest.mark.parametrize('header_type',[tarfile.XHDTYPE,tarfile.XGLTYPE,tarfile.GNUTYPE_LONGNAME,tarfile.GNUTYPE_SPARSE])
def test_oci_extension_headers_are_rejected_before_payload_allocation(tmp_path,monkeypatch,header_type):
    path=tmp_path/'extension.tar'
    member=tarfile.TarInfo('TEST ONLY extension');member.type=header_type;member.size=1024*1024*1024
    with path.open('wb') as stream:stream.write(member.tobuf(format=tarfile.GNU_FORMAT));stream.write(bytes(1024))
    monkeypatch.setattr(pub,'OUT',tmp_path)
    with pytest.raises(contracts.Refusal,match='header refused'):
        pub.oci_evidence(path,'sha256:'+D,image=IMAGE,source=SOURCE,builder=BUILDER,review=construction_review())
