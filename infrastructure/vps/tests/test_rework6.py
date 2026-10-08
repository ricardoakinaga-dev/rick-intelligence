"""V6 public admission controls: RAM OCI, finite files and effect tripwires.

Synthetic reviewed authority does not authenticate GitHub or prove live runtime.
"""
import copy
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import tarfile
from types import SimpleNamespace

import pytest
import contracts
import deploy
import publish_candidate as pub
from test_safety import SOURCE, IMAGE, BUILDER, construction_fixture, construction_review
from test_support import synthetic_sbom


class AdmissionReached(Exception):
    pass


def modeled_root_ancestors(monkeypatch):
    """Sandbox root maps to 65534; model only / and sticky /tmp as root.

    Leaf ownership, modes, links and mutable parents remain real. This is not
    evidence for host DAC; the Parent owns the separated-UID checks.
    """
    roots={(os.stat(p).st_dev,os.stat(p).st_ino) for p in ('/','/tmp')}
    def model(info):
        if (info.st_dev,info.st_ino) in roots and info.st_uid==65534:
            fields={key:getattr(info,key) for key in dir(info) if key.startswith('st_')}
            fields['st_uid']=0
            return SimpleNamespace(**fields)
        return info
    fstat,stat_call=os.fstat,os.stat
    monkeypatch.setattr(os,'fstat',lambda *a,**kw:model(fstat(*a,**kw)))
    monkeypatch.setattr(os,'stat',lambda *a,**kw:model(stat_call(*a,**kw)))


@pytest.mark.parametrize('entry',['policy','fresh'])
@pytest.mark.parametrize('mode',[0o600,0o644])
def test_public_authority_capture_requires_private_before_effects(tmp_path,monkeypatch,entry,mode):
    modeled_root_ancestors(monkeypatch)
    data=b'{"TEST":"ONLY authority"}'
    path=tmp_path/'authority.json';path.write_bytes(data);path.chmod(mode)
    trusted=hashlib.sha256(data).hexdigest()
    captured=[];effects=[]
    def admit(actual,*unused):
        contracts.check_hash(actual,trusted);captured.append(actual)
        return {'TEST':'ONLY admitted'}
    authority={'admission':SimpleNamespace(deployment_policy=admit),
               'fresh_inventory':SimpleNamespace(admit=admit)}
    monkeypatch.setattr(deploy,'captured_modules',lambda *a:authority)
    def reached(*a,**kw):
        raise AdmissionReached
    monkeypatch.setattr(deploy,'run',lambda *a,**kw:effects.append(a))
    if entry=='policy':
        config=tmp_path/'config.env';config.write_bytes(b'TEST_ONLY=1');config.chmod(0o600)
        manifest=tmp_path/'manifest.json';manifest.write_bytes(b'{}');manifest.chmod(0o600)
        args=SimpleNamespace(operation='preflight',retained_schema_inventory=False,
            config=config,manifest=manifest,trusted_config_sha256=contracts.digest(config),
            trusted_manifest_sha256=contracts.digest(manifest),admission_policy=path,
            trusted_admission_policy_sha256=trusted)
        monkeypatch.setattr(deploy.argparse.ArgumentParser,'parse_args',lambda *a:args)
        monkeypatch.setattr(deploy,'images',lambda *a:{})
        monkeypatch.setattr(deploy,'review_inputs',lambda *a:({}, {'infrastructure/vps/config.env.example':b''}))
        monkeypatch.setattr(deploy,'parse_env',lambda *a:{})
        monkeypatch.setattr(deploy,'captured_tls',lambda *a:{})
        monkeypatch.setattr(deploy,'execute_operation',reached)
        invoke=deploy.main
    else:
        args=SimpleNamespace(operation='preflight',captured_assets=({},
            {'infrastructure/vps/config.env.example':b''},{}),admission_inputs=(data,trusted),
            fresh_inventory=path,trusted_fresh_inventory_sha256=trusted)
        monkeypatch.setattr(deploy,'parse_env',lambda *a:{})
        monkeypatch.setattr(deploy,'stage',reached)
        invoke=lambda:deploy.execute_operation(args,{}, {}, {},lambda *a:effects.append(a))
    if mode==0o600:
        with pytest.raises(AdmissionReached):invoke()
        assert captured==[data] if entry=='policy' else captured==[data,data]
    else:
        with pytest.raises(contracts.Refusal,match='private'):invoke()
        assert captured==[] if entry=='policy' else captured==[data]
    assert effects==[]


