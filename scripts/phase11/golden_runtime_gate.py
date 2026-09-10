#!/usr/bin/env python3
"""Bounded evidence gate for ``RICK_GOLDEN_RUNTIME_PATH``.

This gate is an executable contract for the complete Phase 3.6 path::

    upload -> object -> durable job -> worker -> parse/normalize/chunk/embed
    -> Qdrant -> verify/publish -> retrieve/evidence/professor/decision/response

The gate does not construct infrastructure.  A reviewed composition module is
selected explicitly with ``RICK_GOLDEN_RUNTIME_PATH`` (or ``--runtime-path``)
and must return the injected ports declared by :class:`GoldenRuntime`.  The
composition must also state ``authorized=True`` and ``external=True`` and
provide a bounded ``preflight`` callable.  Missing authorization, unavailable
external services, missing fault injection, or an absent composition returns
``BLOCKED_EXTERNAL``.  A supplied but contract-incomplete composition fails;
neither state is upgraded to PASS.

The synthetic fixture is deliberately small, non-clinical, and created only
for this disposable run.  It is not an approved corpus and a PASS proves only
the assertions made here for the injected environment.

No exception text, source text, URL, token, or credential is persisted in the
report.  The report contains bounded status codes, counts, digests of local
identifiers, the failure matrix, and lineage assertions.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable, Iterable, Mapping, Sequence
import contextvars
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.util
import inspect
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import uuid
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
GATE_ID = "RICK_GOLDEN_RUNTIME_PATH"
SCHEMA_VERSION = "phase11-golden-runtime-gate.v1"
DEFAULT_OUTPUT = ".runtime/phase-3/golden-ingestion-runtime-gate.json"
DEFAULT_TIMEOUT_SECONDS = 60.0
MAX_TIMEOUT_SECONDS = 300.0
MAX_WORKER_POLLS = 64
MAX_FIXTURE_BYTES = 16 * 1024
MAX_FAILURE_CASES = 11

PASS = "PASS"
FAIL = "FAIL"
BLOCKED_EXTERNAL = "BLOCKED_EXTERNAL"
NOT_RUN = "NOT_RUN"

FAILURE_POINTS = (
    "after_upload",
    "after_object_store",
    "after_enqueue",
    "after_extraction",
    "after_chunking",
    "after_embedding",
    "during_qdrant",
    "before_verification",
    "after_verification",
    "before_publish",
    "after_publish",
)

LINEAGE_FIELDS = (
    "document_id",
    "document_version",
    "ingestion_version",
    "parser_version",
    "chunker_version",
    "embedding_model",
    "embedding_version",
    "index_version",
    "checksum",
    "object_ref",
    "created_at",
    "verified_at",
    "published_at",
)

PATH_STAGES = (
    "upload",
    "object",
    "durable_job",
    "worker",
    "parse",
    "normalize",
    "chunk",
    "embed",
    "qdrant",
    "verify",
    "publish",
    "retrieve",
    "evidence",
    "professor",
    "decision",
    "response",
)

INTERFACE_CONTRACT: dict[str, object] = {
    "apps/api": {"upload": ("submit_upload", "upload")},
    "apps/worker": {"durable_job": ("get_by_idempotency",), "worker": ("run_once", "run_forever")},
    "packages/ingestion": {"pipeline": ("ingest",), "trace": "explicit stage_trace required for parse/normalize"},
    "knowledge": {"document": ("get_document",), "chunks": ("get_chunks",), "lineage": "verified_at must be injected"},
    "retrieval": {"retrieval": ("retrieve",), "qdrant": ("count_for_document", "search/query")},
    "evidence": {"issue": ("issue", "build_bundle"), "validate": ("validate_bundle",), "authority": "authoritative resolver required"},
    "professor": {"professor": ("generate", "run"), "decision": ("decide",), "response": ("render", "build")},
}

_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$")
_SHA256 = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
_TERMINAL_FAILURES = frozenset({"failed", "dead", "dead_letter", "cancelled", "error"})
_SUCCESS_STATES = frozenset({"published", "succeeded", "success", "acked", "complete", "completed"})
_MISSING = object()
_ACTIVE_DEADLINE: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "rick_golden_runtime_deadline",
    default=None,
)


class GateBlocked(Exception):
    """A safe, non-diagnostic signal that an external assertion cannot run."""


class GateContractError(Exception):
    """A supplied composition violates this gate's explicit port contract."""


@dataclass(frozen=True, slots=True)
class GateResult:
    """One bounded assertion; ``detail`` is a stable safe code."""

    name: str
    result: str
    detail: str = ""
    observed: Mapping[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {"name": self.name, "result": self.result}
        if self.detail:
            value["detail"] = self.detail
        if self.observed:
            value["observed"] = _safe_report_value(self.observed)
        return value


@dataclass(frozen=True, slots=True)
class SyntheticFixture:
    """Bounded disposable input; content is never written to the report."""

    filename: str = "rick-golden-runtime-fixture.txt"
    query: str = "Which runtime invariant protects the verified document version?"
    content: bytes = (
        b"RICK golden runtime fixture. The verified document version remains the "
        b"published authority while a failed replacement is quarantined. "
        b"This synthetic sentence tests lineage, retrieval, evidence, and response.\n"
    )

    @property
    def checksum(self) -> str:
        return "sha256:" + hashlib.sha256(self.content).hexdigest()

    def bounded(self) -> bool:
        return (
            isinstance(self.content, bytes)
            and 1 <= len(self.content) <= MAX_FIXTURE_BYTES
            and isinstance(self.filename, str)
            and bool(self.filename.strip())
            and isinstance(self.query, str)
            and bool(self.query.strip())
        )


@dataclass(slots=True)
class GoldenRuntime:
    """Explicitly injected Phase 3.6 composition.

    ``authorized``, ``external``, and ``preflight`` are mandatory runtime
    assertions.  All service fields are ports, not configuration selectors;
    the gate never fills a missing field with a local implementation.

    ``stage_trace`` must expose a callable, ``snapshot``/``events`` object, or
    a sequence with one successful event for every :data:`PATH_STAGES` entry.
    In particular, ``parse`` and ``normalize`` must be explicit observations;
    they cannot be inferred from a final row in a database.  ``lineage`` must
    expose the complete :data:`LINEAGE_FIELDS` tuple after publication,
    including ``verified_at`` even though the legacy Document model does not
    currently expose that field.
    """

    upload: object | None = None
    object_store: object | None = None
    queue: object | None = None
    worker: object | None = None
    ingestion: object | None = None
    knowledge: object | None = None
    vector_store: object | None = None
    embeddings: object | None = None
    retrieval: object | None = None
    evidence: object | None = None
    professor: object | None = None
    decision: object | None = None
    response: object | None = None
    failure_matrix: object | None = None
    stage_trace: object | None = None
    lineage: object | None = None
    authorized: bool = False
    external: bool = False
    production_safe: bool = False
    preflight: object | None = None
    cleanup: object | None = None
    runtime_metadata: Mapping[str, object] | None = None


_DEPENDENCY_ALIASES: dict[str, tuple[str, ...]] = {
    "upload": ("upload", "upload_service", "api"),
    "object_store": ("object_store", "objects", "storage"),
    "queue": ("queue", "job_queue", "durable_queue"),
    "worker": ("worker", "runtime_worker", "worker_runtime"),
    "ingestion": ("ingestion", "ingestion_service", "pipeline"),
    "knowledge": ("knowledge", "knowledge_store", "documents"),
    "vector_store": ("vector_store", "qdrant", "vectors"),
    "embeddings": ("embeddings", "embedding_provider", "embedder"),
    "retrieval": ("retrieval", "retrieval_engine"),
    "evidence": ("evidence", "evidence_validator", "evidence_gate"),
    "professor": ("professor", "professor_backend", "orchestrator"),
    "decision": ("decision", "decision_layer", "decision_gate"),
    "response": ("response", "response_builder", "renderer", "formatter"),
    "failure_matrix": ("failure_matrix", "fault_injector", "faults"),
    "stage_trace": ("stage_trace", "trace", "events", "event_sink"),
    "lineage": ("lineage", "lineage_provider", "lineage_snapshot"),
}

_PORT_OPERATIONS: dict[str, tuple[str, ...]] = {
    "upload": ("submit_upload", "upload"),
    "object_store": ("head", "get"),
    "queue": ("get_by_idempotency", "get", "get_for_workspace"),
    "worker": ("run_once", "run_forever", "process", "execute"),
    "ingestion": ("ingest",),
    "knowledge": ("get_document", "get_chunks"),
    "vector_store": ("count_for_document", "search", "query"),
    "embeddings": ("embed", "embed_query", "encode"),
    "retrieval": ("retrieve",),
    "evidence": ("build_bundle", "issue", "validate", "validate_bundle"),
    "professor": ("generate", "run", "answer"),
    "decision": ("decide", "evaluate"),
    "response": ("render", "build", "format", "respond"),
    "failure_matrix": ("run", "execute", "inject"),
    "stage_trace": ("snapshot", "events", "read"),
    "lineage": ("snapshot", "read", "resolve"),
}


def _read(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        if name in value:
            return value.get(name, default)
        payload = value.get("payload")
        if isinstance(payload, Mapping) and name in payload:
            return payload.get(name, default)
        return default
    return getattr(value, name, default)


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


def _safe_identifier(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > 512:
        return None
    return value


def _short_digest(value: object) -> str | None:
    text = _safe_identifier(value)
    if text is None:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _safe_report_value(value: object, *, key: str = "") -> object:
    """Project values without persisting content or secret-bearing metadata."""

    lowered = key.casefold()
    if any(marker in lowered for marker in ("secret", "token", "password", "credential", "authorization", "api_key", "dsn", "url")):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(name): _safe_report_value(item, key=str(name)) for name, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_report_value(item) for item in value[:32]]
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"type": "bytes", "size": len(value)}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) > 256:
            return {"type": "text", "size": len(value), "digest": _short_digest(value)}
        if any(marker in lowered for marker in ("text", "content", "answer", "excerpt", "message", "query")):
            return {"type": "text", "size": len(value), "digest": _short_digest(value)}
        return value
    return {"type": type(value).__name__}


