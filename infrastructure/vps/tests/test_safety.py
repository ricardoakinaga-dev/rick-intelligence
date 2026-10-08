from __future__ import annotations
import argparse
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import io
import gzip
import pytest
import yaml

HERE=Path(__file__).resolve().parents[1]
ROOT=HERE.parents[1]
sys.path.insert(0,str(HERE))
import contracts
import deploy
from test_support import synthetic_tls, direct_assets, cli_assets
import db_guard
import publish_guard
import publish_candidate

D='a'*64
SOURCE='b'*40

def config(tmp_path):
    result={}
    for line in (HERE/'config.env.example').read_text().splitlines():
        if line and not line.startswith('#'):
            k,_,v=line.partition('=')
            result[k]=v or 'safe-example-value'
    for key,prefix in deploy.INFRA.items():
        result[key]=prefix+'@sha256:'+D
    for key in ('TLS_STORE_CERT','TLS_STORE_KEY','TLS_STORE_CA'):
        p=tmp_path/key
        p.write_bytes(synthetic_tls()[key]); p.chmod(0o600)
        result[key]=str(p)
    result.update(VPS_DOMAIN='rick.example.org',VPS_ACME_EMAIL='ops@example.org',
        POSTGRES_USER='platform_admin',RICK_IDENTITY_POLICY='postgres-local-v1',
        RICK_OIDC_ISSUER='',RICK_OIDC_AUDIENCE='',RICK_OIDC_JWKS_URL='',
        RICK_EXTERNAL_DATABASE_DSN='postgresql://rick:example@postgres/rick',
        RICK_PREFLIGHT_DATABASE_DSN='postgresql://readonly:example@postgres/rick',
        RICK_MIGRATION_DATABASE_DSN='postgresql://migrator:example@postgres/rick',
        RICK_REDIS_URL='rediss://default:example@redis/0',REDIS_PASSWORD='example',EMBEDDING_DIMENSION='1536',
        CORS_ALLOWED_ORIGINS='https://rick.example.org',MINIO_ROOT_USER='root-user',
        RICK_OBJECT_STORE_ACCESS_KEY_ID='scoped-user')
    return result

def config_file(tmp_path,values):
    path=tmp_path/'config.env'
    path.write_text('\n'.join(k+'='+v for k,v in values.items()))
    path.chmod(0o600)
    return path

def manifest():
    return {'schema':'rick.release.manifest/v1','status':'READY_FOR_REVIEW',
        'source_revision':{'status':'CAPTURED','value':SOURCE},
        'images':[{'service':s,'image_ref':f'ghcr.io/{contracts.REPO}-{s}@sha256:{D}',
                   'digest':'sha256:'+D} for s in contracts.SERVICES]}

@pytest.mark.parametrize('ref',['--help','$(touch /tmp/pwn)','ghcr.io/evil/api@sha256:'+D,
    'ghcr.io/'+contracts.REPO+'-api:latest','ghcr.io/'+contracts.REPO+'-api@sha256:'+D+'\n',
    'ghcr.io/a/../api@sha256:'+D])
def test_malicious_and_mutable_refs(ref):
    with pytest.raises(contracts.Refusal):
        contracts.immutable(ref,'ghcr.io/'+contracts.REPO+'-api')

def test_exact_registry_and_digest_binding():
    packet=manifest()
    assert set(contracts.images(packet))==set(contracts.SERVICES)
    packet['images'][0]['digest']='sha256:'+'f'*64
    with pytest.raises(contracts.Refusal): contracts.images(packet)

def test_candidate_cannot_self_approve():
    packet=manifest();packet['status']='CANDIDATE'
    with pytest.raises(contracts.Refusal): contracts.images(packet)

def test_trusted_hash_and_duplicate_fields(tmp_path):
    path=tmp_path/'m.json';path.write_text('{"x":1,"x":2}')
    with pytest.raises(contracts.Refusal): contracts.load(path,'0'*64)
    with pytest.raises(contracts.Refusal): contracts.load(path,contracts.digest(path))

@pytest.mark.parametrize('key',['RICK_OIDC_ISSUER','RICK_OIDC_AUDIENCE','LLM_MODEL','EMBEDDING_API_KEY','POSTGRES_IMAGE'])
def test_missing_environment_before_effects(tmp_path,key):
    values=config(tmp_path);values.pop(key)
    with pytest.raises(contracts.Refusal,match='missing config'): deploy.read_env(config_file(tmp_path,values))

