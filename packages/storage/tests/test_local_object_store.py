from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat

import pytest

from rick_storage import (
    InvalidObjectKeyError,
    InvalidScopeError,
    LocalObjectStore,
    ObjectIntegrityError,
    ObjectNotFoundError,
    ObjectReadLimitExceededError,
    ObjectScope,
    ObjectStoreCorruptionError,
    ObjectStoreIOError,
    ObjectTooLargeError,
    ProductionModeError,
)


@pytest.fixture()
def scope() -> ObjectScope:
    return ObjectScope("tenant-a", "workspace-a", "source-a")


def test_traversal_and_invalid_scope_are_rejected_without_escape(tmp_path: Path, scope: ObjectScope) -> None:
    store = LocalObjectStore(tmp_path / "objects")

    for key in ("../escape", "/absolute", "nested/../../escape", "nested\\escape", "nested//escape"):
        with pytest.raises(InvalidObjectKeyError):
            store.put(scope, key, b"blocked")
    for value in ("../tenant", "tenant/workspace", "tenant\\workspace", ""):
        with pytest.raises(InvalidScopeError):
            ObjectScope(value, "workspace-a", "source-a")

    assert not (tmp_path / "escape").exists()
    assert store.list(scope) == ()


def test_atomic_replacement_preserves_previous_object_and_reopens(tmp_path: Path, scope: ObjectScope) -> None:
    root = tmp_path / "objects"
    store = LocalObjectStore(root)
    store.put(scope, "docs/report.txt", b"old")

    class FailingReader:
        def __init__(self) -> None:
            self.calls = 0

        def read(self, _size: int) -> bytes:
            self.calls += 1
            if self.calls == 1:
                return b"new-but-incomplete"
            raise OSError("synthetic source failure")

    with pytest.raises(ObjectStoreIOError):
        store.put(scope, "docs/report.txt", FailingReader())  # type: ignore[arg-type]

    assert store.get(scope, "docs/report.txt") == b"old"
    assert not list((root / "tenants").rglob(".tmp-*.part"))

    store.put(scope, "docs/report.txt", b"new")
    reopened = LocalObjectStore(root)
    assert reopened.get(scope, "docs/report.txt") == b"new"


def test_checksum_size_head_and_deterministic_list(tmp_path: Path, scope: ObjectScope) -> None:
    store = LocalObjectStore(tmp_path / "objects")
    payload = b"checksum me\x00"
    metadata = store.put(scope, "b/file.bin", payload)
    store.put(scope, "a/file.bin", b"a")

    assert metadata.size == len(payload)
    assert metadata.checksum == f"sha256:{hashlib.sha256(payload).hexdigest()}"
    assert metadata.sha256 == hashlib.sha256(payload).hexdigest()
    assert store.head(scope, "b/file.bin") == metadata
    assert [item.key for item in store.list(scope)] == ["a/file.bin", "b/file.bin"]
    assert [item.key for item in store.list(scope, prefix="b/")] == ["b/file.bin"]


def test_write_and_read_limits_are_bounded(tmp_path: Path, scope: ObjectScope) -> None:
    store = LocalObjectStore(tmp_path / "objects", max_object_bytes=8, max_read_bytes=3)
    with pytest.raises(ObjectTooLargeError):
        store.put(scope, "too-large", b"123456789")
    assert store.list(scope) == ()

    store.put(scope, "limited", b"1234")
    with pytest.raises(ObjectReadLimitExceededError):
        store.get(scope, "limited")
    reopened = LocalObjectStore(tmp_path / "objects", max_object_bytes=8, max_read_bytes=8)
    assert reopened.get(scope, "limited") == b"1234"


def test_scope_isolation_and_delete(tmp_path: Path, scope: ObjectScope) -> None:
    other = ObjectScope("tenant-b", "workspace-a", "source-a")
    store = LocalObjectStore(tmp_path / "objects")
    store.put(scope, "same-key", b"tenant-a")
    store.put(other, "same-key", b"tenant-b")

    assert store.get(scope, "same-key") == b"tenant-a"
    assert store.get(other, "same-key") == b"tenant-b"
    assert [item.tenant_id for item in store.list(scope)] == ["tenant-a"]
    assert store.delete(scope, "same-key") is True
    assert store.delete(scope, "same-key") is False
    with pytest.raises(ObjectNotFoundError):
        store.get(scope, "same-key")
    assert store.get(other, "same-key") == b"tenant-b"


def test_corrupt_payload_fails_integrity_check(tmp_path: Path, scope: ObjectScope) -> None:
    root = tmp_path / "objects"
    store = LocalObjectStore(root)
    store.put(scope, "corrupt", b"payload")
    object_file = next((root / "tenants").rglob("*.object"))
    with object_file.open("r+b") as handle:
        handle.seek(4096)
        handle.write(b"xayload")

    with pytest.raises(ObjectIntegrityError):
        store.get(scope, "corrupt")


def test_permissions_are_private_on_posix(tmp_path: Path, scope: ObjectScope) -> None:
    if os.name == "nt":
        pytest.skip("POSIX mode bits are not portable to Windows")
    root = tmp_path / "objects"
    store = LocalObjectStore(root)
    store.put(scope, "private", b"data")
    object_file = next((root / "tenants").rglob("*.object"))

    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE(object_file.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(object_file.stat().st_mode) == 0o600


def test_production_mode_is_explicitly_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ProductionModeError):
        LocalObjectStore(tmp_path / "objects", mode="production")
    monkeypatch.setenv("RICK_ENV", "production")
    with pytest.raises(ProductionModeError):
        LocalObjectStore(tmp_path / "objects")


def test_malformed_committed_entry_fails_closed(tmp_path: Path, scope: ObjectScope) -> None:
    root = tmp_path / "objects"
    store = LocalObjectStore(root)
    store.put(scope, "valid", b"data")
    object_file = next((root / "tenants").rglob("*.object"))
    with object_file.open("r+b") as handle:
        handle.seek(0)
        handle.write(b"not-an-object".ljust(4096, b"\x00"))

    with pytest.raises(ObjectStoreCorruptionError):
        store.head(scope, "valid")


@pytest.mark.parametrize(
    "malformed_fields",
    (
        '"metadata":NaN,"size":4,',
        '"size":4,"size":4,',
    ),
)
def test_ambiguous_or_nonfinite_json_header_fails_closed(
    tmp_path: Path,
    scope: ObjectScope,
    malformed_fields: str,
) -> None:
    root = tmp_path / "objects"
    store = LocalObjectStore(root)
    store.put(scope, "valid", b"data")
    object_file = next((root / "tenants").rglob("*.object"))
    checksum = f"sha256:{hashlib.sha256(b'data').hexdigest()}"
    payload = (
        "{"
        f'"checksum":{json.dumps(checksum)},'
        '"format":1,'
        f'"key":{json.dumps("valid")},'
        f"{malformed_fields}"
        f'"source_id":{json.dumps(scope.source_id)},'
        f'"tenant_id":{json.dumps(scope.tenant_id)},'
        f'"workspace_id":{json.dumps(scope.workspace_id)}'
        "}"
    ).encode("ascii")
    header = b"RICK-LOCAL-OBJECT\x00" + payload
    assert len(header) <= 4096
    with object_file.open("r+b") as handle:
        handle.seek(0)
        handle.write(header.ljust(4096, b"\x00"))

    with pytest.raises(ObjectStoreCorruptionError):
        store.head(scope, "valid")
