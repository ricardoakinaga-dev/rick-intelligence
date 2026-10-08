"""Retained, bounded disk inputs for a trusted host publisher.

The host owner/daemon remain trusted. Delegated containers receive only RO
inputs and separate RW outputs; chmod is not isolation from the host UID.
"""
from contextlib import AbstractContextManager
import hashlib
import os
from pathlib import Path
import shutil
import stat
import tempfile

from contracts import Refusal

FIELDS = ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_gid', 'st_nlink',
          'st_size', 'st_mtime_ns', 'st_ctime_ns')
DIRECTORY_FIELDS = ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_gid')


def output_identity(info):
    """Stable tool output metadata; content and write timestamps may change."""
    return tuple(getattr(info, field) for field in DIRECTORY_FIELDS)


def same(a, b, fields):
    return all(getattr(a, field) == getattr(b, field) for field in fields)


class BoundFile:
    """No-follow hierarchy and open leaf retained until the publisher exits."""
    def __init__(self, path, limit, *, private=False):
        self.fds = []; self.parents = []; self.limit = limit
        self.path = Path(path)
        parts = os.fspath(path).split('/')
        if not parts[0] == '' or any(p in {'', '.', '..'} for p in parts[1:]):
            raise Refusal('absolute lexical publication input required')
        try:
            parent = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            self.fds.append(parent)
            for name in parts[1:-1]:
                fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
                self.fds.append(fd); info = os.fstat(fd)
                if (info.st_uid not in {0, os.geteuid()} or
                    (info.st_mode & 0o022 and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX))):
                    raise Refusal('protected publication input parents required')
                self.parents.append((parent, name, info)); parent = fd
            self.fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
            self.fds.append(self.fd); self.info = os.fstat(self.fd)
            if (not stat.S_ISREG(self.info.st_mode) or self.info.st_nlink != 1
                or self.info.st_uid not in {0, os.geteuid()}
                or self.info.st_mode & (0o7077 if private else 0o7022) or self.info.st_size > limit):
                raise Refusal('bounded private protected sole-link publication input required' if private
                              else 'bounded protected sole-link publication input required')
            self.parent, self.name = parent, parts[-1]
            self.sha256 = self.stream()
            self.verify()
        except OSError:
            self.close()
            raise Refusal('publication input unavailable or contains a symlink') from None
        except BaseException:
            self.close(); raise

    def stream(self, destination=None):
        h = hashlib.sha256(); size = 0
        while chunk := os.pread(self.fd, min(65536, self.limit + 1 - size), size):
            size += len(chunk)
            if size > self.limit:
                raise Refusal('publication capture exceeds bound')
            h.update(chunk)
            if destination is not None:
                view = memoryview(chunk)
                while view:
                    written = os.write(destination, view)
                    if written <= 0:
                        raise Refusal('publication snapshot write failed')
                    view = view[written:]
        if size != self.info.st_size:
            raise Refusal('publication input size changed')
        return h.hexdigest()

    def verify(self):
        try:
            for parent, name, info in self.parents:
                if not same(info, os.stat(name, dir_fd=parent, follow_symlinks=False), DIRECTORY_FIELDS):
                    raise Refusal('publication input parent changed')
            if (not same(self.info, os.fstat(self.fd), FIELDS)
                or not same(self.info, os.stat(self.name, dir_fd=self.parent, follow_symlinks=False), FIELDS)
                or self.stream() != self.sha256
                or not same(self.info, os.fstat(self.fd), FIELDS)):
                raise Refusal('retained publication input changed')
        except OSError:
            raise Refusal('retained publication input unavailable') from None

    def read(self):
        # Only bounded metadata, never the archive, enters memory.
        if self.limit > 16 * 1024**2:
            raise Refusal('large publication input requires streaming')
        self.verify()
        data = bytearray(); offset = 0
        while chunk := os.pread(self.fd, min(65536, self.limit + 1 - offset), offset):
            data.extend(chunk); offset += len(chunk)
            if offset > self.limit:
                raise Refusal('publication metadata exceeds bound')
        self.verify()
        if hashlib.sha256(data).hexdigest() != self.sha256:
            raise Refusal('publication metadata changed during read')
        return bytes(data)

    def close(self):
        for fd in reversed(self.fds): os.close(fd)
        self.fds = []