@pytest.mark.parametrize('key,value',[('RICK_CLINICAL_CASES_ENABLED','true'),('RICK_API_COMPOSITION','fake:factory'),
    ('LLM_BASE_URL','http://api.openai.com/v1'),('POSTGRES_VOLUME','another-project-postgres')])
def test_closed_config_and_project_scope(tmp_path,key,value):
    values=config(tmp_path);values[key]=value
    with pytest.raises(contracts.Refusal):deploy.read_env(config_file(tmp_path,values))

def test_valid_runtime_native_environment(tmp_path):
    values=config(tmp_path)
    assert deploy.read_env(config_file(tmp_path,values))==values
    values['LLM_PROVIDER']='anthropic';values['LLM_BASE_URL']='https://api.anthropic.com/v1'
    assert deploy.read_env(config_file(tmp_path,values))['LLM_PROVIDER']=='anthropic'


def test_oidc_urls_do_not_approve_local_identity(tmp_path):
    values=config(tmp_path)
    values['RICK_OIDC_ISSUER']='https://idp.example.org'
    with pytest.raises(contracts.Refusal,match='OIDC'):
        deploy.read_env(config_file(tmp_path,values))

class Cursor:
    def __init__(self,relations,history):
        self.relations=relations;self.history=history;self.sql=[];self.last=''
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def execute(self,sql,*args):self.sql.append(sql);self.last=sql
    def fetchone(self):
        if 'transaction_read_only' in self.last:return ('on',)
        if 'current_schema()' in self.last:return ('public',)
        if 'count(*)' in self.last:return (self.relations,)
        if 'to_regclass' in self.last:return (bool(self.history),)
    def fetchall(self):
        if 'migration_authorization_relations' in self.last:
            return [('public',f'test_relation_{i:04d}','r') for i in range(self.relations)]
        return self.history
class Connection:
    def __init__(self,cursor):self.c=cursor
    def cursor(self):return self.c
class Module:
    AUTHORIZATION_RELATIONS_SQL = '/* migration_authorization_relations */ SELECT test_only'
    def migration_files(self,directory):return [('0001',Path('migration.sql'),D)]
    def validate_history(self,rows,history):return {}

def test_readonly_inventory_never_mutates():
    cur=Cursor(0,[])
    observed=db_guard.inspect_database(Connection(cur),Module())
    assert observed['database_state']=='EMPTY' and observed['pending']
    assert cur.sql[0].endswith('READ ONLY')
    assert not any(word in s for s in cur.sql for word in ('CREATE ','UPDATE ','INSERT ','ALTER ','DELETE '))

def test_existing_data_is_not_assumed_empty():
    with pytest.raises(contracts.Refusal,match='existing database'):
        db_guard.inspect_database(Connection(Cursor(3,[])),Module())

def test_recognized_history_never_auto_repairs():
    with pytest.raises(contracts.Refusal,match='separate reviewed repair'):
        db_guard.inspect_database(Connection(Cursor(3,[('0001','f'*64,'rick')])),Module())

def test_migrations_require_exact_reviewed_inventory_and_backup():
    observed=migration_fixture()['observed']
    plan={'schema':'rick.vps.migration-plan/v1','authorization':'APPLY_REVIEWED_SQL','observed':observed}
    with pytest.raises(contracts.Refusal):db_guard.authorize(plan,observed)
    plan.update(maintenance_window=True,verified_backup_id='backup-verified',backward_compatible=True)
    db_guard.authorize(plan,observed)
    with pytest.raises(contracts.Refusal):db_guard.authorize(plan,dict(observed,pending=[]))

def fake_execute(pending,calls):
    def execute(argv,env=None):
        calls.append((argv,env))
        if 'db-preflight' in argv:return json.dumps({'pending':pending,'database_state':'EXISTING'})
        return ''
    return execute

def args(tmp_path,operation='install'):
    return direct_assets(argparse.Namespace(operation=operation,config=tmp_path/'config.env',plan=None,plan_sha256=None),config(tmp_path),manifest())

def test_pending_migrations_block_bootstrap_and_app_start(tmp_path,monkeypatch):
    calls=[];values=config(tmp_path);monkeypatch.setattr(deploy,'verify',lambda *a:None)
    with pytest.raises(contracts.Refusal,match='pending migrations'):
        deploy.execute_operation(args(tmp_path),values,manifest(),contracts.images(manifest()),fake_execute([1],calls))
    assert calls[0][0][-2:]==['config','--quiet']
    assert not any('db-migrate' in a or 'object-bootstrap' in a or 'vector-bootstrap' in a for a,_ in calls)
    assert not any('up' in a and 'api' in a for a,_ in calls)

