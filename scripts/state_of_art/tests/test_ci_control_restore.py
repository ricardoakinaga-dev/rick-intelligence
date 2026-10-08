"""AUD03-21 authentic bundle, conflict preflight and portable recovery negatives."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'docs/ci'))
spec = importlib.util.spec_from_file_location('ci_restore', ROOT / 'docs/ci/restore_control_inputs.py')
restore = importlib.util.module_from_spec(spec)
spec.loader.exec_module(restore)
BUNDLE = ROOT / 'docs/ci/control-inputs/v2'


@pytest.fixture(scope='module')
def authentic():
    return restore.read_bundle(BUNDLE)


def fixture(root):
    """Copy just the declared controller implementations and canonical state."""
    for relative in ('scripts/control_plane/vendor', 'scripts/state_of_art'):
        shutil.copytree(ROOT / relative, root / relative,
                        ignore=shutil.ignore_patterns('__pycache__', 'tests', 'test_*.py'))
    for name in ('state.json', 'backlog.json'):
        target = root / '.agent' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / '.agent' / name, target)


def test_authentic_predecessor_is_not_approved(authentic):
    manifest, data = authentic
    agent = json.loads(data['snapshot/.agent/state.json'])
    state = json.loads(data['snapshot/.gauntlet/state.json'])
    assert agent['state_revision'] == 380
    assert agent['status'] == 'IN_PROGRESS'
    assert agent['verification_state'] == 'PARTIAL'
    assert state['status'] == 'ACTIVE'
    assert state['stop'] is None
    assert manifest['predecessor']['run_id'] == state['run_id']


@pytest.mark.parametrize('filename', ['manifest.json', 'inputs.tar.xz'])
def test_missing_source_fails(tmp_path, filename):
    shutil.copytree(BUNDLE, tmp_path / 'bundle')
    (tmp_path / 'bundle' / filename).unlink()
    with pytest.raises((OSError, ValueError)):
        restore.read_bundle(tmp_path / 'bundle')


def test_corrupt_archive_fails(tmp_path):
    shutil.copytree(BUNDLE, tmp_path / 'bundle')
    archive = tmp_path / 'bundle/inputs.tar.xz'
    with archive.open('ab') as stream:
        stream.write(b'corruption')
    with pytest.raises(ValueError, match='checksum'):
        restore.read_bundle(tmp_path / 'bundle')


def test_symlink_bundle_fails(tmp_path):
    (tmp_path / 'bundle').symlink_to(BUNDLE, target_is_directory=True)
    with pytest.raises(ValueError, match='symlink'):
        restore.read_bundle(tmp_path / 'bundle')


def test_oversize_archive_fails_before_read(tmp_path):
    shutil.copytree(BUNDLE, tmp_path / 'bundle')
    with (tmp_path / 'bundle/inputs.tar.xz').open('r+b') as stream:
        stream.truncate(restore.MAX_TOTAL + 1)
    with pytest.raises(ValueError, match='size'):
        restore.read_bundle(tmp_path / 'bundle')


@pytest.mark.parametrize('mutation', ['digest', 'duplicate', 'escape', 'snapshot', 'omit', 'size'])
def test_corrupt_inventory_fails(tmp_path, mutation):
    shutil.copytree(BUNDLE, tmp_path / 'bundle')
    path = tmp_path / 'bundle/manifest.json'
    manifest = json.loads(path.read_text())
    entry = manifest['files'][0]
    if mutation == 'digest':
        entry['sha256'] = '0' * 64
    elif mutation == 'duplicate':
        manifest['files'].append(entry.copy())
    elif mutation == 'escape':
        entry['target'] = '.agent/legacy-v1/../../outside'
        entry['member'] = entry['target']
    elif mutation == 'snapshot':
        entry['target'] = None
    elif mutation == 'omit':
        manifest['files'].pop(0)
    else:
        entry['size'] = restore.MAX_MEMBER + 1
    path.write_text(json.dumps(manifest))
    with pytest.raises((ValueError, KeyError)):
        restore.read_bundle(tmp_path / 'bundle')


def test_duplicate_json_keys_fail(tmp_path):
    shutil.copytree(BUNDLE, tmp_path / 'bundle')
    path = tmp_path / 'bundle/manifest.json'
    path.write_text(path.read_text().replace('"schema_version": 1,', '"schema_version": 1, "schema_version": 1,'))
    with pytest.raises(ValueError, match='duplicate JSON'):
        restore.read_bundle(tmp_path / 'bundle')


@pytest.mark.parametrize('kind', ['history', 'view', 'symlink', 'partial_run'])
def test_conflicts_fail_before_any_restore(tmp_path, kind, monkeypatch):
    # Exercise the default interpreter setting even when CI disables bytecode.
    monkeypatch.setattr(sys, 'dont_write_bytecode', False)
    fixture(tmp_path)
    path = tmp_path / '.agent/legacy-v1/state.json'
    if kind == 'view':
        path = tmp_path / '.orchestrate/state.json'
    elif kind == 'partial_run':
        path = tmp_path / '.gauntlet/history.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    if kind == 'symlink':
        outside = tmp_path / 'outside'
        outside.write_bytes(b'unchanged')
        path.symlink_to(outside)
    else:
        path.write_bytes(b'unchanged')
    before = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    with pytest.raises(ValueError):
        restore.restore(tmp_path, BUNDLE)
    after = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    assert before == after


@pytest.mark.parametrize('initial_setting', [False, True])
@pytest.mark.parametrize('fails', [False, True])
def test_module_preserves_tree_and_interpreter_setting(tmp_path, monkeypatch, initial_setting, fails):
    path = tmp_path / 'probe.py'
    content = "raise RuntimeError('import failed')\n" if fails else 'value = 42\n'
    path.write_text(content)
    monkeypatch.setattr(sys, 'dont_write_bytecode', initial_setting)
    if fails:
        with pytest.raises(RuntimeError, match='import failed'):
            restore.module(tmp_path, 'probe.py', 'ci_probe')
    else:
        assert restore.module(tmp_path, 'probe.py', 'ci_probe').value == 42
    assert sys.dont_write_bytecode is initial_setting
    assert list(tmp_path.rglob('*')) == [path]
    assert path.read_text() == content


def test_portable_run_and_restored_corruption(tmp_path, authentic):
    fixture(tmp_path)
    restore.restore(tmp_path, BUNDLE)
    manifest, data = authentic
    state_path = tmp_path / '.gauntlet/state.json'
    state = json.loads(state_path.read_text())
    assert state['repository']['root'] == str(tmp_path)
    assert state['run_id'] != manifest['predecessor']['run_id']
    assert state['goal'] == manifest['predecessor']['goal']
    assert json.loads((tmp_path / '.gauntlet/bar.json').read_text()) == json.loads(data['snapshot/.gauntlet/bar.json'])
    assert state['round_count'] == 0
    assert state['latest_verification'] is None and state['stop'] is None
    assert state['evidence_freshness'] == 'MISSING'
    assert (tmp_path / '.gauntlet/history.jsonl').read_bytes() == b''
    assert (tmp_path / '.gauntlet/artifacts.jsonl').read_bytes() == b''
    state_bytes = state_path.read_bytes()
    restore.restore(tmp_path, BUNDLE, check=True)
    restore.restore(tmp_path, BUNDLE)
    assert state_path.read_bytes() == state_bytes  # Idempotence does not reinitialize.
    target = tmp_path / '.agent/legacy-v1/state.json'
    original = target.read_bytes()
    target.write_bytes(b'corrupt')
    for check in (True, False):
        with pytest.raises(ValueError, match='existing input differs'):
            restore.restore(tmp_path, BUNDLE, check=check)
    assert target.read_bytes() == b'corrupt'
    target.write_bytes(original)
    target.unlink()
    with pytest.raises(ValueError, match='missing restored'):
        restore.restore(tmp_path, BUNDLE, check=True)
    target.write_bytes(original)
    state['repository']['root'] = '/wrong-root'
    state_path.write_text(json.dumps(state))
    with pytest.raises(subprocess.CalledProcessError):
        restore.restore(tmp_path, BUNDLE)
    assert json.loads(state_path.read_text())['repository']['root'] == '/wrong-root'


def test_read_only_check_does_not_bootstrap(tmp_path):
    fixture(tmp_path)
    with pytest.raises(ValueError, match='missing derived view'):
        restore.restore(tmp_path, BUNDLE, check=True)
    assert not (tmp_path / '.agent/legacy-v1').exists()
    assert not (tmp_path / '.gauntlet').exists()
