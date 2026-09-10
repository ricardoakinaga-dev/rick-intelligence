"""Local-only, private filesystem object storage.

The adapter stores one self-describing object envelope per key.  The envelope
is staged in a private directory and committed with ``os.replace`` so readers
observe either the previous complete object or the next complete object.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import errno
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Literal

from rick_storage.errors import (
    InvalidLimitError,
    InvalidObjectDataError,
    InvalidScopeError,
    ObjectIntegrityError,
    ObjectNotFoundError,
    ObjectReadLimitExceededError,
    ObjectStoreConfigurationError,
    ObjectStoreCorruptionError,
    ObjectStoreError,
    ObjectStoreIOError,
    ObjectStorePermissionError,
    ObjectTooLargeError,
    ProductionModeError,
)
from rick_storage.models import ObjectMetadata, ObjectPayload, ObjectScope
from rick_storage.validation import (
    validate_key_prefix,
    validate_object_key,
    validate_scope_component,
)

DEFAULT_MAX_OBJECT_BYTES = 50 * 1024 * 1024
DEFAULT_MAX_READ_BYTES = 50 * 1024 * 1024
DEFAULT_MAX_LIST_ITEMS = 1_000
MAX_CONFIGURED_BYTES = 1 * 1024 * 1024 * 1024
MAX_CONFIGURED_LIST_ITEMS = 100_000

_HEADER_BYTES = 4 * 1024
_FORMAT_VERSION = 1
_MAGIC = b"RICK-LOCAL-OBJECT\x00"
_OBJECT_SUFFIX = ".object"
_COPY_CHUNK_BYTES = 64 * 1024


def _reject_json_constant(_value: str) -> object:
    raise ValueError("non-finite JSON constants are not allowed")


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


class LocalObjectStore:
    """A private, local-only filesystem object store.

    ``mode`` accepts only ``"local"`` or ``"test"``.  The constructor also
    rejects ``RICK_ENV=production`` so this adapter cannot silently become the
    production implementation through the usual application environment.
    """

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        max_object_bytes: int = DEFAULT_MAX_OBJECT_BYTES,
        max_read_bytes: int | None = None,
        max_list_items: int = DEFAULT_MAX_LIST_ITEMS,
        mode: Literal["local", "test"] | str = "local",
    ) -> None:
        if mode not in {"local", "test"} or os.environ.get("RICK_ENV", "").strip().lower() == "production":
            raise ProductionModeError()
        self._max_object_bytes = _positive_bounded_limit(max_object_bytes, MAX_CONFIGURED_BYTES)
        self._max_read_bytes = _positive_bounded_limit(
            self._max_object_bytes if max_read_bytes is None else max_read_bytes,
            MAX_CONFIGURED_BYTES,
        )
        self._max_list_items = _positive_bounded_limit(max_list_items, MAX_CONFIGURED_LIST_ITEMS)
        self._root = _prepare_root(root)
        self._tenants_root = self._root / "tenants"
        _ensure_private_directory(self._tenants_root)

    @property
    def root(self) -> Path:
        """The resolved store root, exposed for diagnostics and maintenance."""

        return self._root

    @property
    def max_object_bytes(self) -> int:
        return self._max_object_bytes

    @property
    def max_read_bytes(self) -> int:
        return self._max_read_bytes

    def put(self, scope: ObjectScope, key: str, data: ObjectPayload) -> ObjectMetadata:
        """Atomically write an object and return its SHA-256/size metadata."""

        scope = _validated_scope(scope)
        key = validate_object_key(key)
        objects_dir = self._scope_objects_dir(scope, create=True)
        target = self._object_path(objects_dir, key)
        if target.is_symlink():
            raise ObjectStoreCorruptionError(operation="put")

        temporary: Path | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                dir=objects_dir,
                prefix=".tmp-",
                suffix=".part",
            )
            temporary = Path(temporary_name)
            with os.fdopen(descriptor, "w+b") as handle:
                os.chmod(temporary, 0o600)
                handle.write(b"\x00" * _HEADER_BYTES)
                digest = hashlib.sha256()
                size = _copy_payload(handle, data, digest, self._max_object_bytes)
                metadata = ObjectMetadata(
                    scope=scope,
                    key=key,
                    size=size,
                    checksum=f"sha256:{digest.hexdigest()}",
                )
                handle.seek(0)
                handle.write(_encode_header(metadata))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            temporary = None
            _sync_directory(objects_dir)
            return metadata
        except ObjectStoreError:
            raise
        except PermissionError as exc:
            raise ObjectStorePermissionError(operation="put") from exc
        except OSError as exc:
            raise ObjectStoreIOError(operation="put") from exc
        except Exception as exc:
            raise ObjectStoreIOError(operation="put") from exc
        finally:
            if temporary is not None:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
                except OSError:
                    pass

    def get(self, scope: ObjectScope, key: str, *, max_bytes: int | None = None) -> bytes:
        """Read one object, refusing to allocate beyond the configured bound."""

        scope = _validated_scope(scope)
        key = validate_object_key(key)
        limit = self._read_limit(max_bytes)
        with self._open_object(scope, key) as (handle, metadata):
            if metadata.size > limit:
                raise ObjectReadLimitExceededError(limit=limit, size=metadata.size)
            payload = bytearray()
            remaining = metadata.size
            while remaining:
                chunk = handle.read(min(_COPY_CHUNK_BYTES, remaining))
                if not chunk:
                    raise ObjectStoreCorruptionError(operation="get")
                payload.extend(chunk)
                remaining -= len(chunk)
            actual = hashlib.sha256(payload).hexdigest()
            if actual != metadata.sha256:
                raise ObjectIntegrityError()
            return bytes(payload)

    def read(self, scope: ObjectScope, key: str, *, max_bytes: int | None = None) -> bytes:
        """Readable-name alias for :meth:`get`."""

        return self.get(scope, key, max_bytes=max_bytes)

    def head(self, scope: ObjectScope, key: str) -> ObjectMetadata:
        """Return metadata without reading the payload into memory."""

        scope = _validated_scope(scope)
        key = validate_object_key(key)
        with self._open_object(scope, key) as (_handle, metadata):
            return metadata

    def list(
        self,
        scope: ObjectScope,
        *,
        prefix: str = "",
        limit: int | None = None,
    ) -> tuple[ObjectMetadata, ...]:
        """List only objects in one scope, in deterministic key order."""

        scope = _validated_scope(scope)
        prefix = validate_key_prefix(prefix)
        result_limit = self._list_limit(limit)
        if result_limit == 0:
            return ()
        objects_dir = self._scope_objects_dir(scope, create=False)
        if objects_dir is None:
            return ()

        metadata_items: list[ObjectMetadata] = []
        try:
            entries = sorted(objects_dir.iterdir(), key=lambda item: item.name)
            for entry in entries:
                if entry.name.startswith(".tmp-"):
                    continue
                if not entry.name.endswith(_OBJECT_SUFFIX):
                    raise ObjectStoreCorruptionError(operation="list")
                with self._open_path(scope, entry, expected_key=None) as (_handle, metadata):
                    if entry.name != _object_filename(metadata.key):
                        raise ObjectStoreCorruptionError(operation="list")
                    if prefix and not metadata.key.startswith(prefix):
                        continue
                    metadata_items.append(metadata)
        except ObjectStoreError:
            raise
        except PermissionError as exc:
            raise ObjectStorePermissionError(operation="list") from exc
        except OSError as exc:
            raise ObjectStoreIOError(operation="list") from exc
        metadata_items.sort(key=lambda item: item.key)
        return tuple(metadata_items[:result_limit])

    def list_objects(
        self,
        scope: ObjectScope,
        *,
        prefix: str = "",
        limit: int | None = None,
    ) -> tuple[ObjectMetadata, ...]:
        """Explicit alias for callers that avoid the built-in name ``list``."""

        return self.list(scope, prefix=prefix, limit=limit)

    def delete(self, scope: ObjectScope, key: str) -> bool:
        """Delete one object; return ``False`` when it was already absent."""

        scope = _validated_scope(scope)
        key = validate_object_key(key)
        objects_dir = self._scope_objects_dir(scope, create=False)
        if objects_dir is None:
            return False
        target = self._object_path(objects_dir, key)
        try:
            info = target.lstat()
        except FileNotFoundError:
            return False
        except PermissionError as exc:
            raise ObjectStorePermissionError(operation="delete") from exc
        except OSError as exc:
            raise ObjectStoreIOError(operation="delete") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise ObjectStoreCorruptionError(operation="delete")
        try:
            target.unlink()
            _sync_directory(objects_dir)
            return True
        except FileNotFoundError:
            return False
        except PermissionError as exc:
            raise ObjectStorePermissionError(operation="delete") from exc
        except OSError as exc:
            raise ObjectStoreIOError(operation="delete") from exc

    def close(self) -> None:
        """Close the logical adapter; operations use short-lived descriptors."""

    def __enter__(self) -> "LocalObjectStore":
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()

    def _read_limit(self, requested: int | None) -> int:
        if requested is None:
            return self._max_read_bytes
        if isinstance(requested, bool) or not isinstance(requested, int) or requested <= 0:
            raise InvalidLimitError()
        return min(requested, self._max_read_bytes)

    def _list_limit(self, requested: int | None) -> int:
        if requested is None:
            return self._max_list_items
        if isinstance(requested, bool) or not isinstance(requested, int) or requested < 0:
            raise InvalidLimitError()
        return min(requested, self._max_list_items)

    def _scope_objects_dir(self, scope: ObjectScope, *, create: bool) -> Path | None:
        parts = (
            self._tenants_root,
            self._tenants_root / scope.tenant_id,
            self._tenants_root / scope.tenant_id / "workspaces",
            self._tenants_root / scope.tenant_id / "workspaces" / scope.workspace_id,
            self._tenants_root
            / scope.tenant_id
            / "workspaces"
            / scope.workspace_id
            / "sources",
            self._tenants_root
            / scope.tenant_id
            / "workspaces"
            / scope.workspace_id
            / "sources"
            / scope.source_id,
            self._tenants_root
            / scope.tenant_id
            / "workspaces"
            / scope.workspace_id
            / "sources"
            / scope.source_id
            / "objects",
        )
        for directory in parts:
            _assert_under_root(self._root, directory)
            if directory.is_symlink():
                raise ObjectStoreCorruptionError(operation="scope")
            if directory.exists():
                if not directory.is_dir():
                    raise ObjectStoreCorruptionError(operation="scope")
                if create:
                    _tighten_directory(directory)
                continue
            if not create:
                return None
            try:
                directory.mkdir(mode=0o700)
                _tighten_directory(directory)
            except FileExistsError:
                if directory.is_symlink() or not directory.is_dir():
                    raise ObjectStoreCorruptionError(operation="scope")
                _tighten_directory(directory)
            except PermissionError as exc:
                raise ObjectStorePermissionError(operation="scope") from exc
            except OSError as exc:
                raise ObjectStoreIOError(operation="scope") from exc
        return parts[-1]

    def _object_path(self, objects_dir: Path, key: str) -> Path:
        path = objects_dir / _object_filename(key)
        _assert_under_root(self._root, path)
        return path

    @contextmanager
    def _open_object(
        self,
        scope: ObjectScope,
        key: str,
    ) -> Iterator[tuple[object, ObjectMetadata]]:
        objects_dir = self._scope_objects_dir(scope, create=False)
        if objects_dir is None:
            raise ObjectNotFoundError()
        with self._open_path(scope, self._object_path(objects_dir, key), expected_key=key) as opened:
            yield opened

    @contextmanager
    def _open_path(
        self,
        scope: ObjectScope,
        path: Path,
        *,
        expected_key: str | None,
    ) -> Iterator[tuple[object, ObjectMetadata]]:
        try:
            info = path.lstat()
        except FileNotFoundError as exc:
            raise ObjectNotFoundError(operation="read") from exc
        except PermissionError as exc:
            raise ObjectStorePermissionError(operation="read") from exc
        except OSError as exc:
            raise ObjectStoreIOError(operation="read") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise ObjectStoreCorruptionError(operation="read")

        descriptor: int | None = None
        handle = None
        try:
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags)
            handle = os.fdopen(descriptor, "rb")
            descriptor = None
            header = handle.read(_HEADER_BYTES)
            metadata = _decode_header(header, scope, expected_key)
            actual_size = os.fstat(handle.fileno()).st_size
            if actual_size != _HEADER_BYTES + metadata.size:
                raise ObjectStoreCorruptionError(operation="read")
            yield handle, metadata
        except ObjectStoreError:
            raise
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise ObjectStoreCorruptionError(operation="read") from exc
            if isinstance(exc, PermissionError):
                raise ObjectStorePermissionError(operation="read") from exc
            if isinstance(exc, FileNotFoundError):
                raise ObjectNotFoundError(operation="read") from exc
            raise ObjectStoreIOError(operation="read") from exc
        finally:
            if handle is not None:
                handle.close()
            elif descriptor is not None:
                os.close(descriptor)


def _positive_bounded_limit(value: object, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= maximum:
        raise InvalidLimitError()
    return value


def _validated_scope(scope: object) -> ObjectScope:
    if not isinstance(scope, ObjectScope):
        raise InvalidScopeError()
    # Revalidate the immutable fields at the adapter boundary as defense in
    # depth if an object was constructed through an unsafe deserializer.
    validate_scope_component(scope.tenant_id)
    validate_scope_component(scope.workspace_id)
    validate_scope_component(scope.source_id)
    return scope


def _prepare_root(root: str | os.PathLike[str]) -> Path:
    try:
        candidate = Path(root).expanduser()
    except (TypeError, ValueError) as exc:
        raise ObjectStoreConfigurationError() from exc
    if str(candidate) in {"", ".", ".."}:
        raise ObjectStoreConfigurationError()
    if candidate.is_symlink():
        raise ObjectStoreConfigurationError()
    try:
        resolved = candidate.resolve(strict=False)
        if resolved == Path(resolved.anchor):
            raise ObjectStoreConfigurationError()
        resolved.mkdir(parents=True, exist_ok=True)
        if resolved.is_symlink() or not resolved.is_dir():
            raise ObjectStoreConfigurationError()
        _tighten_directory(resolved)
        return resolved
    except ObjectStoreError:
        raise
    except PermissionError as exc:
        raise ObjectStorePermissionError(operation="configure") from exc
    except OSError as exc:
        raise ObjectStoreIOError(operation="configure") from exc


def _assert_under_root(root: Path, path: Path) -> None:
    try:
        resolved = path.resolve(strict=False)
        if not resolved.is_relative_to(root):
            raise ObjectStoreConfigurationError()
    except ObjectStoreError:
        raise
    except OSError as exc:
        raise ObjectStoreIOError(operation="scope") from exc


def _tighten_directory(path: Path) -> None:
    try:
        os.chmod(path, 0o700)
        if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise ObjectStorePermissionError(operation="permissions")
    except ObjectStoreError:
        raise
    except PermissionError as exc:
        raise ObjectStorePermissionError(operation="permissions") from exc
    except OSError as exc:
        raise ObjectStoreIOError(operation="permissions") from exc


def _ensure_private_directory(path: Path) -> None:
    _assert_under_root(path.parent if path.parent != path else path, path)
    try:
        if path.is_symlink():
            raise ObjectStoreConfigurationError()
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.is_symlink() or not path.is_dir():
            raise ObjectStoreConfigurationError()
        _tighten_directory(path)
    except ObjectStoreError:
        raise
    except PermissionError as exc:
        raise ObjectStorePermissionError(operation="configure") from exc
    except OSError as exc:
        raise ObjectStoreIOError(operation="configure") from exc


def _copy_payload(
    handle: object,
    data: ObjectPayload,
    digest: hashlib._Hash,
    limit: int,
) -> int:
    if isinstance(data, (bytes, bytearray, memoryview)):
        try:
            view = memoryview(data)
            total = view.nbytes
            if total > limit:
                raise ObjectTooLargeError(limit=limit, observed=total)
            for offset in range(0, total, _COPY_CHUNK_BYTES):
                chunk = view[offset : offset + _COPY_CHUNK_BYTES].tobytes()
                handle.write(chunk)
                digest.update(chunk)
            return total
        except ObjectStoreError:
            raise
        except (TypeError, ValueError) as exc:
            raise InvalidObjectDataError() from exc

    reader = getattr(data, "read", None)
    if not callable(reader):
        raise InvalidObjectDataError()
    total = 0
    while True:
        chunk = reader(_COPY_CHUNK_BYTES)
        if chunk == b"":
            return total
        if not isinstance(chunk, (bytes, bytearray, memoryview)):
            raise InvalidObjectDataError()
        chunk_bytes = bytes(chunk)
        if not chunk_bytes:
            return total
        total += len(chunk_bytes)
        if total > limit:
            raise ObjectTooLargeError(limit=limit, observed=total)
        handle.write(chunk_bytes)
        digest.update(chunk_bytes)


def _object_filename(key: str) -> str:
    return f"{hashlib.sha256(key.encode('utf-8')).hexdigest()}{_OBJECT_SUFFIX}"


def _encode_header(metadata: ObjectMetadata) -> bytes:
    payload = json.dumps(
        {
            "format": _FORMAT_VERSION,
            "tenant_id": metadata.tenant_id,
            "workspace_id": metadata.workspace_id,
            "source_id": metadata.source_id,
            "key": metadata.key,
            "size": metadata.size,
            "checksum": metadata.checksum,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    encoded = _MAGIC + payload
    if len(encoded) > _HEADER_BYTES:
        raise ObjectStoreConfigurationError()
    return encoded + b"\x00" * (_HEADER_BYTES - len(encoded))


def _decode_header(
    header: bytes,
    scope: ObjectScope,
    expected_key: str | None,
) -> ObjectMetadata:
    if len(header) != _HEADER_BYTES or not header.startswith(_MAGIC):
        raise ObjectStoreCorruptionError(operation="read")
    encoded = header[len(_MAGIC) :].rstrip(b"\x00")
    try:
        raw = json.loads(
            encoded.decode("ascii"),
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_json_constant,
        )
    except (RecursionError, UnicodeDecodeError, ValueError):
        raise ObjectStoreCorruptionError(operation="read") from None
    if not isinstance(raw, dict) or raw.get("format") != _FORMAT_VERSION:
        raise ObjectStoreCorruptionError(operation="read")
    if any(raw.get(name) != getattr(scope, name) for name in ("tenant_id", "workspace_id", "source_id")):
        raise ObjectStoreCorruptionError(operation="read")
    raw_key = raw.get("key")
    try:
        parsed_key = validate_object_key(raw_key)
    except ObjectStoreError:
        raise ObjectStoreCorruptionError(operation="read") from None
    if expected_key is not None and parsed_key != expected_key:
        raise ObjectStoreCorruptionError(operation="read")
    raw_size = raw.get("size")
    raw_checksum = raw.get("checksum")
    if (
        isinstance(raw_size, bool)
        or not isinstance(raw_size, int)
        or raw_size < 0
        or not isinstance(raw_checksum, str)
        or len(raw_checksum) != len("sha256:") + 64
        or not raw_checksum.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in raw_checksum[7:])
    ):
        raise ObjectStoreCorruptionError(operation="read")
    try:
        return ObjectMetadata(
            scope=scope,
            key=parsed_key,
            size=raw_size,
            checksum=raw_checksum,
        )
    except (TypeError, ValueError, ObjectStoreError):
        raise ObjectStoreCorruptionError(operation="read") from None


def _sync_directory(path: Path) -> None:
    """Best-effort directory sync after an atomic replacement or delete."""

    if os.name == "nt":
        return
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        os.fsync(descriptor)
    except OSError:
        # The object itself was already atomically committed.  Some local
        # filesystems do not expose directory fsync; the limitation is
        # documented instead of turning a successful replacement into a
        # misleading failure.
        pass
    finally:
        if descriptor is not None:
            os.close(descriptor)


__all__ = [
    "DEFAULT_MAX_LIST_ITEMS",
    "DEFAULT_MAX_OBJECT_BYTES",
    "DEFAULT_MAX_READ_BYTES",
    "LocalObjectStore",
]
