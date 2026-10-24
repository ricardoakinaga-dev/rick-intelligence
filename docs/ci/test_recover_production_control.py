"""Discriminating guards for PROD12 adoption and reversible current-root relocation."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess

import recover_production_control as recovery


class AdoptionTests(unittest.TestCase):
    def test_all_contracts_and_dependencies_without_acceptance(self):
        items = recovery.proposed_items((recovery.ROOT / recovery.SPEC).read_text())
        self.assertEqual(len(items), 56)
        self.assertTrue(all(i['status'] == 'TODO' and not i['accepted'] and not i['evidence_refs'] for i in items))
        self.assertEqual(sum(i['mandatory'] for i in items), 55)
        self.assertEqual(items[16]['dependencies'], [f'PROD12-{n:03d}' for n in range(7, 15)] + ['PROD12-016'])
        self.assertIn('candidato errado/run divergente continua rejeitado', items[1]['acceptance_summary'])

    def test_missing_contract_rejected(self):
        text = (recovery.ROOT / recovery.SPEC).read_text().replace('### PROD12-056', '### REMOVED-056')
        with self.assertRaises(ValueError):
            recovery.proposed_items(text)

    def test_missing_unknown_self_cycle_dependencies_rejected(self):
        text = (recovery.ROOT / recovery.SPEC).read_text()
        for bad in ('999', '002', '056–001', '001,001'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                recovery.proposed_items(text.replace('| Lead/control plane | 001 |', f'| Lead/control plane | {bad} |'))
        with self.assertRaises(ValueError):
            recovery.proposed_items(text.replace('| Lead/QA | — |', '| Lead/QA | 002 |'))

    def test_vendor_has_no_official_relocation(self):
        commands = recovery.official_commands((recovery.ROOT / recovery.VENDOR).read_text())
        self.assertIn('recover', commands)
        self.assertIn('rebaseline', commands)
        self.assertFalse({'rebind', 'relocate'} & set(commands))


class RelocationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.destination = self.root / '.runtime/prod12-control/backup'
        self.state = {'run_id': 'test-run', 'repository': {'root': '/old/root', 'head_at_init': 'old-head'},
                      'status': 'ACTIVE', 'evidence_freshness': 'STALE', 'goal': {'text': 'frozen'},
                      'bar': {'sha256': 'frozen'}, 'artifact_fingerprint': {'historical_root': '/old/root'},
                      'round_count': 7, 'created_at': 'historical'}
        for name in ('.agent/state.json', '.agent/backlog.json', '.agent/PLANS.md', '.agent/execution-log.jsonl',
                     '.agent/verification.jsonl', '.gauntlet/state.json', '.gauntlet/bar.json',
                     '.gauntlet/history.jsonl', '.gauntlet/artifacts.jsonl', '.gauntlet/progress.md', '.gauntlet/state.md'):
            path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('historical bytes\n')
        (self.root / '.gauntlet/state.json').write_text(json.dumps(self.state, indent=2) + '\n')
        self.original = (self.root / '.gauntlet/state.json').read_bytes()
        self.expected = dict(expected_run='test-run', expected_root='/old/root',
                             expected_sha256=recovery.sha(self.original), expected_head='current-head')
        self.git = subprocess.CompletedProcess([], 0, f'{self.root}\ncurrent-head\n', '')

    def tearDown(self):
        self.temp.cleanup()

    def diagnostic(self, root):
        state = recovery.load(root / '.gauntlet/state.json')
        matches = state['repository']['root'] == str(root)
        return {'run_id': state['run_id'], 'recorded_root': state['repository']['root'],
                'state_sha256': recovery.sha((root / '.gauntlet/state.json').read_bytes()),
                'history_sha256': recovery.sha((root / '.gauntlet/history.jsonl').read_bytes()),
                'validation_exit_status': 0 if matches else 2,
                'validation_stdout': json.dumps({'errors': [] if matches else ['state repository root does not match resolved repository']})}

    def invoke(self, expected=None, diagnostic=None, git=None):
        def run(command, **kwargs):
            if command == ['git', 'rev-parse', 'HEAD']:
                return subprocess.CompletedProcess([], 0, 'current-head\n', '')
            return git or self.git
        with patch.object(recovery, 'diagnose', side_effect=diagnostic or self.diagnostic), patch.object(recovery.subprocess, 'run', side_effect=run):
            return recovery.relocate(self.root, self.destination, **(expected or self.expected))

    def test_only_current_root_changes_and_backup_exact(self):
        audit = self.invoke()
        after = recovery.load(self.root / '.gauntlet/state.json')
        after['repository']['root'] = '/old/root'
        self.assertEqual(after, self.state)
        self.assertEqual((self.destination / '.gauntlet/state.json').read_bytes(), self.original)
        self.assertEqual(audit['result'], 'PASS')
        self.assertEqual((self.root / '.gauntlet/history.jsonl').read_bytes(), b'historical bytes\n')

    def test_wrong_run_root_hash_head_rejected_without_write(self):
        for key in self.expected:
            with self.subTest(key=key):
                expected = {**self.expected, key: 'wrong'}
                with self.assertRaises(ValueError):
                    self.invoke(expected=expected)
                self.assertEqual((self.root / '.gauntlet/state.json').read_bytes(), self.original)
                self.assertFalse(self.destination.exists())

    def test_validation_failure_restores_exact_bytes(self):
        before = self.diagnostic(self.root)
        with self.assertRaises(ValueError):
            self.invoke(diagnostic=lambda root: before)
        self.assertEqual((self.root / '.gauntlet/state.json').read_bytes(), self.original)
        self.assertEqual(json.loads((self.destination / 'relocation-audit.json').read_text())['result'], 'ROLLED_BACK')

    def test_additional_validation_failure_refused(self):
        diagnostic = self.diagnostic(self.root)
        diagnostic['validation_stdout'] = json.dumps({'errors': ['wrong history']})
        with self.assertRaises(ValueError):
            self.invoke(diagnostic=lambda root: diagnostic)
        self.assertFalse(self.destination.exists())

    def test_symlink_input_refused(self):
        path = self.root / '.gauntlet/bar.json'; path.unlink()
        path.symlink_to(self.root / '.gauntlet/history.jsonl')
        with self.assertRaises(ValueError):
            self.invoke()
        self.assertEqual((self.root / '.gauntlet/state.json').read_bytes(), self.original)

    def test_backup_traversal_refused_before_any_mkdir(self):
        for relative in ('.runtime/prod12-control/../../outside-runtime',
                         '.runtime/prod12-control/../outside-control',
                         '.runtime/prod12-control/sub/../ambiguous-backup'):
            with self.subTest(relative=relative):
                destination = self.root / relative
                diagnostic = self.diagnostic(self.root)
                # Intercept every mkdir: the red run must never actually escape.
                with patch.object(Path, 'mkdir', side_effect=AssertionError('unsafe mkdir reached before containment rejection')) as mkdir:
                    with self.assertRaises(ValueError):
                        recovery.backup(self.root, destination, diagnostic)
                    mkdir.assert_not_called()
                self.assertEqual((self.root / '.gauntlet/state.json').read_bytes(), self.original)

    def test_backup_symlink_ancestor_rejected_before_resolve_or_write(self):
        allowed = self.root / '.runtime/prod12-control'
        allowed.mkdir(parents=True)
        target = self.root / 'private-fixture-target'
        target.mkdir()
        (allowed / 'jump').symlink_to(target, target_is_directory=True)
        diagnostic = self.diagnostic(self.root)
        with patch.object(Path, 'resolve', side_effect=AssertionError('symlink must not be followed')) as resolve, \
             patch.object(Path, 'mkdir', side_effect=AssertionError('write must not be attempted')) as mkdir:
            with self.assertRaisesRegex(ValueError, 'symlink'):
                recovery.backup(self.root, allowed / 'jump/backup', diagnostic)
            resolve.assert_not_called()
            mkdir.assert_not_called()
        self.assertEqual(list(target.iterdir()), [])

    def test_backup_existing_regular_file_never_overwritten(self):
        self.destination.parent.mkdir(parents=True)
        self.destination.write_bytes(b'preserve existing evidence')
        diagnostic = self.diagnostic(self.root)
        with patch.object(Path, 'mkdir', side_effect=AssertionError('write must not be attempted')) as mkdir:
            with self.assertRaisesRegex(ValueError, 'already exists'):
                recovery.backup(self.root, self.destination, diagnostic)
            mkdir.assert_not_called()
        self.assertEqual(self.destination.read_bytes(), b'preserve existing evidence')

    def test_backup_canonical_containment_checked_before_mkdir(self):
        diagnostic = self.diagnostic(self.root)
        allowed = self.root / '.runtime/prod12-control'
        def resolved(path, strict=False):
            # Structured race defense exercise: after the lexical preflight, the
            # canonical destination must still be confined. No real escape/write.
            return self.root / 'outside-control' if path == self.destination else allowed
        with patch.object(Path, 'resolve', autospec=True, side_effect=resolved), \
             patch.object(Path, 'mkdir', side_effect=AssertionError('write must not be attempted')) as mkdir:
            with self.assertRaisesRegex(ValueError, 'resolved backup escapes'):
                recovery.backup(self.root, self.destination, diagnostic)
            mkdir.assert_not_called()

    def test_backup_overwrite_refused(self):
        self.destination.mkdir(parents=True)
        with self.assertRaises(ValueError):
            self.invoke()
        self.assertEqual((self.root / '.gauntlet/state.json').read_bytes(), self.original)

    def test_current_evidence_not_silently_rehabilitated(self):
        self.state['evidence_freshness'] = 'CURRENT'
        path = self.root / '.gauntlet/state.json'; path.write_text(json.dumps(self.state))
        self.expected['expected_sha256'] = recovery.sha(path.read_bytes())
        with self.assertRaises(ValueError):
            self.invoke()
        self.assertFalse(self.destination.exists())


if __name__ == '__main__':
    unittest.main()
