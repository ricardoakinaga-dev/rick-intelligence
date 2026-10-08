"""Finite public publisher identity tests; delegated tools are callbacks only."""
import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
import assets
import contracts
import publish_candidate as pub
from test_rework5 import candidate
from test_rework6 import modeled_root_ancestors
from test_support import clean_scan
from test_safety import SOURCE


def mounted(argv, target):
    for i, value in enumerate(argv):
        if value == '-v':
            host, container, *mode = argv[i+1].split(':')
            if container == target:
                return Path(host), mode
    # Baseline publisher's original RW mount.
    if target in {'/input', '/output'}:
        return mounted(argv, '/work')
    raise AssertionError(target)


@pytest.mark.parametrize('name', ['image.tar', 'sbom.json'])
def test_public_original_mutation_during_scan_refused_before_auth(candidate, monkeypatch, name):
    modeled_root_ancestors(monkeypatch)
    effects=[]
    class AuthReached(Exception): pass
    def auth(*a, **kw):
        effects.append('auth'); raise AuthReached
    monkeypatch.setattr(pub.tempfile, 'TemporaryDirectory', auth)
    def scan(argv):
        assert 'image' in argv and 'copy' not in argv
        inventory=contracts.parse((candidate/'oci-inventory.json').read_bytes())
        output,_=mounted(argv, '/output')
        (output/'scan.json').write_text(json.dumps(clean_scan(inventory['runnable'][0]['config_digest'])))
        path=candidate/name
        path.write_bytes(path.read_bytes()+b' ')
        return ''
    monkeypatch.setattr(pub,'command',scan)
    with pytest.raises(contracts.Refusal): pub.main()
    assert effects==[]


@pytest.mark.parametrize('mode',[0o600,0o644])
def test_public_assets_report_private_gate(tmp_path, monkeypatch, mode):
    modeled_root_ancestors(monkeypatch)
    data=b'{}';path=tmp_path/'authority.json';path.write_bytes(data);path.chmod(mode)
    args=SimpleNamespace(assets=path,trusted_assets_sha256=hashlib.sha256(data).hexdigest())
    reached=[]
    class Parsed(Exception): pass
    def parse(data, trusted): reached.append(data); raise Parsed
    monkeypatch.setattr(assets,'parse',parse)
    if mode==0o600:
        with pytest.raises(Parsed): assets.review_inputs(args,b'',{})
        assert reached==[data]
    else:
        with pytest.raises(contracts.Refusal,match='private'): assets.review_inputs(args,b'',{})
        assert reached==[]