def test_order_and_runtime_excludes_infrastructure_secrets(tmp_path,monkeypatch):
    calls=[];values=config(tmp_path);monkeypatch.setattr(deploy,'verify',lambda *a:None)
    runtime=[]
    fake=fake_execute([],calls)
    def execute(argv,env=None):
        if env and 'VPS_RUNTIME_FILE' in env:
            runtime.append(Path(env['VPS_RUNTIME_FILE']).read_text())
        return fake(argv,env)
    deploy.execute_operation(args(tmp_path),values,manifest(),contracts.images(manifest()),execute)
    commands=[a for a,_ in calls]
    indices=[next(i for i,a in enumerate(commands) if token in a) for token in ('db-preflight','object-bootstrap','vector-bootstrap')]
    assert indices==sorted(indices)
    assert 'up' in commands[-1] and 'api' in commands[-1]
    assert all('MINIO_ROOT_PASSWORD' not in r and 'POSTGRES_PASSWORD' not in r and 'RICK_MIGRATION_DATABASE_DSN' not in r
        and 'RICK_PREFLIGHT_DATABASE_DSN' not in r for r in runtime)
    assert all(values['POSTGRES_PASSWORD'] not in ' '.join(a) for a in commands)
    assert not any('down' in a or 'prune' in a for a in commands)
    assert all('volume' not in a or 'rm' not in a for a in commands)

def test_validate_has_only_quiet_render(tmp_path):
    calls=[];packet=manifest()
    deploy.execute_operation(args(tmp_path,'validate'),config(tmp_path),packet,contracts.images(packet),fake_execute([],calls))
    assert len(calls)==1 and calls[0][0][-2:]==['config','--quiet']

def test_cli_does_not_echo_secrets(tmp_path):
    path=config_file(tmp_path,config(tmp_path));secret='TOPSECRET_DSN_PASSWORD'
    path.write_text(path.read_text().replace('POSTGRES_PASSWORD=safe-example-value','POSTGRES_PASSWORD='+secret))
    result=subprocess.run([sys.executable,'-B',str(HERE/'deploy.py'),'install','--config',str(path),
        '--trusted-config-sha256','0'*64,'--manifest',str(tmp_path/'missing.json'),
        '--trusted-manifest-sha256','0'*64,*cli_assets(tmp_path,config(tmp_path),manifest())],capture_output=True,text=True)
    assert result.returncode==2 and secret not in result.stderr+result.stdout

def test_captured_driver_failure_no_cleartext(monkeypatch):
    monkeypatch.setattr(subprocess,'run',lambda *a,**kw:subprocess.CompletedProcess(a,1,'secret-dsn','secret-password'))
    with pytest.raises(contracts.Refusal) as error:deploy.run(['docker','compose'])
    assert 'secret' not in str(error.value)

def test_topology_and_declared_executable_health():
    compose=yaml.safe_load((HERE/'compose.yml').read_text())
    assert compose['networks']['private']['internal'] is True
    assert not compose['networks']['outbound'].get('internal',False)
    for name in ('api','worker'):
        assert 'outbound' in compose['services'][name]['networks']
        assert compose['services'][name]['environment']['RICK_CLINICAL_CASES_ENABLED']=='false'
    assert all('ports' not in s for name,s in compose['services'].items() if name!='edge')
    assert compose['services']['qdrant']['healthcheck']['test'][1]=='bash'
    assert compose['services']['object-store']['healthcheck']['test'][1]=='curl'
    assert 'test' not in compose['services']['worker']['healthcheck']
    assert all(v['external'] for v in compose['volumes'].values())
    assert compose['services']['db-migrate']['profiles']==['operations']

@pytest.mark.parametrize('changed', ['sha','skipped','repo','conclusion'])
def test_real_same_sha_quality_required(changed):
    run={'head_sha':SOURCE,'head_branch':'main','path':'.github/workflows/quality.yml','status':'completed',
        'conclusion':'success','event':'push','head_repository':{'full_name':contracts.REPO}}
    jobs=[{'name':name,'conclusion':'success'} for name in publish_guard.REQUIRED_JOBS]
    publish_guard.validate_run(run,jobs,SOURCE)
    if changed=='sha':run['head_sha']='c'*40
    if changed=='repo':run['head_repository']['full_name']='evil/fork'
    if changed=='conclusion':run['conclusion']='cancelled'
    if changed=='skipped':jobs[0]['conclusion']='skipped'
    with pytest.raises(contracts.Refusal):publish_guard.validate_run(run,jobs,SOURCE)