class PublicationCapture(AbstractContextManager):
    def __init__(self, environment):
        self.environment = dict(environment)
        self.root = Path(tempfile.mkdtemp(prefix='rick-publication-capture-'))
        self.sources = []; self.retained = {}; self.prepared_outputs = {}
        self.rootfd = self.outputfd = None
        self.inputs = self.root/'inputs'; self.outputs = self.root/'outputs'
        try:
            self.inputs.mkdir(mode=0o700); self.outputs.mkdir(mode=0o700)
            self.rootfd = os.open(self.inputs, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            self.outputfd = os.open(self.outputs, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            self.directory_info = [(self.inputs, self.rootfd, os.fstat(self.rootfd)),
                                   (self.outputs, self.outputfd, os.fstat(self.outputfd))]
        except BaseException:
            self.__exit__(); raise

    def retain(self, name, path, limit=16 * 1024**2, *, private=False, identity=None):
        if name in self.retained or Path(name).name != name:
            raise Refusal('unique publication snapshot leaf required')
        source = BoundFile(path, limit, private=private)
        if identity is not None and output_identity(source.info) != identity:
            source.close()
            raise Refusal('private tool output identity changed')
        self.sources.append(source)
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=self.rootfd)
        try:
            copied = source.stream(fd); source.verify()
            if copied != source.sha256:
                raise Refusal('publication source changed during snapshot')
            os.fchmod(fd, 0o400); os.fsync(fd)
        finally:
            os.close(fd)
        snapshot = BoundFile(self.inputs/name, limit, private=True)
        self.retained[name] = snapshot
        if snapshot.sha256 != source.sha256 or (snapshot.info.st_dev, snapshot.info.st_ino) == (source.info.st_dev, source.info.st_ino):
            raise Refusal('independent exact publication snapshot required')
        self.verify()
        return snapshot

    def write(self, name, data):
        """Capture generated admission bytes directly, before any public export."""
        if name in self.retained or Path(name).name != name or len(data) > 16 * 1024**2:
            raise Refusal('unique bounded publication metadata required')
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=self.rootfd)
        try:
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                if written <= 0: raise Refusal('publication metadata write failed')
                view = view[written:]
            os.fchmod(fd, 0o400); os.fsync(fd)
        finally:
            os.close(fd)
        bound = BoundFile(self.inputs/name, 16 * 1024**2, private=True)
        self.retained[name] = bound
        if bound.sha256 != hashlib.sha256(data).hexdigest():
            raise Refusal('generated publication metadata changed')
        self.verify()
        return bound

    def prepare_output(self, name):
        """Exclusive private tool output, in the separately mounted RW tree.

        Tools may truncate this inode, but changing its device, inode, full
        mode, uid or gid fails admission. No caller-owned shared authority
        file is chmodded.
        """
        if Path(name).name != name:
            raise Refusal('tool output leaf required')
        self.verify()
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=self.outputfd)
        try:
            info = os.fstat(fd)
        finally:
            os.close(fd)
        identity = output_identity(info)
        self.prepared_outputs[name] = identity
        return identity

    def retain_output(self, name, identity):
        self.verify()
        if name not in self.prepared_outputs or identity != self.prepared_outputs[name]:
            raise Refusal('initial private tool output identity required')
        return self.retain(name, self.outputs/name, private=True, identity=identity)

    def export(self, name, path):
        """Exclusive no-follow export through the original OUT's retained dirfd."""
        path = Path(path); original = self.sources[0]
        if path.parent != original.path.parent or path.name != name:
            raise Refusal('publication export directory identity required')
        self.verify()
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=original.parent)
        try:
            copied = self.retained[name].stream(fd); os.fsync(fd)
        finally:
            os.close(fd)
        exported = BoundFile(path, 16 * 1024**2, private=True); self.sources.append(exported)
        if copied != self.retained[name].sha256 or exported.sha256 != copied:
            raise Refusal('publication export changed')
        self.verify()

    def verify(self):
        if any(os.environ.get(k) != v for k, v in self.environment.items()):
            raise Refusal('publication environment identity changed')
        try:
            for path, fd, info in self.directory_info:
                if (not same(info, os.fstat(fd), DIRECTORY_FIELDS)
                    or not same(info, os.stat(path, follow_symlinks=False), DIRECTORY_FIELDS)):
                    raise Refusal('publication mount directory changed')
            for name, identity in self.prepared_outputs.items():
                info = os.stat(name, dir_fd=self.outputfd, follow_symlinks=False)
                if output_identity(info) != identity or info.st_nlink != 1:
                    raise Refusal('private tool output identity changed')
        except OSError:
            raise Refusal('publication mount directory unavailable') from None
        for bound in [*self.sources, *self.retained.values()]: bound.verify()

    def __exit__(self, *unused):
        for bound in [*self.sources, *self.retained.values()]: bound.close()
        if self.rootfd is not None: os.close(self.rootfd)
        if self.outputfd is not None: os.close(self.outputfd)
        shutil.rmtree(self.root)
