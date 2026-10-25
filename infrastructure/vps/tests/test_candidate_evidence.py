"""Adversarial construction checks; synthetic inputs never grant release authority."""
import copy
import io
import json
from pathlib import Path
import sys
import tarfile

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import candidate_evidence as ce
from contracts import Refusal, REPO
from test_safety import SOURCE, BUILDER, archive


def environment():
    return {'GITHUB_REPOSITORY': REPO, 'GITHUB_REF': ce.REF,
            'GITHUB_WORKFLOW_REF': ce.WORKFLOW, 'GITHUB_ACTIONS': 'true',
            'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_SHA': SOURCE,
            'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1'}


@pytest.mark.parametrize('field,value', [
    ('GITHUB_REPOSITORY', 'someone/fork'), ('GITHUB_REF', 'refs/heads/main'),
    ('GITHUB_WORKFLOW_REF', ce.WORKFLOW.replace('quality.yml', 'other.yml')),
    ('GITHUB_EVENT_NAME', 'pull_request_target'), ('GITHUB_SHA', 'a'*7),
    ('GITHUB_ACTIONS', 'false'), ('GITHUB_RUN_ID', '0'), ('GITHUB_RUN_ATTEMPT', '')])
def test_refuse_wrong_dispatch_authority(field, value):
    env = environment(); env[field] = value
    with pytest.raises(Refusal):
        ce.identity(env, {j: {'result': 'success'} for j in ce.JOBS}, SOURCE, '')


@pytest.mark.parametrize('attack', ['dirty', 'sha', 'missing', 'failure', 'skipped', 'extra'])
def test_require_clean_exact_source_and_all_seven_gates(attack):
    needs = {j: {'result': 'success'} for j in ce.JOBS}
    head, dirty = SOURCE, ''
    if attack == 'dirty': dirty = ' M something'
    if attack == 'sha': head = 'f'*40
    if attack == 'missing': del needs['security']
    if attack in {'failure', 'skipped'}: needs['security']['result'] = attack
    if attack == 'extra': needs['release'] = {'result': 'success'}
    with pytest.raises(Refusal): ce.identity(environment(), needs, head, dirty)


def test_construction_needs_no_promotion_but_confers_no_authority():
    record = ce.identity(environment(), {j: {'result': 'success'} for j in ce.JOBS}, SOURCE, '')
    assert record['production_safe'] is False and record['promotion_authorized'] is False
    assert record['independent_review'] == record['human_release_decision'] == 'MISSING'
    # This is deliberately a different schema from publication quality_record.
    from admission import quality_record
    with pytest.raises(Refusal): quality_record(record, SOURCE)


@pytest.mark.parametrize('layout', ['index', 'wrapped'])
def test_native_oci_construction_preserves_real_subject_bytes(tmp_path, layout):
    path, expected = archive(tmp_path, layout=layout)
    result = ce.inspect_oci(path, expected, SOURCE, BUILDER, 'api', tmp_path)
    assert result['index_digest'] == expected and result['sbom_packages'] > 0
    assert json.loads((tmp_path/'provenance.json').read_text())['predicate']['builder']['id'] == BUILDER
    assert json.loads((tmp_path/'sbom.json').read_text())['predicate']['packages']


def test_scanner_layout_selects_only_exact_application_and_rehashes_all_bytes(tmp_path):
    path, expected = archive(tmp_path)
    layout = tmp_path/'scan-layout'
    result = ce.inspect_oci(path, expected, SOURCE, BUILDER, 'api', tmp_path, layout)
    index = json.loads((layout/'index.json').read_text())
    assert len(index['manifests']) == 1
    assert index['manifests'][0]['digest'] == result['application_digest']
    assert index['manifests'][0]['platform'] == {'os': 'linux', 'architecture': 'amd64'}
    for p in (layout/'blobs/sha256').iterdir():
        assert p.name == ce.sha256(p) and p.stat().st_mode & 0o222 == 0
    config = layout/'blobs/sha256'/result['configuration_digest'].split(':')[1]
    assert config.exists()
    with pytest.raises(FileExistsError):
        ce.inspect_oci(path, expected, SOURCE, BUILDER, 'api', None, layout)


def test_wrong_native_source_cannot_export_scanner_layout(tmp_path):
    path, expected = archive(tmp_path, bad='source')
    layout = tmp_path/'scan-layout'
    with pytest.raises(Refusal):
        ce.inspect_oci(path, expected, SOURCE, BUILDER, 'api', tmp_path, layout)
    assert not layout.exists()


