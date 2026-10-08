#!/usr/bin/env python3
"""Fail-closed restore/check of authentic versioned CI control inputs."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

from snapshot_control_inputs import allowed

ROOT = Path(__file__).resolve().parents[2]
MAX_MEMBER = 32 * 1024 * 1024
MAX_TOTAL = 160 * 1024 * 1024


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError(f'duplicate JSON key: {key}')
        result[key] = value
    return result


def load(data):
    return json.loads(data, object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def scoped(root, relative):
    p = Path(relative)
    if p.is_absolute() or '..' in p.parts or not p.parts:
        raise ValueError(f'unsafe path: {relative}')
    current = root
    for part in p.parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f'symlink path: {relative}')
    return current


def read_bundle(bundle):
    bundle = bundle.absolute()
    if any(path.is_symlink() for path in (bundle, *bundle.parents)):
        raise ValueError('symlink in bundle path')
    manifest_path = scoped(bundle, 'manifest.json')
    if manifest_path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError('oversized manifest')
    manifest = load(manifest_path.read_bytes())
    archive_path = scoped(bundle, 'inputs.tar.xz')
    if not archive_path.is_file() or archive_path.stat().st_size > MAX_TOTAL:
        raise ValueError('invalid archive file/size')
    if manifest['schema_version'] != 1 or sha(archive_path.read_bytes()) != manifest['archive_sha256']:
        raise ValueError('bundle schema/checksum mismatch')
    entries = manifest['files']
    if not entries or len(entries) > 2000 or sum(e['size'] for e in entries) > MAX_TOTAL:
        raise ValueError('invalid bundle inventory/size')
    expected, targets = {}, set()
    for e in entries:
        member = e['member']
        scoped(bundle, member)
        if member in expected or type(e['size']) is not int or not 0 <= e['size'] <= MAX_MEMBER:
            raise ValueError('duplicate member or invalid size')
        target = e['target']
        if target is not None:
            if not allowed(target) or target in targets or member != target:
                raise ValueError('unsafe or duplicate target')
            targets.add(target)
        elif member not in {f'snapshot/{folder}/{name}' for folder, names in {
            '.agent': ('state.json', 'backlog.json', 'execution-log.jsonl', 'verification.jsonl'),
            '.gauntlet': ('state.json', 'bar.json', 'history.jsonl', 'artifacts.jsonl', 'progress.md', 'state.md'),
        }.items() for name in names}:
            raise ValueError('unknown snapshot member')
        expected[member] = e
    data = {}
    with tarfile.open(archive_path, 'r:xz') as archive:
        for member in archive:
            e = expected.get(member.name)
            if e is None or member.name in data or not member.isfile() or member.size != e['size']:
                raise ValueError('archive inventory/type mismatch')
            content = archive.extractfile(member).read(MAX_MEMBER + 1)
            if sha(content) != e['sha256']:
                raise ValueError(f'member checksum mismatch: {member.name}')
            data[member.name] = content
    if set(data) != set(expected):
        raise ValueError('missing archive member')
    # Original manifests are validated without rewriting a single byte.
    for name in ('.agent/legacy-v1/manifest.json', '.review-control-history/manifest.json'):
        history = load(data[name])
        historical = {e['archived']: e['sha256'] for e in history['files']}
        actual = {e['target'] for e in entries if e['target'] and
                  e['target'].startswith(str(Path(name).parent) + '/') and e['target'] != name}
        if (history['schema_version'] != 1 or not historical or
                len(historical) != len(history['files']) or set(historical) != actual):
            raise ValueError('historical inventory mismatch')
        for path, digest in historical.items():
            if sha(data[path]) != digest:
                raise ValueError(f'historical checksum mismatch: {path}')
    predecessor = load(data['snapshot/.gauntlet/state.json'])
    agent = load(data['snapshot/.agent/state.json'])
    if (predecessor['goal'] != manifest['predecessor']['goal'] or
            predecessor['bar'] != manifest['predecessor']['bar'] or
            agent['state_revision'] != manifest['predecessor']['agent_revision']):
        raise ValueError('predecessor identity mismatch')
    goal = data['.gauntlet-state-of-art/goal.txt'].decode().strip()
    canonical = load(data['.gauntlet-state-of-art/bar.canonical.json'])
    original_bar = load(data['snapshot/.gauntlet/bar.json'])
    if predecessor['goal'] != {'text': goal, 'sha256': sha(goal.encode())} or canonical != original_bar:
        raise ValueError('predecessor goal/bar mismatch')
    return manifest, data


def module(root, relative, name):
    spec = importlib.util.spec_from_file_location(name, scoped(root, relative))
    value = importlib.util.module_from_spec(spec)
    # Imports must not mutate the tree before the conflict preflight finishes.
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(value)
    finally:
        sys.dont_write_bytecode = previous
    return value


def run(root, relative, *args):
    subprocess.run([sys.executable, str(root / relative), *map(str, args)],
                   cwd=root, check=True, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})


def restore(root, bundle, check=False):
    manifest, data = read_bundle(bundle)
    sys.path.insert(0, str(root / 'scripts/state_of_art'))
    views = module(root, 'scripts/state_of_art/review_control_views.py', 'ci_views')
    expected_views = views.expected_views(root)
    missing = []
    # Complete conflict preflight precedes any filesystem mutation.
    for e in manifest['files']:
        if e['target'] is None:
            continue
        path = scoped(root, e['target'])
        if path.exists():
            if not path.is_file() or sha(path.read_bytes()) != e['sha256']:
                raise ValueError(f'existing input differs: {e["target"]}')
        else:
            missing.append(e)
    for relative, content in expected_views.items():
        path = scoped(root, relative)
        if path.exists() and (not path.is_file() or path.read_bytes() != content.encode()):
            raise ValueError(f'existing derived view differs: {relative}')
        if check and not path.is_file():
            raise ValueError(f'missing derived view: {relative}')
    state_path = scoped(root, '.gauntlet/state.json')
    new_run = not state_path.exists()
    if new_run:
        directory = scoped(root, '.gauntlet')
        if directory.exists() and any(p.name != 'state.md' for p in directory.iterdir()):
            raise ValueError('incomplete/existing Gauntlet directory; manual recovery required')
    else:
        run(root, 'scripts/control_plane/vendor/gauntlet_loop/gauntlet_state.py', 'validate', '--repo', root)
        # Also reject a valid but unrelated existing run before restoring anything.
        state = load(state_path.read_bytes())
        if state['goal'] != manifest['predecessor']['goal']:
            raise ValueError('existing run has a different goal')
        views.verify_bar(root)
    if check and (missing or new_run):
        raise ValueError(f'missing restored control inputs: {len(missing)}; new run needed: {new_run}')
    if not check:
        for e in missing:
            path = scoped(root, e['target'])
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream:
                stream.write(data[e['member']])
        if new_run:
            # init requires an empty directory. Only an identical derived view may be removed.
            view = scoped(root, '.gauntlet/state.md')
            if view.exists():
                view.unlink()
            try:
                run(root, 'scripts/control_plane/vendor/gauntlet_loop/gauntlet_state.py',
                    'init', '--repo', root, '--goal-file', root / '.gauntlet-state-of-art/goal.txt',
                    '--bar-manifest', root / '.gauntlet-state-of-art/bar.canonical.json')
            finally:
                if not view.exists():
                    view.parent.mkdir(parents=True, exist_ok=True)
                    with view.open('xb') as stream:
                        stream.write(expected_views['.gauntlet/state.md'].encode())
        for relative, content in expected_views.items():
            path = scoped(root, relative)
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open('xb') as stream:
                    stream.write(content.encode())
    run(root, 'scripts/state_of_art/archive_controller.py', '--root', root)
    run(root, 'scripts/state_of_art/review_control_views.py', '--root', root)
    run(root, 'scripts/control_plane/vendor/gauntlet_loop/gauntlet_state.py', 'validate', '--repo', root)
    print(f'PASS: authentic inputs {manifest["version"]}; historical approvals not imported')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--bundle', type=Path)
    parser.add_argument('--check', action='store_true', help='read-only; missing restored inputs fail')
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    bundle = args.bundle or root / 'docs/ci/control-inputs/v2'
    try:
        restore(root, bundle, args.check)
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError, subprocess.CalledProcessError) as exc:
        print(f'FAIL: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
