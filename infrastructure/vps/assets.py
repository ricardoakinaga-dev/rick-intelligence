"""Offline reviewed mounted-byte inventory and protected Linux operation bundle.

Inventory is a proposal. Only an independently supplied manifest hash and bundle
identity admit its bytes. Image signatures do not authenticate mounted code.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import secrets
import yaml
from contracts import Refusal, capture, check_hash, parse

ROOT = Path(__file__).absolute().parents[2]
REPOSITORY_ASSETS = (
    'infrastructure/vps/compose.yml', 'infrastructure/vps/config.env.example',
    'infrastructure/vps/Caddyfile', 'infrastructure/vps/stores.Caddyfile',
    'infrastructure/vps/db_guard.py', 'infrastructure/vps/contracts.py',
    'infrastructure/vps/object-bootstrap.sh', 'infrastructure/vps/deploy.py',
    'infrastructure/vps/assets.py', 'infrastructure/vps/admission.py',
    'infrastructure/vps/trusted_code.py', 'infrastructure/vps/fresh_inventory.py',
    'infrastructure/vps/construction_contract.py', 'infrastructure/vps/publish_guard.py',
    'infrastructure/vps/buildx_binary.py',
    'infrastructure/docker/check_release.py', 'scripts/state_of_art/json_boundary.py',
    'infrastructure/docker/rollout-policy.json',
    'infrastructure/docker/api.Dockerfile', 'infrastructure/docker/worker.Dockerfile',
    'infrastructure/docker/web.Dockerfile', 'docs/operations/0008-scope-preflight.sql',
)
TLS_ROLES = ('TLS_STORE_CERT', 'TLS_STORE_KEY', 'TLS_STORE_CA')

def sha(data):
    return hashlib.sha256(data).hexdigest()

def principal(value, *, allow_root=False):
    if not isinstance(value, str) or not re.fullmatch(r'(0|[1-9][0-9]{0,9}):(0|[1-9][0-9]{0,9})', value):
        raise Refusal('explicit numeric operation/TLS UID:GID required')
    uid, gid = map(int, value.split(':'))
    if max(uid, gid) >= 2**32 - 1 or (not allow_root and (uid == 0 or gid == 0)):
        raise Refusal('operations require a non-root UID and GID')
    if os.geteuid() != 0 and (uid, gid) != (os.geteuid(), os.getegid()):
        raise Refusal('installer needs root to assign another snapshot owner')
    return uid, gid

def identity(packet):
    body = {k: v for k, v in packet.items() if k != 'bundle_id'}
    return sha(json.dumps(body, sort_keys=True, separators=(',', ':')).encode())

def review_inputs(args, config_data, manifest):
    packet = parse(capture(args.assets, private=True), args.trusted_assets_sha256)
    if (packet.get('schema') != 'rick.vps.assets/v1' or packet.get('status') != 'REVIEW_REQUIRED'
        or packet.get('source_sha') != manifest['source_revision']['value']
        or packet.get('config_sha256') != sha(config_data)
        or packet.get('operations_user') != args.operations_user
        or packet.get('tls_user') != args.tls_user
        or packet.get('bundle_root') != str(args.bundle_root)
        or packet.get('bundle_id') != args.reviewed_bundle_id
        or identity(packet) != args.reviewed_bundle_id
        or set(packet.get('files', {})) != set(REPOSITORY_ASSETS)
        or set(packet.get('tls', {})) != set(TLS_ROLES)):
        raise Refusal('reviewed assets identity, source, roles or inventory mismatch')
    principal(args.operations_user)
    principal(args.tls_user, allow_root=True)
    files = {}
    for name in REPOSITORY_ASSETS:
        data = capture(ROOT / name)
        check_hash(data, packet['files'][name])
        files[name] = data
    validate_compose(files['infrastructure/vps/compose.yml'])
    return packet, files

def validate_compose(data):
    """Close the mount inventory; future mounts need an explicit code review."""
    document = yaml.safe_load(data)
    bind_sources = {'./Caddyfile', './stores.Caddyfile', './db_guard.py', './contracts.py',
                    './object-bootstrap.sh'}
    generated = {'TLS_STORE_CERT', 'TLS_STORE_KEY', 'TLS_STORE_CA', 'VPS_SCOPE_SQL',
                 'VPS_PLAN_FILE', 'VPS_ROLLBACK_POLICY_FILE', 'VPS_ROLLBACK_EVIDENCE_FILE',
                 'VPS_RETAINED_MIGRATIONS'}
    persistent = {'postgres-data', 'redis-data', 'qdrant-data', 'object-data', 'caddy-data'}
    jobs = {'db-preflight', 'db-migrate', 'db-retained-preflight', 'db-rollback-preflight',
            'object-bootstrap', 'vector-bootstrap'}
    standard_job = {'TLS_STORE_CA', './db_guard.py', './contracts.py', 'VPS_SCOPE_SQL', 'VPS_PLAN_FILE'}
    permitted = {'postgres': {'postgres-data'}, 'redis': {'redis-data', 'TLS_STORE_CERT', 'TLS_STORE_KEY', 'TLS_STORE_CA'},
                 'qdrant': {'qdrant-data'}, 'object-store': {'object-data'},
                 'stores-tls': {'./stores.Caddyfile', 'TLS_STORE_CERT', 'TLS_STORE_KEY'},
                 'edge': {'./Caddyfile', 'caddy-data'}, 'api': {'TLS_STORE_CA'}, 'worker': {'TLS_STORE_CA'},
                 'web': set(), 'object-bootstrap': {'TLS_STORE_CA', './object-bootstrap.sh'},
                 'db-rollback-preflight': {'TLS_STORE_CA', './db_guard.py', './contracts.py',
                                          'VPS_ROLLBACK_POLICY_FILE', 'VPS_ROLLBACK_EVIDENCE_FILE', 'VPS_RETAINED_MIGRATIONS'},
                 **{name: standard_job for name in ('db-preflight', 'db-migrate', 'db-retained-preflight', 'vector-bootstrap')}}
    destinations = {'./Caddyfile': '/etc/caddy/Caddyfile', './stores.Caddyfile': '/etc/caddy/Caddyfile',
                    './db_guard.py': '/ops/db_guard.py', './contracts.py': '/ops/contracts.py',
                    './object-bootstrap.sh': '/ops/bootstrap.sh', 'TLS_STORE_CERT': '/tls/store.crt',
                    'TLS_STORE_KEY': '/tls/store.key', 'TLS_STORE_CA': '/tls/ca-bundle.crt',
                    'VPS_SCOPE_SQL': '/ops/0008-scope-preflight.sql', 'VPS_PLAN_FILE': '/ops/migration-plan.json',
                    'VPS_ROLLBACK_POLICY_FILE': '/ops/rollback-policy.json',
                    'VPS_ROLLBACK_EVIDENCE_FILE': '/ops/rollback-compatibility.json',
                    'VPS_RETAINED_MIGRATIONS': '/ops/retained-migrations'}
    if not isinstance(document, dict) or set(document) != {'x-bounds', 'x-job', 'services', 'volumes', 'networks'}:
        raise Refusal('unsupported Compose composition outside captured inventory')
    services = document['services']
    if set(services) != {'postgres', 'redis', 'qdrant', 'object-store', 'stores-tls',
                         'db-preflight', 'db-migrate', 'db-retained-preflight',
                         'db-rollback-preflight', 'object-bootstrap', 'vector-bootstrap',
                         'api', 'worker', 'web', 'edge'}:
        raise Refusal('unsupported Compose service outside reviewed operation contract')
    for name, service in services.items():
        if any(k in service for k in ('build', 'extends', 'configs', 'secrets', 'volumes_from')):
            raise Refusal('unsupported Compose asset source')
        seen = set()
        for volume in service.get('volumes', []):
            if not isinstance(volume, str):
                raise Refusal('unsupported Compose mount syntax')
            # Interpolation contains a colon; split only at the mount delimiter.
            match = re.fullmatch(r'(\$\{([A-Z_]+):\?required\}|\./[^:]+|[a-z-]+):(/[^:]+)(:ro)?', volume)
            if not match:
                raise Refusal('unsupported Compose mount outside captured inventory')
            source, variable, target, readonly = match.groups()
            role = variable or source
            if role not in permitted[name] or role in seen:
                raise Refusal('Compose asset role/reader mismatch')
            seen.add(role)
            if source in persistent:
                continue
            if (source not in bind_sources and variable not in generated) or readonly != ':ro':
                raise Refusal('uncaptured or writable Compose mounted asset')
            if target != destinations[role]:
                raise Refusal('Compose asset destination mismatch')
        if seen != permitted[name]:
            raise Refusal('incomplete Compose mounted asset inventory')
        for path in service.get('env_file', []):
            if path not in {'${VPS_'+role+'_FILE:?required}' for role in
                            ('RUNTIME', 'PREFLIGHT', 'MIGRATION', 'OBJECT', 'VECTOR')}:
                raise Refusal('uncaptured Compose environment asset')
        if name in jobs:
            if (service.get('user') != '${VPS_OPERATIONS_USER:?reviewed non-root UID:GID required}'
                or service.get('profiles') != ['operations'] or service.get('read_only') is not True
                or service.get('cap_drop') != ['ALL'] or service.get('security_opt') != ['no-new-privileges:true']):
                raise Refusal('explicit operation user required in Compose')
    for name in ('api', 'worker', 'web'):
        if 'user' in services[name]:
            raise Refusal('application image non-root runtime must be retained')
    for name in ('redis', 'stores-tls', 'edge'):
        if services[name].get('user') != '${VPS_TLS_USER:?reviewed key reader UID:GID required}':
            raise Refusal('explicit TLS/configuration reader required in Compose')

def openssl(*arguments, data=None):
    result = subprocess.run(['openssl', *arguments], input=data, capture_output=True, timeout=15)
    if result.returncode:
        raise Refusal('TLS parsing, identity or chain validation refused')
    return result.stdout

def validate_tls(tls):
    # Entire PEM CA bundle is parsed, then OpenSSL verifies expiry, trust chain,
    # server purpose and every internal DNS identity. No TLS socket is opened.
    ca = tls['TLS_STORE_CA']
    for role in ('TLS_STORE_CA', 'TLS_STORE_CERT'):
        public = tls[role]
        blocks = re.findall(rb'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----', public, re.S)
        remainder = re.sub(rb'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----', b'', public, flags=re.S)
        if not blocks or any(line.strip() and not line.lstrip().startswith(b'#') for line in remainder.splitlines()):
            raise Refusal('public TLS input must contain only PEM certificates and comments')
        for block in blocks:
            openssl('x509', '-noout', data=block)
    if b'ENCRYPTED' in tls['TLS_STORE_KEY']:
        raise Refusal('automated store startup requires a protected unencrypted key')
    key_pub = openssl('pkey', '-pubout', '-outform', 'DER', data=tls['TLS_STORE_KEY'])
    cert_pub = openssl('pkey', '-pubin', '-outform', 'DER',
                       data=openssl('x509', '-pubkey', '-noout', data=tls['TLS_STORE_CERT']))
    if key_pub != cert_pub:
        raise Refusal('TLS certificate/private key identity mismatch')
    with tempfile.TemporaryDirectory(prefix='rick-tls-check-') as folder:
        cert = Path(folder)/'cert.pem'; cert.write_bytes(tls['TLS_STORE_CERT']); cert.chmod(0o600)
        roots = Path(folder)/'ca.pem'; roots.write_bytes(ca); roots.chmod(0o600)
        # Requiring SANs prevents legacy CN fallback admitting the wrong role.
        sans = openssl('x509', '-ext', 'subjectAltName', '-noout', data=tls['TLS_STORE_CERT'])
        for host in ('objects.internal', 'vectors.internal', 'redis'):
            if host.encode() not in re.findall(rb'DNS:([^,\s]+)', sans):
                raise Refusal('TLS store certificate requires all internal SAN identities')
            openssl('verify', '-purpose', 'sslserver', '-verify_hostname', host,
                    '-CAfile', str(roots), str(cert))

def captured_tls(packet, config):
    result = {}
    for role in TLS_ROLES:
        data = capture(Path(config[role]), private=role == 'TLS_STORE_KEY')
        check_hash(data, packet['tls'][role])
        result[role] = data
    validate_tls(result)
    return result


def prove_readable(paths, owner):
    """Read as the actual selected Linux principal.

    Only regular snapshot files are read. The fork does not execute mounted
    scripts; it proves private DAC independently of an image or Docker socket.
    A root installer drops supplementary groups before changing identities.
    """
    uid, gid = owner
    pid = os.fork()
    if pid == 0:
        try:
            if os.geteuid() == 0:
                os.setgroups([]); os.setgid(gid); os.setuid(uid)
            if (os.geteuid(), os.getegid()) != owner:
                os._exit(3)
            for path in paths:
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                try:
                    if not stat.S_ISREG(os.fstat(fd).st_mode):
                        os._exit(4)
                    while os.read(fd, 65536):
                        pass
                finally:
                    os.close(fd)
            os._exit(0)
        except BaseException:
            os._exit(5)
    _, status = os.waitpid(pid, 0)
    if status != 0:
        raise Refusal('selected operation/TLS user cannot read protected snapshots')

def retained_bundle(parent, bundle_id, keeper=None):
    """Create only a new bundle in an explicitly selected protected directory.

    Keep actual runtime bind sources across container restarts. Never enumerate
    or delete other bundles, including when this operation fails.
    """
    value = os.fspath(parent)
    parts = value.split('/')
    if (parts[0] != '' or any(part in {'', '.', '..'} for part in parts[1:])
        or any(c.isspace() or ord(c) < 32 or c in ':$`\'"\\' for c in value)):
        raise Refusal('absolute lexical retained bundle directory required')
    descriptors = []
    bindings = []
    try:
        current = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        descriptors.append(current)
        for component in parts[1:]:
            previous = current
            current = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                              dir_fd=previous)
            descriptors.append(current)
            info = os.fstat(current)
            if (info.st_uid not in {0, os.geteuid()}
                or (info.st_mode & 0o022 and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX))):
                raise Refusal('unprotected retained bundle parent')
            bindings.append((previous, component, info))
        if info.st_uid not in {0, os.geteuid()} or info.st_mode & 0o022:
            raise Refusal('installer-owned protected retained bundle directory required')
        name = bundle_id+'-'+secrets.token_hex(8)
        os.mkdir(name, 0o700, dir_fd=current)
        for directory, component, original in bindings:
            now = os.stat(component, dir_fd=directory, follow_symlinks=False)
            if any(getattr(now,k) != getattr(original,k) for k in ('st_dev','st_ino','st_mode','st_uid','st_gid')):
                os.rmdir(name, dir_fd=current)
                raise Refusal('retained bundle parent replaced during creation')
        if keeper is not None:
            keeper.parent_fd = current
            keeper.ancestors.extend(descriptors)
            keeper.bindings.extend((d,n,original,False) for d,n,original in bindings)
            descriptors = []
        return parent/name
    except OSError:
        raise Refusal('retained bundle directory unavailable or contains symlink') from None
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)

def installer_owner(op_owner, tls_owner):
    # Job identities can read inputs but must never own executable inputs or
    # their parents. Root TLS compatibility explicitly trusts that reader as
    # part of the installer boundary; it grants no isolation from root.
    if os.geteuid() != 0:
        raise Refusal('root installer required for immutable reader snapshots')
    if op_owner[0] == os.geteuid() or (tls_owner[0] == os.geteuid() and tls_owner != (0,0)):
        raise Refusal('installer and operation reader identities must differ')
    return os.geteuid()


class BoundTree:
    """Hold directory/leaf inodes for the entire staging and effect lifetime."""
    def __init__(self):
        self.ancestors = []
        self.bindings = []
        self.directories = {}
        self.leaves = []

    def bind(self, root):
        # retained_bundle has already bound the protected parent hierarchy.
        # validate's temporary parent is the trusted sticky /tmp boundary.
        if hasattr(self,'parent_fd'):
            parent = self.parent_fd
        else:
            parent = os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
            self.ancestors.append(parent)
            for component in root.parent.parts[1:]:
                fd = os.open(component,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=parent)
                self.ancestors.append(fd)
                info = os.fstat(fd)
                if (info.st_uid not in {0,os.geteuid()}
                    or (info.st_mode & 0o022 and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX))):
                    raise Refusal('protected installer snapshot ancestors required')
                self.bindings.append((parent,component,info,False))
                parent = fd
        fd = os.open(root.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=parent)
        self.ancestors.append(fd)
        os.fchmod(fd,0o711)
        info = os.fstat(fd)
        if info.st_uid != os.geteuid():
            raise Refusal('installer-owned snapshot root required')
        self.bindings.append((parent,root.name,info,False))
        self.directories[''] = fd

    def directory(self, relative, gid=None, mode=0o711):
        if relative in self.directories:
            return self.directories[relative]
        path = Path(relative)
        if path.is_absolute() or any(part in {'.','..'} for part in path.parts):
            raise Refusal('lexical snapshot component required')
        parent = self.directory(str(path.parent) if str(path.parent) != '.' else '')
        os.mkdir(path.name,0o700,dir_fd=parent)
        fd = os.open(path.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=parent)
        self.ancestors.append(fd)
        if gid is not None:
            os.fchown(fd,-1,gid)
        os.fchmod(fd,mode)
        self.bindings.append((parent,path.name,os.fstat(fd),False))
        self.directories[relative] = fd
        return fd

    def write(self, relative, data, gid, mode=0o440):
        path = Path(relative)
        parent = self.directory(str(path.parent) if str(path.parent) != '.' else '')
        fd = os.open(path.name,os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=parent)
        self.ancestors.append(fd)
        view = memoryview(data)
        while view:
            written = os.write(fd,view)
            view = view[written:]
        os.fchown(fd,-1,gid)
        os.fchmod(fd,mode)
        os.fsync(fd)
        info = os.fstat(fd)
        if info.st_uid != os.geteuid() or info.st_nlink != 1 or info.st_mode & 0o222:
            raise Refusal('installer-owned sole-link immutable snapshot required')
        self.bindings.append((parent,path.name,info,True))
        self.leaves.append((fd,info))

    def verify(self):
        for parent,name,original,leaf in self.bindings:
            current = os.stat(name,dir_fd=parent,follow_symlinks=False)
            fields = ('st_dev','st_ino','st_mode','st_uid','st_gid')
            if leaf:
                fields += ('st_nlink','st_size','st_mtime_ns','st_ctime_ns')
            if any(getattr(current,k) != getattr(original,k) for k in fields):
                raise Refusal('protected snapshot component changed before effects')
        for fd,original in self.leaves:
            current = os.fstat(fd)
            if any(getattr(current,k) != getattr(original,k) for k in
                   ('st_dev','st_ino','st_mode','st_uid','st_gid','st_nlink','st_size','st_mtime_ns','st_ctime_ns')):
                raise Refusal('protected snapshot bytes changed before effects')

    def close(self):
        for fd in reversed(self.ancestors):
            os.close(fd)


@contextmanager
def stage(args, config, manifest):
    if not hasattr(args, 'captured_assets'):
        raise Refusal('captured reviewed assets required before operation effects')
    packet, files, tls = args.captured_assets
    op_owner = principal(args.operations_user)
    tls_owner = principal(args.tls_user, allow_root=True)
    installer_owner(op_owner,tls_owner)
    tree = BoundTree()
    @contextmanager
    def lifetime():
        if args.operation == 'validate':
            with tempfile.TemporaryDirectory(prefix='rick-protected-bundle-') as folder:
                yield Path(folder)
        else:
            yield retained_bundle(args.bundle_root,packet['bundle_id'],tree)
    try:
        with lifetime() as root:
            tree.bind(root)
            args.bundle_binding = tree
            for name,data in files.items():
                check_hash(data,packet['files'][name])
                gid = tls_owner[1] if name.endswith(('Caddyfile','stores.Caddyfile')) else op_owner[1]
                tree.write(name,data,gid)
            mounted = dict(config)
            for role,data in tls.items():
                path = root/'tls'/role
                tree.write('tls/'+role,data,tls_owner[1] if role == 'TLS_STORE_KEY' else op_owner[1],
                           0o440 if role == 'TLS_STORE_KEY' else 0o444)
                mounted[role] = str(path)
            mounted['VPS_SCOPE_SQL'] = str(root/'docs/operations/0008-scope-preflight.sql')
            mounted['VPS_OPERATIONS_USER'] = args.operations_user
            mounted['VPS_TLS_USER'] = args.tls_user
            tree.write('assets.json',(json.dumps(packet,sort_keys=True,indent=2)+'\n').encode(),os.getegid(),0o400)
            tree.write('private/unused.json',b'{}\n',op_owner[1])
            tree.directory('private/empty-retained',op_owner[1],0o750)
            for attribute in ('plan','rollback_policy','rollback_evidence'):
                original = getattr(args,attribute,None)
                if original is not None:
                    path = root/'private'/attribute
                    tree.write('private/'+attribute,capture(original,private=True),op_owner[1])
                    setattr(args,attribute,path)
            original = getattr(args,'retained_migrations',None)
            if original is not None:
                policy = parse(args.rollback_policy.read_bytes(),args.rollback_policy_sha256)
                tree.directory('private/retained-migrations',op_owner[1],0o750)
                for name,checksum in policy['retained_artifacts'].items():
                    data = capture(original/name,private=True)
                    check_hash(data,checksum)
                    tree.write('private/retained-migrations/'+name,data,op_owner[1])
                args.retained_migrations = root/'private/retained-migrations'
            tree.verify()
            yield root,mounted,op_owner,tls_owner
    finally:
        tree.close()

def inventory(args):
    """Produce a reviewable proposal only; no Docker, signing or approval."""
    from deploy import parse_env
    config_data = capture(args.config, private=True)
    files = {name: capture(ROOT/name) for name in REPOSITORY_ASSETS}
    config = parse_env(config_data, files['infrastructure/vps/config.env.example'])
    validate_compose(files['infrastructure/vps/compose.yml'])
    principal(args.operations_user); principal(args.tls_user, allow_root=True)
    if not re.fullmatch('[0-9a-f]{40}', args.source_sha):
        raise Refusal('full source revision required')
    tls = {role: capture(Path(config[role]), private=role == 'TLS_STORE_KEY') for role in TLS_ROLES}
    validate_tls(tls)
    packet = {'schema': 'rick.vps.assets/v1', 'status': 'REVIEW_REQUIRED',
              'source_sha': args.source_sha, 'config_sha256': sha(config_data),
              'operations_user': args.operations_user, 'tls_user': args.tls_user,
              'bundle_root': str(args.bundle_root),
              'files': {name: sha(data) for name, data in files.items()},
              'tls': {role: sha(data) for role, data in tls.items()}}
    packet['bundle_id'] = identity(packet)
    # The output parent must already exist; bind it component by component just
    # like input capture. Never overwrite an existing proposal or follow an alias.
    value = os.fspath(args.output)
    parts = value.split('/')
    if not value.startswith('/') or any(part in {'', '.', '..'} for part in parts[1:]):
        raise Refusal('absolute lexical proposal output required')
    descriptors = []
    try:
        parent = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        descriptors.append(parent)
        for component in parts[1:-1]:
            parent = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                             dir_fd=parent)
            descriptors.append(parent)
        info = os.fstat(parent)
        if info.st_uid not in {0, os.geteuid()} or info.st_mode & 0o022:
            raise Refusal('protected proposal output parent required')
        fd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        with os.fdopen(fd, 'wb') as stream:
            stream.write((json.dumps(packet, sort_keys=True, indent=2)+'\n').encode())
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['inventory'])
    for name in ('config', 'output', 'bundle-root'):
        parser.add_argument('--'+name, type=Path, required=True)
    for name in ('source-sha', 'operations-user', 'tls-user'):
        parser.add_argument('--'+name, required=True)
    try:
        inventory(parser.parse_args())
    except Exception:
        parser.exit(2, 'VPS assets refused; inspect protected local inputs\n')
