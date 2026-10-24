#!/usr/bin/env python3
"""Inspect PROD12 recovery and preserve authenticated inputs; never restart a run.

Default is read-only. --backup-dir writes only a new workspace evidence directory.
Missing relocation support is a local implementation gap, not runtime approval.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import os
import tempfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
VENDOR = 'scripts/control_plane/vendor/gauntlet_loop/gauntlet_state.py'
SPEC = 'docs/backlog-producao-2026-10-12.md'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pairs(entries):
    result = {}
    for key, value in entries:
        if key in result:
            raise ValueError(f'duplicate JSON key: {key}')
        result[key] = value
    return result


def load(path: Path):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'not a regular input: {path}')
    return json.loads(path.read_bytes(), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def proposed_items(text: str) -> list[dict]:
    """Derive TODO intent/contracts from all 56 rows, never execution or acceptance."""
    rows = re.findall(r'^\| (PROD12-\d{3}) \| (M\d) \| (P\d) \| ([PMG]) \| ([^|]+) \| ([^|]+) \| (Sim|Não) \| ([^|]+) \|$', text, re.M)
    sections = dict((match.group(1), (match.group(2), match.group(3))) for match in re.finditer(
        r'^### (PROD12-\d{3}) — ([^\n]+)\n(.*?)(?=^### PROD12-|^## |\Z)', text, re.M | re.S))
    expected = [f'PROD12-{i:03d}' for i in range(1, 57)]
    if [row[0] for row in rows] != expected or set(sections) != set(expected):
        raise ValueError('expected exactly 56 ordered unique task rows and contracts')
    items = []
    for task, milestone, priority, size, owner, dependencies, required, origin in rows:
        deps = []
        if dependencies.strip() != '—':
            for token in dependencies.strip().split(','):
                match = re.fullmatch(r'(\d{3})(?:–(\d{3}))?', token.strip())
                if not match:
                    raise ValueError(f'invalid dependency: {token}')
                start = int(match[1]); end = int(match[2] or match[1])
                if end < start:
                    raise ValueError('reversed dependency range')
                deps.extend(f'PROD12-{number:03d}' for number in range(start, end + 1))
        if len(set(deps)) != len(deps) or any(dep not in expected or dep == task for dep in deps):
            raise ValueError('invalid or duplicate dependency')
        title, body = sections[task]
        acceptance = re.search(r'\*\*Aceite/verificação:\*\* (.+)', body)
        delivery = re.search(r'\*\*Entrega:\*\* (.+)', body)
        if not acceptance or not delivery:
            raise ValueError(f'missing delivery/acceptance: {task}')
        items.append({'id': task, 'title': title, 'stage': 'BUILD', 'priority': priority,
                      'status': 'TODO', 'origin': f'{SPEC}: {origin.strip()}',
                      'dependencies': deps, 'owner': f'Proposed role / not assigned: {owner.strip()}',
                      'acceptance_summary': acceptance[1].strip(), 'evidence_refs': [],
                      'milestone': milestone, 'size': size, 'mandatory': required == 'Sim',
                      'delivery_summary': delivery[1].strip(), 'accepted': False,
                      'specification_ref': SPEC,
                      'next_action': {'id': f'{task}:INSPECT', 'kind': 'INSPECT',
                                      'summary': 'Inspect the contracted boundary and prerequisite evidence; preparation is not acceptance',
                                      'target': SPEC, 'completion_signal': 'Owner, authority and applicable dependencies are evidenced before task selection'}})
    graph = {item['id']: item['dependencies'] for item in items}
    seen, active = set(), set()
    def visit(task):
        if task in active:
            raise ValueError('cyclic dependency graph')
        if task in seen:
            return
        active.add(task)
        for dep in graph[task]:
            visit(dep)
        active.remove(task); seen.add(task)
    for task in graph:
        visit(task)
    return items


def official_commands(source: str) -> list[str]:
    tree = ast.parse(source)
    return sorted({node.args[0].value for node in ast.walk(tree)
                   if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                   and node.func.attr == 'add_parser' and node.args
                   and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)})


def diagnose(root: Path) -> dict:
    state = load(root / '.gauntlet/state.json')
    history = root / '.gauntlet/history.jsonl'
    commands = official_commands((root / VENDOR).read_text())
    completed = subprocess.run([sys.executable, str(root / VENDOR), 'validate', '--repo', str(root)],
                               cwd=root, capture_output=True, text=True, check=False)
    return {'schema_version': 'prod12-control-diagnostic.v1', 'checkout': str(root),
            'run_id': state['run_id'], 'recorded_root': state['repository']['root'],
            'root_matches': state['repository']['root'] == str(root),
            'state_sha256': sha((root / '.gauntlet/state.json').read_bytes()),
            'history_sha256': sha(history.read_bytes()),
            'history_records': len(history.read_text().splitlines()),
            'goal': state['goal'], 'bar': state['bar'], 'official_commands': commands,
            'official_relocation_supported': bool({'relocate', 'rebind'} & set(commands)),
            'validation_exit_status': completed.returncode,
            'validation_stdout': completed.stdout, 'validation_stderr': completed.stderr,
            'proposed_task_count': len(proposed_items((root / SPEC).read_text())),
            'decision': ('PARTIAL; current-root structurally valid; old artifact evidence remains stale and task acceptance pending'
                         if completed.returncode == 0 else
                         'PARTIAL; preserve run; implement/review explicit relocation procedure before mutation'),
            'limitations': 'Structural validation is not resume, fresh artifact binding, runtime or production approval.'}


def backup(root: Path, destination: Path, diagnostic: dict) -> dict:
    # absolute() does not collapse '..': reject traversal before any filesystem effect.
    if '..' in destination.parts:
        raise ValueError('parent traversal in backup path')
    destination = destination.absolute()
    allowed = root.absolute() / '.runtime/prod12-control'
    if not destination.is_relative_to(allowed):
        raise ValueError('backup must be inside workspace .runtime/prod12-control')
    # Inspect every lexical component before resolve() could follow a symlink.
    if any(path.is_symlink() for path in (destination, *destination.parents, allowed, *allowed.parents)):
        raise ValueError('symlink in backup path')
    destination = destination.resolve(strict=False)
    if not destination.is_relative_to(allowed.resolve(strict=False)):
        raise ValueError('resolved backup escapes workspace .runtime/prod12-control')
    if destination.exists():
        raise ValueError('backup destination already exists; never overwrite evidence')
    names = ['.agent/state.json', '.agent/backlog.json', '.agent/PLANS.md',
             '.agent/execution-log.jsonl', '.agent/verification.jsonl',
             '.gauntlet/state.json', '.gauntlet/bar.json', '.gauntlet/history.jsonl',
             '.gauntlet/artifacts.jsonl', '.gauntlet/progress.md', '.gauntlet/state.md']
    content = {}
    for name in names:
        path = root / name
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents) or not path.is_file():
            raise ValueError(f'unsafe backup input: {name}')
        content[name] = path.read_bytes()
    if sha(content['.gauntlet/state.json']) != diagnostic['state_sha256'] or sha(content['.gauntlet/history.jsonl']) != diagnostic['history_sha256']:
        raise ValueError('inputs changed after diagnosis')
    destination.mkdir(parents=True)
    for name, data in content.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(data)
        if target.read_bytes() != data:
            raise ValueError('backup byte verification failed')
    manifest = {'schema_version': 1, 'run_id': diagnostic['run_id'],
                'files': [{'path': name, 'sha256': sha(data), 'size': len(data)} for name, data in content.items()]}
    with (destination / 'manifest.json').open('x') as stream:
        json.dump(manifest, stream, indent=2, ensure_ascii=False); stream.write('\n')
    return manifest


def replace_bytes(path: Path, data: bytes) -> None:
    mode = path.stat().st_mode & 0o777
    fd, temporary = tempfile.mkstemp(prefix='.prod12-rebind-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def relocate(root: Path, destination: Path, *, expected_run: str, expected_root: str,
             expected_sha256: str, expected_head: str) -> dict:
    """Explicit checked relocation. Preserve all fields except current root.

    This is not vendor rebaseline: old fingerprints/history stay STALE and exact.
    Backup and audit live outside .gauntlet. No resume or approval is implied.
    """
    git = subprocess.run(['git', 'rev-parse', '--show-toplevel', 'HEAD'], cwd=root,
                         capture_output=True, text=True, check=False)
    if git.returncode or git.stdout.splitlines() != [str(root), expected_head]:
        raise ValueError('checkout toplevel/HEAD mismatch')
    diagnostic = diagnose(root)
    if (diagnostic['run_id'] != expected_run or diagnostic['recorded_root'] != expected_root
            or diagnostic['state_sha256'] != expected_sha256):
        raise ValueError('expected run/root/state hash mismatch')
    validation = json.loads(diagnostic['validation_stdout'])
    if validation.get('errors') != ['state repository root does not match resolved repository']:
        raise ValueError('relocation requires exactly the root-only baseline failure')
    state_path = root / '.gauntlet/state.json'
    original = state_path.read_bytes()
    state = load(state_path)
    if state['evidence_freshness'] != 'STALE' or state['status'] != 'ACTIVE':
        raise ValueError('relocation requires explicitly STALE active evidence')
    manifest = backup(root, destination, diagnostic)
    destination = destination.absolute()
    original_root = state['repository']['root']
    state['repository']['root'] = str(root)
    candidate = (json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode()
    # Check semantic equality after reverting the sole permitted field in memory.
    unchanged = json.loads(candidate); unchanged['repository']['root'] = original_root
    if unchanged != json.loads(original):
        raise ValueError('unexpected non-root semantic mutation')
    protected = {name: sha((root / name).read_bytes()) for name in
                 ('.gauntlet/bar.json', '.gauntlet/history.jsonl', '.gauntlet/artifacts.jsonl')}
    audit = {'schema_version': 'prod12-relocation.v1', 'run_id': expected_run,
             'timestamp': datetime.now(timezone.utc).isoformat(), 'head': expected_head,
             'previous_root': expected_root, 'current_root': str(root),
             'previous_state_sha256': expected_sha256, 'candidate_state_sha256': sha(candidate),
             'backup_manifest_sha256': sha((destination / 'manifest.json').read_bytes()),
             'protected_sha256': protected, 'effect': 'current root only; old artifact evidence remains STALE',
             'result': 'PENDING', 'limitations': 'Structural binding only; artifact resume remains fail-closed.'}
    audit_path = destination / 'relocation-audit.json'
    with audit_path.open('x') as stream:
        json.dump(audit, stream, indent=2); stream.write('\n')
    # Recheck all inputs after backup and immediately before writing.
    if state_path.read_bytes() != original or subprocess.run(
            ['git', 'rev-parse', 'HEAD'], cwd=root, capture_output=True, text=True).stdout.strip() != expected_head:
        raise ValueError('inputs changed before relocation')
    try:
        replace_bytes(state_path, candidate)
        result = diagnose(root)
        if result['validation_exit_status'] != 0 or any(sha((root / name).read_bytes()) != value for name, value in protected.items()):
            raise ValueError('post-relocation vendor validation or protected hash failed')
        audit.update(result='PASS', validation_exit_status=0, state_sha256=result['state_sha256'])
    except BaseException:
        replace_bytes(state_path, original)
        audit['result'] = 'ROLLED_BACK'
        audit_path.write_text(json.dumps(audit, indent=2) + '\n')
        if state_path.read_bytes() != original:
            raise ValueError('rollback byte equality failed')
        raise
    audit_path.write_text(json.dumps(audit, indent=2) + '\n')
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--backup-dir', type=Path)
    parser.add_argument('--relocate', action='store_true', help='explicit guarded current-root rebind; never init/rebaseline')
    parser.add_argument('--expected-run')
    parser.add_argument('--expected-root')
    parser.add_argument('--expected-sha256')
    parser.add_argument('--expected-head')
    args = parser.parse_args()
    try:
        root = args.root.resolve(strict=True)
        if args.relocate:
            if not all((args.backup_dir, args.expected_run, args.expected_root, args.expected_sha256, args.expected_head)):
                raise ValueError('relocation requires backup-dir and all expected identity guards')
            audit = relocate(root, args.backup_dir, expected_run=args.expected_run,
                             expected_root=args.expected_root, expected_sha256=args.expected_sha256,
                             expected_head=args.expected_head)
            print(json.dumps(audit, indent=2, ensure_ascii=False))
            return 0
        result = diagnose(root)
        if args.backup_dir:
            result['backup'] = backup(root, args.backup_dir, result)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result['validation_exit_status'] == 0 else 2
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'FAIL: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