def _safe_error(exc: BaseException) -> str:
    """Return a stable code and never the exception message."""

    if isinstance(exc, GateBlocked):
        return "external_unavailable"
    if isinstance(exc, GateContractError):
        return "composition_contract_invalid"
    if isinstance(exc, TimeoutError):
        return "bounded_timeout"
    if isinstance(exc, (asyncio.TimeoutError,)):
        return "bounded_timeout"
    return "dependency_call_failed"


def _normalise_status(value: object) -> str:
    if isinstance(value, bool):
        return PASS if value else FAIL
    if isinstance(value, str):
        text = value.strip().upper().replace("-", "_")
        if text in {PASS, FAIL, BLOCKED_EXTERNAL, NOT_RUN}:
            return text
        if text in {"OK", "SUCCESS", "SUCCEEDED", "COMPLETE", "COMPLETED", "PUBLISHED"}:
            return PASS
        if text in {"BLOCKED", "UNAVAILABLE", "NOT_AVAILABLE"}:
            return BLOCKED_EXTERNAL
    return FAIL


def _status_of(value: object) -> str:
    raw = _read(value, "status", _MISSING)
    if raw is _MISSING:
        raw = _read(value, "state", _MISSING)
    if raw is _MISSING:
        raw = _read(value, "result", _MISSING)
    if raw is _MISSING:
        return ""
    return str(raw).strip().casefold() if raw is not None else ""


def _operation(target: object, names: Iterable[str]) -> Callable[..., object] | None:
    if callable(target):
        return target
    for name in names:
        candidate = getattr(target, name, None)
        if callable(candidate):
            return candidate
    return None


def _operation_name(target: object, names: Iterable[str]) -> str | None:
    if callable(target):
        return "__call__"
    for name in names:
        if callable(getattr(target, name, None)):
            return name
    return None


def _accepted_kwargs(target: Callable[..., object], kwargs: Mapping[str, object]) -> dict[str, object]:
    """Filter keyword arguments without using TypeError as a shape probe."""

    try:
        signature = inspect.signature(target)
    except (TypeError, ValueError):
        return dict(kwargs)
    parameters = signature.parameters.values()
    if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters):
        return dict(kwargs)
    accepted = {
        parameter.name
        for parameter in parameters
        if parameter.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }
    return {name: value for name, value in kwargs.items() if name in accepted}


async def _invoke(
    target: Callable[..., object],
    *args: object,
    timeout: float | None = None,
    **kwargs: object,
) -> object:
    """Invoke a sync/async injected port with filtered named arguments.

    Synchronous ports are required to be bounded by their own adapter.  Async
    ports receive an actual timeout; the gate never starts an unbounded task in
    the background after a timeout.
    """

    effective_timeout = timeout
    active_deadline = _ACTIVE_DEADLINE.get()
    if active_deadline is not None:
        remaining = active_deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("bounded runtime deadline exceeded")
        effective_timeout = remaining if effective_timeout is None else min(effective_timeout, remaining)
    result = target(*args, **_accepted_kwargs(target, kwargs))
    if not inspect.isawaitable(result):
        return result
    if effective_timeout is None:
        return await result
    return await asyncio.wait_for(result, timeout=max(0.01, effective_timeout))


def _run_awaitable(value: object) -> object:
    if not inspect.isawaitable(value):
        return value
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(value)
    raise GateContractError("async call requires the synchronous CLI boundary")


def _runtime_field(runtime: object, name: str, default: object = None) -> object:
    direct = _read(runtime, name, _MISSING)
    if direct is not _MISSING:
        return direct
    for alias in _DEPENDENCY_ALIASES.get(name, ()):
        value = _read(runtime, alias, _MISSING)
        if value is not _MISSING:
            return value
    return default


def _normalise_runtime(value: object) -> GoldenRuntime:
    if isinstance(value, GoldenRuntime):
        return value
    if value is None:
        raise GateBlocked("runtime_missing")
    values: dict[str, object] = {}
    for field in fields(GoldenRuntime):
        value_for_field = _runtime_field(value, field.name, _MISSING)
        if value_for_field is not _MISSING:
            values[field.name] = value_for_field
    if isinstance(value, Mapping):
        # Preserve only declared fields; arbitrary factory metadata is not a
        # dependency and must not become an implicit construction path.
        unknown = set(value) - {field.name for field in fields(GoldenRuntime)} - {
            alias for aliases in _DEPENDENCY_ALIASES.values() for alias in aliases
        }
        if unknown:
            values.setdefault("runtime_metadata", {"unknown_fields": len(unknown)})
    try:
        return GoldenRuntime(**values)
    except TypeError as exc:
        raise GateContractError("runtime_shape_invalid") from exc


def _resolve_factory(module: object, requested: str | None) -> Callable[..., object] | None:
    if requested:
        candidate = getattr(module, requested, None)
        return candidate if callable(candidate) else None
    for name in ("build_golden_runtime", "build_runtime", "create_golden_runtime", "runtime_factory", "factory"):
        candidate = getattr(module, name, None)
        if callable(candidate):
            return candidate
    return None