def test_candidate_construction_does_not_require_prior_image_promotion():
    run={'head_sha':SOURCE,'head_branch':'main','path':'.github/workflows/quality.yml','status':'completed',
        'conclusion':'failure','event':'push','head_repository':{'full_name':contracts.REPO}}
    jobs=[{'name':name,'conclusion':'success'} for name in publish_guard.REQUIRED_JOBS]
    jobs.append({'name':'RELEASE / commit-bound promotion gate','conclusion':'failure'})
    publish_guard.validate_run(run,jobs,SOURCE)
    for name in ('RAG-EVAL / deterministic and ACL','SUPPLY-CHAIN / dependency and secret policy'):
        missing=[job for job in jobs if job['name']!=name]
        with pytest.raises(contracts.Refusal):
            publish_guard.validate_run(run,missing,SOURCE)

def signed(source=SOURCE,digest=D):
    from test_support import admission_fixture
    from construction_contract import canonical_sha256
    from buildx_binary import inputs
    admission = admission_fixture()
    c = json.loads(admission['construction']['api']['json'])
    construction = {key:c[key] for key in ('context','dockerfile','dockerfile_sha256','parameters','materials',
                   'base_materials','build_config_sha256','source_mapping_sha256')}
    construction.update(policy_schema=c['schema'],policy_sha256=admission['construction']['api']['sha256'])
    tools = json.loads(admission['tool_policy']['json'])
    ref=f'ghcr.io/{contracts.REPO}-api@sha256:{D}'
    statement={'_type':'https://in-toto.io/Statement/v1','predicateType':contracts.PREDICATE,'subject':[{'name':ref.split('@')[0],'digest':{'sha256':digest}}],
        'predicate':{'source_sha':source,'image_ref':ref,'scan_status':'PASS','promotion_authorized':False,
            'sbom_sha256':D,'provenance_sha256':D,'scan_sha256':D,'oci_sha256':D,'construction':construction,
            'tool_policy_sha256':admission['tool_policy']['sha256'],'quality':admission['quality'],
            'quality_sha256':canonical_sha256(admission['quality']),
            'configured_build_tools':{k:tools['images'][k] for k in
                ('BUILDKIT_IMAGE','DOCKERFILE_FRONTEND_IMAGE','SBOM_GENERATOR_IMAGE','TRIVY_IMAGE','SKOPEO_IMAGE')},
            'base_images':{k:tools['images'][k] for k in ('PYTHON_IMAGE','NODE_BUILD_IMAGE','NODE_RUNTIME_IMAGE')},
            'buildx_binary':{'version':'v0.25.0','sha256':D,'url':inputs('v0.25.0',D),'platform':'linux/amd64',
                            'reported_version':'github.com/docker/buildx v0.25.0 '+SOURCE},
            'workflow_run':BUILDER,'builder_id':BUILDER,'application_digest':'sha256:'+D,
            'scan_coverage':[{'digest':'sha256:'+D,'platform':{'os':'linux','architecture':'amd64'},'config_digest':'sha256:'+D}],
            'scan_requirements':tools['scan']['api']}}
    return {'payload':base64.b64encode(json.dumps(statement).encode()).decode()}

def test_attestation_binds_actual_source_digest_array_and_jsonl():
    from test_support import admission_fixture
    ref=manifest()['images'][0]['image_ref'];policy=admission_fixture()
    deploy.attestations(json.dumps([signed()]),SOURCE,ref,policy)
    deploy.attestations(json.dumps(signed())+'\n'+json.dumps(signed()),SOURCE,ref,policy)
    for bad in (signed(source='c'*40),signed(digest='f'*64)):
        with pytest.raises(contracts.Refusal):deploy.attestations(json.dumps([bad]),SOURCE,ref,policy)


def test_workflow_construction_never_promotes_and_pins_actions():
    workflow=yaml.safe_load((ROOT/'.github/workflows/publish-images.yml').read_text())
    job=workflow['jobs']['candidate']
    assert workflow['permissions']=={} and 'environment' not in job
    steps=job['steps'];uses=[s['uses'] for s in steps if 'uses' in s]
    assert all(__import__('re').fullmatch(r'[a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+@[0-9a-f]{40}',v) for v in uses)
    build=next(s for s in steps if s.get('id')=='build')
    assert build['with']['push'] is False
    assert build['with']['provenance'].startswith('mode=max,version=v0.2,builder-id=') and 'generator=' in build['with']['sbom']
    text=(HERE/'publish_candidate.py').read_text()
    assert text.index("'--scanners'") < text.index("'--preserve-digests'") < text.index("'cosign','sign'")
    assert "'--severity'" not in text  # UNKNOWN must reach report admission.
    assert "'promotion_authorized':False" in text

