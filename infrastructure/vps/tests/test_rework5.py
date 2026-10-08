"""V5 publisher evidence controls. All authority and scanner outputs are TEST ONLY.

No subprocess, network, TLS or separated-UID checks are exercised here.
"""
import json
from pathlib import Path
import pytest
import contracts
import construction_contract as cc
import publish_candidate as pub
from test_safety import D, SOURCE, IMAGE, BUILDER, ROOT, archive, construction_fixture, construction_review
from test_support import admission_fixture, clean_scan, synthetic_sbom


def statement(document=None):
    return {'_type':'https://in-toto.io/Statement/v0.1',
        'predicateType':'https://spdx.dev/Document',
        'subject':[{'name':f'pkg:docker/{IMAGE}@latest?platform=linux%2Famd64','digest':{'sha256':D}}],
        'predicate':synthetic_sbom() if document is None else document}


@pytest.mark.parametrize('flag,value',[
    ('EOSL',True),('EOSL','false'),('EOSL',None),('EOL',True),
    ('Unsupported',True),('Unsupported',None),('Supported',False),('Supported',None)])
def test_explicit_eol_unsupported_and_unknown_lifecycle_refused(flag,value):
    report=clean_scan('sha256:'+D)
    report['Metadata']['OS'][flag]=value
    with pytest.raises(contracts.Refusal,match='coverage refused'):
        pub.scan_coverage(report,{'runnable':[{'config_digest':'sha256:'+D}]})


@pytest.mark.parametrize('attack',['placeholder','unversioned','no_files','no_relationships',
    'duplicate_id','dangling_relation','unreachable_package','no_file_identity','unlinked_files'])
def test_spdx_substance_refuses_degraded_evidence(attack):
    s=statement(); p=s['predicate']
    if attack=='placeholder':
        p['packages']=[{'SPDXID':'SPDXRef-placeholder','name':'placeholder'}]
        p.pop('files');p.pop('relationships')
    if attack=='unversioned':p['packages'][1].pop('versionInfo')
    if attack=='no_files':p.pop('files')
    if attack=='no_relationships':p.pop('relationships')
    if attack=='duplicate_id':p['packages'][1]['SPDXID']=p['packages'][0]['SPDXID']
    if attack=='dangling_relation':p['relationships'][0]['relatedSpdxElement']='SPDXRef-missing'
    if attack=='unreachable_package':p['relationships']=[r for r in p['relationships'] if r['relatedSpdxElement']!='SPDXRef-package-1']
    if attack=='no_file_identity':p['files'][0].pop('checksums')
    if attack=='unlinked_files':p['relationships']=[r for r in p['relationships'] if not r['relatedSpdxElement'].startswith('SPDXRef-file-')]
    with pytest.raises(contracts.Refusal):
        pub.statement_evidence(s,'https://spdx.dev/Document','sha256:'+D,IMAGE,SOURCE,BUILDER,None)


@pytest.mark.parametrize('family,language',[('debian','python-pkg'),('alpine','python-pkg'),('alpine','node-pkg')])
def test_supported_native_shaped_ecosystems(family,language):
    report=clean_scan('sha256:'+D,family=family,language=language)
    s=statement(synthetic_sbom(family=family,language=language))
    pub.statement_evidence(s,s['predicateType'],'sha256:'+D,IMAGE,SOURCE,BUILDER,None)
    pub.scan_coverage(report,{'runnable':[{'config_digest':'sha256:'+D}]},
                      {'os_family':family,'language_types':[language]})
    pub.reconcile_sbom(report,s)


def test_python_names_normalize_but_versions_and_os_names_do_not():
    report=clean_scan('sha256:'+D);s=statement()
    report['Results'][1]['Packages'][0]['Name']='Rick___Dependency'
    pub.reconcile_sbom(report,s)
    report['Results'][1]['Packages'][0]['Version']='1.0'
    with pytest.raises(contracts.Refusal,match='omitted'):pub.reconcile_sbom(report,s)
    report=clean_scan('sha256:'+D);report['Results'][0]['Packages'][0]['Name']='Libc6'
    with pytest.raises(contracts.Refusal,match='omitted'):pub.reconcile_sbom(report,s)


@pytest.mark.parametrize('attack',['missing_runtime_package','wrong_version','wrong_ecosystem',
    'wrong_namespace','purl_version_disagrees','purl_name_disagrees','extension_only',
    'scanner_purl_disagrees','scanner_identifier_malformed','no_distribution_refs','malformed_escape'])
