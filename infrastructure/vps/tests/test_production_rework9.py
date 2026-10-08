"""Tool output identity through public publication; native tools are callbacks.

Real leaf chmod/chown/link/replace operations run as the current user. These
checks do not prove separated-UID DAC or native tool behavior.
"""
import os
from pathlib import Path
import stat

import pytest
import contracts
import publication_capture as capture
import publish_candidate as pub
from test_rework5 import candidate
from test_rework7 import PublicTools, mounted


ATTACKS = ['readonly', 'executable', 'shared', 'setgid', 'replace',
           'symlink', 'hardlink', 'gid', 'oversize']
EVENTS = ['admission', 'scan', 'auth', 'copy', 'sign_auth', 'sign', 'attest',
          'verify', 'verify-attestation']
OUTPUTS = {'scan': 'scan.json', 'copy': 'registry.digest',
           'sign': 'signature.bundle.json', 'attest': 'attestation.bundle.json'}


def change_output(path, attack):
    modes = {'readonly': 0o400, 'executable': 0o700, 'shared': 0o644,
             'setgid': 0o2600}
    if attack in modes:
        path.chmod(modes[attack])
        assert stat.S_IMODE(path.stat().st_mode) == modes[attack]
    elif attack in {'replace', 'symlink'}:
        before = path.stat()
        saved = path.with_name(path.name + '.previous')
        path.rename(saved)
        if attack == 'replace':
            path.write_bytes(saved.read_bytes())
            path.chmod(0o600)
            assert path.stat().st_ino != before.st_ino
        else:
            path.symlink_to(saved)
    elif attack == 'hardlink':
        os.link(path, path.with_name(path.name + '.alias'))
        assert path.stat().st_nlink == 2
    elif attack == 'oversize':
        with path.open('r+b') as stream:
            stream.truncate(16 * 1024**2 + 1)
    elif attack == 'gid':
        before = path.stat()
        group = next((g for g in {os.getegid(), *os.getgroups()}
                      if g != before.st_gid), None)
        if group is None:
            pytest.skip('alternate member gid unavailable without privilege')
        try:
            os.chown(path, -1, group)
        except PermissionError:
            pytest.skip('owner cannot change output to alternate member gid')
        after = path.stat()
        assert after.st_gid != before.st_gid
        assert (after.st_dev, after.st_ino, after.st_mode, after.st_uid) == (
            before.st_dev, before.st_ino, before.st_mode, before.st_uid)
    else:
        raise AssertionError(attack)


class OutputTools(PublicTools):
    def __init__(self, candidate, monkeypatch, stage=None, attack=None):
        super().__init__(candidate, monkeypatch)
        self.output_stage = stage
        self.output_attack = attack
        self.snapshot_modes = []
        export = capture.PublicationCapture.export

        def exported(captured, name, path):
            result = export(captured, name, path)
            snapshot = captured.retained[name]
            self.snapshot_modes.append(stat.S_IMODE(snapshot.path.stat().st_mode))
            if name in OUTPUTS.values():
                output = captured.outputs / name
                assert stat.S_IMODE(output.stat().st_mode) == 0o600
                assert snapshot.path.stat().st_ino != output.stat().st_ino
                assert Path(path).read_bytes() == snapshot.read()
            return result

        monkeypatch.setattr(capture.PublicationCapture, 'export', exported)

    def command(self, argv):
        if argv[0] == 'docker':
            stage = 'scan' if 'image' in argv else 'copy'
            output = mounted(argv, '/output')[0] / OUTPUTS[stage]
        else:
            stage = argv[1]
            output = (Path(argv[argv.index('--bundle') + 1])
                      if stage in {'sign', 'attest'} else None)
        initial = output.stat() if output is not None else None
        result = super().command(argv)
        if stage in {'sign', 'attest'}:
            output.write_bytes(b'{"TEST_ONLY_bundle":true}\n')
        if output is not None:
            assert output.stat().st_ino == initial.st_ino
            assert output.stat().st_size > initial.st_size
        if stage == self.output_stage:
            change_output(output, self.output_attack)
        return result