BUILDER=f'https://github.com/{contracts.REPO}/actions/runs/123'
IMAGE=f'ghcr.io/{contracts.REPO}-api'

def migration_fixture(existing=True):
    history=[{'version':f'{i:04d}','sha256':D} for i in range(1,8)] if existing else []
    pending=[{'version':'0008','sha256':D}] if existing else [{'version':'0001','sha256':D}]
    return {'schema':'rick.vps.migration-plan/v1','authorization':'APPLY_REVIEWED_SQL',
        'observed':{'schema':'rick.vps.preflight/v1','read_only':True,
                    'database_state':'EXISTING' if existing else 'EMPTY','history':history,'pending':pending,
                    'relation_count':1 if existing else 0,
                    'relations':[['public','test_relation_0000','r']] if existing else []},
        'maintenance_window':existing,'verified_backup_id':'TEST ONLY verified backup' if existing else '',
        'backward_compatible':True}


def construction_fixture():
    """TEST ONLY independently declared expected inputs, not authenticated proof."""
    from construction_contract import canonical_sha256
    dfile='infrastructure/docker/api.Dockerfile';data=(ROOT/dfile).read_bytes()
    refs={k:'docker.io/test-only/'+k.lower()+'@sha256:'+D for k in
          ('PYTHON_IMAGE','NODE_BUILD_IMAGE','NODE_RUNTIME_IMAGE','BUILDKIT_SYNTAX')}
    args={'build-arg:'+k:v for k,v in refs.items()}
    args.update({'build-arg:RICK_API_INTERNAL_URL':'http://api:8000',
                 'label:org.opencontainers.image.source':'https://github.com/'+contracts.REPO,
                 'label:org.opencontainers.image.revision':SOURCE})
    remote='https://github.com/'+contracts.REPO+'.git#'+SOURCE
    materials=[{'uri':remote,'digest':{'sha1':SOURCE}}]
    bases={}
    for key in ('PYTHON_IMAGE','BUILDKIT_SYNTAX'):
        material={'uri':'pkg:docker/test-only/'+key.lower()+'@sha256:'+D+'?platform=linux%2Famd64','digest':{'sha256':D}}
        materials.append(material);bases[key]={'image_ref':refs[key],'material':material}
    recipe={'llbDefinition':[{'id':'step0','op':{'Op':{'source':{'identifier':'TEST ONLY remote recipe'}}}}]}
    mapping={'infos':[{'filename':dfile,'data':base64.b64encode(data).decode()}],
             'locations':{'step0':{'locations':[{'sourceIndex':0,'ranges':[{'start':{'line':1},'end':{'line':1}}]}]}}}
    policy={'schema':'rick.vps.construction-policy/v1','service':'api','source_sha':SOURCE,
        'context':{'uri':remote,'digest':{'sha1':SOURCE},'entryPoint':dfile},'dockerfile':dfile,
        'dockerfile_source_name':dfile,'dockerfile_sha256':hashlib.sha256(data).hexdigest(),
        'parameters':{'frontend':'dockerfile.v0','args':args,'locals':[],'secrets':[],'ssh':[]},
        'materials':materials,'base_materials':bases,'build_config_sha256':canonical_sha256(recipe),
        'source_mapping_sha256':canonical_sha256(mapping)}
    return policy,recipe,mapping


def construction_review():
    policy,_,_=construction_fixture();data=json.dumps(policy).encode()
    return data,hashlib.sha256(data).hexdigest(),(ROOT/policy['dockerfile']).read_bytes()


def blob_layer(files):
    # Structurally valid synthetic tar+gzip; no hosted/build/runtime proof.
    raw=io.BytesIO()
    with tarfile.open(fileobj=raw,mode='w') as tar:
        content=b'TEST ONLY application layer bytes'
        member=tarfile.TarInfo('test-only');member.size=len(content)
        tar.addfile(member,io.BytesIO(content))
    data=gzip.compress(raw.getvalue(),mtime=0);h=hashlib.sha256(data).hexdigest()
    files['blobs/sha256/'+h]=data
    return {'digest':'sha256:'+h,'size':len(data),'mediaType':'application/vnd.oci.image.layer.v1.tar+gzip'}

