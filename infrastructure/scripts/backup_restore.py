#!/usr/bin/env python3
"""Create and verify local backup artifacts without contacting services.

The script is the file-level part of the recovery contract.  Operators hand it
exports from Postgres, object storage, vectors, audit, or conversations; the
tool records bounded counts and SHA-256 checksums, verifies them before a
restore, and never overwrites a non-empty target.  Service-specific dump and
snapshot commands remain outside this dependency-free module.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
from typing import Any
import uuid

try:  # Package import for repository execution; root-relative fallback for direct execution.
    from scripts.state_of_art.json_boundary import load_json
except ImportError:  # pragma: no cover - exercised by direct script execution.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "state_of_art"))
    from json_boundary import load_json


SCHEMA_VERSION = "rick-backup.v1"
MANIFEST_NAME = "manifest.json"
PAYLOAD_DIR = "payload"
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_MAX_FILES = 100_000
_MAX_MANIFEST_BYTES = 32 * 1024 * 1024
_MAX_SEMANTIC_METADATA_BYTES = 16 * 1024
_CHECKSUM_RE = re.compile(r"[0-9a-f]{64}")


class BackupError(RuntimeError):
    """A safe, operator-facing backup or restore failure."""


def _text(value: object, *, field: str, maximum: int = 256) -> str:
    if not isinstance(value, str):
        raise BackupError(f"{field} is invalid")
    value = value.strip()
    if not value or len(value) > maximum or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise BackupError(f"{field} is invalid")
    return value


def _component_name(value: object) -> str:
    name = _text(value, field="component name", maximum=64)
    if _NAME_RE.fullmatch(name) is None:
        raise BackupError("component name is invalid")
    return name


def _safe_relative(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise BackupError("manifest path is invalid")
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise BackupError("manifest path is invalid")
    return path.as_posix()


def _sha256_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as stream:
            while True:
                block = stream.read(1024 * 1024)
                if not block:
                    break
                size += len(block)
                digest.update(block)
    except OSError as exc:
        raise BackupError("backup file could not be read") from exc
    return size, digest.hexdigest()


def _copy_file(source: Path, target: Path) -> tuple[int, str]:
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    try:
        with source.open("rb") as source_stream, target.open("wb") as target_stream:
            while True:
                block = source_stream.read(1024 * 1024)
                if not block:
                    break
                target_stream.write(block)
                size += len(block)
                digest.update(block)
    except OSError as exc:
        raise BackupError("backup file could not be copied") from exc
    return size, digest.hexdigest()


def _ensure_no_overlap(first: Path, second: Path) -> None:
    first = first.resolve()
    second = second.resolve()
    if first == second or first.is_relative_to(second) or second.is_relative_to(first):
        raise BackupError("source and backup/restore paths must be separate")


def _iter_source_files(source: Path) -> tuple[tuple[str, Path], ...]:
    if source.is_symlink() or not source.exists():
        raise BackupError("backup source is unavailable")
    if source.is_file():
        return ((source.name, source),)
    if not source.is_dir():
        raise BackupError("backup source must be a regular file or directory")
    files: list[tuple[str, Path]] = []
    try:
        entries = sorted(source.rglob("*"), key=lambda item: item.as_posix())
    except OSError as exc:
        raise BackupError("backup source could not be enumerated") from exc
    for item in entries:
        if item.is_symlink():
            raise BackupError("backup source contains a symbolic link")
        if item.is_file():
            relative = item.relative_to(source).as_posix()
            files.append((relative, item))
        elif not item.is_dir():
            raise BackupError("backup source contains a non-file entry")
        if len(files) > _MAX_FILES:
            raise BackupError("backup contains too many files")
    return tuple(files)


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _semantic_metadata(value: object, *, field: str = "semantic metadata") -> dict[str, Any]:
    """Validate bounded logical reconciliation metadata.

    File checksums prove that an export was copied intact.  These optional
    fields let an exporter also declare the logical scope and relationships it
    observed, so a restore rehearsal can fail closed when ACL/conversation/
    vector relationships are absent or changed.  The script never invents
    these values and never connects to a service to obtain them.
    """

    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise BackupError(f"{field} is invalid")
    allowed = {"scope", "record_count", "acl_sha256", "relation_checksums", "logical_checksum"}
    if any(not isinstance(key, str) or key not in allowed for key in value):
        raise BackupError(f"{field} contains an unsupported field")

    result: dict[str, Any] = {}
    if "record_count" in value:
        count = value["record_count"]
        if isinstance(count, bool) or not isinstance(count, int) or count < 0 or count > 2**63 - 1:
            raise BackupError(f"{field}.record_count is invalid")
        result["record_count"] = count

    for checksum_field in ("acl_sha256", "logical_checksum"):
        if checksum_field in value:
            checksum = value[checksum_field]
            if not isinstance(checksum, str) or _CHECKSUM_RE.fullmatch(checksum) is None:
                raise BackupError(f"{field}.{checksum_field} is invalid")
            result[checksum_field] = checksum

    if "scope" in value:
        scope = value["scope"]
        if not isinstance(scope, Mapping):
            raise BackupError(f"{field}.scope is invalid")
        allowed_scope = {"tenant_ids", "workspace_ids", "collection_ids"}
        if any(not isinstance(key, str) or key not in allowed_scope for key in scope):
            raise BackupError(f"{field}.scope contains an unsupported field")
        normalized_scope: dict[str, list[str]] = {}
        for key, raw_ids in scope.items():
            if not isinstance(raw_ids, list) or len(raw_ids) > 10_000:
                raise BackupError(f"{field}.scope.{key} is invalid")
            ids: list[str] = []
            for identifier in raw_ids:
                ids.append(_text(identifier, field=f"{field}.scope.{key}", maximum=256))
            normalized_scope[key] = sorted(set(ids))
        result["scope"] = normalized_scope

    if "relation_checksums" in value:
        relations = value["relation_checksums"]
        if not isinstance(relations, Mapping) or len(relations) > 1_000:
            raise BackupError(f"{field}.relation_checksums is invalid")
        normalized_relations: dict[str, str] = {}
        for relation, checksum in relations.items():
            relation_name = _text(relation, field=f"{field}.relation_checksums key", maximum=128)
            if not isinstance(checksum, str) or _CHECKSUM_RE.fullmatch(checksum) is None:
                raise BackupError(f"{field}.relation_checksums is invalid")
            normalized_relations[relation_name] = checksum
        result["relation_checksums"] = dict(sorted(normalized_relations.items()))

    if len(_canonical(result)) > _MAX_SEMANTIC_METADATA_BYTES:
        raise BackupError(f"{field} is too large")
    return result


def _manifest_path(backup_dir: Path) -> Path:
    return backup_dir / MANIFEST_NAME


def _read_manifest(backup_dir: Path, *, match_directory_name: bool = True) -> dict[str, Any]:
    if not backup_dir.is_dir() or backup_dir.is_symlink():
        raise BackupError("backup directory is unavailable")
    path = _manifest_path(backup_dir)
    try:
        if path.is_symlink() or not path.is_file():
            raise BackupError("backup manifest is invalid")
        if path.stat().st_size > _MAX_MANIFEST_BYTES:
            raise BackupError("backup manifest is too large")
        payload = load_json(path, maximum_bytes=_MAX_MANIFEST_BYTES)
    except BackupError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackupError("backup manifest is invalid") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise BackupError("backup manifest is invalid")
    if not isinstance(payload.get("files"), list) or not isinstance(payload.get("components"), list):
        raise BackupError("backup manifest is invalid")
    backup_id = _text(payload.get("backup_id"), field="backup_id", maximum=128)
    if _NAME_RE.fullmatch(backup_id) is None or (match_directory_name and backup_id != backup_dir.name):
        raise BackupError("backup manifest is invalid")
    _text(payload.get("created_at"), field="created_at", maximum=64)
    _text(payload.get("operator"), field="operator", maximum=256)
    _text(payload.get("restore_target"), field="restore_target", maximum=1_024)
    if len(payload["files"]) > _MAX_FILES:
        raise BackupError("backup contains too many files")
    return payload


def _manifest_file_entries(manifest: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in manifest.get("files", []):
        if not isinstance(raw, Mapping):
            raise BackupError("backup manifest is invalid")
        relative = _safe_relative(raw.get("path"))
        if not relative.startswith(f"{PAYLOAD_DIR}/") or relative in seen:
            raise BackupError("backup manifest path is invalid")
        size = raw.get("size")
        checksum = raw.get("sha256")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0 or size > 2**63 - 1:
            raise BackupError("backup manifest size is invalid")
        if not isinstance(checksum, str) or re.fullmatch(r"[0-9a-f]{64}", checksum) is None:
            raise BackupError("backup manifest checksum is invalid")
        component = _component_name(raw.get("component"))
        seen.add(relative)
        entries.append({"path": relative, "size": size, "sha256": checksum, "component": component})
    return tuple(entries)


def verify_backup(backup_dir: str | Path, *, _allow_staging: bool = False) -> dict[str, Any]:
    """Verify every declared file and return bounded reconciliation data."""

    supplied_root = Path(backup_dir)
    if supplied_root.is_symlink():
        raise BackupError("backup directory is unavailable")
    root = supplied_root.resolve()
    manifest = _read_manifest(root, match_directory_name=not _allow_staging)
    entries = _manifest_file_entries(manifest)
    declared_paths = {entry["path"] for entry in entries}
    payload_root = root / PAYLOAD_DIR
    actual_paths: set[str] = set()
    if payload_root.is_symlink() or not payload_root.is_dir():
        raise BackupError("backup payload is incomplete")
    for candidate in payload_root.rglob("*"):
        if candidate.is_symlink():
            raise BackupError("backup payload contains a symbolic link")
        if candidate.is_file():
            actual_paths.add(candidate.relative_to(root).as_posix())
        elif not candidate.is_dir():
            raise BackupError("backup payload contains a non-file entry")
    if actual_paths != declared_paths:
        raise BackupError("backup payload does not match its manifest")
    counts: dict[str, dict[str, Any]] = {}
    for entry in entries:
        path = (root / entry["path"]).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise BackupError("backup manifest escapes its directory") from exc
        if path.is_symlink() or not path.is_file():
            raise BackupError("backup payload is incomplete")
        size, checksum = _sha256_file(path)
        if size != entry["size"] or checksum != entry["sha256"]:
            raise BackupError("backup payload checksum verification failed")
        component = str(entry["component"])
        summary = counts.setdefault(component, {"file_count": 0, "byte_count": 0, "sha256": hashlib.sha256()})
        summary["file_count"] += 1
        summary["byte_count"] += size
        summary["sha256"].update(bytes.fromhex(checksum))
    component_counts = {
        name: {
            "file_count": value["file_count"],
            "byte_count": value["byte_count"],
            "sha256": value["sha256"].hexdigest(),
        }
        for name, value in sorted(counts.items())
    }
    declared = manifest.get("component_summary")
    if not isinstance(declared, Mapping) or dict(declared) != component_counts:
        raise BackupError("backup component summary does not match payload")
    declared_components: dict[str, dict[str, Any]] = {}
    for raw in manifest.get("components", []):
        if not isinstance(raw, Mapping):
            raise BackupError("backup manifest is invalid")
        name = _component_name(raw.get("name"))
        if name in declared_components:
            raise BackupError("backup manifest is invalid")
        semantic = _semantic_metadata(raw.get("semantic"), field=f"component {name} semantic metadata")
        declared_components[name] = {
            "file_count": raw.get("file_count"),
            "byte_count": raw.get("byte_count"),
            "sha256": raw.get("sha256"),
            "semantic": semantic,
        }
    if {name: {key: value for key, value in summary.items() if key != "semantic"} for name, summary in declared_components.items()} != component_counts:
        raise BackupError("backup component summary does not match payload")
    semantic_metadata = {name: value["semantic"] for name, value in declared_components.items() if value["semantic"]}
    return {
        "schema_version": SCHEMA_VERSION,
        "backup_id": str(manifest["backup_id"]),
        "status": "PASS",
        "file_count": len(entries),
        "byte_count": sum(int(entry["size"]) for entry in entries),
        "component_summary": component_counts,
        "component_metadata": semantic_metadata,
    }


def create_backup(
    components: Mapping[str, str | Path],
    output_root: str | Path,
    *,
    backup_id: str,
    operator: str,
    restore_target: str | Path,
    created_at: datetime | None = None,
    component_metadata: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Snapshot declared file/directory exports into an atomic backup folder."""

    if not isinstance(components, Mapping) or not components:
        raise BackupError("at least one backup component is required")
    backup_id = _text(backup_id, field="backup_id", maximum=128)
    if _NAME_RE.fullmatch(backup_id) is None:
        raise BackupError("backup_id is invalid")
    operator = _text(operator, field="operator", maximum=256)
    restore_target = _text(str(restore_target), field="restore_target", maximum=1_024)
    if component_metadata is None:
        component_metadata = {}
    if not isinstance(component_metadata, Mapping):
        raise BackupError("component metadata is invalid")
    output = Path(output_root).resolve()
    final_candidate = output / backup_id
    if final_candidate.is_symlink() or final_candidate.exists():
        raise BackupError("backup destination already exists")
    final = final_candidate.resolve()
    try:
        final.relative_to(output)
    except ValueError as exc:
        raise BackupError("backup path must remain below output root") from exc
    source_paths: list[tuple[str, Path]] = []
    for raw_name, raw_source in components.items():
        name = _component_name(raw_name)
        source = Path(raw_source).resolve()
        if Path(raw_source).is_symlink():
            raise BackupError("backup source contains a symbolic link")
        _ensure_no_overlap(source, output)
        if any(existing_name == name for existing_name, _ in source_paths):
            raise BackupError("backup component names must be unique")
        if name in component_metadata:
            _semantic_metadata(component_metadata[name], field=f"component {name} semantic metadata")
        source_paths.append((name, source))
    unknown_metadata = set(component_metadata) - {name for name, _ in source_paths}
    if unknown_metadata:
        raise BackupError("component metadata refers to an undeclared component")
    output.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{backup_id}.tmp-", dir=output))
    try:
        all_entries: list[dict[str, Any]] = []
        component_summary: dict[str, dict[str, Any]] = {}
        for name, source in sorted(source_paths):
            files = _iter_source_files(source)
            summary = {"file_count": 0, "byte_count": 0, "sha256": hashlib.sha256()}
            for relative, source_file in files:
                stored = f"{PAYLOAD_DIR}/{name}/{relative}"
                target = staging / stored
                size, checksum = _copy_file(source_file, target)
                summary["file_count"] += 1
                summary["byte_count"] += size
                summary["sha256"].update(bytes.fromhex(checksum))
                all_entries.append({"path": stored, "component": name, "size": size, "sha256": checksum})
            component_summary[name] = {
                "file_count": summary["file_count"],
                "byte_count": summary["byte_count"],
                "sha256": summary["sha256"].hexdigest(),
            }
        timestamp = (created_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "backup_id": backup_id,
            "created_at": timestamp,
            "components": [
                {
                    "name": name,
                    "file_count": summary["file_count"],
                    "byte_count": summary["byte_count"],
                    "sha256": summary["sha256"],
                    "semantic": _semantic_metadata(component_metadata.get(name), field=f"component {name} semantic metadata"),
                }
                for name, summary in sorted(component_summary.items())
            ],
            "component_summary": component_summary,
            "files": all_entries,
            "restore_target": restore_target,
            "operator": operator,
            "status": "PASS",
        }
        manifest_bytes = _canonical(manifest)
        if len(manifest_bytes) > _MAX_MANIFEST_BYTES:
            raise BackupError("backup manifest is too large")
        (staging / MANIFEST_NAME).write_bytes(manifest_bytes + b"\n")
        # Verify the staged artifact before publication.  This also catches a
        # short write or an accidental path mismatch before the atomic rename.
        verify_backup(staging, _allow_staging=True)
        staging.replace(final)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return manifest


