"""TEST ONLY offline byte fixtures. These hashes never authorize production."""
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import assets

@lru_cache
def synthetic_tls():
    with tempfile.TemporaryDirectory(prefix='rick-test-only-tls-') as folder:
        p = Path(folder)
        def run(*parts):
            subprocess.run(['openssl', *parts], cwd=p, check=True, capture_output=True, timeout=15)
        run('req','-x509','-newkey','rsa:2048','-nodes','-keyout','ca.key','-out','ca.pem',
            '-days','1','-subj','/CN=TEST ONLY ephemeral CA')
        run('req','-newkey','rsa:2048','-nodes','-keyout','store.key','-out','store.csr',
            '-subj','/CN=TEST ONLY ephemeral store')
        (p/'ext').write_text('subjectAltName=DNS:objects.internal,DNS:vectors.internal,DNS:redis\nextendedKeyUsage=serverAuth\nbasicConstraints=CA:FALSE\n')
        run('x509','-req','-in','store.csr','-CA','ca.pem','-CAkey','ca.key','-CAcreateserial',
            '-out','store.pem','-days','1','-extfile','ext')
        return {role:(p/name).read_bytes() for role,name in
                (('TLS_STORE_CERT','store.pem'),('TLS_STORE_KEY','store.key'),('TLS_STORE_CA','ca.pem'))}

def proposal(config_data, values, source):
    tls = {role: Path(values[role]).read_bytes() for role in assets.TLS_ROLES}
    packet = {'schema':'rick.vps.assets/v1','status':'REVIEW_REQUIRED','source_sha':source,
              'config_sha256':assets.sha(config_data),
              'bundle_root':str(Path(values['TLS_STORE_KEY']).parent/'runtime-bundles'),
              'operations_user':f'{os.geteuid()}:{os.getegid()}',
              'tls_user':f'{os.geteuid()}:{os.getegid()}',
              'files':{name:assets.sha((assets.ROOT/name).read_bytes()) for name in assets.REPOSITORY_ASSETS},
              'tls':{role:assets.sha(data) for role,data in tls.items()}}
    packet['bundle_id'] = assets.identity(packet)
    return packet

def cli_assets(tmp_path, values, manifest):
    data = (tmp_path/'config.env').read_bytes()
    packet = proposal(data, values, manifest['source_revision']['value'])
    path = tmp_path/'TEST_ONLY_assets.json'
    path.write_text(json.dumps(packet)); path.chmod(0o600)
    bundle_root = Path(packet['bundle_root']); bundle_root.mkdir(mode=0o700, exist_ok=True)
    admission, trusted_admission = admission_file(tmp_path, manifest['source_revision']['value'])
    return ['--assets',str(path),'--trusted-assets-sha256',assets.sha(path.read_bytes()),
            '--reviewed-bundle-id',packet['bundle_id'],'--operations-user',packet['operations_user'],
            '--tls-user',packet['tls_user'],'--bundle-root',str(bundle_root),
            '--admission-policy',str(admission),'--trusted-admission-policy-sha256',trusted_admission]

def direct_assets(args, values, manifest):
    packet = proposal(b'TEST ONLY direct call config', values, manifest['source_revision']['value'])
    args.operations_user = packet['operations_user']; args.tls_user = packet['tls_user']
    args.bundle_root = Path(packet['bundle_root']); args.bundle_root.mkdir(mode=0o700, exist_ok=True)
    files = {name:(assets.ROOT/name).read_bytes() for name in assets.REPOSITORY_ASSETS}
    args.captured_assets = packet, files, assets.captured_tls(packet, values)
    args.admission_policy, args.trusted_admission_policy_sha256 = admission_file(Path(values['TLS_STORE_KEY']).parent,manifest['source_revision']['value'])
    args.admission_inputs = args.admission_policy.read_bytes(), args.trusted_admission_policy_sha256
    return args