def test_runtime_inventory_must_reconcile_by_identity(attack):
    report=clean_scan('sha256:'+D);s=statement();p=s['predicate']['packages'][2]
    ref=p['externalRefs'][0]
    if attack=='missing_runtime_package':report['Results'][1]['Packages'].append({'Name':'missing','Version':'1'})
    if attack=='wrong_version':report['Results'][1]['Packages'][0]['Version']='1+vendor'
    if attack=='wrong_ecosystem':ref['referenceLocator']='pkg:npm/rick-dependency@1'
    if attack=='wrong_namespace':ref['referenceLocator']='pkg:pypi/vendor/rick-dependency@1'
    if attack=='purl_version_disagrees':ref['referenceLocator']='pkg:pypi/rick-dependency@2'
    if attack=='purl_name_disagrees':ref['referenceLocator']='pkg:pypi/other-name@1'
    if attack=='extension_only':ref['referenceLocator']='pkg:pypi/rick-dependency@1#c-ext/module'
    if attack=='scanner_purl_disagrees':report['Results'][1]['Packages'][0]['PkgIdentifier']={'PURL':'pkg:pypi/wrong@1'}
    if attack=='scanner_identifier_malformed':report['Results'][1]['Packages'][0]['PkgIdentifier']=[]
    if attack=='no_distribution_refs':p['externalRefs']=[]
    if attack=='malformed_escape':ref['referenceLocator']='pkg:pypi/rick%ZZdependency@1'
    with pytest.raises(contracts.Refusal):pub.reconcile_sbom(report,s)


def test_npm_scope_and_os_epoch_revision_preserved():
    report=clean_scan('sha256:'+D,family='alpine',language='node-pkg')
    s=statement(synthetic_sbom(family='alpine',language='node-pkg'))
    for result,p,url,name,version in [
        (report['Results'][0],s['predicate']['packages'][1],'pkg:apk/alpine/musl@1%3A2-r3','musl','1:2-r3'),
        (report['Results'][1],s['predicate']['packages'][2],'pkg:npm/%40rick/dependency@1','@rick/dependency','1')]:
        result['Packages'][0].update(Name=name,Version=version,PkgIdentifier={'PURL':url})
        p.update(name=name,versionInfo=version);p['externalRefs'][0]['referenceLocator']=url
    pub.reconcile_sbom(report,s)
    report['Results'][0]['Packages'][0].update(Version='2-r3')
    with pytest.raises(contracts.Refusal):pub.reconcile_sbom(report,s)


def test_scanner_cannot_omit_a_comparable_spdx_distribution():
    s=statement(); p=s['predicate']
    p['packages'].append({'SPDXID':'SPDXRef-extra','name':'extra','versionInfo':'1','externalRefs':[
        {'referenceType':'purl','referenceLocator':'pkg:pypi/extra@1'}]})
    p['relationships'].append({'spdxElementId':'SPDXRef-root','relatedSpdxElement':'SPDXRef-extra','relationshipType':'CONTAINS'})
    with pytest.raises(contracts.Refusal,match='scanner omitted'):
        pub.reconcile_sbom(clean_scan('sha256:'+D),s)


def test_bundled_subpath_version_is_not_an_installed_distribution_version():
    s=statement();p=s['predicate']
    p['packages'].append({'SPDXID':'SPDXRef-bundled','name':'bundled-shim','versionInfo':'2','externalRefs':[
        {'referenceType':'purl','referenceLocator':'pkg:pypi/rick-dependency@1#thirdparty/bundled-shim'}]})
    p['relationships'].append({'spdxElementId':'SPDXRef-root','relatedSpdxElement':'SPDXRef-bundled','relationshipType':'CONTAINS'})
    pub.reconcile_sbom(clean_scan('sha256:'+D),s)


def test_unversioned_primary_purl_and_unknown_runtime_version_are_refused():
    s=statement();p=s['predicate']['packages'][2]
    p['versionInfo']='UNKNOWN';p['externalRefs'][0]['referenceLocator']='pkg:pypi/rick-dependency'
    with pytest.raises(contracts.Refusal,match='versioned'):pub.reconcile_sbom(clean_scan('sha256:'+D),s)
    s=statement();report=clean_scan('sha256:'+D);report['Results'][1]['Packages'][0]['Version']='UNKNOWN'
    with pytest.raises(contracts.Refusal):pub.reconcile_sbom(report,s)


