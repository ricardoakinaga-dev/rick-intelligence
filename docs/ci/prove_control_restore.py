#!/usr/bin/env python3
"""Prove AUD03-21 on a new synthetic Git projection without ignored host inputs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time


def prove(root, evidence, python):
    evidence.mkdir(parents=True, exist_ok=True)
    projection = Path(tempfile.mkdtemp(prefix='rick-ci-restore-'))
    paths = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=root).split(b'\0')
    records = []
    for raw in sorted(set(paths)):
        if not raw:
            continue
        relative = raw.decode()
        p = Path(relative)
        # The current campaign contains concurrently-created disposable test repos.
        # It is output of this candidate, not an input of the revision-380 controller.
        # Missing canonical references still fail the unchanged validators.
        if relative.startswith('docs/reports/evidence/implementation-aud03-2026-10-03/'):
            continue
        if any(part.startswith('.env') and not part.endswith('.example') or part.endswith(('.pem', '.key')) for part in p.parts):
            raise ValueError(f'sensitive path refused: {relative}')
        source = root / relative
        if not source.is_file():
            raise ValueError(f'projection path missing/not regular: {relative}')
        if source.is_symlink():
            raise ValueError(f'projection symlink refused: {relative}')
        content = source.read_bytes()
        target = projection / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        shutil.copymode(source, target)
        records.append(dict(path=relative, size=len(content), sha256=hashlib.sha256(content).hexdigest(),
                            mode=oct(source.stat().st_mode & 0o777)))
    ignored_controls = ('.agent/legacy-v1', '.review-control-history', '.gauntlet/state.json',
                        '.gauntlet-state-of-art', '.orchestrate', '.orchestrate-state-of-art')
    assert all(not (projection / path).exists() for path in ignored_controls)
    projection_bytes = (json.dumps(records, sort_keys=True, separators=(',', ':')) + '\n').encode()
    (evidence / 'projection-files.json').write_bytes(projection_bytes)
    results = []
    env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}
    # Host Python is an explicitly declared test runtime; no NODE_PATH, ignored control or shared dependencies.
    env.pop('NODE_PATH', None)
    env.pop('PYTHONPATH', None)

    def command(name, argv, cwd=projection, expected=0):
        started = time.time()
        with (evidence / f'{name}.txt').open('wb') as log:
            result = subprocess.run(argv, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, check=False)
        item = dict(name=name, command=argv, cwd=str(cwd), exit_status=result.returncode,
                    elapsed_seconds=round(time.time() - started, 3))
        results.append(item)
        (evidence / 'commands.json').write_text(json.dumps(dict(projection=str(projection),
            excluded_generated_output_prefix='docs/reports/evidence/implementation-aud03-2026-10-03/',
            projection_manifest_sha256=hashlib.sha256(projection_bytes).hexdigest(),
            source_head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root).decode().strip(),
            commands=results), indent=2) + '\n')
        print(name, result.returncode, flush=True)
        if expected == 'failure':
            if result.returncode == 0:
                raise ValueError(f'{name} unexpectedly passed')
        elif result.returncode != expected:
            raise ValueError(f'{name} failed: see {evidence / (name + ".txt")}')

    command('git-init', ['git', 'init', '-q'])
    command('git-add', ['git', 'add', '.'])
    command('git-synthetic-commit', ['git', '-c', 'user.name=CI restore proof', '-c',
                                   'user.email=ci-restore@example.invalid', 'commit', '-qm', 'Synthetic candidate projection; not a shared-repository commit'])
    command('before-make-validate', ['make', 'validate', f'PYTHON={python}'], expected='failure')
    command('before-control-plane', [python, 'docs/ci/check_control_plane.py'], expected='failure')
    command('npm-ci', ['npm', 'ci', '--no-audit', '--no-fund'], cwd=projection / 'apps/web')
    command('restore', ['make', 'control-inputs-restore', f'PYTHON={python}'])
    command('after-make-validate', ['make', 'validate', f'PYTHON={python}'])
    command('check-clean', [python, 'docs/ci/check_control_plane.py', '--require-clean'])
    command('idempotent-restore', ['make', 'control-inputs-restore', f'PYTHON={python}'])
    state = json.loads((projection / '.gauntlet/state.json').read_text())
    assert state['repository']['root'] == str(projection)
    assert state['round_count'] == 0 and state['stop'] is None and state['evidence_freshness'] == 'MISSING'
    target = projection / '.agent/legacy-v1/state.json'
    original = target.read_bytes()
    target.write_bytes(b'negative fixture: corruption')
    command('corrupt-restored-validate', ['make', 'validate', f'PYTHON={python}'], expected='failure')
    command('corrupt-restored-restore', ['make', 'control-inputs-restore', f'PYTHON={python}'], expected='failure')
    assert target.read_bytes() == b'negative fixture: corruption'
    target.write_bytes(original)
    target.unlink()
    command('missing-restored-validate', ['make', 'validate', f'PYTHON={python}'], expected='failure')
    target.write_bytes(original)
    archive = projection / 'docs/ci/control-inputs/v2/inputs.tar.xz'
    with archive.open('ab') as stream:
        stream.write(b'negative fixture')
    command('corrupt-source-validate', ['make', 'validate', f'PYTHON={python}'], expected='failure')
    command('corrupt-source-restore', ['make', 'control-inputs-restore', f'PYTHON={python}'], expected='failure')
    archive.unlink()
    command('missing-source-validate', ['make', 'validate', f'PYTHON={python}'], expected='failure')
    shutil.copyfile(root / 'docs/ci/control-inputs/v2/inputs.tar.xz', archive)
    command('final-make-validate', ['make', 'validate', f'PYTHON={python}'])
    (evidence / 'fresh-run.json').write_text(json.dumps({k: state[k] for k in (
        'run_id', 'repository', 'goal', 'bar', 'status', 'phase', 'round_count', 'evidence_freshness',
        'latest_verification', 'stop', 'capabilities', 'budget')}, indent=2) + '\n')
    print(projection, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--python', required=True)
    args = parser.parse_args()
    prove(args.root.resolve(), args.evidence.resolve(), args.python)