class PublicTools:
    """Native-shaped fixture through public main; never runs a command/auth CLI."""
    def __init__(self, candidate, monkeypatch, stage=None, name=None, location='original', attack='append'):
        self.original=candidate; self.stage=stage; self.name=name
        self.location=location; self.attack=attack; self.events=[]; self.archive_hashes=[]
        self.inputs=None; self.outputs=None; self.snapshot_root=None
        self.original_hash=hashlib.sha256((candidate/'image.tar').read_bytes()).hexdigest()
        monkeypatch.setenv('GITHUB_RUN_ATTEMPT','1')
        admission=pub.oci_evidence
        def admit(path, *args, **kwargs):
            self.events.append('admission'); self.inputs=path.parent
            self.snapshot_root=self.inputs.parent
            assert path != candidate/'image.tar'
            assert os.stat(path).st_ino != os.stat(candidate/'image.tar').st_ino
            self.archive_hashes.append(hashlib.sha256(path.read_bytes()).hexdigest())
            result=admission(path,*args,**kwargs)
            self.mutate('after_admission')
            return result
        monkeypatch.setattr(pub,'oci_evidence',admit)
        reconciliation=pub.reconcile_sbom
        def reconcile(*args):
            result=reconciliation(*args); self.mutate('before_auth'); return result
        monkeypatch.setattr(pub,'reconcile_sbom',reconcile)
        from publication_capture import PublicationCapture
        export=PublicationCapture.export
        def exported(capture, name, path):
            result=export(capture,name,path)
            if name=='predicate.json': self.mutate('before_sign')
            return result
        monkeypatch.setattr(PublicationCapture,'export',exported)
        @contextmanager
        def auth():
            self.events.append('auth'); self.mutate('before_copy')
            # This pathname is an inert callback argument, never a credential.
            yield candidate/'TEST_ONLY_AUTH_NOT_OPENED'
        @contextmanager
        def signing():
            self.events.append('sign_auth'); yield
        monkeypatch.setattr(pub,'registry_auth',auth)
        monkeypatch.setattr(pub,'cosign_auth',signing)
        monkeypatch.setattr(pub,'command',self.command)

    def mutate(self, stage):
        if stage != self.stage: return
        if self.location=='environment':
            os.environ[self.name]+=' '; return
        if self.location=='dockerfile':
            import construction_contract
            path=construction_contract.ROOT/'infrastructure/docker/api.Dockerfile'
        else:
            folder=self.original if self.location=='original' else self.inputs
            path=folder/self.name
        if self.attack=='append':
            path.chmod(0o600); path.write_bytes(path.read_bytes()+b' ')
        elif self.attack=='restore':
            data=path.read_bytes(); path.chmod(0o600)
            path.write_bytes(data+b' '); path.write_bytes(data)
        elif self.attack=='replace':
            data=path.read_bytes(); path.unlink(); path.write_bytes(data)
        elif self.attack=='link':
            os.link(path,path.with_name(path.name+'.alias'))
        elif self.attack=='symlink':
            saved=path.with_name(path.name+'.saved');path.rename(saved);path.symlink_to(saved)
        elif self.attack=='parent':
            path.parent.rename(path.parent.with_name(path.parent.name+'-replaced'))
            path.parent.mkdir(mode=0o700);path.write_bytes(b'TEST ONLY replacement')
        else: raise AssertionError(self.attack)

    def command(self, argv):
        if argv[0]=='docker':
            inputs,mode=mounted(argv,'/input'); outputs,outmode=mounted(argv,'/output')
            assert mode==['ro'] and outmode==['rw']
            assert inputs==self.inputs and inputs!=outputs and inputs!=self.original
            assert '--cap-drop=ALL' in argv and '--security-opt=no-new-privileges' in argv
            assert argv[argv.index('--user')+1]==f'{os.geteuid()}:{os.getegid()}'
            assert inputs.stat().st_mode & 0o777==0o700
            assert (inputs/'image.tar').stat().st_mode & 0o777==0o400
            self.outputs=outputs
            self.archive_hashes.append(hashlib.sha256((inputs/'image.tar').read_bytes()).hexdigest())
            if 'image' in argv:
                self.events.append('scan')
                inventory=contracts.parse((inputs/'oci-inventory.json').read_bytes())
                (outputs/'scan.json').write_text(json.dumps(clean_scan(inventory['runnable'][0]['config_digest'])))
                self.mutate('scan_return')
            else:
                assert 'copy' in argv and 'oci-archive:/input/image.tar' in argv
                self.events.append('copy')
                (outputs/'registry.digest').write_text(os.environ['BUILT_DIGEST'])
                self.mutate('copy_return')
            return ''
        assert argv[0]=='cosign'
        self.events.append(argv[1])
        if argv[1]=='sign': self.mutate('sign_return')
        if argv[1]=='attest':
            path=Path(argv[argv.index('--predicate')+1])
            assert path.parent==self.inputs
            self.predicate=contracts.parse(path.read_bytes())
            assert self.predicate['oci_sha256']==self.original_hash
        return '{}\n'


def test_public_healthy_exact_bytes_admitted_scanned_copied_and_signed(candidate,monkeypatch):
    h=PublicTools(candidate,monkeypatch)
    pub.main()
    assert h.events==['admission','scan','auth','copy','sign_auth','sign','attest','verify','verify-attestation']
    assert h.archive_hashes==[h.original_hash]*3
    fragment=contracts.parse((candidate/'candidate.json').read_bytes())
    assert fragment['publication']==h.predicate
    for key,name in [('oci_sha256','image.tar'),('scan_sha256','scan.json'),
                     ('sbom_sha256','sbom.json'),('provenance_sha256','provenance.json')]:
        assert h.predicate[key]==hashlib.sha256((candidate/name).read_bytes()).hexdigest()
    assert not h.predicate['promotion_authorized']
    assert not h.snapshot_root.exists()