def archive(tmp_path,with_sbom=True, *, bad=None, layout='wrapped', artifact=False):
    """Synthetic BuildKit-format metadata; no hosted/build/runtime proof."""
    files={'oci-layout':b'{"imageLayoutVersion":"1.0.0"}'}
    def blob(obj, media='application/vnd.oci.image.manifest.v1+json'):
        content=json.dumps(obj,separators=(',',':')).encode()
        h=hashlib.sha256(content).hexdigest();files['blobs/sha256/'+h]=content
        return {'digest':'sha256:'+h,'size':len(content),'mediaType':media}
    labels={'org.opencontainers.image.source':'https://github.com/'+contracts.REPO,
            'org.opencontainers.image.revision':SOURCE}
    if bad=='config_revision':labels['org.opencontainers.image.revision']='e'*40
    layer=blob_layer(files)
    diff_id='sha256:'+hashlib.sha256(gzip.decompress(files['blobs/sha256/'+layer['digest'].split(':')[1]])).hexdigest()
    conf=blob({'architecture':'amd64','os':'linux','config':{'Labels':labels,'User':'10001:10001'},
               'rootfs':{'type':'layers','diff_ids':[diff_id]}},'application/vnd.oci.image.config.v1+json')
    app=blob({'schemaVersion':2,'mediaType':'application/vnd.oci.image.manifest.v1+json',
              'config':conf,'layers':[layer]})
    app['platform']={'os':'linux','architecture':'amd64'}
    if bad=='platform':app['platform']['architecture']='arm64'
    from test_support import synthetic_sbom
    sbom=synthetic_sbom()
    policy, recipe, mapping = construction_fixture()
    provenance={'buildType':'https://mobyproject.org/buildkit@v1','builder':{'id':BUILDER},
        'invocation':{'configSource':policy['context'],'parameters':policy['parameters'],
                      'environment':{'platform':'linux/amd64'}},
        'materials':policy['materials'],'buildConfig':recipe,
        'metadata':{'buildStartedOn':'2026-10-04T00:00:00Z','buildFinishedOn':'2026-10-04T00:01:00Z',
                    'completeness':{'parameters':True,'materials':True},
                    'https://mobyproject.org/buildkit@v1#metadata':{'source':mapping,
                        'vcs':{'source':'https://github.com/'+contracts.REPO+'.git','revision':SOURCE}}}}
    if bad=='source':provenance['invocation']['configSource']['uri']='https://github.com/evil/fork.git#'+SOURCE
    if bad=='revision':provenance['invocation']['configSource']['digest']['sha1']='f'*40
    if bad=='dockerfile':provenance['invocation']['configSource']['entryPoint']='infrastructure/docker/worker.Dockerfile'
    if bad=='directory':provenance['invocation']['configSource']['entryPoint']='unrelated/api.Dockerfile'
    if bad=='builder':provenance['builder']['id']='https://example.org/unrelated-build'
    if bad=='materials':provenance['materials']=[]
    if bad=='build_steps':provenance['buildConfig']={}
    if bad=='packages':sbom['packages']=[]
    layers=[]
    for kind in (['https://spdx.dev/Document'] if with_sbom else [])+['https://slsa.dev/provenance/v0.2']:
        subject={'name':f'pkg:docker/{IMAGE}@latest?platform=linux%2Famd64',
                 'digest':{'sha256':app['digest'].split(':')[1]}}
        if bad=='name':subject['name']='pkg:docker/different-image@latest?platform=linux%2Famd64'
        if bad=='subject_digest':subject['digest']['sha256']='c'*64
        predicate=sbom if kind=='https://spdx.dev/Document' else provenance
        if bad=='empty':predicate={}
        layer=blob({'_type':'https://in-toto.io/Statement/v0.1','subject':[subject],
                    'predicateType':kind,'predicate':predicate},'application/vnd.in-toto+json')
        layer['annotations']={'in-toto.io/predicate-type':kind};layers.append(layer)
    att_obj={'schemaVersion':2,'layers':layers,'config':blob({},'application/vnd.oci.empty.v1+json' if artifact else 'application/vnd.oci.image.config.v1+json')}
    if artifact:
        att_obj.update(artifactType='application/vnd.docker.attestation.manifest.v1+json',subject=app)
    att=blob(att_obj)
    att['annotations']={'vnd.docker.reference.type':'attestation-manifest',
                        'vnd.docker.reference.digest':app['digest'] if bad!='attachment' else 'sha256:'+'c'*64}
    att['platform']={'os':'unknown','architecture':'unknown'}
    root={'schemaVersion':2,'mediaType':'application/vnd.oci.image.index.v1+json','manifests':[app,att]}
    if layout=='wrapped':
        index=blob(root,'application/vnd.oci.image.index.v1+json')
        files['index.json']=json.dumps({'schemaVersion':2,'manifests':[index]}).encode()
        expected=index['digest']
    else:
        files['index.json']=json.dumps(root).encode()
        expected='sha256:'+hashlib.sha256(files['index.json']).hexdigest() if layout=='index' else app['digest']
    path=tmp_path/'image.tar'
    with tarfile.open(path,'w') as tar:
        for name,content in files.items():
            member=tarfile.TarInfo(name);member.size=len(content);tar.addfile(member,io.BytesIO(content))
    return path,expected

