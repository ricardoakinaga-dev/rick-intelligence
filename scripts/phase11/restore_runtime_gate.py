#!/usr/bin/env python3
"""Run the external Phase 3.10 disaster-recovery/restore gate.

This gate deliberately does not create a local backup, an in-memory service,
or a simulated restore.  A caller must select an explicitly authorized
external disposable composition with ``RICK_RESTORE_RUNTIME_PATH`` (or
``--runtime-path``).  The composition supplies real service-bound operations
for this exact sequence::

    seed -> backup -> destroy -> restore -> rebuild -> verify

The composition contract is intentionally narrow and observable.  Its
``runtime_metadata`` must identify an external disposable service boundary,
declare destructive operations and all required components, and the
``preflight`` result must prove that the target is authorized, reachable and
ready.  Every operation must return an explicit PASS/FAIL/BLOCKED status,
scope, checksum, component coverage and an external timestamp.  The gate
never infers a successful step from a later state.

The report is a safe projection: identifiers are digested, content and
exception text are omitted, and only bounded checksums/measurements are
persisted.  Missing authority is ``BLOCKED_EXTERNAL`` and never PASS.  A
PASS from this Phase 11 gate is runtime evidence for the exercised disposable
composition only; the Phase 3 adapter separately binds it to a clean commit.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timezone
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Callable
import uuid


ROOT = Path(__file__).resolve().parents[2]
GATE_ID = "RICK_RESTORE_RUNTIME_PATH"
SCHEMA_VERSION = "phase11-restore-runtime-gate.v1"
DEFAULT_OUTPUT = ".runtime/phase-3/restore-runtime-gate.json"
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_RPO_SECONDS = 300.0
DEFAULT_RTO_SECONDS = 900.0
MAX_TIMEOUT_SECONDS = 900.0
MAX_BUDGET_SECONDS = 86_400.0
MAX_SCOPE_IDS = 64
MAX_COMPONENTS = 16

PASS = "PASS"
FAIL = "FAIL"
BLOCKED_EXTERNAL = "BLOCKED_EXTERNAL"
NOT_RUN = "NOT_RUN"

OPERATIONS = ("seed", "backup", "destroy", "restore", "rebuild", "verify")
REQUIRED_COMPONENTS = (
    "postgresql",
    "object_storage",
    "jobs",
    "audit",
    "evidence_lineage",
    "qdrant",
)

INTERFACE_CONTRACT: dict[str, object] = {
    "runtime_selection": "RICK_RESTORE_RUNTIME_PATH or --runtime-path",
    "required_flags": ["authorized=true", "external=true", "disposable=true"],
    "required_metadata": [
        "execution_mode in {external_disposable, live_external}",
        "service_boundary=true",
        "destructive_operations=true",
        "all required components declared",
    ],
    "preflight_checks": [
        "external=true",
        "disposable=true",
        "destructive_authorized=true",
        "empty_target_ready=true",
        "clock_verified=true",
        "all required components reachable",
    ],
    "operations": list(OPERATIONS),
    "operation_observations": [
        "status=PASS",
        "scope",
        "checksum",
        "component_checksums",
        "completed_at with timezone",
    ],
    "rpo_measurement": "backup.completed_at - backup.source_state_at",
    "rto_measurement": "verify.completed_at - destroy.completed_at",
}

_MISSING = object()
_CHECKSUM = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$", re.IGNORECASE)
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}$")
_SAFE_DETAIL = re.compile(r"^[a-z0-9_]{1,96}$")
_FORBIDDEN_MODES = frozenset({"local", "in_memory", "in-memory", "fake", "mock", "stub", "simulated", "fixture"})
_ALLOWED_MODES = frozenset({"external_disposable", "external-disposable", "live_external", "live-external"})
_FORBIDDEN_TRANSPORTS = frozenset({"local", "in_memory", "in-memory", "fake", "mock", "stub", "simulated"})


class _BlockedExternal(Exception):
    """The external restore authority is absent or not authorized."""


class _InvalidConfiguration(Exception):
    """The selected composition or gate configuration is malformed."""


class _StepFailure(Exception):
    """A live operation returned an invalid or unsuccessful observation."""


class _OperationTimeout(Exception):
    """A bounded external operation exceeded its remaining budget."""


@dataclass(frozen=True, slots=True)
class GateResult:
    """One safe assertion in the report."""

    name: str
    result: str
    detail: str = ""
    observed: Mapping[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"name": self.name, "result": self.result}
        if self.detail:
            payload["detail"] = self.detail
        if self.observed:
            payload["observed"] = _safe_report_value(self.observed)
        return payload


@dataclass(frozen=True, slots=True)
class _Step:
    """Validated, non-secret state carried between operations."""

    name: str
    scope: dict[str, list[str]]
    checksum: str
    component_checksums: dict[str, str]
    components: tuple[str, ...]
    completed_at: datetime
    values: Mapping[str, object]


def _value(source: object, name: str, default: object = None) -> object:
    if isinstance(source, Mapping):
        return source.get(name, default)
    return getattr(source, name, default)


def _first(source: object, names: Sequence[str], default: object = _MISSING) -> object:
    for name in names:
        value = _value(source, name, _MISSING)
        if value is not _MISSING:
            return value
    return default


def _mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        try:
            result = dump()
        except Exception:
            return {}
        return result if isinstance(result, Mapping) else {}
    if is_dataclass(value) and not isinstance(value, type):
        try:
            return {field.name: getattr(value, field.name) for field in fields(value)}
        except Exception:
            return {}
    return {}


def _safe_report_value(value: object, *, key: str = "") -> object:
    """Keep the report bounded and avoid persisting external payloads."""

    lowered = key.casefold()
    if any(marker in lowered for marker in ("secret", "token", "password", "credential", "authorization", "url", "content", "payload", "message", "error")):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(name): _safe_report_value(item, key=str(name)) for name, item in value.items() if len(str(name)) <= 128}
    if isinstance(value, (list, tuple)):
        return [_safe_report_value(item) for item in list(value)[:MAX_COMPONENTS * 4]]
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"type": "bytes", "size": len(value)}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) > 256:
            return {"type": "text", "size": len(value), "digest": _digest(value)}
        return value
    return {"type": type(value).__name__}


def _digest(value: object) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]


def _safe_identifier(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise _StepFailure(f"{field}_invalid")
    value = value.strip()
    if _SAFE_ID.fullmatch(value) is None:
        raise _StepFailure(f"{field}_invalid")
    return value


def _normalise_checksum(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _CHECKSUM.fullmatch(value.strip()) is None:
        raise _StepFailure(f"{field}_invalid")
    text = value.strip().lower()
    return text if text.startswith("sha256:") else f"sha256:{text}"


def _normalise_status(value: object) -> str:
    if isinstance(value, bool):
        return PASS if value else FAIL
    if not isinstance(value, str):
        return ""
    text = value.strip().upper().replace("-", "_")
    if text in {PASS, FAIL, BLOCKED_EXTERNAL, NOT_RUN}:
        return text
    if text in {"OK", "SUCCESS", "SUCCEEDED", "COMPLETE", "COMPLETED"}:
        return PASS
    if text in {"BLOCKED", "UNAVAILABLE", "NOT_AVAILABLE"}:
        return BLOCKED_EXTERNAL
    return ""


def _parse_timestamp(value: object, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise _StepFailure(f"{field}_missing")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise _StepFailure(f"{field}_invalid") from None
    if parsed.tzinfo is None:
        raise _StepFailure(f"{field}_timezone_missing")
    return parsed.astimezone(timezone.utc)


def _timestamp_value(source: object, *, field: str) -> datetime:
    value = _first(source, (field, "completed_at", "finished_at", "ended_at"))
    return _parse_timestamp(value, field=field)


def _normalise_scope(value: object, *, field: str = "scope") -> dict[str, list[str]]:
    raw = _mapping(value)
    if not raw:
        raise _StepFailure(f"{field}_missing")
    aliases: dict[str, tuple[str, ...]] = {
        "tenant_ids": ("tenant_ids", "tenant_id"),
        "workspace_ids": ("workspace_ids", "workspace_id"),
        "collection_ids": ("collection_ids", "collection_id"),
    }
    known_names = {name for names in aliases.values() for name in names}
    if any(not isinstance(name, str) or name not in known_names for name in raw):
        raise _StepFailure(f"{field}_contains_unsupported_dimension")
    result: dict[str, list[str]] = {}
    for canonical, names in aliases.items():
        present = [name for name in names if name in raw]
        if len(present) != 1:
            raise _StepFailure(f"{field}_{canonical}_missing")
        candidate = raw[present[0]]
        if isinstance(candidate, str):
            candidates: list[object] = [candidate]
        elif isinstance(candidate, Sequence) and not isinstance(candidate, (str, bytes, bytearray)):
            candidates = list(candidate)
        else:
            raise _StepFailure(f"{field}_{canonical}_invalid")
        if not 1 <= len(candidates) <= MAX_SCOPE_IDS:
            raise _StepFailure(f"{field}_{canonical}_invalid")
        identifiers: list[str] = []
        for item in candidates:
            if not isinstance(item, str) or not item.strip() or any(ord(char) < 0x20 or ord(char) == 0x7F for char in item):
                raise _StepFailure(f"{field}_{canonical}_invalid")
            identifiers.append(item.strip())
        if len(set(identifiers)) != len(identifiers):
            raise _StepFailure(f"{field}_{canonical}_duplicate")
        result[canonical] = sorted(identifiers)
    return result


def _scope_digest(scope: Mapping[str, Sequence[str]]) -> str:
    encoded = json.dumps(scope, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalise_components(value: object, *, field: str) -> tuple[str, ...]:
    if isinstance(value, Mapping):
        raw_names = list(value.keys())
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        raw_names = list(value)
    else:
        raise _StepFailure(f"{field}_missing")
    aliases = {
        "postgres": "postgresql",
        "postgresql": "postgresql",
        "object_store": "object_storage",
        "object-storage": "object_storage",
        "object_storage": "object_storage",
        "storage": "object_storage",
        "job": "jobs",
        "jobs": "jobs",
        "audit": "audit",
        "evidence": "evidence_lineage",
        "evidence_lineage": "evidence_lineage",
        "lineage": "evidence_lineage",
        "qdrant": "qdrant",
        "vectors": "qdrant",
        "vector": "qdrant",
    }
    normalized: set[str] = set()
    for item in raw_names:
        if not isinstance(item, str):
            raise _StepFailure(f"{field}_invalid")
        name = aliases.get(item.strip().casefold())
        if name is None:
            raise _StepFailure(f"{field}_unknown_component")
        normalized.add(name)
    if len(normalized) > MAX_COMPONENTS:
        raise _StepFailure(f"{field}_too_large")
    if len(normalized) != len(raw_names):
        raise _StepFailure(f"{field}_duplicate_component")
    if set(REQUIRED_COMPONENTS) != normalized:
        raise _StepFailure(f"{field}_coverage_incomplete")
    return tuple(sorted(normalized))


def _normalise_component_checksums(value: object, *, field: str) -> dict[str, str]:
    raw = _mapping(value)
    if not raw:
        raise _StepFailure(f"{field}_missing")
    aliases = {
        "postgres": "postgresql",
        "postgresql": "postgresql",
        "object_store": "object_storage",
        "object-storage": "object_storage",
        "object_storage": "object_storage",
        "storage": "object_storage",
        "job": "jobs",
        "jobs": "jobs",
        "audit": "audit",
        "evidence": "evidence_lineage",
        "evidence_lineage": "evidence_lineage",
        "lineage": "evidence_lineage",
        "qdrant": "qdrant",
        "vectors": "qdrant",
        "vector": "qdrant",
    }
    result: dict[str, str] = {}
    for raw_name, checksum in raw.items():
        if not isinstance(raw_name, str):
            raise _StepFailure(f"{field}_invalid")
        name = aliases.get(raw_name.strip().casefold())
        if name is None:
            raise _StepFailure(f"{field}_unknown_component")
        if name in result:
            raise _StepFailure(f"{field}_duplicate_component")
        result[name] = _normalise_checksum(checksum, field=f"{field}_{name}")
    if set(result) != set(REQUIRED_COMPONENTS):
        raise _StepFailure(f"{field}_coverage_incomplete")
    return dict(sorted(result.items()))


def _safe_output(raw: str | os.PathLike[str], *, root: Path) -> Path:
    if not isinstance(raw, (str, os.PathLike)) or not str(raw).strip():
        raise _InvalidConfiguration()
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        raise _InvalidConfiguration() from None
    return path


def _safe_runtime_path(raw: str | os.PathLike[str], *, root: Path) -> Path:
    if not isinstance(raw, (str, os.PathLike)) or not str(raw).strip():
        raise _BlockedExternal()
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    try:
        if path.is_symlink() or not path.is_file():
            raise _BlockedExternal()
    except OSError:
        raise _BlockedExternal() from None
    return path.resolve()


def _accepted_kwargs(target: Callable[..., object], values: Mapping[str, object]) -> dict[str, object]:
    try:
        signature = inspect.signature(target)
    except (TypeError, ValueError):
        return dict(values)
    parameters = signature.parameters.values()
    if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters):
        return dict(values)
    accepted = {
        parameter.name
        for parameter in parameters
        if parameter.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }
    return {name: value for name, value in values.items() if name in accepted}


def _call_factory(factory: Callable[..., object], *, run_id: str, timeout_seconds: float, rpo_seconds: float, rto_seconds: float) -> object:
    values = {
        "run_id": run_id,
        "timeout_seconds": timeout_seconds,
        "rpo_seconds": rpo_seconds,
        "rto_seconds": rto_seconds,
    }
    kwargs = _accepted_kwargs(factory, values)
    try:
        return factory(**kwargs)
    except Exception:
        raise _BlockedExternal() from None


def _load_runtime(
    raw_path: str | os.PathLike[str],
    *,
    root: Path,
    run_id: str,
    timeout_seconds: float,
    rpo_seconds: float,
    rto_seconds: float,
) -> object:
    path = _safe_runtime_path(raw_path, root=root)
    spec = importlib.util.spec_from_file_location(f"rick_restore_runtime_{uuid.uuid4().hex}", path)
    if spec is None or spec.loader is None:
        raise _BlockedExternal()
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        raise _BlockedExternal() from None
    for name in ("create_runtime", "build_runtime", "get_runtime"):
        factory = getattr(module, name, None)
        if callable(factory):
            runtime = _call_factory(
                factory,
                run_id=run_id,
                timeout_seconds=timeout_seconds,
                rpo_seconds=rpo_seconds,
                rto_seconds=rto_seconds,
            )
            if runtime is None:
                raise _InvalidConfiguration()
            return runtime
    raise _InvalidConfiguration()


def _runtime_operation(runtime: object, operation: str) -> Callable[..., object] | None:
    for name in (operation, f"run_{operation}"):
        candidate = _value(runtime, name, None)
        if callable(candidate):
            return candidate
    generic = _value(runtime, "run_step", None)
    if callable(generic):
        return generic
    return None


async def _invoke(target: Callable[..., object], *, operation: str, context: Mapping[str, object], timeout: float) -> object:
    values: dict[str, object] = {
        "operation": operation,
        "context": context,
        "run_id": context.get("run_id"),
        "scope": context.get("scope"),
        "previous": context.get("previous"),
        "timeout_seconds": timeout,
        "rpo_budget_seconds": context.get("rpo_budget_seconds"),
        "rto_budget_seconds": context.get("rto_budget_seconds"),
    }
    kwargs = _accepted_kwargs(target, values)
    try:
        if inspect.iscoroutinefunction(target):
            result = await asyncio.wait_for(target(**kwargs), timeout=timeout)
        else:
            result = await asyncio.wait_for(asyncio.to_thread(target, **kwargs), timeout=timeout)
        if inspect.isawaitable(result):
            result = await asyncio.wait_for(result, timeout=timeout)
        return result
    except asyncio.TimeoutError:
        raise _OperationTimeout() from None
    except _BlockedExternal:
        raise
    except _StepFailure:
        raise
    except _OperationTimeout:
        raise
    except Exception:
        raise _StepFailure("operation_execution_failed") from None


async def _invoke_preflight(runtime: object, *, context: Mapping[str, object], timeout: float) -> object:
    target = _value(runtime, "preflight", None)
    if target is None:
        raise _InvalidConfiguration()
    if callable(target):
        return await _invoke(target, operation="preflight", context=context, timeout=timeout)
    return target


def _validate_external_metadata(runtime: object) -> dict[str, object]:
    if _value(runtime, "authorized", False) is not True or _value(runtime, "external", False) is not True:
        raise _BlockedExternal()
    if _value(runtime, "disposable", False) is not True:
        raise _BlockedExternal()
    metadata = _mapping(_value(runtime, "runtime_metadata", None))
    if not metadata:
        raise _BlockedExternal()
    mode = _first(metadata, ("execution_mode", "runtime_kind", "kind"), default=_MISSING)
    transport = _first(metadata, ("transport", "boundary"), default=_MISSING)
    authority = _first(metadata, ("authority", "authority_id", "operator"), default=_MISSING)
    if not isinstance(mode, str) or mode.strip().casefold() in _FORBIDDEN_MODES or mode.strip().casefold() not in _ALLOWED_MODES:
        raise _BlockedExternal()
    if not isinstance(transport, str) or transport.strip().casefold() in _FORBIDDEN_TRANSPORTS or not transport.strip():
        raise _BlockedExternal()
    if not isinstance(authority, str) or not authority.strip() or len(authority.strip()) > 128 or any(ord(char) < 0x20 or ord(char) == 0x7F for char in authority):
        raise _BlockedExternal()
    transport_label = transport.strip().casefold()
    if any(char in transport_label for char in "/:@") or len(transport_label) > 64:
        raise _BlockedExternal()
    clock_source = str(_first(metadata, ("clock_source",), default="external")).strip().casefold()
    if not clock_source or len(clock_source) > 64 or any(ord(char) < 0x20 or ord(char) == 0x7F for char in clock_source):
        raise _BlockedExternal()
    if _value(metadata, "service_boundary", False) is not True or _value(metadata, "destructive_operations", False) is not True:
        raise _BlockedExternal()
    components = _normalise_components(_value(metadata, "components", None), field="metadata_components")
    return {
        "authority_digest": _digest(authority.strip()),
        "execution_mode": mode.strip().casefold(),
        "transport": transport.strip().casefold(),
        "service_boundary": True,
        "destructive_operations": True,
        "components": list(components),
        "clock_source": clock_source,
    }


def _validate_preflight(value: object) -> dict[str, object]:
    status = _normalise_status(_first(value, ("status", "result", "state"), default=_MISSING))
    if status == BLOCKED_EXTERNAL:
        raise _BlockedExternal()
    if status != PASS:
        raise _StepFailure("preflight_not_ready")
    checks = _mapping(_value(value, "checks", None))
    required_checks = (*REQUIRED_COMPONENTS, "destructive_authorized", "empty_target_ready", "clock_verified")
    if any(_value(checks, key, False) is not True for key in required_checks):
        raise _BlockedExternal()
    if _value(value, "external", False) is not True or _value(value, "disposable", False) is not True:
        raise _BlockedExternal()
    return {
        "status": PASS,
        "checks": {key: True for key in required_checks},
        "external": True,
        "disposable": True,
    }


def _checksum_for(operation: str, value: object) -> str:
    names = {
        "seed": ("seed_checksum", "data_checksum", "checksum"),
        "backup": ("source_checksum", "data_checksum", "checksum", "backup_checksum"),
        "destroy": ("source_checksum", "data_checksum", "checksum"),
        "restore": ("restore_checksum", "data_checksum", "checksum", "source_checksum"),
        "rebuild": ("rebuild_checksum", "data_checksum", "checksum", "source_checksum"),
        "verify": ("verified_checksum", "data_checksum", "checksum", "source_checksum"),
    }
    candidate = _first(value, names[operation], default=_MISSING)
    if candidate is _MISSING:
        raise _StepFailure(f"{operation}_checksum_missing")
    return _normalise_checksum(candidate, field=f"{operation}_checksum")


def _components_for(operation: str, value: object) -> tuple[str, ...]:
    candidate = _first(value, ("components", "component_counts", "component_checksums"), default=_MISSING)
    if candidate is _MISSING:
        raise _StepFailure(f"{operation}_components_missing")
    return _normalise_components(candidate, field=f"{operation}_components")


def _step_observed(step: _Step) -> dict[str, object]:
    observed: dict[str, object] = {
        "scope_digest": _scope_digest(step.scope),
        "components": list(step.components),
        "checksum": step.checksum,
        "component_checksums": dict(step.component_checksums),
        "completed_at": step.completed_at.isoformat().replace("+00:00", "Z"),
    }
    for key in ("seed_id", "backup_id", "destruction_id"):
        value = step.values.get(key)
        if isinstance(value, str):
            observed[f"{key}_digest"] = _digest(value)
    for key in ("destroyed", "destruction_observed", "restored", "rebuilt", "qdrant_rebuilt", "index_rebuilt", "verified", "jobs_reconciled", "audit_reconciled", "evidence_lineage", "qdrant_consistent", "no_data_loss"):
        if key in step.values:
            observed[key] = step.values[key]
    return observed


def _validate_operation(operation: str, value: object) -> _Step:
    raw = _mapping(value)
    if not raw:
        raise _StepFailure(f"{operation}_observation_invalid")
    status = _normalise_status(_first(raw, ("status", "result", "state"), default=_MISSING))
    if status == BLOCKED_EXTERNAL:
        raise _BlockedExternal()
    if status != PASS:
        raise _StepFailure(f"{operation}_did_not_pass")
    scope = _normalise_scope(_first(raw, ("scope", "resource_scope"), default=_MISSING), field=f"{operation}_scope")
    completed_at = _timestamp_value(raw, field=f"{operation}_completed_at")
    checksum = _checksum_for(operation, raw)
    components = _components_for(operation, raw)
    component_checksums = _normalise_component_checksums(
        _first(raw, ("component_checksums", "checksums"), default=_MISSING),
        field=f"{operation}_component_checksums",
    )
    values: dict[str, object] = {}
    if operation == "seed":
        values["seed_id"] = _safe_identifier(_first(raw, ("seed_id", "snapshot_id"), default=_MISSING), field="seed_id")
        values["seeded_at"] = _parse_timestamp(_first(raw, ("seeded_at", "completed_at"), default=_MISSING), field="seeded_at")
    elif operation == "backup":
        values["backup_id"] = _safe_identifier(_first(raw, ("backup_id", "snapshot_id"), default=_MISSING), field="backup_id")
        values["source_state_at"] = _parse_timestamp(_first(raw, ("source_state_at", "data_as_of", "last_committed_at"), default=_MISSING), field="source_state_at")
        values["seed_id"] = _safe_identifier(_first(raw, ("seed_id", "source_seed_id"), default=_MISSING), field="backup_seed_id")
    elif operation == "destroy":
        for field in ("destroyed", "destruction_observed"):
            if _value(raw, field, False) is not True:
                raise _StepFailure(f"{field}_not_confirmed")
        remaining = _first(raw, ("remaining_components",), default=_MISSING)
        if remaining is _MISSING:
            counts = _mapping(_value(raw, "remaining_counts", None))
            if not counts or any(value != 0 for value in counts.values()):
                raise _StepFailure("destroy_remaining_scope_unknown")
        elif not isinstance(remaining, Sequence) or isinstance(remaining, (str, bytes, bytearray)) or list(remaining):
            raise _StepFailure("destroy_remaining_scope_nonempty")
        values["destroyed"] = True
        values["destruction_observed"] = True
        destruction_id = _first(raw, ("destruction_id", "destroy_id"), default=_MISSING)
        if destruction_id is not _MISSING:
            values["destruction_id"] = _safe_identifier(destruction_id, field="destruction_id")
        values["backup_id"] = _safe_identifier(_first(raw, ("backup_id",), default=_MISSING), field="destroy_backup_id")
    elif operation == "restore":
        if _value(raw, "restored", False) is not True:
            raise _StepFailure("restore_not_confirmed")
        values["restored"] = True
        values["backup_id"] = _safe_identifier(_first(raw, ("backup_id", "snapshot_id"), default=_MISSING), field="restore_backup_id")
        restored_components = _first(raw, ("restored_components", "components"), default=_MISSING)
        if _normalise_components(restored_components, field="restored_components") != components:
            raise _StepFailure("restore_component_coverage_mismatch")
    elif operation == "rebuild":
        for field in ("rebuilt", "qdrant_rebuilt", "index_rebuilt"):
            if _value(raw, field, False) is not True:
                raise _StepFailure(f"{field}_not_confirmed")
        values.update({"rebuilt": True, "qdrant_rebuilt": True, "index_rebuilt": True})
    elif operation == "verify":
        for field in ("verified", "jobs_reconciled", "audit_reconciled", "evidence_lineage", "qdrant_consistent", "no_data_loss"):
            aliases = {
                "evidence_lineage": ("evidence_lineage", "evidence_lineage_verified", "lineage_verified"),
            }.get(field, (field,))
            if _first(raw, aliases, default=False) is not True:
                raise _StepFailure(f"{field}_not_confirmed")
            values[field] = True
    return _Step(operation, scope, checksum, component_checksums, components, completed_at, values)


def _check_transition(operation: str, step: _Step, previous: Mapping[str, _Step]) -> None:
    if operation != "seed":
        prior_name = OPERATIONS[OPERATIONS.index(operation) - 1]
        prior = previous.get(prior_name)
        if prior is None:
            raise _StepFailure(f"{operation}_sequence_predecessor_missing")
        if step.completed_at < prior.completed_at:
            raise _StepFailure(f"{operation}_timestamp_order_invalid")
        if step.scope != prior.scope:
            raise _StepFailure(f"{operation}_scope_mismatch")
        if operation in {"restore", "rebuild", "verify"} and step.component_checksums != prior.component_checksums:
            raise _StepFailure(f"{operation}_component_checksum_mismatch")
    if operation == "backup":
        seed = previous["seed"]
        if step.values.get("seed_id") != seed.values.get("seed_id"):
            raise _StepFailure("backup_seed_mismatch")
        if step.checksum != seed.checksum or step.component_checksums != seed.component_checksums:
            raise _StepFailure("backup_checksum_mismatch")
        source_state_at = step.values["source_state_at"]
        seeded_at = seed.values["seeded_at"]
        if not isinstance(source_state_at, datetime) or not isinstance(seeded_at, datetime) or source_state_at < seeded_at:
            raise _StepFailure("backup_source_time_invalid")
    elif operation == "destroy":
        if step.values.get("backup_id") != previous["backup"].values.get("backup_id"):
            raise _StepFailure("destroy_backup_mismatch")
        if step.checksum != previous["backup"].checksum or step.component_checksums != previous["backup"].component_checksums:
            raise _StepFailure("destroy_checksum_mismatch")
    elif operation == "restore":
        if step.values.get("backup_id") != previous["backup"].values.get("backup_id"):
            raise _StepFailure("restore_backup_mismatch")
        if step.checksum != previous["backup"].checksum:
            raise _StepFailure("restore_checksum_mismatch")
    elif operation == "rebuild":
        if step.checksum != previous["restore"].checksum:
            raise _StepFailure("rebuild_checksum_mismatch")
    elif operation == "verify":
        if step.checksum != previous["rebuild"].checksum:
            raise _StepFailure("verify_checksum_mismatch")


def _metrics(steps: Mapping[str, _Step], *, rpo_budget: float, rto_budget: float) -> tuple[dict[str, object], dict[str, object]]:
    seed = steps["seed"]
    backup = steps["backup"]
    destroy = steps["destroy"]
    verify = steps["verify"]
    source_state_at = backup.values["source_state_at"]
    seeded_at = seed.values["seeded_at"]
    if not isinstance(source_state_at, datetime) or not isinstance(seeded_at, datetime):
        raise _StepFailure("rpo_measurement_unavailable")
    rpo = (backup.completed_at - source_state_at).total_seconds()
    if rpo < 0:
        raise _StepFailure("rpo_measurement_negative")
    rto = (verify.completed_at - destroy.completed_at).total_seconds()
    if rto < 0:
        raise _StepFailure("rto_measurement_negative")
    rpo_record = {
        "measured_seconds": round(rpo, 3),
        "budget_seconds": rpo_budget,
        "within_budget": rpo <= rpo_budget,
        "seeded_at": seeded_at.isoformat().replace("+00:00", "Z"),
        "source_state_at": source_state_at.isoformat().replace("+00:00", "Z"),
        "backup_completed_at": backup.completed_at.isoformat().replace("+00:00", "Z"),
    }
    rto_record = {
        "measured_seconds": round(rto, 3),
        "budget_seconds": rto_budget,
        "within_budget": rto <= rto_budget,
        "destroy_completed_at": destroy.completed_at.isoformat().replace("+00:00", "Z"),
        "verify_completed_at": verify.completed_at.isoformat().replace("+00:00", "Z"),
    }
    return rpo_record, rto_record


def _status(results: Sequence[GateResult]) -> str:
    if any(item.result == FAIL for item in results):
        return FAIL
    if any(item.result == BLOCKED_EXTERNAL for item in results):
        return BLOCKED_EXTERNAL
    if any(item.result == NOT_RUN for item in results):
        return BLOCKED_EXTERNAL
    return PASS if results and all(item.result == PASS for item in results) else FAIL


def _empty_operations(result: str, detail: str) -> list[GateResult]:
    return [GateResult(operation, result, detail) for operation in OPERATIONS]


def _budget(value: object, *, default: float, field: str) -> float:
    raw = default if value is None or (isinstance(value, str) and not value.strip()) else value
    try:
        number = float(raw)
    except (TypeError, ValueError):
        raise _InvalidConfiguration() from None
    if not 0.1 <= number <= MAX_BUDGET_SECONDS:
        raise _InvalidConfiguration()
    return number


def _base_report(*, status: str, detail: str, rpo_budget: float, rto_budget: float) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "gate_id": GATE_ID,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "runtime_claim": False,
        "production_safe": False,
        "run_id": None,
        "required_components": list(REQUIRED_COMPONENTS),
        "required_sequence": list(OPERATIONS),
        "executed_sequence": [],
        "sequence_valid": False,
        "interface_contract": INTERFACE_CONTRACT,
        "rpo": {"measured_seconds": None, "budget_seconds": rpo_budget, "within_budget": False},
        "rto": {"measured_seconds": None, "budget_seconds": rto_budget, "within_budget": False},
        "runtime": {"authorized": False, "external": False, "disposable": False},
        "preflight": {"status": status if status != FAIL else FAIL},
        "results": [item.to_dict() for item in _empty_operations(status, detail)],
        "detail": detail,
        "limitations": [
            "No local or in-memory implementation is accepted as external runtime evidence.",
            "Missing authority remains BLOCKED_EXTERNAL and is not a runtime claim.",
            "A PASS covers only the explicitly composed disposable services and this exact recovery sequence.",
        ],
    }


async def _run_gate(
    runtime_path: str | os.PathLike[str] | None,
    *,
    root: Path,
    output: str | os.PathLike[str],
    timeout_seconds: float,
    rpo_budget: float,
    rto_budget: float,
) -> dict[str, object]:
    output_path = _safe_output(output, root=root)
    run_id = uuid.uuid4().hex
    report = _base_report(status=BLOCKED_EXTERNAL, detail="runtime_path_not_configured", rpo_budget=rpo_budget, rto_budget=rto_budget)
    report["run_id"] = run_id
    raw_path = runtime_path
    if raw_path is None or not str(raw_path).strip():
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return report

    try:
        runtime = _load_runtime(
            raw_path,
            root=root,
            run_id=run_id,
            timeout_seconds=timeout_seconds,
            rpo_seconds=rpo_budget,
            rto_seconds=rto_budget,
        )
        metadata = _validate_external_metadata(runtime)
        report["runtime"] = {
            "authorized": True,
            "external": True,
            "disposable": True,
            **metadata,
        }
        deadline = time.monotonic() + timeout_seconds
        context = {
            "run_id": run_id,
            "operation": "preflight",
            "timeout_seconds": timeout_seconds,
            "rpo_budget_seconds": rpo_budget,
            "rto_budget_seconds": rto_budget,
        }
        preflight = await _invoke_preflight(runtime, context=context, timeout=min(timeout_seconds, max(0.1, deadline - time.monotonic())))
        report["preflight"] = _validate_preflight(preflight)
        results: list[GateResult] = [GateResult("external_authorization", PASS, "authorized_external_disposable_composition", {"mode": metadata["execution_mode"], "transport": metadata["transport"]}), GateResult("external_preflight", PASS, "external_target_ready", report["preflight"])]
        steps: dict[str, _Step] = {}
        previous_projection: dict[str, object] = {}
        for index, operation in enumerate(OPERATIONS):
            remaining = deadline - time.monotonic()
            if remaining < 0.1:
                results.append(GateResult(operation, FAIL, "gate_timeout"))
                results.extend(GateResult(item, NOT_RUN, "sequence_stopped_after_failure") for item in OPERATIONS[index + 1 :])
                break
            target = _runtime_operation(runtime, operation)
            if target is None:
                results.append(GateResult(operation, FAIL, "operation_port_missing"))
                results.extend(GateResult(item, NOT_RUN, "sequence_stopped_after_failure") for item in OPERATIONS[index + 1 :])
                break
            context = {
                "run_id": run_id,
                "operation": operation,
                "previous": previous_projection,
                "scope": steps.get("seed").scope if "seed" in steps else None,
                "timeout_seconds": min(timeout_seconds, max(0.1, remaining)),
                "rpo_budget_seconds": rpo_budget,
                "rto_budget_seconds": rto_budget,
            }
            try:
                observed = await _invoke(target, operation=operation, context=context, timeout=min(timeout_seconds, max(0.1, remaining)))
                step = _validate_operation(operation, observed)
                _check_transition(operation, step, steps)
            except _BlockedExternal:
                results.append(GateResult(operation, BLOCKED_EXTERNAL, "external_operation_unavailable"))
                results.extend(GateResult(item, NOT_RUN, "sequence_stopped_after_block") for item in OPERATIONS[index + 1 :])
                break
            except _OperationTimeout:
                results.append(GateResult(operation, FAIL, "operation_timeout"))
                results.extend(GateResult(item, NOT_RUN, "sequence_stopped_after_failure") for item in OPERATIONS[index + 1 :])
                break
            except _StepFailure as exc:
                candidate_detail = str(exc)
                detail = candidate_detail if _SAFE_DETAIL.fullmatch(candidate_detail) else "operation_contract_invalid"
                results.append(GateResult(operation, FAIL, detail))
                results.extend(GateResult(item, NOT_RUN, "sequence_stopped_after_failure") for item in OPERATIONS[index + 1 :])
                break
            except Exception:
                results.append(GateResult(operation, FAIL, "operation_contract_invalid"))
                results.extend(GateResult(item, NOT_RUN, "sequence_stopped_after_failure") for item in OPERATIONS[index + 1 :])
                break
            steps[operation] = step
            previous_projection[operation] = _step_observed(step)
            results.append(GateResult(operation, PASS, "external_operation_verified", _step_observed(step)))
        if len(steps) == len(OPERATIONS):
            try:
                rpo_record, rto_record = _metrics(steps, rpo_budget=rpo_budget, rto_budget=rto_budget)
                report["rpo"] = rpo_record
                report["rto"] = rto_record
                results.append(GateResult("rpo", PASS if rpo_record["within_budget"] else FAIL, "within_budget" if rpo_record["within_budget"] else "budget_exceeded", {"measured_seconds": rpo_record["measured_seconds"], "budget_seconds": rpo_budget}))
                results.append(GateResult("rto", PASS if rto_record["within_budget"] else FAIL, "within_budget" if rto_record["within_budget"] else "budget_exceeded", {"measured_seconds": rto_record["measured_seconds"], "budget_seconds": rto_budget}))
            except _StepFailure:
                results.append(GateResult("rpo", FAIL, "measurement_unavailable"))
                results.append(GateResult("rto", FAIL, "measurement_unavailable"))
        status = _status(results)
        report["status"] = status
        report["runtime_claim"] = status == PASS
        report["production_safe"] = bool(status == PASS and _value(runtime, "production_safe", False) is True)
        report["results"] = [item.to_dict() for item in results]
        report["executed_sequence"] = list(steps)
        report["sequence_valid"] = bool(status == PASS and list(steps) == list(OPERATIONS))
        report["detail"] = "seed_backup_destroy_restore_rebuild_verify_completed" if status == PASS else "recovery_sequence_not_proven"
        if steps:
            report["scope"] = {"digest": _scope_digest(steps["seed"].scope), "dimensions": {key: len(value) for key, value in steps["seed"].scope.items()}}
    except _BlockedExternal:
        report["status"] = BLOCKED_EXTERNAL
        report["detail"] = "authorized_external_restore_runtime_unavailable"
        report["results"] = [
            GateResult("external_authorization", BLOCKED_EXTERNAL, "authorized_external_disposable_composition_required").to_dict(),
            *[item.to_dict() for item in _empty_operations(BLOCKED_EXTERNAL, "sequence_not_run")],
        ]
    except _InvalidConfiguration:
        report["status"] = FAIL
        report["detail"] = "restore_runtime_composition_contract_invalid"
        report["results"] = [
            GateResult("external_authorization", FAIL, "composition_contract_invalid").to_dict(),
            *[item.to_dict() for item in _empty_operations(NOT_RUN, "sequence_not_run")],
        ]
    except _StepFailure:
        report["status"] = FAIL
        report["detail"] = "restore_runtime_composition_contract_invalid"
        report["results"] = [
            GateResult("external_authorization", FAIL, "composition_contract_invalid").to_dict(),
            *[item.to_dict() for item in _empty_operations(NOT_RUN, "sequence_not_run")],
        ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return report


def run_gate(
    runtime_path: str | os.PathLike[str] | None = None,
    *,
    root: Path = ROOT,
    output: str | os.PathLike[str] = DEFAULT_OUTPUT,
    timeout_seconds: object = DEFAULT_TIMEOUT_SECONDS,
    rpo_seconds: object = None,
    rto_seconds: object = None,
) -> dict[str, object]:
    """Run the bounded external recovery sequence and write its artifact."""

    root = root.resolve()
    selected_path = runtime_path if runtime_path is not None else os.environ.get(GATE_ID, "")
    try:
        timeout = _budget(timeout_seconds, default=DEFAULT_TIMEOUT_SECONDS, field="timeout_seconds")
        rpo_budget = _budget(rpo_seconds if rpo_seconds is not None else os.environ.get("RICK_RESTORE_RPO_SECONDS"), default=DEFAULT_RPO_SECONDS, field="rpo_seconds")
        rto_budget = _budget(rto_seconds if rto_seconds is not None else os.environ.get("RICK_RESTORE_RTO_SECONDS"), default=DEFAULT_RTO_SECONDS, field="rto_seconds")
        if timeout > MAX_TIMEOUT_SECONDS:
            raise _InvalidConfiguration()
        return asyncio.run(
            _run_gate(
                selected_path,
                root=root,
                output=output,
                timeout_seconds=timeout,
                rpo_budget=rpo_budget,
                rto_budget=rto_budget,
            )
        )
    except _InvalidConfiguration:
        try:
            output_path = _safe_output(output, root=root)
            report = _base_report(status=FAIL, detail="restore_runtime_configuration_invalid", rpo_budget=DEFAULT_RPO_SECONDS, rto_budget=DEFAULT_RTO_SECONDS)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            return report
        except Exception:
            return {"schema_version": SCHEMA_VERSION, "gate_id": GATE_ID, "status": FAIL, "runtime_claim": False, "production_safe": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-path", default=None)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout-seconds", default=None)
    parser.add_argument("--rpo-seconds", default=None)
    parser.add_argument("--rto-seconds", default=None)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        report = run_gate(
            args.runtime_path,
            root=ROOT,
            output=args.output,
            timeout_seconds=args.timeout_seconds if args.timeout_seconds is not None else DEFAULT_TIMEOUT_SECONDS,
            rpo_seconds=args.rpo_seconds,
            rto_seconds=args.rto_seconds,
        )
    except Exception:
        report = {"schema_version": SCHEMA_VERSION, "gate_id": GATE_ID, "status": FAIL, "runtime_claim": False, "production_safe": False}
    print(json.dumps({"gate_id": GATE_ID, "status": report.get("status", FAIL), "output": args.output}, sort_keys=True))
    status = report.get("status")
    return 0 if status == PASS else 2 if status == BLOCKED_EXTERNAL else 1


if __name__ == "__main__":
    raise SystemExit(main())