def _load_module_from_file(path: Path) -> object:
    if not path.is_file():
        raise GateBlocked("runtime_file_missing")
    module_name = "rick_golden_runtime_" + hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16]
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise GateBlocked("runtime_module_unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise GateBlocked("runtime_module_unavailable") from exc
    return module


def _select_runtime_source(raw: str, root: Path) -> tuple[object, str | None]:
    candidate = raw.strip()
    if not candidate:
        raise GateBlocked("runtime_path_missing")
    if ":" in candidate and not Path(candidate).exists():
        module_name, separator, factory_name = candidate.partition(":")
        if not module_name or not separator:
            raise GateBlocked("runtime_selector_invalid")
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        try:
            return importlib.import_module(module_name), factory_name or None
        except Exception as exc:
            raise GateBlocked("runtime_module_unavailable") from exc
    path = Path(candidate)
    if not path.is_absolute():
        path = (root / path).resolve()
    if path.is_dir():
        for name in ("golden_runtime.py", "runtime.py"):
            selected = path / name
            if selected.is_file():
                return _load_module_from_file(selected), None
        raise GateBlocked("runtime_factory_missing")
    return _load_module_from_file(path), None


def load_runtime(
    runtime_path: str | os.PathLike[str] | None = None,
    *,
    root: Path = ROOT,
    run_id: str | None = None,
    fixture: SyntheticFixture | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[GoldenRuntime | None, GateResult]:
    """Load only an explicitly selected composition module.

    This function intentionally returns a blocked result for every absence or
    unavailability at the external boundary.  It never imports a fallback
    client or assembles local substitutes.
    """

    raw = str(runtime_path).strip() if runtime_path is not None else os.environ.get(GATE_ID, "").strip()
    if not raw:
        return None, GateResult("runtime_composition", BLOCKED_EXTERNAL, "runtime_path_not_configured")
    try:
        module, requested_factory = _select_runtime_source(raw, root)
        factory = _resolve_factory(module, requested_factory)
        if factory is None:
            raise GateBlocked("runtime_factory_missing")
        kwargs = {
            "root": root,
            "run_id": run_id or uuid.uuid4().hex,
            "fixture": fixture or SyntheticFixture(),
            "timeout_seconds": timeout_seconds,
        }
        selected_kwargs = _accepted_kwargs(factory, kwargs)
        result = factory(**selected_kwargs)
        if inspect.isawaitable(result):
            raise GateContractError("async_factory_not_supported")
        runtime = _normalise_runtime(result)
    except GateContractError:
        return None, GateResult("runtime_composition", FAIL, "runtime_factory_contract_invalid")
    except GateBlocked:
        return None, GateResult("runtime_composition", BLOCKED_EXTERNAL, "runtime_unavailable")
    except Exception:
        return None, GateResult("runtime_composition", BLOCKED_EXTERNAL, "runtime_unavailable")
    return runtime, GateResult("runtime_composition", PASS, "explicit_composition_loaded")


async def _preflight(runtime: GoldenRuntime, timeout_seconds: float) -> GateResult:
    if runtime.authorized is not True or runtime.external is not True:
        return GateResult("external_authorization", BLOCKED_EXTERNAL, "authorization_or_external_flag_missing")
    target = runtime.preflight
    if not callable(target):
        return GateResult("external_preflight", BLOCKED_EXTERNAL, "preflight_not_injected")
    try:
        result = await _invoke(target, timeout=timeout_seconds)
    except Exception as exc:
        return GateResult("external_preflight", BLOCKED_EXTERNAL, _safe_error(exc))
    if isinstance(result, Mapping):
        ready = result.get("ready", result.get("available", result.get("ok", _MISSING)))
        if ready is not True:
            return GateResult("external_preflight", BLOCKED_EXTERNAL, "external_preflight_not_ready")
    elif result is not True:
        return GateResult("external_preflight", BLOCKED_EXTERNAL, "external_preflight_not_ready")
    return GateResult("external_preflight", PASS, "external_preflight_ready")


def audit_interfaces(runtime: GoldenRuntime) -> tuple[list[GateResult], dict[str, object]]:
    """Audit the current app/package seams without constructing dependencies."""

    results: list[GateResult] = []
    report: dict[str, object] = {}
    for name in (
        "upload", "object_store", "queue", "worker", "ingestion", "knowledge",
        "vector_store", "embeddings", "retrieval", "evidence", "professor",
        "decision", "response", "failure_matrix", "stage_trace", "lineage",
    ):
        target = getattr(runtime, name)
        operation_name = _operation_name(target, _PORT_OPERATIONS[name]) if target is not None else None
        available = target is not None and operation_name is not None
        report[name] = {
            "injected": target is not None,
            "operation": operation_name,
            "available": available,
        }
        if target is None:
            result = BLOCKED_EXTERNAL if name in {"failure_matrix"} else FAIL
            detail = "dependency_not_injected"
        elif operation_name is None:
            result = FAIL
            detail = "required_operation_missing"
        else:
            result = PASS
            detail = "required_operation_available"
        results.append(GateResult(f"interface.{name}", result, detail))
    return results, report


def _make_object_scope(tenant_id: str, workspace_id: str, source_id: str) -> object:
    try:
        from rick_storage import ObjectScope
    except ImportError as exc:
        raise GateBlocked("object_scope_contract_unavailable") from exc
    try:
        return ObjectScope(tenant_id=tenant_id, workspace_id=workspace_id, source_id=source_id)
    except Exception as exc:
        raise GateContractError("object_scope_invalid") from exc


async def _call_upload(
    target: Callable[..., object],
    fixture: SyntheticFixture,
    *,
    scope: Mapping[str, str],
    run_id: str,
    idempotency_key: str,
    timeout_seconds: float,
) -> object:
    kwargs = {
        "filename": fixture.filename,
        "display_filename": fixture.filename,
        "collection_id": scope["collection_id"],
        "workspace_id": scope["workspace_id"],
        "tenant_id": scope["tenant_id"],
        "request_id": f"golden-{run_id}",
        "correlation_id": f"golden-{run_id}",
        "idempotency_key": idempotency_key,
        "operation": "ingest",
    }
    return await _invoke(target, fixture.content, timeout=timeout_seconds, **kwargs)


async def _get_job(queue: object, scope: Mapping[str, str], idempotency_key: str, timeout: float) -> object:
    target = _operation(queue, ("get_by_idempotency",))
    if target is None:
        raise GateContractError("queue_idempotency_read_missing")
    return await _invoke(
        target,
        timeout=timeout,
        tenant_id=scope["tenant_id"],
        workspace_id=scope["workspace_id"],
        collection_id=scope["collection_id"],
        idempotency_key=idempotency_key,
    )


def _job_payload(job: object) -> Mapping[str, object]:
    payload = _read(job, "payload", {})
    return payload if isinstance(payload, Mapping) else {}


def _job_id(job: object) -> str | None:
    value = _read(job, "job_id", _read(job, "id", None))
    return _safe_identifier(value)


def _job_state(job: object) -> str:
    raw = _read(job, "status", _MISSING)
    if raw is _MISSING:
        raw = _read(job, "state", _MISSING)
    if raw is _MISSING:
        raw = _read(job, "contract_state", _MISSING)
    return str(raw).strip().casefold() if raw is not _MISSING and raw is not None else ""


def _payload_digest(payload: Mapping[str, object]) -> str:
    try:
        encoded = json.dumps(dict(payload), sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    except Exception:
        encoded = repr(sorted(str(key) for key in payload)).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _require_scope(value: object, scope: Mapping[str, str]) -> bool:
    return all(_read(value, field, None) == expected for field, expected in scope.items())


async def _check_upload_and_object(
    runtime: GoldenRuntime,
    fixture: SyntheticFixture,
    *,
    scope: Mapping[str, str],
    run_id: str,
    timeout_seconds: float,
) -> tuple[list[GateResult], object | None, Mapping[str, object], object | None]:
    results: list[GateResult] = []
    idempotency_key = f"golden-{run_id}"
    upload_target = _operation(runtime.upload, ("submit_upload", "upload"))
    if upload_target is None:
        return [GateResult("upload", FAIL, "upload_operation_missing")], None, {}, None
    try:
        uploaded = await _call_upload(
            upload_target,
            fixture,
            scope=scope,
            run_id=run_id,
            idempotency_key=idempotency_key,
            timeout_seconds=timeout_seconds,
        )
        results.append(GateResult("upload", PASS, "upload_accepted"))
    except Exception as exc:
        return [GateResult("upload", FAIL, _safe_error(exc))], None, {}, None

    try:
        job = await _get_job(runtime.queue, scope, idempotency_key, timeout_seconds)
        if job is None:
            raise GateBlocked("durable_job_not_found")
        payload = _job_payload(job)
        required = ("object_key", "object_source_id", "checksum", "byte_size")
        if any(not payload.get(name) and payload.get(name) != 0 for name in required):
            raise GateContractError("durable_job_payload_incomplete")
        byte_size = payload.get("byte_size")
        if isinstance(byte_size, str) and byte_size.isdecimal():
            byte_size = int(byte_size)
        if payload.get("checksum") != fixture.checksum or byte_size != len(fixture.content):
            raise GateContractError("durable_job_payload_integrity_mismatch")
        uploaded_job_id = _job_id(uploaded)
        durable_job_id = _job_id(job)
        if uploaded_job_id and durable_job_id and uploaded_job_id != durable_job_id:
            raise GateContractError("upload_job_identity_mismatch")
        results.append(GateResult("durable_job", PASS, "durable_job_persisted", {"state": _job_state(job)}))
    except Exception as exc:
        return results + [GateResult("durable_job", BLOCKED_EXTERNAL if isinstance(exc, GateBlocked) else FAIL, _safe_error(exc))], None, {}, None

    try:
        replayed = await _call_upload(
            upload_target,
            fixture,
            scope=scope,
            run_id=run_id,
            idempotency_key=idempotency_key,
            timeout_seconds=timeout_seconds,
        )
        replay_job_id = _job_id(replayed)
        if durable_job_id and replay_job_id and durable_job_id != replay_job_id:
            raise GateContractError("idempotency_created_second_job")
        replay_job = await _get_job(runtime.queue, scope, idempotency_key, timeout_seconds)
        if _job_id(replay_job) != durable_job_id or _payload_digest(_job_payload(replay_job)) != _payload_digest(payload):
            raise GateContractError("idempotency_replay_changed_job")
        results.append(GateResult("upload_idempotency", PASS, "same_key_reused_same_job"))
    except Exception as exc:
        results.append(GateResult("upload_idempotency", FAIL, _safe_error(exc)))

    object_key = payload.get("object_key")
    source_id = payload.get("object_source_id")
    if not isinstance(object_key, str) or not object_key.strip() or not isinstance(source_id, str) or not source_id.strip():
        return results + [GateResult("object", FAIL, "object_reference_invalid")], job, payload, uploaded
    object_scope = _make_object_scope(scope["tenant_id"], scope["workspace_id"], source_id)
    head_target = _operation(runtime.object_store, ("head",))
    get_target = _operation(runtime.object_store, ("get", "read"))
    if head_target is None or get_target is None:
        return results + [GateResult("object", BLOCKED_EXTERNAL, "object_read_operations_missing")], job, payload, uploaded
    try:
        metadata = await _invoke(head_target, object_scope, object_key, timeout=timeout_seconds)
        if not _require_scope(metadata, {
            "tenant_id": scope["tenant_id"],
            "workspace_id": scope["workspace_id"],
            "source_id": source_id,
        }):
            raise GateContractError("object_scope_mismatch")
        if _read(metadata, "size", None) != len(fixture.content) or _read(metadata, "checksum", None) != fixture.checksum:
            raise GateContractError("object_metadata_integrity_mismatch")
        stored = await _invoke(get_target, object_scope, object_key, max_bytes=MAX_FIXTURE_BYTES, timeout=timeout_seconds)
        if not isinstance(stored, bytes) or stored != fixture.content:
            raise GateContractError("object_read_integrity_mismatch")
        results.append(GateResult("object", PASS, "object_head_and_get_verified", {"size": len(stored)}))
    except Exception as exc:
        results.append(GateResult(
            "object",
            BLOCKED_EXTERNAL if isinstance(exc, GateBlocked) else FAIL,
            _safe_error(exc),
        ))
    return results, job, payload, uploaded


async def _refresh_job(runtime: GoldenRuntime, scope: Mapping[str, str], idempotency_key: str, timeout: float) -> object:
    return await _get_job(runtime.queue, scope, idempotency_key, timeout)


async def _drive_worker(
    runtime: GoldenRuntime,
    *,
    scope: Mapping[str, str],
    idempotency_key: str,
    timeout_seconds: float,
) -> tuple[GateResult, object | None]:
    target = _operation(runtime.worker, ("run_once", "run_forever", "process", "execute"))
    if target is None:
        return GateResult("worker", BLOCKED_EXTERNAL, "worker_operation_missing"), None
    deadline = time.monotonic() + timeout_seconds
    last_job: object | None = None
    polls = 0
    operation_name = _operation_name(runtime.worker, ("run_once", "run_forever", "process", "execute"))
    try:
        if operation_name == "run_forever":
            await _invoke(target, max_runtime_seconds=max(0.1, timeout_seconds), timeout=timeout_seconds + 1.0)
            last_job = await _refresh_job(runtime, scope, idempotency_key, timeout_seconds)
        else:
            while polls < MAX_WORKER_POLLS and time.monotonic() < deadline:
                polls += 1
                await _invoke(
                    target,
                    job_id=_job_id(last_job),
                    tenant_id=scope["tenant_id"],
                    workspace_id=scope["workspace_id"],
                    collection_id=scope["collection_id"],
                    wait=False,
                    timeout_seconds=min(timeout_seconds, max(0.1, deadline - time.monotonic())),
                    timeout=min(timeout_seconds, max(0.1, deadline - time.monotonic())),
                )
                last_job = await _refresh_job(runtime, scope, idempotency_key, timeout_seconds)
                state = _job_state(last_job)
                if state in _SUCCESS_STATES or state in _TERMINAL_FAILURES:
                    break
                if polls < MAX_WORKER_POLLS and time.monotonic() < deadline:
                    await asyncio.sleep(0.01)
        state = _job_state(last_job)
        if state in _SUCCESS_STATES:
            return GateResult("worker", PASS, "durable_job_processed_and_published", {"polls": polls, "state": state}), last_job
        if state in _TERMINAL_FAILURES:
            return GateResult("worker", FAIL, "durable_job_terminal_failure", {"polls": polls, "state": state}), last_job
        return GateResult("worker", FAIL, "worker_deadline_without_publish", {"polls": polls, "state": state}), last_job
    except Exception as exc:
        return GateResult("worker", FAIL, _safe_error(exc), {"polls": polls}), last_job


def _document_id(job: object | None, uploaded: object | None) -> str | None:
    for value in (job, uploaded):
        if value is None:
            continue
        direct = _read(value, "document_id", None)
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        result = _mapping(_read(value, "result", None))
        nested = result.get("document_id")
        if isinstance(nested, str) and nested.strip():
            return nested.strip()
        payload = _job_payload(value)
        nested = payload.get("document_id")
        if isinstance(nested, str) and nested.strip():
            return nested.strip()
    return None


async def _get_document(knowledge: object, document_id: str, scope: Mapping[str, str], timeout: float) -> object:
    target = _operation(knowledge, ("get_document",))
    if target is None:
        raise GateContractError("knowledge_document_read_missing")
    return await _invoke(
        target,
        document_id,
        tenant_id=scope["tenant_id"],
        workspace_id=scope["workspace_id"],
        timeout=timeout,
    )


async def _get_chunks(knowledge: object, document_id: str, scope: Mapping[str, str], timeout: float) -> object:
    target = _operation(knowledge, ("get_chunks",))
    if target is None:
        raise GateContractError("knowledge_chunk_read_missing")
    return await _invoke(
        target,
        document_id,
        tenant_id=scope["tenant_id"],
        workspace_id=scope["workspace_id"],
        timeout=timeout,
    )


def _sequence(value: object) -> list[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return []


def _lineage_value(value: object, name: str) -> object:
    aliases = {
        "checksum": ("checksum", "content_checksum", "document_checksum"),
        "document_version": ("document_version", "version"),
        "object_ref": ("object_ref", "object_key"),
    }.get(name, (name,))
    for alias in aliases:
        direct = _read(value, alias, _MISSING)
        if direct is not _MISSING and direct is not None and str(direct).strip():
            return direct
    metadata = _read(value, "metadata", None)
    if isinstance(metadata, Mapping):
        for alias in aliases + (name,):
            direct = metadata.get(alias, _MISSING)
            if direct is not _MISSING and direct is not None and str(direct).strip():
                return direct
    return None


def _nonempty(value: object) -> bool:
    return (
        isinstance(value, (str, int, float, datetime))
        and not isinstance(value, bool)
        and bool(str(value).strip())
    )


def _lineage_snapshot(value: object | None) -> Mapping[str, object]:
    if value is None:
        return {}
    for name in ("snapshot", "read", "resolve"):
        target = getattr(value, name, None)
        if callable(target):
            try:
                value = _run_awaitable(target())
            except Exception:
                return {}
            break
    else:
        if callable(value):
            try:
                value = _run_awaitable(value())
            except Exception:
                return {}
    raw = _mapping(value)
    if isinstance(raw.get("lineage"), Mapping):
        return raw["lineage"]  # type: ignore[return-value]
    return raw


def check_lineage(
    document: object,
    chunks: Sequence[object],
    *,
    scope: Mapping[str, str],
    lineage: Mapping[str, object] | None = None,
    vector_projection: object | None = None,
) -> tuple[GateResult, dict[str, object]]:
    """Check exact lineage and cross-projection consistency.

    ``verified_at`` is mandatory in the injected snapshot.  This deliberately
    exposes the current model gap instead of treating ``published_at`` as a
    verification timestamp.
    """

    supplied = dict(lineage or {})
    observed: dict[str, object] = {}
    for field in LINEAGE_FIELDS:
        value = supplied.get(field, _lineage_value(document, field))
        if value is None and chunks:
            value = _lineage_value(chunks[0], field)
        observed[field] = value
    missing = [field for field, value in observed.items() if not _nonempty(value)]
    if missing:
        return GateResult("lineage.complete", FAIL, "lineage_fields_missing", {"missing": missing}), observed
    if not _require_scope(document, scope):
        return GateResult("lineage.scope", FAIL, "document_scope_mismatch"), observed
    if _lineage_value(document, "document_id") != observed["document_id"]:
        return GateResult("lineage.document", FAIL, "document_identity_mismatch"), observed
    for chunk in chunks:
        if _read(chunk, "document_id", None) != observed["document_id"] or _read(chunk, "tenant_id", None) != scope["tenant_id"]:
            return GateResult("lineage.chunks", FAIL, "chunk_scope_or_document_mismatch"), observed
        for field in ("parser_version", "chunker_version", "embedding_version"):
            chunk_value = _lineage_value(chunk, field)
            if chunk_value is not None and chunk_value != observed[field]:
                return GateResult("lineage.chunks", FAIL, "chunk_version_mismatch"), observed
    if vector_projection is not None:
        projection_fields = (
            "document_id", "document_version", "checksum", "ingestion_version",
            "parser_version", "chunker_version", "embedding_version", "index_version",
            "object_ref", "created_at", "published_at",
        )
        chunk_checksums = {
            _lineage_value(chunk, "checksum") for chunk in chunks
            if _nonempty(_lineage_value(chunk, "checksum"))
        }
        for field in projection_fields:
            vector_value = _lineage_value(vector_projection, field)
            if not _nonempty(vector_value):
                return GateResult("lineage.vector", FAIL, "vector_lineage_field_missing"), observed
            if field == "checksum":
                if vector_value not in ({observed[field]} | chunk_checksums):
                    return GateResult("lineage.vector", FAIL, "vector_checksum_mismatch"), observed
                continue
            if vector_value != observed[field]:
                return GateResult("lineage.vector", FAIL, "vector_lineage_mismatch"), observed
    return GateResult("lineage.complete", PASS, "lineage_fields_and_scope_consistent", {"fields": len(observed), "chunks": len(chunks)}), observed


def check_failed_version_invariant(case: object, baseline: Mapping[str, object]) -> GateResult:
    """Prove a failed replacement cannot replace the last verified version."""

    if not isinstance(baseline, Mapping) or not baseline.get("document_version") or not baseline.get("checksum"):
        return GateResult("invariant.failed_version_never_replaces_verified", FAIL, "baseline_lineage_incomplete")
    raw = _mapping(case)
    injected = raw.get("injected", raw.get("fault_injected", _MISSING))
    failed = raw.get("failed", raw.get("failure_observed", _MISSING))
    preserved = raw.get("last_verified_preserved", raw.get("verified_version_preserved", _MISSING))
    published_version = raw.get("published_version", raw.get("active_document_version", _MISSING))
    published_checksum = raw.get("published_checksum", raw.get("active_checksum", _MISSING))
    replacement_published = raw.get("new_version_published", raw.get("replacement_published", False))
    replayed = raw.get(
        "replay_verified",
        raw.get("replayed", raw.get("recovery_verified", raw.get("rollback_verified", _MISSING))),
    )
    if injected is not True or failed is not True:
        return GateResult("invariant.failed_version_never_replaces_verified", FAIL, "failure_not_injected_and_observed")
    if preserved is not True:
        return GateResult("invariant.failed_version_never_replaces_verified", FAIL, "verified_baseline_not_explicitly_preserved")
    if published_version is _MISSING or published_checksum is _MISSING:
        return GateResult("invariant.failed_version_never_replaces_verified", FAIL, "post_failure_verified_snapshot_missing")
    if replayed is not True:
        return GateResult("invariant.failed_version_never_replaces_verified", FAIL, "rollback_replay_not_verified")
    if replacement_published is True:
        return GateResult("invariant.failed_version_never_replaces_verified", FAIL, "failed_replacement_published")
    if published_version is not _MISSING and published_version != baseline.get("document_version"):
        return GateResult("invariant.failed_version_never_replaces_verified", FAIL, "published_version_changed")
    if published_checksum is not _MISSING and published_checksum != baseline.get("checksum"):
        return GateResult("invariant.failed_version_never_replaces_verified", FAIL, "published_checksum_changed")
    return GateResult("invariant.failed_version_never_replaces_verified", PASS, "verified_baseline_preserved")


def evaluate_failure_matrix(
    raw_matrix: object,
    baseline: Mapping[str, object],
) -> tuple[dict[str, GateResult], bool]:
    """Evaluate all eleven declared failure boundaries; missing rows never pass."""

    if callable(raw_matrix):
        try:
            raw_matrix = _run_awaitable(raw_matrix())
        except Exception:
            raw_matrix = None
    if not isinstance(raw_matrix, Mapping):
        return {
            point: GateResult(f"failure_matrix.{point}", BLOCKED_EXTERNAL, "failure_matrix_not_available")
            for point in FAILURE_POINTS
        }, False
    rows: dict[str, GateResult] = {}
    all_pass = True
    for point in FAILURE_POINTS:
        raw = raw_matrix.get(point, _MISSING)
        if raw is _MISSING:
            rows[point] = GateResult(f"failure_matrix.{point}", NOT_RUN, "failure_boundary_not_executed")
            all_pass = False
            continue
        result = _normalise_status(_read(raw, "status", _MISSING))
        if result != PASS:
            rows[point] = GateResult(f"failure_matrix.{point}", result if result in {FAIL, BLOCKED_EXTERNAL, NOT_RUN} else FAIL, "fault_case_not_passed")
            all_pass = False
            continue
        invariant = check_failed_version_invariant(raw, baseline)
        if invariant.result != PASS:
            rows[point] = GateResult(f"failure_matrix.{point}", FAIL, invariant.detail)
            all_pass = False
        else:
            rows[point] = GateResult(f"failure_matrix.{point}", PASS, "fault_recovery_and_lineage_invariant_verified")
    return rows, all_pass


def _trace_events(value: object | None) -> list[object]:
    if value is None:
        return []
    target = value
    for name in ("snapshot", "events", "read"):
        method = getattr(target, name, None)
        if callable(method):
            try:
                target = _run_awaitable(method())
            except Exception:
                return []
            break
    else:
        if callable(target):
            try:
                target = _run_awaitable(target())
            except Exception:
                return []
    if isinstance(target, Mapping):
        for key in ("events", "stages", "trace"):
            if key in target:
                return _sequence(target[key])
    return _sequence(target)


def _canonical_stage(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().casefold().replace("-", "_").replace(" ", "_")
    aliases = {
        "object_store": "object", "object_storage": "object", "durable_job": "durable_job",
        "enqueue": "durable_job", "job": "durable_job", "extraction": "parse", "parsing": "parse",
        "normalization": "normalize", "chunking": "chunk", "embedding": "embed", "qdrant_upsert": "qdrant",
        "index": "qdrant", "verification": "verify", "publication": "publish", "retrieval": "retrieve",
        "evidencing": "evidence", "generation": "professor", "answer": "response",
    }
    text = aliases.get(text, text)
    return text if text in PATH_STAGES else None


def check_stage_trace(stage_trace: object | None) -> GateResult:
    events = _trace_events(stage_trace)
    observed: list[str] = []
    failed: set[str] = set()
    incomplete_status: set[str] = set()
    for event in events:
        stage = _canonical_stage(_read(event, "stage", _read(event, "name", event)))
        if stage is None:
            continue
        event_status = _status_of(event)
        if event_status in _TERMINAL_FAILURES or event_status in {"fail", "failed", "error"}:
            failed.add(stage)
        elif event_status not in {"pass", "ok", "success", "succeeded", "complete", "completed", "published", "verified", "processed"}:
            incomplete_status.add(stage)
        if stage not in observed:
            observed.append(stage)
    missing = [stage for stage in PATH_STAGES if stage not in observed]
    if failed:
        return GateResult("stage_trace", FAIL, "stage_failure_observed", {"failed": sorted(failed), "observed_count": len(observed)})
    if incomplete_status:
        return GateResult("stage_trace", FAIL, "stage_status_not_successful", {"stages": sorted(incomplete_status)})
    if missing:
        return GateResult("stage_trace", FAIL, "stage_observation_incomplete", {"missing": missing, "observed_count": len(observed)})
    positions = [observed.index(stage) for stage in PATH_STAGES]
    if positions != sorted(positions):
        return GateResult("stage_trace", FAIL, "stage_order_invalid", {"observed_count": len(observed)})
    return GateResult("stage_trace", PASS, "all_path_stages_observed_in_order", {"observed_count": len(observed)})


async def _embedding_for_query(embeddings: object, query: str, timeout: float) -> object:
    target = _operation(embeddings, ("embed_query", "embed", "encode"))
    if target is None:
        raise GateContractError("query_embedding_operation_missing")
    operation_name = _operation_name(embeddings, ("embed_query", "embed", "encode"))
    argument: object = query if operation_name in {"embed_query", "encode"} else [query]
    result = await _invoke(target, argument, timeout=timeout)
    if isinstance(result, Sequence) and not isinstance(result, (str, bytes, bytearray)):
        if result and isinstance(result[0], (int, float)):
            return list(result)
        if len(result) == 1 and isinstance(result[0], Sequence):
            return list(result[0])
    raise GateContractError("query_embedding_invalid")


def _candidate_items(value: object) -> list[object]:
    if isinstance(value, Mapping):
        for key in ("evidence", "candidates", "items", "results"):
            items = _sequence(value.get(key))
            if items:
                return items
    for key in ("evidence", "candidates", "items", "results"):
        items = _sequence(_read(value, key, None))
        if items:
            return items
    return []


def _bundle_items(bundle: object) -> list[object]:
    return _sequence(_read(bundle, "evidence", None))


def _bundle_id(bundle: object) -> str | None:
    return _safe_identifier(_read(bundle, "bundle_id", _read(bundle, "id", None)))


def _evidence_id(item: object) -> str | None:
    return _safe_identifier(_read(item, "evidence_id", _read(item, "id", None)))


def _validate_evidence_bundle(
    bundle: object,
    evidence: object,
    scope: Mapping[str, str],
    expected_version: str,
    *,
    document_id: object | None = None,
    checksum: object | None = None,
    chunk_ids: set[object] | None = None,
    chunk_checksums: Mapping[object, object] | None = None,
) -> GateResult:
    if bundle is None or not _bundle_items(bundle):
        return GateResult("evidence", FAIL, "evidence_bundle_empty")
    if not _bundle_id(bundle) or not _bundle_id(bundle).startswith("eb_"):
        return GateResult("evidence", FAIL, "evidence_bundle_id_invalid")
    issued_ids: list[str] = []
    for item in _bundle_items(bundle):
        if not _require_scope(item, scope):
            return GateResult("evidence", FAIL, "evidence_scope_mismatch")
        if document_id is not None and _read(item, "document_id", None) != document_id:
            return GateResult("evidence", FAIL, "evidence_document_identity_mismatch")
        if _read(item, "document_version", None) != expected_version:
            return GateResult("evidence", FAIL, "evidence_stale_document_version")
        if chunk_ids is not None and _read(item, "chunk_id", None) not in chunk_ids:
            return GateResult("evidence", FAIL, "evidence_unknown_chunk")
        item_checksum = _read(item, "checksum", None)
        if checksum is not None and item_checksum != checksum:
            # Canonical payloads use a chunk checksum for an evidence excerpt,
            # while the document lineage uses the full object checksum.
            # Either is safe only when the chunk checksum is the authoritative
            # value for the exact cited chunk.
            expected_chunk_checksum = (
                chunk_checksums.get(_read(item, "chunk_id", None), _MISSING)
                if chunk_checksums is not None else _MISSING
            )
            if expected_chunk_checksum is _MISSING or item_checksum != expected_chunk_checksum:
                return GateResult("evidence", FAIL, "evidence_checksum_mismatch")
        if not _read(item, "checksum", None) or not _read(item, "document_id", None) or not _read(item, "chunk_id", None):
            return GateResult("evidence", FAIL, "evidence_provenance_incomplete")
        evidence_id = _evidence_id(item)
        if not evidence_id or not evidence_id.startswith("ev_"):
            return GateResult("evidence", FAIL, "evidence_id_invalid")
        issued_ids.append(evidence_id)
    citation_map = _read(bundle, "citation_map", None)
    if isinstance(citation_map, Mapping):
        expected_map = {identifier: f"[cite:{identifier}]" for identifier in issued_ids}
        if dict(citation_map) != expected_map:
            return GateResult("evidence", FAIL, "citation_map_invalid")
    return GateResult("evidence", PASS, "server_issued_bundle_matches_lineage", {"items": len(issued_ids)})


async def _retrieve_evidence(
    runtime: GoldenRuntime,
    fixture: SyntheticFixture,
    *,
    scope: Mapping[str, str],
    document: object,
    chunks: Sequence[object],
    document_version: str,
    checksum: str,
    timeout: float,
) -> tuple[list[GateResult], object | None, list[object]]:
    results: list[GateResult] = []
    retrieval_target = _operation(runtime.retrieval, ("retrieve",))
    if retrieval_target is None:
        return [GateResult("retrieve", FAIL, "retrieval_operation_missing")], None, []
    context = {
        "tenant_id": scope["tenant_id"],
        "workspace_id": scope["workspace_id"],
        "allowed_collection_ids": [scope["collection_id"]],
        "permissions": ["golden_runtime"],
    }
    try:
        retrieved = await _invoke(retrieval_target, query=fixture.query, context=context, timeout=timeout)
        candidates = _candidate_items(retrieved)
        chunk_checksums = {
            _read(chunk, "chunk_id", None): _lineage_value(chunk, "checksum")
            for chunk in chunks
        }
        matches = [
            candidate for candidate in candidates
            if _read(candidate, "document_id", None) == _read(document, "document_id", None)
            and _read(candidate, "tenant_id", scope["tenant_id"]) == scope["tenant_id"]
            and _read(candidate, "workspace_id", scope["workspace_id"]) == scope["workspace_id"]
            and _read(candidate, "collection_id", scope["collection_id"]) == scope["collection_id"]
            and _read(candidate, "document_version", None) == document_version
            and _read(candidate, "checksum", _read(candidate, "content_checksum", None)) in (
                {checksum} | {value for value in chunk_checksums.values() if value}
            )
            and _read(candidate, "chunk_id", None) in {
                chunk_id for chunk_id in chunk_checksums
            }
            and _read(candidate, "checksum", _read(candidate, "content_checksum", None))
            == chunk_checksums.get(_read(candidate, "chunk_id", None), checksum)
        ]
        if not matches:
            raise GateContractError("retrieval_did_not_return_published_version")
        results.append(GateResult("retrieve", PASS, "retrieval_scope_and_version_verified", {"candidates": len(candidates)}))
    except Exception as exc:
        return [GateResult("retrieve", FAIL, _safe_error(exc))], None, []

    evidence_target = _operation(runtime.evidence, ("build_bundle", "issue", "validate", "validate_bundle"))
    if evidence_target is None:
        return results + [GateResult("evidence", FAIL, "evidence_operation_missing")], None, candidates
    try:
        # The canonical EvidenceValidator accepts these names.  Custom
        # adapters can expose a narrower signature; _invoke filters only
        # declared names and never retries a failed call with a different shape.
        bundle = await _invoke(
            evidence_target,
            query=fixture.query,
            candidates=matches,
            scope=dict(scope),
            document_version=document_version,
            expected_scope=dict(scope),
            timeout=timeout,
        )
        if _operation_name(runtime.evidence, ("validate_bundle",)) == "validate_bundle":
            # A validator-only adapter returns a report, not a bundle.  It is
            # not enough to claim the evidence stage; the composition must
            # expose an issuing build operation.
            raise GateContractError("evidence_builder_missing")
        validation = _validate_evidence_bundle(
            bundle,
            runtime.evidence,
            scope,
            document_version,
            document_id=_read(document, "document_id", None),
            checksum=checksum,
            chunk_ids={_read(chunk, "chunk_id", None) for chunk in chunks},
            chunk_checksums=chunk_checksums,
        )
        if validation.result != PASS:
            raise GateContractError(validation.detail)
        validator_target = _operation(runtime.evidence, ("validate_bundle",))
        if validator_target is None:
            raise GateContractError("evidence_validation_operation_missing")
        validation_report = await _invoke(
            validator_target,
            bundle,
            expected_scope=dict(scope),
            timeout=timeout,
        )
        if _read(validation_report, "valid", None) is not True:
            raise GateContractError("evidence_bundle_validation_failed")
        results.append(validation)
        return results, bundle, candidates
    except Exception as exc:
        return results + [GateResult("evidence", FAIL, _safe_error(exc))], None, candidates


def _candidate_for_negative(candidate: object) -> dict[str, object]:
    """Copy only provenance fields needed by the evidence negative tests."""

    names = (
        "evidence_id", "tenant_id", "workspace_id", "collection_id", "document_id",
        "document_version", "chunk_id", "source", "text", "checksum", "page_start",
        "page_end", "section", "retrieval_score", "reranking_score", "score",
    )
    return {name: _read(candidate, name, None) for name in names if _read(candidate, name, None) is not None}


def _evidence_issuer(target: object) -> Callable[..., object] | None:
    return _operation(target, ("issue", "issue_evidence"))


def _negative_rejected(value: object, *, expected_name: str, supplied: object | None = None) -> bool:
    """Accept an explicit rejection or an exception; never accept silence."""

    if isinstance(value, Mapping):
        if value.get("rejected") is True or value.get("accepted") is False:
            return True
        if expected_name == "FORGED_EVIDENCE_ID_REJECTED":
            returned = value.get("evidence_id")
            return supplied is not None and returned != supplied
    if expected_name == "FORGED_EVIDENCE_ID_REJECTED":
        returned = _evidence_id(value)
        return supplied is not None and returned != supplied
    return False


async def _run_evidence_negatives(
    runtime: GoldenRuntime,
    *,
    candidate: object,
    scope: Mapping[str, str],
    document_version: str,
    timeout: float,
) -> list[GateResult]:
    """Exercise the five declared evidence rejection boundaries.

    An authoritative resolver is mandatory for checksum and unknown-chunk
    negatives.  A validator that merely sanitizes or silently replaces a bad
    value does not pass a rejection assertion.
    """

    issuer = _evidence_issuer(runtime.evidence)
    if issuer is None:
        return [GateResult(f"evidence_negative.{name}", BLOCKED_EXTERNAL, "evidence_issuer_missing") for name in (
            "FORGED_EVIDENCE_ID_REJECTED", "CROSS_TENANT_EVIDENCE_REJECTED",
            "STALE_DOCUMENT_VERSION_REJECTED", "WRONG_CHECKSUM_REJECTED", "UNKNOWN_CHUNK_REJECTED",
        )]
    validator = _read(runtime.evidence, "validator", runtime.evidence)
    authority = _read(validator, "authority", None)
    if not callable(getattr(authority, "resolve", None)):
        return [GateResult(f"evidence_negative.{name}", BLOCKED_EXTERNAL, "authoritative_evidence_resolver_missing") for name in (
            "FORGED_EVIDENCE_ID_REJECTED", "CROSS_TENANT_EVIDENCE_REJECTED",
            "STALE_DOCUMENT_VERSION_REJECTED", "WRONG_CHECKSUM_REJECTED", "UNKNOWN_CHUNK_REJECTED",
        )]
    base = _candidate_for_negative(candidate)
    forged = dict(base)
    forged_id = "ev_" + ("f" * 32)
    forged["evidence_id"] = forged_id
    stale = dict(base)
    stale["document_version"] = "stale-" + document_version[:32]
    wrong_checksum = dict(base)
    wrong_checksum["checksum"] = "sha256:" + ("0" * 64)
    cross_tenant = dict(base)
    cross_tenant["tenant_id"] = "golden-other-tenant"
    unknown_chunk = dict(base)
    unknown_chunk["chunk_id"] = "unknown-chunk-" + document_version[:12]
    cases = (
        ("FORGED_EVIDENCE_ID_REJECTED", forged, forged_id, document_version),
        ("CROSS_TENANT_EVIDENCE_REJECTED", cross_tenant, None, document_version),
        ("STALE_DOCUMENT_VERSION_REJECTED", stale, None, document_version),
        ("WRONG_CHECKSUM_REJECTED", wrong_checksum, None, document_version),
        ("UNKNOWN_CHUNK_REJECTED", unknown_chunk, None, document_version),
    )
    results: list[GateResult] = []
    for name, mutated, supplied, expected_version in cases:
        try:
            value = await _invoke(
                issuer,
                mutated,
                scope=dict(scope),
                document_version=expected_version,
                timeout=timeout,
            )
        except Exception:
            results.append(GateResult(f"evidence_negative.{name}", PASS, name.lower()))
        else:
            if _negative_rejected(value, expected_name=name, supplied=supplied):
                results.append(GateResult(f"evidence_negative.{name}", PASS, name.lower()))
            else:
                results.append(GateResult(f"evidence_negative.{name}", FAIL, "invalid_evidence_was_accepted"))
    return results


def _response_text(value: object) -> str | None:
    for name in ("answer", "response", "content", "text", "message"):
        candidate = _read(value, name, None)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _decision_action(value: object) -> str | None:
    action = _read(value, "action", None)
    if action is None:
        return None
    raw = getattr(action, "value", action)
    return str(raw).strip().upper() if raw is not None else None


_CITATION_SUPPORT_FIELDS = (
    "citation_precision",
    "citation_recall",
    "citation_completeness",
    "unsupported_claim_rate",
    "faithfulness",
)


def _bounded_observed_signal(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        return None
    return number


def _citation_support_metric_value(value: object) -> float | None:
    if isinstance(value, Mapping):
        value = value.get("value", _MISSING)
    return _bounded_observed_signal(value)


def _citation_support_observation(value: object) -> tuple[dict[str, object] | None, str | None]:
    """Extract a bound, observed claim-support result from runtime output.

    A scalar ``citation_support`` value is intentionally ignored.  The gate
    accepts either the flat response metadata contract or the evaluator's
    nested metric shape, but always requires all five metrics, a PASS status,
    a positive claim count and an explicit source.
    """

    payload = _mapping(value)
    containers: list[Mapping[str, object]] = []
    metadata = payload.get("metadata")
    if isinstance(metadata, Mapping):
        containers.append(metadata)
    containers.append(payload)
    candidates: list[Mapping[str, object]] = []
    for container in containers:
        for key in ("citation_support_metrics", "citation_support"):
            nested = container.get(key, _MISSING)
            if isinstance(nested, Mapping):
                candidates.append(nested)
        if any(key in container for key in _CITATION_SUPPORT_FIELDS):
            candidates.append(container)

    if not candidates:
        return None, "citation_support_metrics_missing"
    raw = candidates[0]
    status = raw.get("status", raw.get("citation_support_status", _MISSING))
    if not isinstance(status, str) or status.strip().upper() != PASS:
        return None, "citation_support_metrics_not_pass"

    normalized: dict[str, object] = {"status": PASS}
    for field in _CITATION_SUPPORT_FIELDS:
        observed = _citation_support_metric_value(raw.get(field, _MISSING))
        if observed is None:
            return None, "citation_support_metrics_incomplete"
        child = raw.get(field)
        if isinstance(child, Mapping):
            child_status = child.get("status")
            if child_status is not None and (
                not isinstance(child_status, str) or child_status.strip().upper() != PASS
            ):
                return None, "citation_support_metrics_not_pass"
        normalized[field] = observed

    evaluated_claims = raw.get(
        "evaluated_claims",
        raw.get("citation_evaluated_claims", raw.get("claim_count", _MISSING)),
    )
    if (
        isinstance(evaluated_claims, bool)
        or not isinstance(evaluated_claims, int)
        or not 1 <= evaluated_claims <= 10_000
    ):
        return None, "citation_support_claim_count_invalid"
    source = raw.get("source", raw.get("citation_support_source", _MISSING))
    if not isinstance(source, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,127}", source.strip()):
        return None, "citation_support_source_missing"
    normalized["evaluated_claims"] = evaluated_claims
    normalized["source"] = source.strip()
    return normalized, None


def _observed_retrieval_quality(candidates: Sequence[object], bundle: object) -> float | None:
    """Use a bounded score actually attached to an observed candidate."""

    values: list[float] = []
    for item in list(candidates) + list(_bundle_items(bundle)):
        for name in ("retrieval_quality_score", "confidence_score", "reranking_score", "score"):
            observed = _bounded_observed_signal(_read(item, name, _MISSING))
            if observed is not None:
                values.append(observed)
                break
    return max(values) if values else None


async def _run_downstream(
    runtime: GoldenRuntime,
    fixture: SyntheticFixture,
    *,
    scope: Mapping[str, str],
    bundle: object,
    candidates: Sequence[object],
    timeout: float,
    run_id: str,
) -> list[GateResult]:
    results: list[GateResult] = []
    professor_target = _operation(runtime.professor, ("generate", "run", "answer"))
    if professor_target is None:
        return [GateResult("professor", FAIL, "professor_operation_missing")]
    context = {
        "tenant_id": scope["tenant_id"],
        "workspace_id": scope["workspace_id"],
        "allowed_collection_ids": [scope["collection_id"]],
        "permissions": ["golden_runtime"],
    }
    try:
        professor_output = await _invoke(
            professor_target,
            message=fixture.query,
            query=fixture.query,
            context=context,
            retrieval_context=context,
            conversation_id=f"golden-{run_id}",
            evidence_bundle=bundle,
            evidence=bundle,
            candidates=candidates,
            timeout=timeout,
        )
        if _response_text(professor_output) is None:
            raise GateContractError("professor_response_empty")
        results.append(GateResult("professor", PASS, "professor_received_grounded_evidence"))
    except Exception as exc:
        return [GateResult("professor", FAIL, _safe_error(exc))]

    citation_support_metrics, citation_metrics_error = _citation_support_observation(professor_output)
    if citation_metrics_error is not None or citation_support_metrics is None:
        return results + [GateResult("decision.citation_support", FAIL, citation_metrics_error or "citation_support_metrics_missing")]
    retrieval_quality = _observed_retrieval_quality(candidates, bundle)
    if retrieval_quality is None:
        return results + [GateResult("decision.retrieval_quality", FAIL, "retrieval_quality_missing")]
    provider_signal = _bounded_observed_signal(
        _read(_read(professor_output, "metadata", {}), "provider_confidence_signal", _MISSING)
    )
    if provider_signal is None:
        return results + [GateResult("decision.provider_signal", FAIL, "provider_signal_missing")]

    decision_target = _operation(runtime.decision, ("decide", "evaluate"))
    if decision_target is None:
        return results + [GateResult("decision", FAIL, "decision_operation_missing")]
    decision_input: object = {
        "evidence_bundle": bundle,
        "tenant_id": scope["tenant_id"],
        "workspace_id": scope["workspace_id"],
        "collection_id": scope["collection_id"],
        "retrieval_quality": retrieval_quality,
        "evidence_count": len(_bundle_items(bundle)),
        "citation_support": min(
            citation_support_metrics["citation_precision"],
            citation_support_metrics["citation_recall"],
            citation_support_metrics["citation_completeness"],
            1.0 - citation_support_metrics["unsupported_claim_rate"],
        ),
        "citation_support_metrics": citation_support_metrics,
        "provider_confidence_signal": provider_signal,
        "retrieval_available": True,
        "integrity_ok": True,
        "policy_allows_answer": True,
        "retrieval_attempt": 0,
    }
    try:
        try:
            from rick_decision import (
                DecisionInput,
                DecisionLayer,
                DecisionPolicy,
                DomainRisk,
                IntentClarity,
                UserIntent,
            )
        except Exception as exc:
            raise GateContractError("decision_contract_unavailable") from exc
        decision_input["domain_risk"] = DomainRisk.LOW
        decision_input["user_intent"] = UserIntent(
            intent_code="golden_grounded_query",
            clarity=IntentClarity.CLEAR,
        )
        decision_input["policy"] = DecisionPolicy(
            min_retrieval_quality=0.50,
            min_citation_support=0.80,
            require_citation_support_metrics=True,
            min_citation_precision=0.80,
            min_citation_recall=0.80,
            min_citation_completeness=0.80,
            max_unsupported_claim_rate=0.0,
            min_faithfulness=0.80,
            require_faithfulness=True,
            required_citation_support_source="approved_claim_support",
            min_provider_confidence_signal=0.0,
            max_retrieval_attempts=0,
        )
        try:
            decision_input = DecisionInput(**decision_input)
        except Exception as exc:
            raise GateContractError("decision_input_invalid") from exc
        canonical_decision = DecisionLayer().decide(decision_input)
        if _decision_action(canonical_decision) != "ANSWER":
            raise GateContractError("decision_policy_rejected")
        decision = await _invoke(
            decision_target,
            decision_input,
            decision_input=decision_input,
            context=decision_input,
            evidence_bundle=bundle,
            timeout=timeout,
        )
        if _decision_action(decision) != "ANSWER":
            raise GateContractError("decision_did_not_answer")
        expected_bundle_id = _bundle_id(bundle)
        actual_bundle_id = _safe_identifier(_read(decision, "evidence_bundle_id", None))
        if expected_bundle_id and actual_bundle_id != expected_bundle_id:
            raise GateContractError("decision_bundle_identity_mismatch")
        results.append(GateResult("decision", PASS, "decision_answer_bound_to_bundle"))
    except Exception as exc:
        return results + [GateResult("decision", FAIL, _safe_error(exc))]

    response_target = _operation(runtime.response, ("render", "build", "format", "respond"))
    if response_target is None:
        return results + [GateResult("response", FAIL, "response_operation_missing")]
    try:
        response = await _invoke(
            response_target,
            professor_output=professor_output,
            draft=professor_output,
            decision=decision,
            evidence_bundle=bundle,
            evidence=bundle,
            context=context,
            timeout=timeout,
        )
        if _response_text(response) is None:
            raise GateContractError("final_response_empty")
        response_ids = _sequence(_read(response, "citations", None))
        issued_ids = {_evidence_id(item) for item in _bundle_items(bundle)}
        issued_ids.discard(None)
        for citation in response_ids:
            citation_id = _evidence_id(citation) or _read(citation, "citation_id", None)
            if citation_id is not None and citation_id not in issued_ids:
                raise GateContractError("response_citation_not_in_bundle")
        results.append(GateResult("response", PASS, "response_bound_to_decision_and_evidence"))
    except Exception as exc:
        results.append(GateResult("response", FAIL, _safe_error(exc)))
    return results


async def _run_fault_matrix(
    runtime: GoldenRuntime,
    fixture: SyntheticFixture,
    *,
    scope: Mapping[str, str],
    baseline: Mapping[str, object],
    run_id: str,
    timeout_seconds: float,
) -> tuple[list[GateResult], dict[str, object]]:
    target = _operation(runtime.failure_matrix, ("run", "execute", "inject"))
    if target is None:
        return [GateResult("failure_matrix", BLOCKED_EXTERNAL, "fault_injection_operation_missing")], {}
    matrix: dict[str, object] = {}
    results: list[GateResult] = []
    deadline = time.monotonic() + timeout_seconds
    for point in FAILURE_POINTS:
        if time.monotonic() >= deadline:
            results.append(GateResult(f"failure_matrix.{point}", FAIL, "failure_matrix_deadline_exceeded"))
            continue
        try:
            value = await _invoke(
                target,
                point=point,
                failure_point=point,
                fixture=fixture,
                scope=dict(scope),
                baseline=dict(baseline),
                run_id=f"{run_id}-{point}",
                timeout_seconds=min(timeout_seconds, max(0.1, deadline - time.monotonic())),
                timeout=min(timeout_seconds, max(0.1, deadline - time.monotonic())),
            )
            matrix[point] = value
        except Exception as exc:
            matrix[point] = {"status": FAIL, "error_code": _safe_error(exc)}
    evaluated, all_pass = evaluate_failure_matrix(matrix, baseline)
    results.extend(evaluated.values())
    return results, {
        "points": {point: result.to_dict() for point, result in evaluated.items()},
        "all_pass": all_pass,
    }


async def _execute_runtime_inner(
    runtime: GoldenRuntime,
    fixture: SyntheticFixture,
    *,
    run_id: str,
    timeout_seconds: float,
) -> tuple[list[GateResult], dict[str, object], dict[str, object]]:
    preflight = await _preflight(runtime, timeout_seconds)
    interface_results, interface_report = audit_interfaces(runtime)
    if preflight.result != PASS:
        # Authorization/availability is the external boundary.  Do not let
        # local contract diagnostics turn an unavailable environment into a
        # FAIL that could be mistaken for a runtime assertion.
        return [preflight], {"interfaces": interface_report}, {}
    results = interface_results + [preflight]
    if not fixture.bounded():
        return results + [GateResult("fixture", FAIL, "synthetic_fixture_invalid")], {"interfaces": interface_report}, {}
    scope = {
        "tenant_id": f"golden-tenant-{run_id[:12]}",
        "workspace_id": f"golden-workspace-{run_id[:12]}",
        "collection_id": f"golden-collection-{run_id[:12]}",
    }
    upload_results, initial_job, payload, uploaded = await _check_upload_and_object(
        runtime, fixture, scope=scope, run_id=run_id, timeout_seconds=timeout_seconds
    )
    results.extend(upload_results)
    if any(result.result != PASS for result in upload_results if result.name in {"upload", "durable_job", "object"}):
        return results, {"interfaces": interface_report, "scope": {"ids": {key: _short_digest(value) for key, value in scope.items()}}}, {}
    worker_result, final_job = await _drive_worker(
        runtime, scope=scope, idempotency_key=f"golden-{run_id}", timeout_seconds=timeout_seconds
    )
    results.append(worker_result)
    document_id = _document_id(final_job, uploaded)
    if worker_result.result != PASS or not document_id:
        results.append(GateResult("ingestion.persisted", FAIL, "published_document_identity_unavailable"))
        return results, {"interfaces": interface_report}, {}
    try:
        document = await _get_document(runtime.knowledge, document_id, scope, timeout_seconds)
        chunks_raw = await _get_chunks(runtime.knowledge, document_id, scope, timeout_seconds)
        chunks = _sequence(chunks_raw)
        if document is None or _status_of(document) != "published" or not chunks:
            raise GateContractError("published_document_or_chunks_missing")
        results.append(GateResult("ingestion.persisted", PASS, "published_document_and_chunks_present", {"chunks": len(chunks)}))
    except Exception as exc:
        results.append(GateResult("ingestion.persisted", FAIL, _safe_error(exc)))
        return results, {"interfaces": interface_report}, {}

    # A real Qdrant projection is required.  The composition must identify it
    # explicitly; class names are not treated as an authorization signal.
    metadata = dict(runtime.runtime_metadata or {})
    if metadata.get("vector_backend") != "qdrant":
        results.append(GateResult("qdrant.identity", BLOCKED_EXTERNAL, "qdrant_backend_not_explicitly_identified"))
        return results, {"interfaces": interface_report}, {}
    count_target = _operation(runtime.vector_store, ("count_for_document",))
    search_target = _operation(runtime.vector_store, ("search", "query"))
    if count_target is None or search_target is None:
        results.append(GateResult("qdrant", BLOCKED_EXTERNAL, "qdrant_count_operation_missing"))
        return results, {"interfaces": interface_report}, {}
    try:
        count = await _invoke(
            count_target,
            document_id,
            scope["collection_id"],
            collection_id=scope["collection_id"],
            tenant_id=scope["tenant_id"],
            workspace_id=scope["workspace_id"],
            timeout=timeout_seconds,
        )
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise GateContractError("qdrant_projection_empty")
        query_vector = await _embedding_for_query(runtime.embeddings, fixture.query, timeout_seconds)
        # QdrantHttpVectorStore takes the query vector positionally and owns
        # the ACL filter.  Custom adapters receive the same explicit scope.
        projection = await _invoke(
            search_target,
            query_vector,
            tenant_id=scope["tenant_id"],
            workspace_id=scope["workspace_id"],
            allowed_collection_ids=[scope["collection_id"]],
            limit=4,
            timeout=timeout_seconds,
        )
        projection_items = _sequence(projection)
        projection_match = next(
            (
                item for item in projection_items
                if _read(item, "document_id", None) == document_id
                and _read(item, "tenant_id", None) == scope["tenant_id"]
                and _read(item, "workspace_id", None) == scope["workspace_id"]
                and _read(item, "collection_id", None) == scope["collection_id"]
            ),
            None,
        )
        if projection_match is None:
            raise GateContractError("qdrant_search_did_not_return_published_document")
        results.append(GateResult("qdrant", PASS, "qdrant_projection_count_and_search_verified", {"points": count, "hits": len(projection_items)}))
    except Exception as exc:
        results.append(GateResult("qdrant", FAIL, _safe_error(exc)))
        return results, {"interfaces": interface_report}, {}

    lineage_snapshot = _lineage_snapshot(runtime.lineage)
    lineage_result, observed_lineage = check_lineage(
        document,
        chunks,
        scope=scope,
        lineage=lineage_snapshot,
        vector_projection=projection_match,
    )
    results.append(lineage_result)
    if lineage_result.result != PASS:
        return results, {"interfaces": interface_report}, {"lineage": observed_lineage}
    if observed_lineage.get("checksum") != fixture.checksum:
        results.append(GateResult("lineage.object", FAIL, "lineage_checksum_not_fixture_checksum"))
        return results, {"interfaces": interface_report}, {"lineage": observed_lineage}
    if payload.get("object_key") != observed_lineage.get("object_ref"):
        results.append(GateResult("lineage.object", FAIL, "lineage_object_ref_mismatch"))
        return results, {"interfaces": interface_report}, {"lineage": observed_lineage}
    document_version = str(observed_lineage["document_version"])
    retrieval_results, bundle, candidates = await _retrieve_evidence(
        runtime,
        fixture,
        scope=scope,
        document=document,
        chunks=chunks,
        document_version=document_version,
        checksum=str(observed_lineage["checksum"]),
        timeout=timeout_seconds,
    )
    results.extend(retrieval_results)
    if bundle is None or any(result.result != PASS for result in retrieval_results):
        return results, {"interfaces": interface_report}, {"lineage": observed_lineage}
    evidence_candidate = next(
        (
            candidate for candidate in candidates
            if _read(candidate, "document_id", None) == _read(document, "document_id", None)
            and _read(candidate, "document_version", None) == document_version
        ),
        None,
    )
    if evidence_candidate is None:
        results.append(GateResult("evidence_negative", FAIL, "negative_test_candidate_missing"))
        return results, {"interfaces": interface_report}, {"lineage": observed_lineage}
    negative_results = await _run_evidence_negatives(
        runtime,
        candidate=evidence_candidate,
        scope=scope,
        document_version=document_version,
        timeout=timeout_seconds,
    )
    results.extend(negative_results)
    if any(result.result != PASS for result in negative_results):
        return results, {"interfaces": interface_report}, {"lineage": observed_lineage}
    downstream_results = await _run_downstream(
        runtime,
        fixture,
        scope=scope,
        bundle=bundle,
        candidates=candidates,
        timeout=timeout_seconds,
        run_id=run_id,
    )
    results.extend(downstream_results)
    trace_result = check_stage_trace(runtime.stage_trace)
    results.append(trace_result)
    baseline = dict(observed_lineage)
    matrix_results, matrix_report = await _run_fault_matrix(
        runtime,
        fixture,
        scope=scope,
        baseline=baseline,
        run_id=run_id,
        timeout_seconds=timeout_seconds,
    )
    results.extend(matrix_results)
    details = {
        "interfaces": interface_report,
        "scope": {"ids": {key: _short_digest(value) for key, value in scope.items()}},
        "lineage": _lineage_report(observed_lineage),
        "failure_matrix": matrix_report,
        "fixture": {"bytes": len(fixture.content), "checksum": fixture.checksum},
    }
    return results, details, observed_lineage


async def _execute_runtime(
    runtime: GoldenRuntime,
    fixture: SyntheticFixture,
    *,
    run_id: str,
    timeout_seconds: float,
) -> tuple[list[GateResult], dict[str, object], dict[str, object]]:
    """Apply one wall-clock budget to the complete injected path."""

    token = _ACTIVE_DEADLINE.set(time.monotonic() + timeout_seconds)
    try:
        return await _execute_runtime_inner(
            runtime,
            fixture,
            run_id=run_id,
            timeout_seconds=timeout_seconds,
        )
    finally:
        _ACTIVE_DEADLINE.reset(token)


def _final_status(results: Sequence[GateResult], *, runtime: GoldenRuntime | None) -> str:
    if not results:
        return NOT_RUN
    if any(result.result == FAIL for result in results):
        return FAIL
    if any(result.result in {BLOCKED_EXTERNAL, NOT_RUN} for result in results):
        return BLOCKED_EXTERNAL
    if runtime is None or runtime.authorized is not True or runtime.external is not True:
        return BLOCKED_EXTERNAL
    if not all(result.result == PASS for result in results):
        return FAIL
    return PASS


def _lineage_report(values: Mapping[str, object] | None) -> dict[str, object]:
    observed = values or {}
    return {
        "required_fields": list(LINEAGE_FIELDS),
        "observed": {
            field: {
                "present": _nonempty(observed.get(field)),
                "digest": _short_digest(observed.get(field)) if _nonempty(observed.get(field)) else None,
            }
            for field in LINEAGE_FIELDS
        },
        "verified_at_is_distinct_requirement": True,
    }


def _failure_matrix_report(
    details: Mapping[str, object],
    results: Sequence[GateResult],
) -> dict[str, object]:
    raw = details.get("failure_matrix")
    if isinstance(raw, Mapping) and isinstance(raw.get("points"), Mapping):
        points = dict(raw["points"])
    else:
        composition = next((item for item in results if item.name == "runtime_composition"), None)
        preflight = next((item for item in results if item.name == "external_preflight"), None)
        not_available = composition is None or composition.result == BLOCKED_EXTERNAL or (
            preflight is not None and preflight.result == BLOCKED_EXTERNAL
        )
        fallback_status = BLOCKED_EXTERNAL if not_available else NOT_RUN
        points = {
            point: {
                "name": f"failure_matrix.{point}",
                "result": fallback_status,
                "detail": "failure_boundary_not_executed",
            }
            for point in FAILURE_POINTS
        }
    return {
        "expected_points": list(FAILURE_POINTS),
        "points": {point: points.get(point, {
            "name": f"failure_matrix.{point}",
            "result": NOT_RUN,
            "detail": "failure_boundary_not_executed",
        }) for point in FAILURE_POINTS},
        "all_pass": all(
            _read(points.get(point, {}), "result", None) == PASS
            for point in FAILURE_POINTS
        ),
        "invariant": "failed_version_never_replaces_last_verified_version",
    }


def _invariant_report(results: Sequence[GateResult], matrix: Mapping[str, object], lineage: Mapping[str, object] | None) -> dict[str, object]:
    matrix_points = matrix.get("points", {}) if isinstance(matrix, Mapping) else {}
    matrix_values = matrix_points.values() if isinstance(matrix_points, Mapping) else ()
    matrix_statuses = [_read(value, "result", None) for value in matrix_values]
    lineage_result = next((item for item in results if item.name == "lineage.complete"), None)
    evidence_result = next((item for item in results if item.name == "evidence"), None)
    negative_results = [item for item in results if item.name.startswith("evidence_negative.")]
    if matrix_statuses and all(status == PASS for status in matrix_statuses):
        version_invariant = PASS
    elif any(status == FAIL for status in matrix_statuses):
        version_invariant = FAIL
    else:
        version_invariant = BLOCKED_EXTERNAL if any(status == BLOCKED_EXTERNAL for status in matrix_statuses) else NOT_RUN
    if lineage_result is None:
        lineage_status = NOT_RUN
    else:
        lineage_status = lineage_result.result
    if evidence_result is None:
        evidence_status = NOT_RUN
    elif negative_results and all(item.result == PASS for item in negative_results):
        evidence_status = PASS if evidence_result.result == PASS else evidence_result.result
    else:
        evidence_status = evidence_result.result
    return {
        "failed_version_never_replaces_last_verified": version_invariant,
        "verified_at_required": lineage_status,
        "evidence_exact_version_and_scope": evidence_status,
        "proof_is_explicit": bool(lineage),
    }


def _safe_output_path(raw: str, root: Path) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise GateContractError("output_path_outside_repository") from exc
    return path


def _write_report(path: Path, report: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def run_gate(
    runtime_path: str | os.PathLike[str] | None = None,
    *,
    root: Path = ROOT,
    output: str | os.PathLike[str] | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    run_id: str | None = None,
    dependencies: object | None = None,
) -> dict[str, object]:
    """Run the bounded gate and return its safe JSON-compatible report."""

    root = root.resolve()
    report_path = _safe_output_path(str(output or DEFAULT_OUTPUT), root)
    observed_run_id = run_id or uuid.uuid4().hex
    try:
        timeout = float(timeout_seconds)
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT_SECONDS
    if not 0.1 <= timeout <= MAX_TIMEOUT_SECONDS:
        timeout = min(MAX_TIMEOUT_SECONDS, max(0.1, timeout))
    fixture = SyntheticFixture()
    results: list[GateResult] = []
    details: dict[str, object] = {}
    observed_lineage: dict[str, object] = {}
    runtime: GoldenRuntime | None = None
    composition_result: GateResult
    if dependencies is None:
        runtime, composition_result = load_runtime(
            runtime_path,
            root=root,
            run_id=observed_run_id,
            fixture=fixture,
            timeout_seconds=timeout,
        )
    else:
        try:
            runtime = _normalise_runtime(dependencies)
            composition_result = GateResult("runtime_composition", PASS, "explicit_dependencies_supplied")
        except GateBlocked:
            composition_result = GateResult("runtime_composition", BLOCKED_EXTERNAL, "dependencies_unavailable")
        except GateContractError:
            composition_result = GateResult("runtime_composition", FAIL, "dependencies_contract_invalid")
            runtime = None
    results.append(composition_result)
    if runtime is not None:
        try:
            execution_results, details, observed_lineage = _run_awaitable(
                _execute_runtime(runtime, fixture, run_id=observed_run_id, timeout_seconds=timeout)
            )
            results.extend(execution_results)
        except Exception as exc:
            results.append(GateResult("gate_execution", FAIL, _safe_error(exc)))
    status = _final_status(results, runtime=runtime)
    matrix_report = _failure_matrix_report(details, results)
    report: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "gate_id": GATE_ID,
        "status": status,
        "runtime_claim": status == PASS,
        "production_safe": bool(status == PASS and runtime is not None and runtime.production_safe is True),
        "run_id": observed_run_id,
        "timeout_seconds": timeout,
        "fixture": {"kind": "synthetic_disposable", "bytes": len(fixture.content), "corpus_approved": False},
        "interface_contract": INTERFACE_CONTRACT,
        "results": [result.to_dict() for result in results],
        "details": _safe_report_value(details),
        "failure_matrix": matrix_report,
        "lineage": _lineage_report(observed_lineage),
        "invariants": _invariant_report(results, matrix_report, observed_lineage),
        "limitations": [
            "PASS covers only the explicitly injected runtime and assertions in this gate.",
            "The synthetic fixture is not an approved corpus or promotion approval.",
            "A failed replacement must preserve the last verified lineage; missing proof remains blocked or failed.",
        ],
    }
    try:
        _write_report(report_path, report)
    except Exception:
        # The caller still receives a safe object and a non-pass result.  The
        # CLI path handles this as an execution failure without leaking details.
        report["status"] = FAIL
        report["runtime_claim"] = False
        report["production_safe"] = False
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-path", default=None, help="explicit module.py, directory, or module:factory selector")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        report = run_gate(
            args.runtime_path,
            root=ROOT,
            output=args.output,
            timeout_seconds=args.timeout_seconds,
        )
        print(json.dumps({"gate_id": GATE_ID, "status": report["status"], "output": args.output}, sort_keys=True))
        return 0 if report["status"] == PASS else 2 if report["status"] == BLOCKED_EXTERNAL else 1
    except Exception:
        # CLI failures remain fail-closed and intentionally diagnostic-free.
        try:
            path = _safe_output_path(args.output, ROOT)
            report = {
                "schema_version": SCHEMA_VERSION,
                "gate_id": GATE_ID,
                "status": FAIL,
                "runtime_claim": False,
                "production_safe": False,
                "results": [{"name": "gate", "result": FAIL, "detail": "gate_output_failed"}],
            }
            _write_report(path, report)
        except Exception:
            pass
        print(json.dumps({"gate_id": GATE_ID, "status": FAIL}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