def tar_layer(content=b'TEST ONLY runtime material', *, extension=None):
    raw=io.BytesIO()
    with tarfile.open(fileobj=raw,mode='w',format=tarfile.PAX_FORMAT) as tar:
        member=tarfile.TarInfo('test-only/material');member.size=len(content)
        if extension:member.pax_headers=extension
        tar.addfile(member,io.BytesIO(content))
    return raw.getvalue()


def memory_archive(*, attack=None, compression='gzip', layers=1):
    """Complete closure including re-bound attestation subjects, all in RAM."""
    files={'oci-layout':b'{"imageLayoutVersion":"1.0.0"}'}
    def blob(data,media):
        if not isinstance(data,bytes):data=json.dumps(data,separators=(',',':')).encode()
        h=hashlib.sha256(data).hexdigest();files['blobs/sha256/'+h]=data
        return {'digest':'sha256:'+h,'size':len(data),'mediaType':media}
    material=[];diff_ids=[]
    for i in range(layers):
        uncompressed=tar_layer(('TEST ONLY layer '+str(i)).encode())
        if attack=='empty_layer':uncompressed=bytes(1024)
        if attack=='bomb':uncompressed=tar_layer(bytes(1024**2))
        if attack=='pax':uncompressed=tar_layer(extension={'path':'test-only/'+('p'*150)})
        if attack=='not_tar':uncompressed=b'NOT A TAR'
        if attack=='trailing_tar':uncompressed+=b'NOT ZERO'+bytes(504)
        if attack=='truncated_tar':uncompressed=uncompressed[:512]
        if attack=='sparse':
            h=tarfile.TarInfo('sparse');h.type=tarfile.GNUTYPE_SPARSE
            uncompressed=h.tobuf()+bytes(1024)
        if attack=='pax_size':uncompressed=tar_layer(extension={'size':'1'})
        data=gzip.compress(uncompressed,mtime=0) if compression=='gzip' else uncompressed
        if attack=='truncated_gzip':data=data[:-8]
        if attack=='gzip_crc':data=data[:-8]+bytes([data[-8]^1])+data[-7:]
        if attack=='concat_gzip':data+=gzip.compress(uncompressed,mtime=0)
        if attack=='trailing_gzip':data+=b'opaque'
        if attack=='fake_gzip':data=uncompressed
        media='application/vnd.oci.image.layer.v1.tar'+('+gzip' if compression=='gzip' else '')
        if attack=='zstd':media='application/vnd.oci.image.layer.v1.tar+zstd'
        material.append(blob(data,media));diff_ids.append('sha256:'+hashlib.sha256(uncompressed).hexdigest())
    config={'architecture':'amd64','os':'linux','config':{'User':'10001:10001','Labels':{
        'org.opencontainers.image.source':'https://github.com/'+contracts.REPO,
        'org.opencontainers.image.revision':SOURCE}},'rootfs':{'type':'layers','diff_ids':diff_ids}}
    if attack=='missing_rootfs':config.pop('rootfs')
    if attack=='rootfs_type':config['rootfs']['type']='other'
    if attack=='rootfs_list':config['rootfs']=[]
    if attack=='diff_type':config['rootfs']['diff_ids']='sha256:'+'a'*64
    if attack=='diff_invalid':config['rootfs']['diff_ids'][0]='sha256:bad'
    if attack=='diff_count':config['rootfs']['diff_ids']=[]
    if attack=='diff_extra':config['rootfs']['diff_ids'].append('sha256:'+'a'*64)
    if attack=='diff_mismatch':config['rootfs']['diff_ids'][0]='sha256:'+'a'*64
    if attack=='compressed_as_diff':config['rootfs']['diff_ids'][0]=material[0]['digest']
    if attack=='diff_order':config['rootfs']['diff_ids'].reverse()
    if attack=='user_missing':config['config'].pop('User')
    if attack and attack.startswith('user='):config['config']['User']=attack[5:]
    conf=blob(config,'application/vnd.oci.image.config.v1+json')
    app=blob({'schemaVersion':2,'config':conf,'layers':material},'application/vnd.oci.image.manifest.v1+json')
    app['platform']={'os':'linux','architecture':'amd64'}
    policy,recipe,mapping=construction_fixture()
    provenance={'buildType':'https://mobyproject.org/buildkit@v1','builder':{'id':BUILDER},
        'invocation':{'configSource':policy['context'],'parameters':policy['parameters']},
        'materials':policy['materials'],'buildConfig':recipe,'metadata':{
        'buildStartedOn':'2026-10-04T00:00:00Z','buildFinishedOn':'2026-10-04T00:01:00Z',
        'completeness':{'parameters':True,'materials':True},
        'https://mobyproject.org/buildkit@v1#metadata':{'source':mapping}}}
    if attack=='local_provenance':
        provenance['invocation']['parameters']['locals']=[{'name':'context'}]
        provenance['builder']['id']='';provenance['metadata']['completeness']['materials']=False
    att_layers=[]
    for kind,predicate in [('https://spdx.dev/Document',synthetic_sbom()),
                           ('https://slsa.dev/provenance/v0.2',provenance)]:
        d=blob({'_type':'https://in-toto.io/Statement/v0.1','predicateType':kind,
            'subject':[{'name':f'pkg:docker/{IMAGE}@latest?platform=linux%2Famd64',
                        'digest':{'sha256':app['digest'].split(':')[1]}}],
            'predicate':predicate},'application/vnd.in-toto+json')
        d['annotations']={'in-toto.io/predicate-type':kind};att_layers.append(d)
    att=blob({'schemaVersion':2,'config':blob({},'application/vnd.oci.empty.v1+json'),
              'layers':att_layers},'application/vnd.oci.image.manifest.v1+json')
    att.update(platform={'os':'unknown','architecture':'unknown'},annotations={
        'vnd.docker.reference.type':'attestation-manifest','vnd.docker.reference.digest':app['digest']})
    manifests=[app,att]
    if attack=='second_application':manifests.append(copy.deepcopy(app))
    if attack=='unreferenced':blob(b'UNREFERENCED','application/octet-stream')
    files['index.json']=json.dumps({'schemaVersion':2,'manifests':manifests}).encode()
    expected='sha256:'+hashlib.sha256(files['index.json']).hexdigest()
    raw=io.BytesIO()
    with tarfile.open(fileobj=raw,mode='w') as tar:
        for name,data in files.items():
            member=tarfile.TarInfo(name);member.size=len(data);tar.addfile(member,io.BytesIO(data))
    return raw.getvalue(),expected


