"""Discriminating Linux/byte-boundary probes; all authority is TEST ONLY.

Docker and registry effects are replaced only outside the filesystem boundary.
The multi-UID test requires real CAP_SETUID/CAP_CHOWN and is explicitly skipped
in a one-UID sandbox. It is never replaced with a mocked readability result.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
import yaml
from test_safety import config, config_file, manifest, args, SOURCE, migration_fixture
from test_support import cli_assets, proposal, synthetic_tls
import assets
import contracts
import deploy

@pytest.mark.parametrize('attack', ['proc', 'parent', 'leaf', 'dotdot', 'fifo', 'world_write', 'sticky_world_child'])
def test_capture_component_boundaries_use_real_linux_filesystem(tmp_path, attack):
    child = tmp_path/'private'; child.mkdir(mode=0o700)
    p = child/'input'; p.write_bytes(b'TEST ONLY protected bytes'); p.chmod(0o600)
    assert contracts.capture(p, private=True) == p.read_bytes()
    if attack == 'proc':
        p = Path('/proc/self/root/usr/lib/os-release')
    elif attack == 'parent':
        alias = tmp_path/'alias'; alias.symlink_to(child, target_is_directory=True); p = alias/'input'
    elif attack == 'leaf':
        alias = child/'alias'; alias.symlink_to(p); p = alias
    elif attack == 'dotdot':
        p = child/'..'/'private'/'input'
    elif attack == 'fifo':
        p.unlink(); os.mkfifo(p, 0o600)
    elif attack == 'world_write':
        p.chmod(0o666)
    else:
        child.chmod(0o777)
    with pytest.raises(contracts.Refusal):
        contracts.capture(p)

def test_sticky_tmp_parent_and_private_child_are_supported(tmp_path):
    p = tmp_path/'input'; p.write_bytes(b'TEST ONLY'); p.chmod(0o600)
    assert contracts.capture(p, private=True) == b'TEST ONLY'
    assert Path('/tmp').stat().st_mode & 0o1000

@pytest.mark.parametrize('bad', ['hardlink_private', 'special_mode', 'oversize', 'double_slash', 'dot'])
def test_regular_role_and_lexical_bounds(tmp_path, bad):
    p = tmp_path/'input'; p.write_bytes(b'TEST ONLY'); p.chmod(0o600)
    if bad == 'hardlink_private': os.link(p,tmp_path/'alias')
    if bad == 'special_mode': p.chmod(0o4600)
    if bad == 'oversize':
        with p.open('r+b') as stream: stream.truncate(16*1024*1024+1)
    if bad == 'double_slash': p = str(tmp_path)+'//input'
    if bad == 'dot': p = str(tmp_path)+'/./input'
    with pytest.raises(contracts.Refusal): contracts.capture(p, private=True)

@pytest.mark.parametrize('replacement', ['symlink', 'directory', 'leaf'])
def test_capture_refuses_real_parent_replacement_after_dirfd_open(tmp_path, monkeypatch, replacement):
    parent = tmp_path/'bound'; parent.mkdir(mode=0o700)
    p = parent/'input'; p.write_bytes(b'ORIGINAL TEST ONLY'); p.chmod(0o600)
    other = tmp_path/'other'; other.mkdir(mode=0o700)
    (other/'input').write_bytes(b'REPLACEMENT TEST ONLY'); (other/'input').chmod(0o600)
    original = contracts.os.open; attacked = []
    def racing_open(path, flags, *a, **kw):
        fd = original(path, flags, *a, **kw)
        if path == ('input' if replacement == 'leaf' else 'bound') and not attacked:
            attacked.append(True)
            if replacement == 'leaf':
                p.rename(parent/'old-input'); (other/'input').rename(p)
            else:
                parent.rename(tmp_path/'retained-original')
                if replacement == 'symlink': parent.symlink_to(other, target_is_directory=True)
                else: other.rename(parent)
        return fd
    monkeypatch.setattr(contracts.os, 'open', racing_open)
    with pytest.raises(contracts.Refusal, match='replaced'):
        contracts.capture(p, private=True)
    assert attacked

def test_capture_refuses_changes_to_bound_file_during_read(tmp_path, monkeypatch):
    p = tmp_path/'input'; p.write_bytes(b'ORIGINAL'); p.chmod(0o600)
    original = contracts.os.read; attacked = []
    def racing_read(fd, size):
        data = original(fd, size)
        if not attacked:
            attacked.append(True); p.write_bytes(b'CHANGED BYTES')
        return data
    monkeypatch.setattr(contracts.os, 'read', racing_read)
    with pytest.raises(contracts.Refusal, match='changed'):
        contracts.capture(p)

@pytest.mark.parametrize('bad', ['public_key', 'fake_private_key', 'key_mismatch', 'ca_parse', 'cert_parse', 'untrusted_ca',
                               'ca_contains_key', 'cert_contains_key'])
def test_tls_requires_private_key_and_verified_public_identity(tmp_path, bad):
    values = config(tmp_path)
    if bad == 'public_key': Path(values['TLS_STORE_KEY']).chmod(0o644)
    if bad == 'fake_private_key': Path(values['TLS_STORE_KEY']).write_bytes(b'PUBLIC SYSTEM METADATA IS NOT A KEY')
    if bad == 'key_mismatch':
        result = subprocess.run(['openssl','genpkey','-algorithm','ED25519'],capture_output=True,check=True,timeout=15)
        Path(values['TLS_STORE_KEY']).write_bytes(result.stdout)
    if bad == 'ca_parse': Path(values['TLS_STORE_CA']).write_bytes(b'NOT PEM')
    if bad == 'cert_parse': Path(values['TLS_STORE_CERT']).write_bytes(b'NOT PEM')
    if bad == 'untrusted_ca':
        Path(values['TLS_STORE_CA']).write_bytes(synthetic_tls()['TLS_STORE_CERT'])
    if bad in {'ca_contains_key', 'cert_contains_key'}:
        p = Path(values['TLS_STORE_CA' if bad == 'ca_contains_key' else 'TLS_STORE_CERT'])
        p.write_bytes(p.read_bytes()+synthetic_tls()['TLS_STORE_KEY'])
    data = config_file(tmp_path, values).read_bytes()
    packet = proposal(data, values, SOURCE)  # Hashes of bad bytes cannot admit a bad TLS role.
    with pytest.raises(contracts.Refusal):
        assets.captured_tls(packet, values)

def test_tls_positive_parses_chain_and_all_three_sans(tmp_path):
    values = config(tmp_path); packet = proposal(config_file(tmp_path, values).read_bytes(), values, SOURCE)
    tls = assets.captured_tls(packet, values)
    assert set(tls) == set(assets.TLS_ROLES)

@pytest.mark.parametrize('path', ['/usr/lib/os-release', '/proc/self/root/usr/lib/os-release'])
def test_cli_public_metadata_key_never_reaches_operation_effects(tmp_path, monkeypatch, path):
    values = config(tmp_path)
    changed = dict(values, TLS_STORE_KEY=path)
    conf = config_file(tmp_path, changed); packet = manifest()
    m = tmp_path/'release.json'; m.write_text(json.dumps(packet)); m.chmod(0o600)
    cli = cli_assets(tmp_path, values, packet)
    proposal_path = Path(cli[1]); reviewed = json.loads(proposal_path.read_bytes())
    # Bind the actual public bytes correctly. Neither a correct hash nor a
    # synthetic review record can waive the key's filesystem role boundary.
    reviewed['tls']['TLS_STORE_KEY'] = assets.sha(Path(path).read_bytes())
    reviewed['bundle_id'] = assets.identity(reviewed)
    proposal_path.write_text(json.dumps(reviewed)); cli[3] = assets.sha(proposal_path.read_bytes()); cli[5] = reviewed['bundle_id']
    monkeypatch.setattr(sys, 'argv', ['deploy.py','install','--config',str(conf),
        '--trusted-config-sha256',assets.sha(conf.read_bytes()),'--manifest',str(m),
        '--trusted-manifest-sha256',assets.sha(m.read_bytes()),*cli])
    invoked = []
    monkeypatch.setattr(deploy,'execute_operation',lambda *a: invoked.append(a))
    with pytest.raises(contracts.Refusal, match='symlink' if '/proc/' in path else 'private config'):
        deploy.main()
    assert invoked == []

@pytest.mark.parametrize('bad', ['expired', 'missing_san'])
def test_tls_certificate_validity_and_san_are_enforced(tmp_path, bad):
    values = config(tmp_path)
    cert = Path(values['TLS_STORE_CERT']); key = Path(values['TLS_STORE_KEY'])
    command = ['openssl','req','-new','-x509','-key',str(key),'-out',str(cert),
               '-subj','/CN=TEST ONLY','-days','1']
    if bad == 'expired':
        # Sign a leaf with a past expiry; matching key and trusted self-signed
        # CA bytes cannot turn a stale certificate into a valid server identity.
        csr = tmp_path/'csr'
        subprocess.run(['openssl','req','-new','-key',str(key),'-out',str(csr),'-subj','/CN=TEST ONLY'],
                       check=True,capture_output=True,timeout=15)
        ext = tmp_path/'ext'; ext.write_text('subjectAltName=DNS:objects.internal,DNS:vectors.internal,DNS:redis\n')
        command = ['openssl','x509','-req','-in',str(csr),'-signkey',str(key),'-out',str(cert),
                   '-days','-1','-extfile',str(ext)]
    subprocess.run(command,check=True,capture_output=True,timeout=15)
    Path(values['TLS_STORE_CA']).write_bytes(cert.read_bytes())
    packet = proposal(config_file(tmp_path, values).read_bytes(), values, SOURCE)
    with pytest.raises(contracts.Refusal): assets.captured_tls(packet, values)

def test_inventory_is_reviewable_proposal_and_never_self_approves(tmp_path):
    values = config(tmp_path); conf = config_file(tmp_path, values)
    out = tmp_path/'proposal.json'
    a = argparse.Namespace(config=conf, output=out, source_sha=SOURCE,
                           bundle_root=tmp_path/'runtime-bundles',
                           operations_user=f'{os.geteuid()}:{os.getegid()}',
                           tls_user=f'{os.geteuid()}:{os.getegid()}')
    assets.inventory(a)
    packet = json.loads(out.read_bytes())
    assert packet['status'] == 'REVIEW_REQUIRED' and packet['bundle_id'] == assets.identity(packet)
    assert packet['config_sha256'] == assets.sha(conf.read_bytes())
    assert set(packet['files']) == set(assets.REPOSITORY_ASSETS)
    assert out.stat().st_mode & 0o777 == 0o600
    assert b'PRIVATE KEY' not in out.read_bytes() and 'authorization' not in packet
    with pytest.raises(FileExistsError): assets.inventory(a)

def test_unused_plan_mount_cannot_leak_runtime_credentials(tmp_path, monkeypatch):
    calls = []
    def execute(argv, env=None):
        if env:
            p = Path(env['VPS_PLAN_FILE'])
            assert p.read_bytes() == b'{}\n'
            assert p != Path(env['VPS_RUNTIME_FILE']) and p.stat().st_mode & 0o777 == 0o440
        calls.append(argv)
        return ''
    packet = manifest()
    deploy.execute_operation(args(tmp_path,'validate'),config(tmp_path),packet,contracts.images(packet),execute)
    assert len(calls) == 1

@pytest.mark.parametrize('bad', ['source_byte', 'manifest_hash', 'bundle_id', 'source_revision', 'role', 'missing_asset', 'extra_asset', 'tls_hash'])
def test_external_review_binding_refuses_changed_assets_before_effects(tmp_path, bad):
    values = config(tmp_path); config_data = config_file(tmp_path, values).read_bytes()
    cli = cli_assets(tmp_path, values, manifest())
    a = argparse.Namespace(assets=Path(cli[1]), trusted_assets_sha256=cli[3], reviewed_bundle_id=cli[5],
                           operations_user=cli[7], tls_user=cli[9], bundle_root=Path(cli[11]))
    if bad == 'source_byte':
        p = assets.ROOT/'infrastructure/vps/db_guard.py'; p.write_bytes(p.read_bytes()+b'\n# UNREVIEWED')
    elif bad == 'manifest_hash': a.trusted_assets_sha256 = '0'*64
    elif bad == 'bundle_id': a.reviewed_bundle_id = '0'*64
    elif bad == 'role': a.operations_user = '10001:10001'
    else:
        packet = json.loads(a.assets.read_bytes())
        if bad == 'source_revision': packet['source_sha'] = 'e'*40
        if bad == 'missing_asset': packet['files'].pop('infrastructure/vps/contracts.py')
        if bad == 'extra_asset': packet['files']['/proc/self/root/extra'] = '0'*64
        if bad == 'tls_hash': packet['tls']['TLS_STORE_KEY'] = '0'*64
        packet['bundle_id'] = assets.identity(packet); a.reviewed_bundle_id = packet['bundle_id']
        a.assets.write_text(json.dumps(packet)); a.trusted_assets_sha256 = assets.sha(a.assets.read_bytes())
    with pytest.raises(contracts.Refusal):
        packet, _ = assets.review_inputs(a, config_data, manifest())
        assets.captured_tls(packet, values)

@pytest.mark.parametrize('bad', ['bind', 'writable', 'env_file', 'include', 'build', 'job_user', 'application_user',
                               'root_script', 'destination', 'missing_profile'])
def test_compose_cannot_add_uncaptured_mounts_or_override_application_uid(bad):
    document = yaml.safe_load((assets.ROOT/'infrastructure/vps/compose.yml').read_bytes())
    if bad == 'bind': document['services']['edge']['volumes'].append('./UNREVIEWED:/secret:ro')
    if bad == 'writable': document['services']['edge']['volumes'][0] = './Caddyfile:/etc/caddy/Caddyfile'
    if bad == 'env_file': document['services']['api']['env_file'] = ['./mutable.env']
    if bad == 'include': document['include'] = ['./other-compose.yml']
    if bad == 'build': document['services']['api']['build'] = '.'
    if bad == 'job_user': document['services']['db-migrate']['user'] = '0:0'
    if bad == 'application_user': document['services']['api']['user'] = '0:0'
    if bad == 'root_script': document['services']['redis']['volumes'].append('./db_guard.py:/ops/db_guard.py:ro')
    if bad == 'destination': document['services']['edge']['volumes'][0] = './Caddyfile:/ops/db_guard.py:ro'
    if bad == 'missing_profile': document['services']['db-migrate']['profiles'] = []
    with pytest.raises(contracts.Refusal): assets.validate_compose(yaml.safe_dump(document).encode())

@pytest.mark.parametrize('name', ['compose', 'caddy', 'sql', 'code', 'tls_key', 'tls_cert', 'tls_ca'])
def test_cli_original_asset_replacement_never_reaches_compose_mounts(tmp_path, monkeypatch, name):
    values = config(tmp_path); conf = config_file(tmp_path, values); packet = manifest()
    m = tmp_path/'release.json'; m.write_text(json.dumps(packet)); m.chmod(0o600)
    targets = {'compose':assets.ROOT/'infrastructure/vps/compose.yml',
               'caddy':assets.ROOT/'infrastructure/vps/stores.Caddyfile',
               'sql':assets.ROOT/'docs/operations/0008-scope-preflight.sql',
               'code':assets.ROOT/'infrastructure/vps/db_guard.py',
               'tls_key':Path(values['TLS_STORE_KEY']), 'tls_cert':Path(values['TLS_STORE_CERT']),
               'tls_ca':Path(values['TLS_STORE_CA'])}
    target = targets[name]; expected = target.read_bytes(); original = assets.capture; count = []
    monkeypatch.setattr(sys,'argv',['deploy.py','install','--config',str(conf),
        '--trusted-config-sha256',assets.sha(conf.read_bytes()),'--manifest',str(m),
        '--trusted-manifest-sha256',assets.sha(m.read_bytes()),*cli_assets(tmp_path,values,packet)])
    def race(path, **kw):
        data = original(path, **kw)
        if path == target: count.append(True); target.write_bytes(b'UNREVIEWED REPLACEMENT')
        return data
    monkeypatch.setattr(assets, 'capture', race)
    from infrastructure.docker import check_release
    monkeypatch.setattr(deploy, 'release_errors', lambda *a,**kw: [])
    monkeypatch.setattr(deploy,'verify',lambda *a: None)
    calls = []; bundles = []
    operation = deploy.execute_operation
    def execute(argv, env=None):
        calls.append(argv)
        if argv[:2] == ['docker','compose']:
            compose = Path(argv[argv.index('-f')+1]); bundle = compose.parents[2]; bundles.append(bundle)
            assert compose != assets.ROOT/'infrastructure/vps/compose.yml'
            if name.startswith('tls_'):
                snap = Path(env[{'tls_key':'TLS_STORE_KEY','tls_cert':'TLS_STORE_CERT','tls_ca':'TLS_STORE_CA'}[name]])
            else: snap = bundle/target.relative_to(assets.ROOT)
            assert snap.read_bytes() == expected
            assert snap != target
            assert snap.stat().st_mode & 0o222 == 0
            assert Path(env['VPS_SCOPE_SQL']).is_relative_to(bundle)
        if argv[:2] == ['docker','run'] and '-v' in argv:
            mounts = [argv[i+1] for i,v in enumerate(argv) if v == '-v']
            assert all(':ro' in mount and str(target)+':' not in mount for mount in mounts)
        return json.dumps({'pending':[],'database_state':'EXISTING'}) if 'db-preflight' in argv else ''
    monkeypatch.setattr(deploy,'execute_operation',lambda a,c,m,r: operation(a,c,m,r,execute))
    deploy.main()
    assert len(count) == 1 and any('up' in c and 'api' in c for c in calls)
    assert bundles and all(bundle.exists() for bundle in bundles)
    assert all((bundle/'assets.json').exists() for bundle in bundles)

def test_simulated_installer_snapshot_modes_and_same_uid_read_access(tmp_path):
    assert os.geteuid() != 10001  # This Linux fixture is the different operator UID.
    values = config(tmp_path); a = args(tmp_path)
    plan = tmp_path/'plan'; plan.write_bytes(b'TEST ONLY private plan'); plan.chmod(0o600); a.plan = plan
    with assets.stage(a, values, manifest()) as (bundle, mounted, owner, tls_owner):
        assert owner[0] == os.geteuid() and owner[0] != 10001
        assert a.plan.stat().st_uid == owner[0] and a.plan.stat().st_mode & 0o777 == 0o440
        assets.prove_readable([a.plan], owner)
        # The same actual Linux reader loses access when owner-read is removed.
        # CAP_DAC_OVERRIDE-free caller is necessary for this negative probe.
        if os.geteuid() != 0:
            a.plan.chmod(0)
            with pytest.raises(contracts.Refusal, match='cannot read'):
                assets.prove_readable([a.plan], owner)
        assert Path(mounted['TLS_STORE_KEY']).stat().st_mode & 0o777 == 0o440
        assert Path(mounted['TLS_STORE_CA']).stat().st_mode & 0o777 == 0o444

@pytest.mark.skipif(os.geteuid() != 0, reason='NOT_RUN: sandbox has no CAP_SETUID/CAP_CHOWN or second UID mapping')
def test_linux_root_owned_snapshots_readable_by_selected_uid_and_immutable_to_reader(tmp_path, monkeypatch):
    # Run only in a disposable Linux test namespace with both UIDs mapped.
    # DAC needs virtual byte markers only; no certificate/key is generated.
    import test_safety
    virtual = {role:('TEST ONLY VIRTUAL '+role).encode() for role in assets.TLS_ROLES}
    monkeypatch.setattr(test_safety,'synthetic_tls',lambda:dict(virtual))
    values = config(tmp_path)
    a = argparse.Namespace(operation='validate', plan=None, retained_migrations=None, rollback_policy=None,
                           rollback_evidence=None, tls_user='0:0', operations_user='20002:20002')
    packet = proposal(b'TEST ONLY', values, SOURCE)
    a.captured_assets = packet, {name:(assets.ROOT/name).read_bytes() for name in assets.REPOSITORY_ASSETS}, virtual
    originals = {}
    for name in ('plan', 'rollback_evidence'):
        p = tmp_path/name; p.write_bytes(b'TEST ONLY private evidence'); p.chmod(0o600)
        originals[name] = p
    retained = tmp_path/'retained'; retained.mkdir(mode=0o700)
    sql = retained/'0001_test.sql'; sql.write_bytes(b'-- TEST ONLY retained SQL'); sql.chmod(0o600)
    policy = tmp_path/'policy'; policy.write_text(json.dumps({'retained_artifacts':{sql.name:assets.sha(sql.read_bytes())}}))
    policy.chmod(0o600); originals.update(rollback_policy=policy, retained_migrations=retained)
    a.rollback_policy_sha256 = assets.sha(policy.read_bytes())
    def selected_paths(bundle):
        return [bundle/'infrastructure/vps/db_guard.py', a.plan, a.rollback_policy,
                a.rollback_evidence, a.retained_migrations/sql.name]
    for name, path in originals.items(): setattr(a, name, path)
    # Stage itself creates the same real 0400 mount sources used by Compose.
    with assets.stage(a, values, manifest()) as (bundle, _, owner, _):
        paths = selected_paths(bundle)
        assert a.retained_migrations.stat().st_uid == 0 and a.retained_migrations.stat().st_gid == 20002
        assert a.retained_migrations.stat().st_mode & 0o777 == 0o750
        assert all(p.stat().st_uid == 0 and p.stat().st_mode & 0o777 == 0o440 for p in paths)
        assets.prove_readable(paths, owner)
        pid=os.fork()
        if pid == 0:
            try:
                os.setgroups([]);os.setgid(owner[1]);os.setuid(owner[0])
                for path in paths:
                    for change in (lambda:os.chmod(path,0o640),
                                   lambda:os.open(path,os.O_WRONLY),
                                   lambda:os.rename(path,path.with_suffix('.replaced'))):
                        try:change()
                        except PermissionError:pass
                        else:os._exit(6)
                os._exit(0)
            except BaseException:os._exit(7)
        _,status=os.waitpid(pid,0);assert status==0
        with pytest.raises(contracts.Refusal, match='cannot read'):
            assets.prove_readable(paths,(10001,10001))
    a.operations_user = '10001:10001'
    for name, path in originals.items(): setattr(a, name, path)
    with assets.stage(a, values, manifest()) as (bundle, _, owner, _):
        assets.prove_readable(selected_paths(bundle), owner)

def test_wrong_operation_owner_requires_privilege_before_effects(tmp_path):
    if os.geteuid() == 0: pytest.skip('root can assign scoped ownership')
    with pytest.raises(contracts.Refusal, match='needs root'):
        assets.principal('10001:10001')

def test_dac_image_probe_failure_precedes_writer_stop(tmp_path, monkeypatch):
    values = config(tmp_path); a = args(tmp_path,'migrate')
    p = tmp_path/'plan'; p.write_text(json.dumps(migration_fixture())); p.chmod(0o600); a.plan = p; a.plan_sha256 = assets.sha(p.read_bytes())
    monkeypatch.setattr(deploy,'verify',lambda *a: None)
    calls = []
    def execute(argv, env=None):
        calls.append(argv)
        if argv[:2] == ['docker','run'] and '--user' in argv and 'python' in argv:
            raise contracts.Refusal('TEST ONLY selected image cannot read bind files')
        return ''
    with pytest.raises(contracts.Refusal, match='cannot read'):
        deploy.execute_operation(a, values, manifest(), contracts.images(manifest()), execute)
    assert not any('stop' in c or 'up' in c or 'db-migrate' in c for c in calls)
    command = calls[-1]
    assert command[command.index('--network')+1] == 'none'
    assert command[command.index('--user')+1] == f'{os.geteuid()}:{os.getegid()}'

def test_missing_reviewed_bundle_cannot_invoke_execute_callback(tmp_path):
    a = argparse.Namespace(operation='install')
    calls = []
    with pytest.raises(contracts.Refusal, match='captured reviewed'):
        deploy.execute_operation(a,config(tmp_path),manifest(),contracts.images(manifest()),lambda *a: calls.append(a))
    assert calls == []

@pytest.mark.parametrize('bad', ['proc', 'parent_alias', 'public_directory', 'relative'])
def test_retained_bundle_directory_is_explicit_protected_and_nofollow(tmp_path, bad):
    parent = tmp_path/'bundles'; parent.mkdir(mode=0o700)
    if bad == 'proc': parent = Path('/proc/self/root')/str(parent).lstrip('/')
    if bad == 'parent_alias':
        alias = tmp_path/'alias'; alias.symlink_to(parent, target_is_directory=True); parent = alias
    if bad == 'public_directory': parent.chmod(0o777)
    if bad == 'relative': parent = Path('relative')
    with pytest.raises(contracts.Refusal): assets.retained_bundle(parent, 'a'*64)

def test_retained_bundle_parent_replacement_race_is_refused(tmp_path, monkeypatch):
    parent = tmp_path/'bundles'; parent.mkdir(mode=0o700)
    other = tmp_path/'other'; other.mkdir(mode=0o700)
    original = assets.os.open; attacked = []
    def racing_open(path, flags, *a, **kw):
        fd = original(path, flags, *a, **kw)
        if path == 'bundles' and not attacked:
            attacked.append(True)
            parent.rename(tmp_path/'old-bundles'); parent.symlink_to(other, target_is_directory=True)
        return fd
    monkeypatch.setattr(assets.os,'open',racing_open)
    with pytest.raises(contracts.Refusal, match='replaced'):
        assets.retained_bundle(parent, 'a'*64)
    assert list(other.iterdir()) == [] and list((tmp_path/'old-bundles').iterdir()) == []

def test_live_effect_failure_retains_mount_sources_and_old_bundles(tmp_path, monkeypatch):
    values = config(tmp_path); a = args(tmp_path,'preflight'); packet = manifest()
    sentinel = a.bundle_root/'OLD_BUNDLE_SENTINEL'; sentinel.write_bytes(b'RETAIN OLD BYTES')
    monkeypatch.setattr(deploy, 'verify', lambda *a: None)
    observed = []
    def execute(argv, env=None):
        if argv[:2] == ['docker','compose']:
            bundle = Path(argv[argv.index('-f')+1]).parents[2]
            observed.append(bundle)
            if 'db-preflight' in argv: raise contracts.Refusal('TEST ONLY failure after store startup')
        return ''
    with pytest.raises(contracts.Refusal):
        deploy.execute_operation(a, values, packet, contracts.images(packet), execute)
    assert sentinel.read_bytes() == b'RETAIN OLD BYTES'
    assert observed and all(bundle.exists() for bundle in observed)
    bundle = observed[-1]
    assert (bundle/'tls/TLS_STORE_KEY').read_bytes() == synthetic_tls()['TLS_STORE_KEY']
    assert (bundle/'infrastructure/vps/stores.Caddyfile').exists()
    assert (bundle/'assets.json').exists()

@pytest.mark.parametrize('user', ['0:0', '1000:0', 'root:root', '10001', '-1:10001', '4294967295:10001'])
def test_operation_user_contract_has_no_root_or_implicit_selection(user):
    with pytest.raises(contracts.Refusal): assets.principal(user)