@pytest.mark.parametrize('attack', ['config_revision', 'platform', 'source', 'revision',
    'dockerfile', 'directory', 'builder', 'materials', 'packages', 'name', 'subject_digest', 'attachment', 'empty'])
def test_reject_rehashed_oci_with_wrong_source_subject_or_missing_native_evidence(tmp_path, attack):
    path, expected = archive(tmp_path, bad=attack)
    with pytest.raises(Refusal): ce.inspect_oci(path, expected, SOURCE, BUILDER, 'api', tmp_path)


@pytest.mark.parametrize('attack', ['digest', 'blob', 'duplicate', 'link', 'traversal', 'trailing', 'sbom'])
def test_reject_untrusted_archive_bytes_without_extracting(tmp_path, attack):
    path, expected = archive(tmp_path, with_sbom=attack != 'sbom')
    if attack == 'digest': expected = 'sha256:'+'f'*64
    elif attack == 'trailing':
        with path.open('ab') as stream: stream.write(b'unpublished extra bytes')
    elif attack not in {'sbom'}:
        with tarfile.open(path) as tar:
            entries = [(item, tar.extractfile(item).read()) for item in tar]
        if attack == 'blob':
            item, data = next((i,d) for i,d in entries if i.name.startswith('blobs/'))
            entries[entries.index((item,data))] = (item, data[:-1]+b'!')
        elif attack == 'duplicate': entries.append(copy.copy(entries[0]))
        elif attack in {'link', 'traversal'}:
            item = tarfile.TarInfo('../../outside' if attack == 'traversal' else 'link')
            if attack == 'link': item.type = tarfile.SYMTYPE; item.linkname = '/etc/passwd'
            entries.append((item, b''))
        with tarfile.open(path, 'w') as tar:
            for item, data in entries: tar.addfile(item, io.BytesIO(data))
    with pytest.raises(Refusal): ce.inspect_oci(path, expected, SOURCE, BUILDER, 'api', tmp_path)
    assert not (tmp_path/'outside').exists()


@pytest.mark.parametrize('attack', ['none', 'mutation', 'missing', 'traversal', 'production', 'source', 'symlink'])
def test_inventory_verification_rejects_substitution(tmp_path, monkeypatch, attack):
    monkeypatch.setattr(ce, 'OUT', tmp_path)
    monkeypatch.setenv('GITHUB_SHA', SOURCE)
    files = {}
    for name in ('image.tar', 'scan.json', 'sbom.json', 'provenance.json', 'quality.json', 'toolchain.json', 'buildx.json'):
        (tmp_path/name).write_bytes(b'original actual artifact')
        files[name] = {'sha256': ce.sha256(tmp_path/name), 'bytes': (tmp_path/name).stat().st_size}
    record = {'schema': 'rick.candidate-build-evidence/v1', 'source_sha': SOURCE,
        'service': 'api', 'production_safe': False, 'promotion_authorized': False,
        'signature_scope': 'CI_CONSTRUCTION_INVENTORY_ONLY', 'files': files}
    if attack == 'mutation': (tmp_path/'image.tar').write_bytes(b'wrong')
    if attack == 'missing': (tmp_path/'scan.json').unlink()
    if attack == 'traversal': files['../escape'] = files.pop('image.tar')
    if attack == 'production': record['production_safe'] = True
    if attack == 'source': record['source_sha'] = 'f'*40
    if attack == 'symlink':
        (tmp_path/'image.tar').unlink(); (tmp_path/'image.tar').symlink_to(tmp_path/'scan.json')
    ce.write(tmp_path/'inventory.json', record)
    if attack == 'none': ce.verify_files()
    else:
        with pytest.raises(Refusal): ce.verify_files()


def test_workflow_evidence_does_not_publish_or_weaken_promotion():
    workflow = yaml.safe_load((ce.ROOT/'.github/workflows/quality.yml').read_text())
    job = workflow['jobs']['candidate-image-evidence']
    assert set(job['needs']) == set(ce.JOBS)
    assert job['permissions'] == {'contents': 'read', 'id-token': 'write'}
    assert 'environment' not in job and 'phase3/a8a83ca-candidate' in job['if']
    build = next(s for s in job['steps'] if s.get('id') == 'build')
    assert build['with']['push'] is False
    assert 'github.sha' in build['with']['context']
    assert build['with']['provenance'].startswith('mode=max,version=v0.2,builder-id=')
    assert 'oci-artifact=false' in build['with']['outputs']
    from publish_guard import REQUIRED_JOBS
    assert 'PHASE3 / capability evidence matrix' in REQUIRED_JOBS