def public_memory_admit(monkeypatch, *, archive=None, **kwargs):
    data,expected=memory_archive(**kwargs) if archive is None else archive
    sentinel=87654321
    class MemoryRaw(io.BytesIO):
        def fileno(self):return sentinel
    raw=MemoryRaw(data)
    info=SimpleNamespace(st_mode=stat.S_IFREG|0o600,st_nlink=1,st_size=len(data),
                         st_dev=1,st_ino=1,st_mtime_ns=0,st_ctime_ns=0)
    real_open,real_fdopen,real_fstat=os.open,os.fdopen,os.fstat
    path=Path('/TEST-ONLY-RAM-OCI.tar')
    def open_ram(name,flags,*a,**kw):
        if name==path:
            assert flags & os.O_NOFOLLOW and flags & os.O_NONBLOCK
            return sentinel
        return real_open(name,flags,*a,**kw)
    monkeypatch.setattr(os,'open',open_ram)
    monkeypatch.setattr(os,'fdopen',lambda fd,*a,**kw:raw if fd==sentinel else real_fdopen(fd,*a,**kw))
    monkeypatch.setattr(os,'fstat',lambda fd:info if fd==sentinel else real_fstat(fd))
    outputs={}
    class Sink:
        def __init__(self,name=''):self.name=name
        def __truediv__(self,name):return Sink(name)
        def write_bytes(self,data):outputs[self.name]=data
        def write_text(self,data):outputs[self.name]=data.encode()
    monkeypatch.setattr(pub,'OUT',Sink())
    return lambda:pub.oci_evidence(path,expected,image=IMAGE,source=SOURCE,builder=BUILDER,
                                  review=construction_review()),outputs