def admission_fixture(source=None):
    """Synthetic independent policy inputs. Never production authority."""
    import copy
    import contracts
    from test_safety import construction_fixture, SOURCE, D, ROOT
    import publish_guard
    source = source or SOURCE
    original,_,_ = construction_fixture()
    construction = {}
    for service in contracts.SERVICES:
        policy = copy.deepcopy(original)
        policy.update(service=service,source_sha=source,dockerfile=f'infrastructure/docker/{service}.Dockerfile')
        policy['dockerfile_source_name'] = policy['dockerfile']
        policy['dockerfile_sha256'] = hashlib.sha256((ROOT/policy['dockerfile']).read_bytes()).hexdigest()
        policy['context']['entryPoint'] = policy['dockerfile']
        policy['context']['uri'] = f'https://github.com/{contracts.REPO}.git#'+source
        policy['context']['digest'] = {'sha1':source}
        policy['parameters']['args']['label:org.opencontainers.image.revision'] = source
        policy['materials'][0] = {'uri':policy['context']['uri'],'digest':{'sha1':source}}
        if service == 'web':
            policy['base_materials'].pop('PYTHON_IMAGE')
            policy['materials'] = [m for m in policy['materials'] if 'python_image' not in m['uri']]
            for key in ('NODE_BUILD_IMAGE','NODE_RUNTIME_IMAGE'):
                material = {'uri':'pkg:docker/test-only/'+key.lower()+'@sha256:'+D+'?platform=linux%2Famd64','digest':{'sha256':D}}
                policy['materials'].append(material)
                policy['base_materials'][key] = {'image_ref':policy['parameters']['args']['build-arg:'+key],'material':material}
        data = json.dumps(policy)
        construction[service] = {'json':data,'sha256':hashlib.sha256(data.encode()).hexdigest()}
    arguments = original['parameters']['args']
    images = {k:arguments['build-arg:'+k] for k in ('PYTHON_IMAGE','NODE_BUILD_IMAGE','NODE_RUNTIME_IMAGE')}
    images.update({key:'docker.io/test-only/'+key.lower()+'@sha256:'+D for key in
                   ('BUILDKIT_IMAGE','SBOM_GENERATOR_IMAGE','TRIVY_IMAGE','SKOPEO_IMAGE')})
    images['DOCKERFILE_FRONTEND_IMAGE'] = arguments['build-arg:BUILDKIT_SYNTAX']
    tools = {'schema':'rick.vps.tool-policy/v1','images':images,'buildx':{'version':'v0.25.0','sha256':D},
             'cosign_version':'v2.5.3','scan':{service:({'os_family':'debian','language_types':['python-pkg']} if service != 'web'
             else {'os_family':'alpine','language_types':['node-pkg']}) for service in contracts.SERVICES}}
    data = json.dumps(tools)
    quality = {'run_url':f'https://github.com/{contracts.REPO}/actions/runs/123','run_id':123,'run_attempt':1,
        'head_sha':source,'conclusion':'failure','required_jobs':list(publish_guard.REQUIRED_JOBS),
        'path':'.github/workflows/quality.yml','event':'push','head_branch':'main','head_repository':contracts.REPO,
        'status':'completed','job_conclusions':{name:'success' for name in publish_guard.REQUIRED_JOBS}}
    return {'schema':'rick.vps.admission-policy/v1','source_sha':source,'construction':construction,
            'tool_policy':{'json':data,'sha256':hashlib.sha256(data.encode()).hexdigest()},'quality':quality}


def admission_file(tmp_path, source):
    p = tmp_path/'TEST_ONLY_admission.json'
    p.write_text(json.dumps(admission_fixture(source))); p.chmod(0o600)
    return p, assets.sha(p.read_bytes())


def clean_scan(config_digest, *, family='debian', language='python-pkg'):
    return {'SchemaVersion':2,'ArtifactName':'TEST ONLY archive','ArtifactType':'container_image',
        'Metadata':{'ImageID':config_digest,'OS':{'Family':family,'Name':'12' if family=='debian' else '3.24.2','EOSL':False}},
        'Results':[{'Target':'TEST ONLY OS','Class':'os-pkgs','Type':family,
                    'Packages':[{'Name':'libc6' if family=='debian' else 'musl','Version':'1'}]},
                   {'Target':'TEST ONLY app','Class':'lang-pkgs','Type':language,
                    'Packages':[{'Name':'rick-dependency','Version':'1'}]}]}


def synthetic_sbom(*, family='debian', language='python-pkg'):
    """TEST ONLY identities/graph agreeing with clean_scan, never release evidence."""
    packages=[{'SPDXID':'SPDXRef-root','name':'TEST ONLY runtime','primaryPackagePurpose':'FILE'}]
    files=[]; relationships=[{'spdxElementId':'SPDXRef-DOCUMENT','relatedSpdxElement':'SPDXRef-root','relationshipType':'DESCRIBES'}]
    identities=[('libc6','deb/debian') if family=='debian' else ('musl','apk/alpine'),
                ('rick-dependency','pypi' if language=='python-pkg' else 'npm')]
    for index,(name,kind) in enumerate(identities):
        package_id=f'SPDXRef-package-{index}'; file_id=f'SPDXRef-file-{index}'
        packages.append({'SPDXID':package_id,'name':name,'versionInfo':'1','externalRefs':[
            {'referenceCategory':'PACKAGE-MANAGER','referenceType':'purl','referenceLocator':f'pkg:{kind}/{name}@1'}]})
        files.append({'SPDXID':file_id,'fileName':f'usr/lib/TEST-ONLY-{name}',
                      'checksums':[{'algorithm':'SHA256','checksumValue':hashlib.sha256(name.encode()).hexdigest()}]})
        relationships.extend([{'spdxElementId':'SPDXRef-root','relatedSpdxElement':package_id,'relationshipType':'CONTAINS'},
                              {'spdxElementId':package_id,'relatedSpdxElement':file_id,'relationshipType':'CONTAINS'}])
    return {'SPDXID':'SPDXRef-DOCUMENT','spdxVersion':'SPDX-2.3','name':'TEST ONLY buildkit-sbom',
        'documentNamespace':'https://example.org/test-fixture-only',
        'creationInfo':{'creators':['Tool: TEST ONLY fixture-generator'],'created':'2026-10-04T00:00:00Z'},
        'packages':packages,'files':files,'relationships':relationships}
