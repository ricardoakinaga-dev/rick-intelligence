"""Small shared, secret-free input boundaries for publication and installation."""
from __future__ import annotations
import hashlib
import json
import os
import re
import stat
from pathlib import Path
from urllib.parse import urlsplit

REPO = 'ricardoakinaga-dev/rick-intelligence'
IDENTITY = f'https://github.com/{REPO}/.github/workflows/publish-images.yml@refs/heads/main'
ISSUER = 'https://token.actions.githubusercontent.com'
PREDICATE = 'https://rick-intelligence.dev/attestations/candidate/v1'
SERVICES = ('api', 'worker', 'web')
REF = re.compile(r'[a-z0-9]+(?:[.-][a-z0-9]+)*(?::[0-9]+)?/[a-z0-9._/-]+(?:[a-z0-9])?@sha256:[0-9a-f]{64}')
HEX = re.compile(r'[0-9a-f]{64}')

class Refusal(ValueError):
    pass

def immutable(value: str, prefix: str | None = None) -> str:
    if not isinstance(value, str) or not REF.fullmatch(value) or '..' in value or '//' in value:
        raise Refusal('invalid immutable image reference')
    if prefix and value.split('@')[0] != prefix:
        raise Refusal('image registry/repository is not authorized')
    return value

def postgres_endpoint(value, database=None):
    try:
        endpoint = urlsplit(value)
        if (endpoint.scheme != 'postgresql' or endpoint.hostname != 'postgres'
            or endpoint.netloc.rsplit('@',1)[-1] not in {'postgres','postgres:5432'}
            or endpoint.port not in {None,5432} or not endpoint.username or not endpoint.password
            or endpoint.query or endpoint.fragment or not re.fullmatch(r'/[a-z][a-z0-9_-]{1,62}',endpoint.path)
            or (database is not None and endpoint.path != '/'+database)):
            raise ValueError('endpoint mismatch')
        return endpoint
    except (ValueError,TypeError):
        raise Refusal('fixed internal PostgreSQL endpoint postgres:5432 required') from None


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def unique(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise Refusal('duplicate JSON field')
        obj[key] = value
    return obj

def load(path: Path, expected: str | None = None):
    data = path.read_bytes()
    return parse(data, expected)

def capture(path: Path, *, private: bool = False) -> bytes:
    """Bind every component to a no-follow dirfd, then check the binding again.

    A rename cannot redirect a later open into the replacement parent. Refuse
    observed replacement as well as symlinks; a sticky /tmp with a private
    child is supported. Only the returned, externally hash-checked bytes may
    subsequently be used. Paths in diagnostics never include secret inputs.
    """
    value = os.fspath(path)
    parts = value.split('/')
    if not value.startswith('/') or any(p in {'.', '..', ''} for p in parts[1:]):
        raise Refusal('lexical absolute regular input required')
    descriptors = []
    bindings = []
    try:
        parent = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        descriptors.append(parent)
        for name in parts[1:-1]:
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
            descriptors.append(child)
            info = os.fstat(child)
            if (info.st_uid not in {0, os.geteuid()}
                or (info.st_mode & 0o022 and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX))):
                raise Refusal('unprotected input parent')
            bindings.append((parent, name, info))
            parent = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
        descriptors.append(fd)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 16 * 1024 * 1024:
            raise Refusal('bounded regular input required')
        if info.st_mode & ((0o077 if private else 0o022) | 0o7000):
            raise Refusal('private config or protected evidence file required')
        if info.st_uid not in {0, os.geteuid()} or info.st_nlink != 1:
            raise Refusal('input must have a trusted sole owner')
        bindings.append((parent, parts[-1], info))
        chunks = []
        size = 0
        while chunk := os.read(fd, min(65536, 16 * 1024 * 1024 + 1 - size)):
            chunks.append(chunk)
            size += len(chunk)
            if size > 16 * 1024 * 1024:
                raise Refusal('bounded regular input required')
        after = os.fstat(fd)
        fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_uid', 'st_gid', 'st_mode', 'st_nlink')
        if any(getattr(info, k) != getattr(after, k) for k in fields):
            raise Refusal('input changed during capture')
        for directory, name, original in bindings:
            current = os.stat(name, dir_fd=directory, follow_symlinks=False)
            # A directory's link count changes when an unrelated child is
            # created/removed (including another private test root in /tmp).
            # Its device/inode and protected owner/mode bind its identity.
            # Regular inputs still require exactly one link, both before and
            # after reading; changing that leaf is never accepted.
            binding_fields = ('st_dev','st_ino','st_mode','st_uid','st_gid')
            if not stat.S_ISDIR(original.st_mode):
                binding_fields += ('st_nlink',)
            if any(getattr(current, k) != getattr(original, k) for k in
                   binding_fields):
                raise Refusal('input parent or leaf replaced during capture')
        return b''.join(chunks)
    except OSError:
        raise Refusal('input path unavailable or contains a symlink') from None
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)

def check_hash(data: bytes, expected: str):
    if not isinstance(expected, str) or not HEX.fullmatch(expected) or hashlib.sha256(data).hexdigest() != expected:
        raise Refusal('reviewed input hash mismatch')

def parse(data: bytes, expected: str | None = None):
    if expected is not None and (not HEX.fullmatch(expected) or hashlib.sha256(data).hexdigest() != expected):
        raise Refusal('reviewed manifest hash mismatch')
    if len(data) > 16*1024*1024:
        raise Refusal('bounded JSON input required')
    def reject_constant(value):
        raise Refusal('non-finite JSON input refused')
    return json.loads(data, object_pairs_hook=unique,parse_constant=reject_constant)

def images(manifest):
    if manifest.get('schema') != 'rick.release.manifest/v1' or manifest.get('status') != 'READY_FOR_REVIEW':
        raise Refusal('reviewed REC-33 release manifest required')
    source = manifest.get('source_revision', {})
    if source.get('status') != 'CAPTURED' or not re.fullmatch('[0-9a-f]{40}', str(source.get('value', ''))):
        raise Refusal('exact source SHA required')
    result = {}
    for image in manifest.get('images', []):
        service = image.get('service')
        if service not in SERVICES or service in result:
            raise Refusal('release services invalid')
        ref = immutable(image.get('image_ref'), f'ghcr.io/{REPO}-{service}')
        if image.get('digest') != ref.split('@')[1]:
            raise Refusal('release digest mismatch')
        result[service] = ref
    if set(result) != set(SERVICES):
        raise Refusal('all release services required')
    return result