def test_oci_evidence_requires_hash_bound_sbom_provenance(tmp_path,monkeypatch):
    monkeypatch.setattr(publish_candidate,'OUT',tmp_path)
    path,d=archive(tmp_path)
    publish_candidate.oci_evidence(path,d,image=IMAGE,source=SOURCE,builder=BUILDER,review=construction_review())
    assert (tmp_path/'sbom.json').is_file() and (tmp_path/'provenance.json').is_file()
    with pytest.raises(contracts.Refusal):publish_candidate.oci_evidence(path,'sha256:'+'0'*64,image=IMAGE,source=SOURCE,builder=BUILDER,review=construction_review())
    path,d=archive(tmp_path,False)
    with pytest.raises(contracts.Refusal,match='SBOM'):publish_candidate.oci_evidence(path,d,image=IMAGE,source=SOURCE,builder=BUILDER,review=construction_review())

def test_scan_failure_cannot_reach_hosted_copy(tmp_path,monkeypatch):
    from test_rework6 import modeled_root_ancestors
    modeled_root_ancestors(monkeypatch)
    import construction_contract
    installer=tmp_path/'reviewed-source'
    p=installer/'infrastructure/docker/api.Dockerfile';p.parent.mkdir(parents=True)
    p.write_bytes((ROOT/'infrastructure/docker/api.Dockerfile').read_bytes());p.chmod(0o600)
    monkeypatch.setattr(construction_contract,'ROOT',installer)
    # TEST ONLY independent reviewed bytes at the capture seam. Real parent
    # ownership/DAC checks are separate; mapped /tmp must not mask this test's
    # scanner-before-copy assertion. Production capture is unchanged.
    def reviewed_capture(service,source):
        assert service=='api' and source==SOURCE
        return construction_review()
    monkeypatch.setattr(publish_candidate,'environment_review',reviewed_capture)
    path,built=archive(tmp_path)
    monkeypatch.setattr(publish_candidate,'OUT',tmp_path)
    for k,v in {'SERVICE':'api','SOURCE_SHA':SOURCE,'BUILT_DIGEST':built,
        'GITHUB_RUN_ID':'123','BUILDX_VERSION':'v0.25.0','BUILDX_SHA256':D,
        'TRIVY_IMAGE':'docker.io/aquasec/trivy@sha256:'+D,
        'SKOPEO_IMAGE':'quay.io/skopeo/stable@sha256:'+D}.items():monkeypatch.setenv(k,v)
    data,h,_=construction_review()
    monkeypatch.setenv('CONSTRUCTION_POLICY_JSON',data.decode());monkeypatch.setenv('CONSTRUCTION_POLICY_SHA256',h)
    for key,value in construction_fixture()[0]['parameters']['args'].items():
        if key.startswith('build-arg:') and key!='build-arg:RICK_API_INTERNAL_URL':
            name=key.removeprefix('build-arg:');monkeypatch.setenv('DOCKERFILE_FRONTEND_IMAGE' if name=='BUILDKIT_SYNTAX' else name,value)
    (tmp_path/'buildx.json').write_text(json.dumps({'version':'v0.25.0','sha256':D,'platform':'linux/amd64',
        'url':'https://github.com/docker/buildx/releases/download/v0.25.0/buildx-v0.25.0.linux-amd64'}))
    from test_support import admission_fixture
    reviewed=admission_fixture();tools=json.loads(reviewed['tool_policy']['json'])
    monkeypatch.setenv('TOOL_POLICY_JSON',reviewed['tool_policy']['json'])
    monkeypatch.setenv('TOOL_POLICY_SHA256',reviewed['tool_policy']['sha256'])
    for key,value in tools['images'].items():monkeypatch.setenv(key,value)
    (tmp_path/'quality.json').write_text(json.dumps(reviewed['quality']))
    calls=[]
    def failed(argv):
        calls.append(argv);raise contracts.Refusal('scanner failed')
    monkeypatch.setattr(publish_candidate,'command',failed)
    with pytest.raises(contracts.Refusal):publish_candidate.main()
    assert len(calls)==1 and 'image' in calls[0] and 'copy' not in calls[0]