@pytest.mark.parametrize('name',['image.tar','quality.json','buildx.json','sbom.json','provenance.json',
    'construction-binding.json','oci-inventory.json','construction-policy.json','tool-policy.json'])
@pytest.mark.parametrize('stage',['after_admission','scan_return','before_auth','copy_return','before_sign'])
def test_public_original_identity_stage_matrix(candidate,monkeypatch,name,stage):
    h=PublicTools(candidate,monkeypatch,stage,name)
    with pytest.raises(contracts.Refusal): pub.main()
    assert 'sign' not in h.events and 'attest' not in h.events
    if stage in {'after_admission','scan_return','before_auth'}:
        assert 'auth' not in h.events and 'copy' not in h.events
    if stage=='after_admission': assert 'scan' not in h.events
    assert not (candidate/'candidate.json').exists()
    assert not h.snapshot_root.exists()


@pytest.mark.parametrize('name',['image.tar','sbom.json','provenance.json','construction-binding.json',
    'oci-inventory.json','construction-policy.json','tool-policy.json','quality.json','buildx.json'])
def test_public_retained_identity_tool_return_refused(candidate,monkeypatch,name):
    h=PublicTools(candidate,monkeypatch,'scan_return',name,location='retained')
    with pytest.raises(contracts.Refusal): pub.main()
    assert h.events==['admission','scan']


@pytest.mark.parametrize('attack',['restore','replace','link','symlink','parent'])
@pytest.mark.parametrize('location',['original','retained'])
def test_public_archive_alias_replacement_and_restored_bytes_refused(candidate,monkeypatch,attack,location):
    h=PublicTools(candidate,monkeypatch,'scan_return','image.tar',location,attack)
    with pytest.raises(contracts.Refusal): pub.main()
    assert h.events==['admission','scan']


@pytest.mark.parametrize('name',['CONSTRUCTION_POLICY_JSON','CONSTRUCTION_POLICY_SHA256',
    'TOOL_POLICY_JSON','TOOL_POLICY_SHA256','TRIVY_IMAGE','SKOPEO_IMAGE','BUILDX_SHA256','SOURCE_SHA'])
def test_public_environment_authority_mutation_refused(candidate,monkeypatch,name):
    h=PublicTools(candidate,monkeypatch,'scan_return',name,'environment')
    with pytest.raises(contracts.Refusal): pub.main()
    assert h.events==['admission','scan']


def test_public_reviewed_source_identity_retained(candidate,monkeypatch):
    h=PublicTools(candidate,monkeypatch,'scan_return',None,'dockerfile')
    with pytest.raises(contracts.Refusal): pub.main()
    assert h.events==['admission','scan']


@pytest.mark.parametrize('stage,name',[('before_copy','image.tar'),('copy_return','scan.json'),
    ('before_sign','predicate.json'),('sign_return','predicate.json')])
def test_public_last_check_before_copy_sign_and_attest(candidate,monkeypatch,stage,name):
    h=PublicTools(candidate,monkeypatch,stage,name)
    with pytest.raises(contracts.Refusal): pub.main()
    assert 'attest' not in h.events
    if stage=='before_copy': assert 'copy' not in h.events
    if stage!='sign_return': assert 'sign' not in h.events
    assert not (candidate/'candidate.json').exists()