@pytest.mark.parametrize('attack', ['none', 'config', 'empty', 'no-language', 'no-os', 'packages', 'unknown-finding'])
def test_scan_covers_actual_configuration_os_language_and_all_severities(attack):
    digest = 'sha256:'+'d'*64
    report = {'SchemaVersion': 2, 'ArtifactType': 'container_image',
        'Metadata': {'ImageID': digest, 'OS': {'Family': 'alpine'}}, 'Results': [
            {'Class': 'os-pkgs', 'Type': 'alpine', 'Packages': [{'Name': 'musl', 'Version': '1.2.6-r3'}]},
            {'Class': 'lang-pkgs', 'Type': 'python-pkg', 'Packages': [{'Name': 'fastapi', 'Version': '1'}]}]}
    if attack == 'config': report['Metadata']['ImageID'] = 'sha256:'+'e'*64
    if attack == 'empty': report['Results'] = []
    if attack == 'no-language': report['Results'].pop()
    if attack == 'no-os': report['Results'].pop(0)
    if attack == 'packages': report['Results'][0]['Packages'] = []
    if attack == 'unknown-finding':
        report['Results'][0]['Vulnerabilities'] = [{'VulnerabilityID': 'CVE-TEST', 'PkgName': 'musl', 'Severity': 'UNKNOWN'}]
        assert ce.scan_result(report, digest, 'api') == 1
    elif attack == 'none': assert ce.scan_result(report, digest, 'api') == 0
    else:
        with pytest.raises(Refusal): ce.scan_result(report, digest, 'api')


def test_signature_checks_exact_sha_ref_identity_issuer_and_file_bytes(tmp_path, monkeypatch):
    monkeypatch.setenv('GITHUB_SHA', SOURCE)
    commands = []
    monkeypatch.setattr(ce.subprocess, 'run', lambda argv, **kw: commands.append((argv, kw)))
    checked = []
    monkeypatch.setattr(ce, 'verify_files', lambda: checked.append(True))
    ce.verify_signature()
    argv, kwargs = commands[0]
    for flag, value in [('--certificate-identity', 'https://github.com/'+ce.WORKFLOW),
                        ('--certificate-oidc-issuer', ce.ISSUER),
                        ('--certificate-github-workflow-sha', SOURCE),
                        ('--certificate-github-workflow-ref', ce.REF),
                        ('--certificate-github-workflow-repository', REPO)]:
        assert argv[argv.index(flag)+1] == value
    assert not any('insecure' in word for word in argv)
    assert kwargs['check'] is True and checked == [True]


def test_publication_scanner_uses_admitted_application_without_registry_effects(tmp_path):
    import publish_candidate as pub
    from test_safety import construction_review, IMAGE
    path, expected = archive(tmp_path)
    pub.oci_evidence(path, expected, image=IMAGE, source=SOURCE, builder=BUILDER,
        review=construction_review(), writer=lambda name, data: (tmp_path/name).write_bytes(data))
    inventory = json.loads((tmp_path/'oci-inventory.json').read_text())
    descriptor = json.loads(pub.scanner_index(inventory))['manifests'][0]
    assert descriptor['digest'] == inventory['runnable'][0]['digest']
    assert descriptor['platform'] == {'os': 'linux', 'architecture': 'amd64'}
    argv = pub.scanner_command(['-v', '/private/inputs:/input:ro', '-v', '/private/outputs:/output:rw'], 'scanner@sha256:'+'d'*64)
    assert argv[argv.index('--entrypoint')+1] == '/bin/sh'
    script = argv[argv.index('-c')+1]
    assert 'mktemp -d' in script and 'tar -xf /input/image.tar' in script
    assert '/input/scan-index.json' in script and 'trivy "$@" --input "$scan_dir"' in script
    assert 'image' in argv and 'copy' not in argv and '--severity' not in argv


@pytest.mark.parametrize('attack', ['extra', 'missing', 'platform', 'digest'])
def test_publication_scanner_rejects_ambiguous_or_unbound_application(attack):
    import publish_candidate as pub
    digest = 'sha256:'+'d'*64
    inventory = {'runnable': [{'digest': digest, 'platform': {'os': 'linux', 'architecture': 'amd64'}}],
        'members': {'blobs/sha256/'+'d'*64: {'type': 'file', 'size': 123}}}
    if attack == 'extra': inventory['runnable'].append(copy.deepcopy(inventory['runnable'][0]))
    if attack == 'missing': inventory['members'] = {}
    if attack == 'platform': inventory['runnable'][0]['platform']['architecture'] = 'arm64'
    if attack == 'digest': inventory['runnable'][0]['digest'] = '../../outside'
    with pytest.raises(Refusal): pub.scanner_index(inventory)