def restore_backup(
    backup_dir: str | Path,
    target: str | Path,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Restore a verified backup into a new or empty target directory."""

    supplied_backup = Path(backup_dir)
    supplied_destination = Path(target)
    if supplied_backup.is_symlink():
        raise BackupError("backup directory is unavailable")
    if supplied_destination.is_symlink():
        raise BackupError("restore target must be a directory")
    backup = supplied_backup.resolve()
    destination = supplied_destination.resolve()
    _ensure_no_overlap(backup, destination)
    report = verify_backup(backup)
    if destination.exists():
        if destination.is_symlink() or not destination.is_dir():
            raise BackupError("restore target must be a directory")
        try:
            if next(destination.iterdir(), None) is not None:
                raise BackupError("restore target must be empty")
        except OSError as exc:
            raise BackupError("restore target is unavailable") from exc
    if dry_run:
        return {**report, "operation": "restore", "status": "DRY_RUN", "target": str(destination)}
    parent = destination.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.restore-", dir=parent))
    try:
        manifest = _read_manifest(backup)
        for entry in _manifest_file_entries(manifest):
            source = backup / entry["path"]
            target_file = staging / Path(entry["path"]).relative_to(PAYLOAD_DIR)
            size, checksum = _copy_file(source, target_file)
            if size != entry["size"] or checksum != entry["sha256"]:
                raise BackupError("restore checksum verification failed")
        if destination.exists():
            destination.rmdir()
        staging.replace(destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {**report, "operation": "restore", "status": "PASS", "target": str(destination)}


def purge_backups(
    output_root: str | Path,
    *,
    retention_days: int,
    keep_latest: int = 1,
    dry_run: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    """List or remove only recognized backups past the retention window."""

    if isinstance(retention_days, bool) or not isinstance(retention_days, int) or retention_days < 0 or retention_days > 36_500:
        raise BackupError("retention_days is invalid")
    if isinstance(keep_latest, bool) or not isinstance(keep_latest, int) or keep_latest < 0 or keep_latest > 10_000:
        raise BackupError("keep_latest is invalid")
    root = Path(output_root).resolve()
    if not root.is_dir() or root.is_symlink():
        raise BackupError("backup output root is unavailable")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = current - timedelta(days=retention_days)
    recognized: list[tuple[datetime, Path]] = []
    for candidate in sorted(root.iterdir(), key=lambda item: item.name):
        if not candidate.is_dir() or candidate.is_symlink() or not _manifest_path(candidate).is_file():
            continue
        try:
            manifest = _read_manifest(candidate)
            created = datetime.fromisoformat(str(manifest["created_at"]).replace("Z", "+00:00")).astimezone(timezone.utc)
        except (BackupError, TypeError, ValueError, OSError):
            continue
        recognized.append((created, candidate))
    recognized.sort(key=lambda item: (item[0], item[1].name), reverse=True)
    keep = {path for _created, path in recognized[:keep_latest]}
    eligible = [path for created, path in recognized if created < cutoff and path not in keep]
    if not dry_run:
        for path in eligible:
            shutil.rmtree(path)
    return {
        "operation": "purge",
        "status": "DRY_RUN" if dry_run else "PASS",
        "retention_days": retention_days,
        "keep_latest": keep_latest,
        "eligible": [str(path) for path in eligible],
        "deleted": [] if dry_run else [str(path) for path in eligible],
        "kept": [str(path) for path in sorted(keep)],
    }


def reconcile_backup(
    backup_dir: str | Path,
    observed: Mapping[str, Mapping[str, Any]],
    *,
    required_components: Sequence[str] = (),
    expected_scope: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, Any]:
    """Compare file and declared logical observations with an external snapshot.

    ``observed`` is an adapter output, not a live-service client.  Each value
    must contain the file summary returned by :func:`verify_backup` and may
    contain ``semantic`` metadata with record counts, ACL scope, and relation
    checksums.  When a backup declares semantic metadata, omitting it from the
    observed restore is a mismatch rather than an implicit pass.
    """

    if not isinstance(observed, Mapping):
        raise BackupError("observed reconciliation data is invalid")
    report = verify_backup(backup_dir)
    required = tuple(_component_name(name) for name in required_components)
    if len(set(required)) != len(required):
        raise BackupError("required components must be unique")
    if expected_scope is not None:
        expected_scope = _semantic_metadata({"scope": expected_scope}, field="expected scope")["scope"]
    expected = report["component_summary"]
    expected_semantic = report.get("component_metadata", {})
    differences: list[dict[str, Any]] = []
    for name in required:
        if name not in observed or name not in expected:
            differences.append({"component": name, "reason": "required component is missing"})
    for name in sorted(set(expected) | set(observed)):
        left = expected.get(name)
        right = observed.get(name)
        if not isinstance(right, Mapping):
            differences.append({"component": name, "expected": left, "observed": None})
            continue
        normalized = {key: right.get(key) for key in ("file_count", "byte_count", "sha256")}
        if left != normalized:
            differences.append({"component": name, "expected": left, "observed": normalized})
            continue
        expected_meta = expected_semantic.get(name, {})
        raw_meta = right.get("semantic")
        if expected_meta and raw_meta is None:
            differences.append({"component": name, "reason": "semantic metadata is missing from observed restore", "expected": expected_meta})
            continue
        try:
            observed_meta = _semantic_metadata(raw_meta, field=f"observed component {name} semantic metadata")
        except BackupError as exc:
            differences.append({"component": name, "reason": str(exc)})
            continue
        if expected_meta != observed_meta:
            differences.append({"component": name, "expected_semantic": expected_meta, "observed_semantic": observed_meta})
        if expected_scope is not None:
            observed_scope = observed_meta.get("scope")
            if observed_scope is None:
                differences.append({"component": name, "reason": "expected ACL scope is missing from observed restore", "expected_scope": expected_scope})
            elif observed_scope != expected_scope:
                differences.append({"component": name, "expected_scope": expected_scope, "observed_scope": observed_scope})
    return {
        "operation": "reconcile",
        "status": "PASS" if not differences else "MISMATCH",
        "backup_id": report["backup_id"],
        "differences": differences,
    }


def _component_arg(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("component must use NAME=PATH")
    name, path = value.split("=", 1)
    try:
        return _component_name(name), _text(path, field="component path", maximum=1_024)
    except BackupError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--output-root", type=Path, required=True)
    create.add_argument("--backup-id", required=True)
    create.add_argument("--operator", required=True)
    create.add_argument("--restore-target", required=True)
    create.add_argument("--component", action="append", type=_component_arg, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("backup", type=Path)
    restore = subparsers.add_parser("restore")
    restore.add_argument("backup", type=Path)
    restore.add_argument("target", type=Path)
    restore.add_argument("--dry-run", action="store_true")
    purge = subparsers.add_parser("purge")
    purge.add_argument("output_root", type=Path)
    purge.add_argument("--retention-days", type=int, required=True)
    purge.add_argument("--keep-latest", type=int, default=1)
    purge.add_argument("--apply", action="store_true", help="delete eligible backups")
    reconcile = subparsers.add_parser("reconcile")
    reconcile.add_argument("backup", type=Path)
    reconcile.add_argument("observed", type=Path, help="JSON component summary")
    reconcile.add_argument("--required-component", action="append", default=[])
    reconcile.add_argument("--expected-scope", type=Path, help="JSON object with tenant_ids/workspace_ids/collection_ids")
    args = parser.parse_args(argv)
    try:
        if args.operation == "create":
            result = create_backup(dict(args.component), args.output_root, backup_id=args.backup_id, operator=args.operator, restore_target=args.restore_target)
        elif args.operation == "verify":
            result = verify_backup(args.backup)
        elif args.operation == "restore":
            result = restore_backup(args.backup, args.target, dry_run=args.dry_run)
        elif args.operation == "purge":
            result = purge_backups(args.output_root, retention_days=args.retention_days, keep_latest=args.keep_latest, dry_run=not args.apply)
        else:
            observed = load_json(args.observed)
            expected_scope = None
            if args.expected_scope is not None:
                expected_scope = load_json(args.expected_scope)
            result = reconcile_backup(
                args.backup,
                observed,
                required_components=args.required_component,
                expected_scope=expected_scope,
            )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result.get("status") not in {"MISMATCH"} else 1
    except (BackupError, OSError, ValueError, json.JSONDecodeError):
        print("backup operation failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