@pytest.mark.parametrize('mode',[0o600,0o644])
def test_public_assets_complete_healthy_and_private_refusal(tmp_path,monkeypatch,mode):
    modeled_root_ancestors(monkeypatch)
    repository=tmp_path/'reviewed-repository'; repository.mkdir(mode=0o700)
    files={name:(assets.ROOT/name).read_bytes() for name in assets.REPOSITORY_ASSETS}
    for name,data in files.items():
        path=repository/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(data);path.chmod(0o600)
    monkeypatch.setattr(assets,'ROOT',repository)
    owner=f'{os.geteuid()}:{os.getegid()}' if os.geteuid() else '10001:10001'
    config=b'TEST ONLY config identity; contains no credentials'
    packet={'schema':'rick.vps.assets/v1','status':'REVIEW_REQUIRED','source_sha':SOURCE,
        'config_sha256':hashlib.sha256(config).hexdigest(),'operations_user':owner,'tls_user':owner,
        'bundle_root':str(tmp_path/'bundles'),
        'files':{name:hashlib.sha256(data).hexdigest() for name,data in files.items()},
        'tls':{role:'a'*64 for role in assets.TLS_ROLES}}
    packet['bundle_id']=assets.identity(packet)
    path=tmp_path/'assets.json';path.write_text(json.dumps(packet));path.chmod(mode)
    args=SimpleNamespace(assets=path,trusted_assets_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        operations_user=owner,tls_user=owner,bundle_root=tmp_path/'bundles',reviewed_bundle_id=packet['bundle_id'])
    if mode==0o600:
        assert assets.review_inputs(args,config,{'source_revision':{'value':SOURCE}})==(packet,files)
    else:
        with pytest.raises(contracts.Refusal,match='private'):
            assets.review_inputs(args,config,{'source_revision':{'value':SOURCE}})


@pytest.mark.parametrize('attack',[None,'user=0','diff_mismatch','compressed_as_diff','truncated_gzip',
    'concat_gzip','second_application','unreferenced','local_provenance'])
def test_public_capture_preserves_v6_native_shaped_admission(candidate,monkeypatch,attack):
    from test_rework6 import memory_archive
    data,built=memory_archive(attack=attack)
    (candidate/'image.tar').write_bytes(data);monkeypatch.setenv('BUILT_DIGEST',built)
    h=PublicTools(candidate,monkeypatch)
    if attack is None:
        pub.main()
        assert h.archive_hashes==[hashlib.sha256(data).hexdigest()]*3
    else:
        with pytest.raises(contracts.Refusal): pub.main()
        assert h.events==['admission']
        assert not (candidate/'candidate.json').exists()


@pytest.mark.parametrize('attack',['hardlink','symlink','oversize','mutable_mode'])
def test_public_source_capture_refused_before_admission_or_tools(candidate,monkeypatch,attack):
    path=candidate/'image.tar'
    if attack=='hardlink': os.link(path,candidate/'alias')
    if attack=='symlink':
        path.rename(candidate/'original');path.symlink_to(candidate/'original')
    if attack=='oversize':monkeypatch.setattr(pub,'MAX_ARCHIVE_BYTES',1)
    if attack=='mutable_mode':path.chmod(0o666)
    h=PublicTools(candidate,monkeypatch)
    with pytest.raises(contracts.Refusal): pub.main()
    assert h.events==[]


def test_public_archive_mutation_during_streaming_capture(candidate,monkeypatch):
    h=PublicTools(candidate,monkeypatch)
    pread=os.pread; changed=[]
    target=os.stat(candidate/'image.tar').st_ino
    def raced(fd,count,offset):
        result=pread(fd,count,offset)
        if os.fstat(fd).st_ino==target and not changed:
            changed.append(True)
            path=candidate/'image.tar';path.write_bytes(path.read_bytes()+b' ')
        return result
    monkeypatch.setattr(os,'pread',raced)
    with pytest.raises(contracts.Refusal): pub.main()
    assert changed==[True] and h.events==[]


@pytest.mark.parametrize('name',['sbom.json','construction-policy.json','scan.json','predicate.json'])
def test_public_export_does_not_follow_or_overwrite_operator_alias(candidate,monkeypatch,name):
    untouched=candidate/'TEST_ONLY_do_not_overwrite';untouched.write_bytes(b'TEST ONLY untouched')
    (candidate/name).symlink_to(untouched)
    h=PublicTools(candidate,monkeypatch)
    with pytest.raises(contracts.Refusal): pub.main()
    assert untouched.read_bytes()==b'TEST ONLY untouched'
    assert 'sign' not in h.events
    if name in {'sbom.json','construction-policy.json','scan.json'}:
        assert 'auth' not in h.events and 'copy' not in h.events