@pytest.mark.parametrize('stage', list(OUTPUTS))
@pytest.mark.parametrize('attack', ATTACKS)
def test_public_output_drift_stops_before_snapshot_export_or_next_effect(
        candidate, monkeypatch, stage, attack):
    tools = OutputTools(candidate, monkeypatch, stage, attack)
    with pytest.raises(contracts.Refusal):
        pub.main()
    assert tools.events == EVENTS[:EVENTS.index(stage) + 1]
    assert not (candidate / OUTPUTS[stage]).exists()
    assert not (candidate / 'candidate.json').exists()
    assert not tools.snapshot_root.exists()


@pytest.mark.parametrize('authority_mode', [0o400, 0o600, 0o700])
def test_public_healthy_tool_writes_keep_readonly_snapshots(
        candidate, monkeypatch, authority_mode):
    # Public source policy remains broader than the prepared output binding.
    authority = candidate / 'quality.json'
    authority.chmod(authority_mode)
    for name in ['image.tar', 'buildx.json']:
        (candidate / name).chmod(0o644)
    tools = OutputTools(candidate, monkeypatch)
    pub.main()
    assert tools.events == EVENTS
    assert tools.snapshot_modes and set(tools.snapshot_modes) == {0o400}
    assert contracts.parse((candidate / 'candidate.json').read_bytes())['status'] == 'CANDIDATE'
    assert stat.S_IMODE(authority.stat().st_mode) == authority_mode
    assert not tools.snapshot_root.exists()


@pytest.mark.parametrize('attack', ATTACKS)
def test_output_rejected_before_any_retained_snapshot(attack):
    with capture.PublicationCapture({}) as captured:
        identity = captured.prepare_output('scan.json')
        output = captured.outputs / 'scan.json'
        output.write_bytes(b'{}')
        change_output(output, attack)
        with pytest.raises(contracts.Refusal):
            captured.retain_output('scan.json', identity)
        assert captured.retained == {}
        assert captured.sources == []
        assert not (captured.inputs / 'scan.json').exists()


def test_initial_metadata_binding_allows_content_size_and_timestamp_updates():
    with capture.PublicationCapture({}) as captured:
        identity = captured.prepare_output('scan.json')
        output = captured.outputs / 'scan.json'
        initial = output.stat()
        assert identity == (initial.st_dev, initial.st_ino, initial.st_mode,
                            initial.st_uid, initial.st_gid)
        output.write_bytes(b'{"first":true}')
        captured.verify()
        output.write_bytes(b'{}')
        os.utime(output, ns=(initial.st_atime_ns, initial.st_mtime_ns + 1_000_000_000))
        captured.verify()
        snapshot = captured.retain_output('scan.json', identity)
        assert snapshot.read() == b'{}'
        assert stat.S_IMODE(snapshot.path.stat().st_mode) == 0o400
        assert stat.S_IMODE(output.stat().st_mode) == 0o600


def test_caller_cannot_rebind_drifted_output():
    with capture.PublicationCapture({}) as captured:
        captured.prepare_output('scan.json')
        output = captured.outputs / 'scan.json'
        output.write_bytes(b'{}')
        output.chmod(0o400)
        current = output.stat()
        forged = (current.st_dev, current.st_ino, current.st_mode,
                  current.st_uid, current.st_gid)
        with pytest.raises(contracts.Refusal):
            captured.retain_output('scan.json', forged)
        assert not (captured.inputs / 'scan.json').exists()


@pytest.mark.parametrize('attack', ['readonly', 'executable', 'replace', 'gid'])
def test_opened_output_rechecked_before_snapshot(monkeypatch, attack):
    with capture.PublicationCapture({}) as captured:
        identity = captured.prepare_output('scan.json')
        output = captured.outputs / 'scan.json'
        output.write_bytes(b'{}')
        bound_file = capture.BoundFile

        def changed_before_open(path, *args, **kwargs):
            if Path(path) == output:
                change_output(output, attack)
            return bound_file(path, *args, **kwargs)

        monkeypatch.setattr(capture, 'BoundFile', changed_before_open)
        with pytest.raises(contracts.Refusal):
            captured.retain_output('scan.json', identity)
        assert captured.sources == []
        assert captured.retained == {}
        assert not (captured.inputs / 'scan.json').exists()