@pytest.mark.parametrize('compression',['gzip','tar'])
@pytest.mark.parametrize('layers',[1,2])
def test_public_memory_closed_rootfs_healthy(monkeypatch,compression,layers):
    admit,outputs=public_memory_admit(monkeypatch,compression=compression,layers=layers)
    assert admit().startswith('sha256:')
    assert set(outputs)=={'sbom.json','provenance.json','construction-binding.json','oci-inventory.json'}


@pytest.mark.parametrize('attack',[
    'missing_rootfs','rootfs_type','rootfs_list','diff_type','diff_invalid','diff_count','diff_extra',
    'diff_mismatch','compressed_as_diff','diff_order','user_missing','user=0:0','user=10001:0',
    'user=0:10001','user=10002:10002','user=rick','user=10001','user=',
    'not_tar','trailing_tar','truncated_tar','sparse','pax_size','truncated_gzip','gzip_crc',
    'concat_gzip','trailing_gzip','fake_gzip','zstd','local_provenance',
    'second_application','unreferenced'])
def test_public_memory_rootfs_and_identity_refuse_without_outputs(monkeypatch,attack):
    admit,outputs=public_memory_admit(monkeypatch,attack=attack,layers=2 if attack=='diff_order' else 1)
    with pytest.raises(contracts.Refusal):admit()
    assert outputs=={}


def test_native_pax_path_is_bounded_and_compatible(monkeypatch):
    admit,outputs=public_memory_admit(monkeypatch,attack='pax')
    assert admit().startswith('sha256:') and outputs


def test_empty_tar_layer_is_valid_material(monkeypatch):
    admit,outputs=public_memory_admit(monkeypatch,attack='empty_layer')
    assert admit().startswith('sha256:') and outputs


def test_high_expansion_gzip_refused_before_unbounded_output(monkeypatch):
    data,expected=memory_archive(attack='bomb')
    assert len(data)<40000  # More than 1 MiB expanded from a small RAM input.
    monkeypatch.setattr(pub,'MAX_LAYER_BYTES',65536)
    admit,outputs=public_memory_admit(monkeypatch,archive=(data,expected))
    with pytest.raises(contracts.Refusal,match='bound'):admit()
    assert outputs=={}


@pytest.mark.parametrize('limit,value',[
    ('MAX_LAYER_BYTES',1024),('MAX_ROOTFS_BYTES',15000),
    ('MAX_LAYER_MEMBERS',0),('MAX_ROOTFS_MEMBERS',1),('MAX_LAYER_EXTENSION_BYTES',16)])
def test_public_memory_expansion_and_member_work_have_finite_bounds(monkeypatch,limit,value):
    monkeypatch.setattr(pub,limit,value)
    admit,outputs=public_memory_admit(monkeypatch,layers=2,
        attack='pax' if limit=='MAX_LAYER_EXTENSION_BYTES' else None)
    with pytest.raises(contracts.Refusal,match='bound'):admit()
    assert outputs=={}


@pytest.mark.parametrize('service',contracts.SERVICES)
def test_reviewed_dockerfiles_bind_final_nonroot_numeric_identity(service):
    root=Path(__file__).resolve().parents[3]
    data=(root/f'infrastructure/docker/{service}.Dockerfile').read_bytes()
    assert pub.reviewed_runtime_user(data)=='10001:10001'
    with pytest.raises(contracts.Refusal):pub.reviewed_runtime_user(data+b'\nFROM scratch\n')
    with pytest.raises(contracts.Refusal):pub.reviewed_runtime_user(data.replace(b'USER 10001:10001',b'USER 0:0'))