@pytest.fixture
def candidate(tmp_path,monkeypatch):
    from test_rework6 import modeled_root_ancestors
    modeled_root_ancestors(monkeypatch)
    installer=tmp_path/'reviewed-source'
    p=installer/'infrastructure/docker/api.Dockerfile';p.parent.mkdir(parents=True)
    p.write_bytes((ROOT/'infrastructure/docker/api.Dockerfile').read_bytes());p.chmod(0o600)
    monkeypatch.setattr(cc,'ROOT',installer)
    path,built=archive(tmp_path);monkeypatch.setattr(pub,'OUT',tmp_path)
    data,h,_=construction_review();reviewed=admission_fixture();tools=json.loads(reviewed['tool_policy']['json'])
    # TEST ONLY capture seam: /tmp ownership is mapped in the Linux sandbox.
    # OCI admission still checks this independent policy/hash/recipe tuple;
    # filesystem capture and separated-UID DAC belong to the Parent lane.
    def reviewed_capture(service,source):
        assert service=='api' and source==SOURCE
        return construction_review()
    monkeypatch.setattr(pub,'environment_review',reviewed_capture)
    env={'SERVICE':'api','SOURCE_SHA':SOURCE,'BUILT_DIGEST':built,'GITHUB_RUN_ID':'123',
        'BUILDX_VERSION':'v0.25.0','BUILDX_SHA256':D,
        'CONSTRUCTION_POLICY_JSON':data.decode(),'CONSTRUCTION_POLICY_SHA256':h,
        'TOOL_POLICY_JSON':reviewed['tool_policy']['json'],'TOOL_POLICY_SHA256':reviewed['tool_policy']['sha256']}
    for key,value in construction_fixture()[0]['parameters']['args'].items():
        if key.startswith('build-arg:') and key!='build-arg:RICK_API_INTERNAL_URL':
            name=key.removeprefix('build-arg:');env['DOCKERFILE_FRONTEND_IMAGE' if name=='BUILDKIT_SYNTAX' else name]=value
    env.update(tools['images'])
    for key,value in env.items():monkeypatch.setenv(key,value)
    (tmp_path/'quality.json').write_text(json.dumps(reviewed['quality']))
    (tmp_path/'buildx.json').write_text(json.dumps({'version':'v0.25.0','sha256':D,'platform':'linux/amd64',
        'url':'https://github.com/docker/buildx/releases/download/v0.25.0/buildx-v0.25.0.linux-amd64'}))
    return tmp_path


@pytest.mark.parametrize('case',['healthy','low','medium','high','critical','unknown','eol','missing_package','wrong_version'])
def test_publication_reconciles_before_any_registry_authentication(candidate,monkeypatch,case):
    calls=[];auth=[]
    class AdmissionReached(Exception):pass
    def forbidden_auth(*args,**kwargs):
        auth.append(True);raise AdmissionReached
    monkeypatch.setattr(pub.tempfile,'TemporaryDirectory',forbidden_auth)
    def scanner(argv):
        calls.append(argv)
        assert '--severity' not in argv and '--list-all-pkgs' in argv
        assert argv[argv.index('--exit-code')+1]=='0'
        assert 'copy' not in argv
        inventory=contracts.parse((candidate/'oci-inventory.json').read_bytes())
        report=clean_scan(inventory['runnable'][0]['config_digest'])
        if case in {'low','medium','high','critical','unknown'}:
            report['Results'][0]['Vulnerabilities']=[{'VulnerabilityID':'TEST-ONLY','PkgName':'libc6','Severity':case.upper()}]
        if case=='eol':report['Metadata']['OS'].update(EOSL=True,Name='8')
        if case=='missing_package':report['Results'][1]['Packages'].append({'Name':'missing','Version':'1'})
        if case=='wrong_version':report['Results'][1]['Packages'][0]['Version']='2'
        output=next(Path(argv[i+1].split(':')[0]) for i,value in enumerate(argv)
                    if value=='-v' and argv[i+1].split(':')[1]=='/output')
        (output/'scan.json').write_text(json.dumps(report));return ''
    monkeypatch.setattr(pub,'command',scanner)
    if case in {'healthy','low','medium'}:
        with pytest.raises(AdmissionReached):pub.main()
        assert auth==[True]
    else:
        with pytest.raises(contracts.Refusal):pub.main()
        assert auth==[]
    assert len(calls)==1