def test_explicit_migrate_stops_writers_then_preflights_before_apply(tmp_path,monkeypatch):
    calls=[];values=config(tmp_path);monkeypatch.setattr(deploy,'verify',lambda *a:None)
    observed=migration_fixture()['observed']
    plan={'schema':'rick.vps.migration-plan/v1','authorization':'APPLY_REVIEWED_SQL','observed':observed,
        'maintenance_window':True,'verified_backup_id':'verified-backup','backward_compatible':True}
    path=tmp_path/'plan.json';path.write_text(json.dumps(plan));path.chmod(0o600)
    a=args(tmp_path,'migrate');a.plan=path;a.plan_sha256=contracts.digest(path)
    def execute(argv,env=None):
        calls.append(argv)
        return json.dumps(observed) if 'db-preflight' in argv else ''
    deploy.execute_operation(a,values,manifest(),contracts.images(manifest()),execute)
    stop=next(i for i,c in enumerate(calls) if 'stop' in c)
    inspections=[i for i,c in enumerate(calls) if 'db-preflight' in c]
    apply=next(i for i,c in enumerate(calls) if 'db-migrate' in c)
    assert len(inspections)==2 and inspections[0]<stop<inspections[1]<apply
    assert not any('object-bootstrap' in c or ('up' in c and 'api' in c) for c in calls)

def test_reviewed_rollback_refuses_schema_incompatibility(tmp_path,monkeypatch):
    calls=[];monkeypatch.setattr(deploy,'verify',lambda *a:None)
    with pytest.raises(contracts.Refusal,match='rollback schema compatibility'):
        deploy.execute_operation(args(tmp_path,'rollback'),config(tmp_path),manifest(),
            contracts.images(manifest()),fake_execute([],calls))
    assert not any('object-bootstrap' in a or ('up' in a and 'api' in a) for a,_ in calls)

def test_old_populated_schema_requires_staged_scope_review():
    with pytest.raises(contracts.Refusal,match='staged upgrade'):
        db_guard.inspect_database(Connection(Cursor(3,[('0001',D,'rick')])),Module())

@pytest.mark.parametrize('key,value',[
    ('RICK_PREFLIGHT_DATABASE_DSN','postgresql://readonly:example@postgres/other'),
    ('RICK_EXTERNAL_DATABASE_DSN','postgresql://rick:example@postgres/rick?options=search_path%3Devil'),
    ('RICK_MIGRATION_DATABASE_DSN','postgresql://rick:example@postgres/rick'),
    ('RICK_OBJECT_STORE_ACCESS_KEY_ID','root-user')])
def test_roles_database_and_root_credentials_cannot_drift(tmp_path,key,value):
    values=config(tmp_path);values[key]=value
    with pytest.raises(contracts.Refusal):deploy.read_env(config_file(tmp_path,values))

def test_actual_image_settings_failure_precedes_store_effects(tmp_path,monkeypatch):
    calls=[];monkeypatch.setattr(deploy,'verify',lambda *a:None)
    def execute(argv,env=None):
        calls.append(argv)
        if 'python' in argv and '-c' in argv:
            raise contracts.Refusal('actual canonical image settings refused')
        return ''
    with pytest.raises(contracts.Refusal):
        deploy.execute_operation(args(tmp_path),config(tmp_path),manifest(),contracts.images(manifest()),execute)
    assert not any('up' in c or 'stop' in c or 'db-preflight' in c for c in calls)


def test_selected_redis_tls_environment_uses_actual_settings(tmp_path,monkeypatch):
    for p in ROOT.joinpath('packages').glob('*/src'):monkeypatch.syspath_prepend(str(p))
    from rick_locking import RedisSettings
    values=config(tmp_path)
    values['RICK_REDIS_TLS_CA_FILE']=values['TLS_STORE_CA']
    settings=RedisSettings.from_env(values)
    assert settings.tls_enabled and settings.effective_require_tls and settings.effective_require_auth
    with pytest.raises(ValueError):RedisSettings.from_env(dict(values,RICK_REDIS_URL='redis://:example@redis/0'))
