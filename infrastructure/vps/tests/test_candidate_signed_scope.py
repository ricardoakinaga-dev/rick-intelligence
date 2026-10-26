"""Synthetic post-scan boundaries, not native builds or production approvals.

Native OCI identity and Cosign flags have their own tests. Here a previously
verified native identity isolates scope generation and semantic substitution.
"""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import candidate_evidence as ce
from contracts import Refusal
from test_support import clean_scan, synthetic_sbom
from test_safety import SOURCE, D


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(ce, 'OUT', tmp_path)
    monkeypatch.setenv('GITHUB_SHA', SOURCE)
    monkeypatch.setenv('GITHUB_RUN_ID', '123')
    monkeypatch.setenv('SERVICE', 'api')
    monkeypatch.setenv('BUILT_DIGEST', 'sha256:'+D)
    monkeypatch.setattr(ce, 'inspect_oci', lambda *a, **kw: {
        'configuration_digest': 'sha256:'+D, 'index_digest': 'sha256:'+D,
        'application_digest': 'sha256:'+D, 'sbom_packages': 2})
    (tmp_path/'image.tar').write_bytes(b'TEST ONLY previously verified native OCI')
    for name, value in {'scan.json': clean_scan('sha256:'+D, family='alpine'),
        'sbom.json': {'predicate': synthetic_sbom(family='alpine')},
        'quality.json': {'source_sha': SOURCE}, 'provenance.json': {},
        'toolchain.json': {}, 'buildx.json': {}}.items():
        (tmp_path/name).write_text(json.dumps(value))
    return tmp_path


def rewrite_inventory(folder, record):
    (folder/'inventory.json').write_text(json.dumps(record))


def rehash(record, folder, name):
    path = folder/name
    record['files'][name] = {'sha256': ce.sha256(path), 'bytes': path.stat().st_size}


def test_inventory_v2_binds_reconciled_scope_before_signature(candidate):
    ce.inventory()
    record = json.loads((candidate/'inventory.json').read_text())
    assert record['schema'] == ce.SCHEMA_V2
    assert len(record['files']) == 8 and 'sbom-scope.json' in record['files']
    scope = record['sbom_scope']
    assert scope == json.loads((candidate/'sbom-scope.json').read_text())
    assert scope['native_sbom_sha256'] == ce.sha256(candidate/'sbom.json')
    assert scope['runtime_packages'] == scope['scanner_packages'] == 2
    assert record['sbom_scope_sha256'] == ce.canonical_sha256(scope)
    assert record['production_safe'] is record['promotion_authorized'] is False
    assert record['independent_review'] == record['human_release_decision'] == 'MISSING'
    ce.verify_files(require_scope=True)


@pytest.mark.parametrize('attack', ['missing-inline', 'missing-hash', 'wrong-hash',
    'missing-file-entry', 'modified-file', 'rehash-file', 'rebind-all',
    'wrong-native-binding', 'canonical-type-change', 'scope-symlink',
    'rehashed-scan-without-language', 'rehashed-sbom-version-drift', 'promotion'])
def test_rehashed_scope_or_inputs_cannot_replace_native_reconciliation(candidate, attack):
    ce.inventory()
    record = json.loads((candidate/'inventory.json').read_text())
    path = candidate/'sbom-scope.json'
    scope = json.loads(path.read_text())
    if attack == 'missing-inline': record.pop('sbom_scope')
    if attack == 'missing-hash': record.pop('sbom_scope_sha256')
    if attack == 'wrong-hash': record['sbom_scope_sha256'] = 'f'*64
    if attack == 'missing-file-entry': record['files'].pop('sbom-scope.json')
    if attack in {'modified-file', 'rehash-file', 'rebind-all', 'wrong-native-binding'}:
        if attack != 'wrong-native-binding': scope['runtime_packages'] += 1
        if attack == 'wrong-native-binding': scope['native_sbom_sha256'] = 'e'*64
        path.write_text(json.dumps(scope))
        if attack != 'modified-file': rehash(record, candidate, 'sbom-scope.json')
        if attack in {'rebind-all', 'wrong-native-binding'}:
            record['sbom_scope'] = scope
            record['sbom_scope_sha256'] = ce.canonical_sha256(scope)
    if attack == 'canonical-type-change':
        record['sbom_scope']['runtime_packages'] = float(scope['runtime_packages'])
    if attack == 'scope-symlink':
        path.unlink(); path.symlink_to(candidate/'quality.json')
    if attack == 'rehashed-scan-without-language':
        report = json.loads((candidate/'scan.json').read_text())
        report['Results'].pop()
        (candidate/'scan.json').write_text(json.dumps(report))
        rehash(record, candidate, 'scan.json')
    if attack == 'rehashed-sbom-version-drift':
        statement = json.loads((candidate/'sbom.json').read_text())
        package = statement['predicate']['packages'][2]
        package['versionInfo'] = '2'
        package['externalRefs'][0]['referenceLocator'] = 'pkg:pypi/rick-dependency@2'
        (candidate/'sbom.json').write_text(json.dumps(statement))
        rehash(record, candidate, 'sbom.json')
    if attack == 'promotion': record['promotion_authorized'] = True
    rewrite_inventory(candidate, record)
    with pytest.raises(Refusal): ce.verify_files(require_scope=True)


def test_failed_reconciliation_cannot_emit_inventory_or_scope(candidate, monkeypatch):
    def reject(*args): raise Refusal('TEST ONLY unmatched installed runtime distribution')
    monkeypatch.setattr(ce, 'reconcile_sbom', reject)
    with pytest.raises(Refusal): ce.inventory()
    assert not (candidate/'inventory.json').exists()
    assert not (candidate/'sbom-scope.json').exists()


def test_legacy_inventory_is_not_an_accepted_scoped_inventory(candidate):
    ce.inventory()
    record = json.loads((candidate/'inventory.json').read_text())
    record['schema'] = ce.SCHEMA_V1
    record.pop('sbom_scope'); record.pop('sbom_scope_sha256')
    record['files'].pop('sbom-scope.json')
    rewrite_inventory(candidate, record)
    ce.verify_files(require_scope=False)
    with pytest.raises(Refusal, match='legacy'): ce.verify_files(require_scope=True)
    record['sbom_scope'] = {'pretend': 'local scope cannot extend historical signature'}
    rewrite_inventory(candidate, record)
    with pytest.raises(Refusal, match='legacy'): ce.verify_files(require_scope=False)
