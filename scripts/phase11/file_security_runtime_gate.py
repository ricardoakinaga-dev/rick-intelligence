#!/usr/bin/env python3
"""Run the external file-security/process-isolation runtime gate.

This gate is intentionally an evidence boundary, not a local parser test.  A
caller must supply a Python composition through ``--runtime-path`` or
``RICK_FILE_SECURITY_RUNTIME_PATH``.  The composition is accepted only when
both its module and its runtime identify themselves as authorized and
external, and its bounded preflight attests to hard timeout, process
isolation, resource limits, bounded output and ephemeral payload handling.

The external composition contract is deliberately small:

* the module exposes ``AUTHORIZED``/``authorized`` and ``EXTERNAL``/``external``
  boolean markers (the longer ``AUTHORIZED_EXTERNAL_RUNTIME`` and
  ``EXTERNAL_RUNTIME`` spellings are also accepted);
* it exposes ``create_runtime``/``build_runtime``/``get_runtime`` or a
  ``runtime`` object; the resulting runtime repeats the authorization and
  external markers;
* the runtime exposes ``preflight`` and ``run_case`` (aliases
  ``run_security_case``, ``execute_case`` and ``probe_case`` are accepted);
* preflight returns a ready status and explicit true values for
  ``process_isolated``, ``hard_timeout``, ``resource_limits_applied``,
  ``output_bounded`` and ``payloads_ephemeral``;
* each case returns a safe, metadata-only observation.  It must reject or
  quarantine the malicious probe, report ``payload_persisted=False`` and
  ``secret_leak=False`` (or ``leak_free=True``), and attest process, limit,
  output and time bounds.  The parser-hang case additionally requires a
  timeout and termination/kill observation.

The gate sends descriptors, never payload bytes.  The external runtime is
responsible for materializing the probe in memory and for exercising its real
upload/parser boundary.  Every invocation is itself a fresh subprocess with a
wall-clock timeout; on POSIX it also receives CPU, address-space, file-size,
core-dump and file-descriptor limits.  Child stdout is read with a hard bound,
stderr is discarded, and no child response or exception text is persisted.
Missing authority is ``BLOCKED_EXTERNAL``.  Malformed composition, timeout,
overflow, a missing assertion or any unsafe result is ``FAIL``.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Mapping, Sequence
import contextlib
import importlib.util
import inspect
import json
import math
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time
import uuid


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ".runtime/phase-3/file-security-runtime-gate.json"
DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_TIMEOUT_SECONDS = 120.0
MIN_TIMEOUT_SECONDS = 0.1
DEFAULT_MEMORY_BYTES = 512 * 1024 * 1024
MIN_MEMORY_BYTES = 64 * 1024 * 1024
MAX_MEMORY_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_CPU_SECONDS = 12
MAX_CPU_SECONDS = 120
MAX_RUNTIME_MODULE_BYTES = 2 * 1024 * 1024
MAX_WORKER_INPUT_BYTES = 48 * 1024
MAX_WORKER_OUTPUT_BYTES = 64 * 1024
MAX_CASE_OUTPUT_BYTES = MAX_WORKER_OUTPUT_BYTES
MAX_CASES = 10

PASS = "PASS"
FAIL = "FAIL"
BLOCKED_EXTERNAL = "BLOCKED_EXTERNAL"
NOT_RUN = "NOT_RUN"

CASE_IDS = (
    "path-traversal",
    "fake-mime",
    "malformed-pdf",
    "huge-page-count",
    "deep-archives",
    "decompression-bomb",
    "polyglot",
    "invalid-unicode",
    "parser-hang",
    "oversized-metadata",
)
# A descriptive alias makes the mandatory corpus easy for callers and tests to
# discover without allowing callers to shrink it.
REQUIRED_CASES = CASE_IDS

_AUTH_NAMES = (
    "AUTHORIZED_EXTERNAL_RUNTIME",
    "EXTERNAL_RUNTIME_AUTHORIZED",
    "RICK_RUNTIME_AUTHORIZED",
    "authorized",
    "AUTHORIZED",
)
_EXTERNAL_NAMES = (
    "EXTERNAL_RUNTIME",
    "EXTERNAL_COMPOSITION",
    "external",
    "EXTERNAL",
)
_FACTORY_NAMES = ("create_runtime", "build_runtime", "get_runtime", "runtime")
_PREFLIGHT_NAMES = ("preflight", "healthcheck", "readiness", "ready")
_CASE_METHOD_NAMES = ("run_case", "run_security_case", "execute_case", "probe_case")
_READY_STATUSES = frozenset({"pass", "ready", "ok", "healthy"})
_DENY_STATUSES = frozenset(
    {
        "blocked",
        "denied",
        "rejected",
        "quarantined",
        "filtered",
        "abstain",
        "fail_closed",
        "timeout",
        "terminated",
        "killed",
    }
)
_SAFE_STATUS = frozenset(
    {
        "accepted",
        "allowed",
        "blocked",
        "denied",
        "rejected",
        "quarantined",
        "filtered",
        "abstain",
        "fail_closed",
        "timeout",
        "terminated",
        "killed",
        "failed",
        "error",
        "ok",
        "ready",
        "healthy",
        "pass",
    }
)

_PAYLOAD_SPECS: dict[str, dict[str, object]] = {
    "path-traversal": {
        "filename_profile": "encoded-and-platform-traversal",
        "filename_variants": ("../escape.txt", "..\\\\escape.txt", "%2e%2e%2fescape.txt"),
        "declared_mime": "text/plain",
        "expected_control": "reject-outside-staging-root",
    },
    "fake-mime": {
        "filename_profile": "text-extension-with-binary-signature",
        "magic_profile": "pdf-signature",
        "declared_mime": "application/pdf",
        "expected_control": "magic-extension-mime-agreement",
    },
    "malformed-pdf": {
        "filename_profile": "pdf",
        "declared_mime": "application/pdf",
        "content_profile": "truncated-and-invalid-cross-reference",
        "expected_control": "bounded-parser-rejection",
    },
    "huge-page-count": {
        "filename_profile": "pdf",
        "page_count_profile": "over-10000-pages",
        "declared_mime": "application/pdf",
        "content_profile": "page-count-over-safety-ceiling",
        "expected_control": "page-limit-before-extraction",
    },
    "deep-archives": {
        "filename_profile": "docx-zip",
        "archive_depth_profile": "over-64-nested-containers",
        "declared_mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "content_profile": "nested-archive-depth-over-ceiling",
        "expected_control": "archive-depth-and-member-bounds",
    },
    "decompression-bomb": {
        "filename_profile": "docx-zip",
        "compression_profile": "ratio-over-1000-to-1",
        "declared_mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "content_profile": "bounded-high-compression-ratio",
        "expected_control": "compressed-and-uncompressed-budgets",
    },
    "polyglot": {
        "filename_profile": "pdf-zip-polyglot",
        "declared_mime": "application/pdf",
        "content_profile": "conflicting-container-signatures",
        "expected_control": "single-format-admission",
    },
    "invalid-unicode": {
        "filename_profile": "ill-formed-unicode-name-and-content",
        "encoding_profile": "invalid-utf8-and-control-sequences",
        "declared_mime": "text/plain",
        "content_profile": "invalid-utf8-and-control-sequences",
        "expected_control": "safe-decoding-and-name-normalization",
    },
    "parser-hang": {
        "filename_profile": "supported-parser-input",
        "declared_mime": "text/plain",
        "content_profile": "non-terminating-parser-probe",
        "expected_control": "hard-timeout-and-process-kill",
    },
    "oversized-metadata": {
        "filename_profile": "supported-document",
        "metadata_size_profile": "over-1MiB",
        "declared_mime": "text/plain",
        "content_profile": "metadata-over-safety-ceiling",
        "expected_control": "bounded-metadata-and-error-envelope",
    },
}


class _BlockedExternal(Exception):
    """The external authority is absent or not authorized."""


class _InvalidConfiguration(Exception):
    """The supplied composition or gate configuration is unsafe."""


def _field(source: object, *names: str) -> object:
    """Read one of a small set of fields without serializing the source."""

    for name in names:
        try:
            if isinstance(source, Mapping):
                if name in source:
                    return source[name]
            else:
                value = getattr(source, name, None)
                if value is not None:
                    return value
        except BaseException:
            # The external object is untrusted.  A hostile property must not
            # escape the worker or become an evidence string.
            return None
    return None


def _true_field(source: object, *names: str) -> bool | None:
    value = _field(source, *names)
    return value if type(value) is bool else None


def _status(source: object, *names: str) -> str:
    value = _field(source, *names)
    if not isinstance(value, str):
        return ""
    normalized = value.strip().lower().replace(" ", "_")
    return normalized[:32] if normalized in _SAFE_STATUS else ""


def _safe_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        return None
    return number


def _safe_nonnegative_int(value: object) -> int | None:
    if type(value) is not int or value < 0:
        return None
    return value


def _safe_path(raw: str, *, root: Path) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise _InvalidConfiguration()
    candidate = Path(raw)
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in str(candidate)):
        raise _InvalidConfiguration()
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        stat_result = candidate.lstat()
    except (OSError, ValueError):
        raise _BlockedExternal() from None
    if not candidate.is_file() or candidate.is_symlink():
        raise _BlockedExternal()
    if stat_result.st_size <= 0 or stat_result.st_size > MAX_RUNTIME_MODULE_BYTES:
        raise _InvalidConfiguration()
    return candidate.resolve()


def _safe_output(raw: str, *, root: Path) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise _InvalidConfiguration()
    root = root.resolve()
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        raise _InvalidConfiguration() from None
    cursor = root
    for component in relative.parts:
        cursor /= component
        if cursor.is_symlink():
            raise _InvalidConfiguration()
    if candidate.exists() and (candidate.is_symlink() or not candidate.is_file()):
        raise _InvalidConfiguration()
    return candidate


def _safe_json_write(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if len(encoded.encode("utf-8")) > 256 * 1024:
        raise _InvalidConfiguration()
    path.write_text(encoded, encoding="utf-8")


def _module_flag(module: object, names: Sequence[str]) -> bool:
    return any(_true_field(module, name) is True for name in names)


def _factory_value(module: object) -> object:
    for name in _FACTORY_NAMES:
        try:
            candidate = getattr(module, name, None)
        except BaseException:
            continue
        if candidate is None:
            continue
        if callable(candidate):
            return candidate
        if name == "runtime":
            return candidate
    # A module-level composition with the required methods is still an
    # external composition; the authorization markers prevent an accidental
    # local import from becoming a runtime claim.
    if any(callable(getattr(module, name, None)) for name in _PREFLIGHT_NAMES) and any(
        callable(getattr(module, name, None)) for name in _CASE_METHOD_NAMES
    ):
        return module
    raise _InvalidConfiguration()


def _accepted_kwargs(target: object, values: Mapping[str, object]) -> tuple[dict[str, object], bool]:
    """Return supported kwargs and whether a positional case is required."""

    try:
        parameters = inspect.signature(target).parameters
    except (TypeError, ValueError):
        return dict(values), False
    if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
        return dict(values), False
    accepted = {
        name: value
        for name, value in values.items()
        if name in parameters
        and parameters[name].kind
        in {inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY}
    }
    required_positionals = [
        parameter
        for parameter in parameters.values()
        if parameter.kind is inspect.Parameter.POSITIONAL_ONLY
        or (
            parameter.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
            and parameter.default is inspect.Parameter.empty
        )
    ]
    return accepted, bool(required_positionals and "case" in values and not accepted)


async def _invoke(target: object, *, case: Mapping[str, object] | None, timeout: float, limits: Mapping[str, object]) -> object:
    if not callable(target):
        raise _InvalidConfiguration()
    values: dict[str, object] = {"timeout_seconds": timeout, "limits": limits}
    if case is not None:
        values.update({"case": case, "probe": case, "descriptor": case, "request": case})
    kwargs, positional_case = _accepted_kwargs(target, values)
    try:
        if positional_case and case is not None:
            result = target(case)
        else:
            result = target(**kwargs)
    except (TypeError, ValueError) as exc:
        # Do not retry after a call: retrying can duplicate an upload or probe.
        raise _InvalidConfiguration() from exc
    if inspect.isawaitable(result):
        try:
            return await asyncio.wait_for(result, timeout=timeout)
        except asyncio.TimeoutError:
            raise
    return result


async def _resolve_runtime(module: object, *, timeout: float, run_id: str) -> object:
    candidate = _factory_value(module)
    if callable(candidate) and candidate is not module:
        values = {"run_id": run_id, "timeout_seconds": timeout}
        kwargs, positional_case = _accepted_kwargs(candidate, values)
        if positional_case:
            raise _InvalidConfiguration()
        try:
            runtime = candidate(**kwargs)
        except (TypeError, ValueError) as exc:
            raise _InvalidConfiguration() from exc
        if inspect.isawaitable(runtime):
            runtime = await asyncio.wait_for(runtime, timeout=timeout)
        return runtime
    return candidate


def _preflight_target(runtime: object) -> object:
    for name in _PREFLIGHT_NAMES:
        target = _field(runtime, name)
        if target is not None:
            return target
    raise _InvalidConfiguration()


def _case_target(runtime: object) -> object:
    for name in _CASE_METHOD_NAMES:
        target = _field(runtime, name)
        if target is not None:
            return target
    raise _InvalidConfiguration()


def _marker_present(value: object, marker: str, *, depth: int = 0, budget: list[int] | None = None) -> bool:
    """Detect a per-run marker without retaining or returning untrusted data."""

    if not marker or depth > 4:
        return False
    if budget is None:
        budget = [256]
    budget[0] -= 1
    if budget[0] < 0:
        return False
    try:
        if isinstance(value, str):
            return marker in value
        if isinstance(value, (bytes, bytearray, memoryview)):
            return marker.encode("utf-8") in bytes(value[:MAX_CASE_OUTPUT_BYTES])
        if isinstance(value, Mapping):
            for index, (key, item) in enumerate(value.items()):
                if index >= 128:
                    break
                if _marker_present(key, marker, depth=depth + 1, budget=budget):
                    return True
                if _marker_present(item, marker, depth=depth + 1, budget=budget):
                    return True
            return False
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray, memoryview)):
            for index, item in enumerate(value):
                if index >= 128:
                    break
                if _marker_present(item, marker, depth=depth + 1, budget=budget):
                    return True
            return False
        if hasattr(value, "__dict__"):
            return _marker_present(vars(value), marker, depth=depth + 1, budget=budget)
    except BaseException:
        return True
    return False


def _case_projection(value: object, *, marker: str) -> dict[str, object]:
    """Project only allowlisted booleans/numbers from an untrusted response."""

    allowed = _true_field(value, "allowed", "accepted")
    blocked = _true_field(value, "blocked", "rejected", "quarantined", "denied")
    status = _status(value, "status", "outcome", "result", "decision")
    if status in _DENY_STATUSES:
        blocked = True
    leak_free = _true_field(value, "leak_free", "no_secret_leak", "secret_free")
    secret_leak = _true_field(value, "secret_leak", "leaked_secret", "credential_leak")
    marker_leak = _marker_present(value, marker)
    if marker_leak:
        secret_leak = True
    elif secret_leak is None and leak_free is True:
        secret_leak = False

    payload_persisted = _true_field(
        value,
        "payload_persisted",
        "persisted",
        "payload_written",
        "payload_on_disk",
    )
    process_isolated = _true_field(value, "process_isolated", "isolated", "sandboxed")
    limits_applied = _true_field(
        value,
        "resource_limits_applied",
        "limits_applied",
        "sandbox_limits_applied",
    )
    output_bounded = _true_field(value, "output_bounded", "bounded_output")
    time_bounded = _true_field(value, "time_bounded", "bounded_time", "deadline_enforced")
    case_executed = _true_field(value, "case_executed", "probe_executed", "executed")
    probe_materialized = _true_field(value, "probe_materialized", "payload_materialized", "fixture_materialized")
    timed_out = _true_field(value, "timed_out", "timeout")
    terminated = _true_field(value, "terminated", "killed", "process_killed")
    output_bytes = _safe_nonnegative_int(_field(value, "output_bytes", "response_bytes"))
    duration_ms = _safe_float(_field(value, "duration_ms", "elapsed_ms", "duration"))
    observed_case_id = _field(value, "case_id", "probe_case_id")
    if not isinstance(observed_case_id, str) or observed_case_id not in CASE_IDS:
        observed_case_id = None
    return {
        "case_id": observed_case_id,
        "blocked": blocked is True,
        "allowed": allowed,
        "status": status,
        "payload_persisted": payload_persisted,
        "secret_leak": secret_leak,
        "process_isolated": process_isolated,
        "resource_limits_applied": limits_applied,
        "output_bounded": output_bounded,
        "time_bounded": time_bounded,
        "case_executed": case_executed,
        "probe_materialized": probe_materialized,
        "timed_out": timed_out,
        "terminated": terminated,
        "output_bytes": output_bytes,
        "duration_ms": duration_ms,
    }


def _preflight_projection(value: object, *, authorized: bool, external: bool, production_safe: bool | None) -> dict[str, object]:
    return {
        "status": _status(value, "status", "state", "result"),
        "authorized": authorized,
        "external": external,
        "process_isolated": _true_field(value, "process_isolated", "isolated", "sandboxed"),
        "hard_timeout": _true_field(value, "hard_timeout", "hard_timeout_enforced", "process_kill_on_timeout"),
        "resource_limits_applied": _true_field(value, "resource_limits_applied", "limits_applied", "sandbox_limits_applied"),
        "output_bounded": _true_field(value, "output_bounded", "bounded_output"),
        "payloads_ephemeral": _true_field(value, "payloads_ephemeral", "no_payload_persistence", "payloads_in_memory_only"),
        "production_safe": production_safe,
    }


def _worker_limits_from_input(raw: Mapping[str, object]) -> tuple[float, int, int]:
    timeout = _safe_float(raw.get("timeout_seconds"))
    memory = _safe_nonnegative_int(raw.get("memory_bytes"))
    cpu = _safe_nonnegative_int(raw.get("cpu_seconds"))
    if timeout is None or not MIN_TIMEOUT_SECONDS <= timeout <= MAX_TIMEOUT_SECONDS:
        raise _InvalidConfiguration()
    if memory is None or not MIN_MEMORY_BYTES <= memory <= MAX_MEMORY_BYTES:
        raise _InvalidConfiguration()
    if cpu is None or not 1 <= cpu <= MAX_CPU_SECONDS:
        raise _InvalidConfiguration()
    return timeout, memory, cpu


async def _worker_operation(raw: Mapping[str, object]) -> dict[str, object]:
    runtime_path = raw.get("runtime_path")
    if not isinstance(runtime_path, str) or not runtime_path:
        raise _InvalidConfiguration()
    timeout, _memory, _cpu = _worker_limits_from_input(raw)
    operation = raw.get("operation")
    if operation not in {"preflight", "case"}:
        raise _InvalidConfiguration()

    # Load/import and all external calls remain inside this child.  External
    # print statements are discarded so the parent receives only our bounded
    # protocol JSON.
    with open(os.devnull, "w", encoding="utf-8") as quiet, contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        path = _safe_path(runtime_path, root=Path(runtime_path).resolve().parent)
        module_name = f"rick_file_security_runtime_{uuid.uuid4().hex}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise _InvalidConfiguration()
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except BaseException as exc:
            raise _InvalidConfiguration() from exc
        module_authorized = _module_flag(module, _AUTH_NAMES)
        module_external = _module_flag(module, _EXTERNAL_NAMES)
        if not module_authorized or not module_external:
            return {"ok": False, "status": BLOCKED_EXTERNAL, "kind": "authorization"}
        run_id = raw.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise _InvalidConfiguration()
        runtime = await _resolve_runtime(module, timeout=timeout, run_id=run_id)
        runtime_authorized = _module_flag(runtime, _AUTH_NAMES)
        runtime_external = _module_flag(runtime, _EXTERNAL_NAMES)
        if not runtime_authorized or not runtime_external:
            return {"ok": False, "status": BLOCKED_EXTERNAL, "kind": "authorization"}
        production_safe = _true_field(runtime, "production_safe")
        limits = {
            "wall_timeout_seconds": timeout,
            "memory_bytes": _memory,
            "cpu_seconds": _cpu,
            "max_output_bytes": MAX_CASE_OUTPUT_BYTES,
            "payloads_persisted": False,
        }
        if operation == "preflight":
            target = _preflight_target(runtime)
            result = await _invoke(target, case=None, timeout=timeout, limits=limits)
            observation = _preflight_projection(
                result,
                authorized=runtime_authorized,
                external=runtime_external,
                production_safe=production_safe,
            )
            observation["worker_resource_limits_applied"] = _child_limits_satisfied(
                cpu_seconds=_cpu,
                memory_bytes=_memory,
            )
            return {"ok": True, "kind": "preflight", "observation": observation}

        case = raw.get("case")
        if not isinstance(case, Mapping):
            raise _InvalidConfiguration()
        marker = case.get("leak_marker")
        if not isinstance(marker, str) or not marker:
            raise _InvalidConfiguration()
        target = _case_target(runtime)
        result = await _invoke(target, case=case, timeout=timeout, limits=limits)
        observation = _case_projection(result, marker=marker)
        observation["worker_resource_limits_applied"] = _child_limits_satisfied(
            cpu_seconds=_cpu,
            memory_bytes=_memory,
        )
        return {"ok": True, "kind": "case", "observation": observation}


def _worker_main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--runtime-path", required=True)
    parser.add_argument("--operation", choices=("preflight", "case"), required=True)
    args = parser.parse_args(list(argv))
    try:
        raw_bytes = sys.stdin.buffer.read(MAX_WORKER_INPUT_BYTES + 1)
        if len(raw_bytes) > MAX_WORKER_INPUT_BYTES:
            raise _InvalidConfiguration()
        value = json.loads(raw_bytes.decode("utf-8"))
        if not isinstance(value, dict):
            raise _InvalidConfiguration()
        value["runtime_path"] = args.runtime_path
        value["operation"] = args.operation
        result = asyncio.run(_worker_operation(value))
    except _BlockedExternal:
        result = {"ok": False, "status": BLOCKED_EXTERNAL, "kind": "external"}
    except BaseException:
        # The worker boundary intentionally emits no exception details,
        # traceback, path, payload or secret.
        result = {"ok": False, "status": FAIL, "kind": "worker"}
    try:
        encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(encoded) + 1 > MAX_WORKER_OUTPUT_BYTES:
            return 1
        sys.stdout.buffer.write(encoded)
        sys.stdout.buffer.write(b"\n")
        sys.stdout.buffer.flush()
    except BaseException:
        return 1
    return 0


def _apply_child_limits(*, cpu_seconds: int, memory_bytes: int) -> None:
    """Apply best-effort POSIX limits before importing the external module."""

    if os.name != "posix":
        return
    try:
        import resource

        current_cpu = resource.getrlimit(resource.RLIMIT_CPU)
        current_soft_cpu, hard_cpu = current_cpu
        requested_cpu = max(1, int(cpu_seconds))
        soft_cpu = requested_cpu
        if current_soft_cpu != resource.RLIM_INFINITY:
            soft_cpu = min(soft_cpu, current_soft_cpu)
        if hard_cpu != resource.RLIM_INFINITY:
            soft_cpu = min(soft_cpu, hard_cpu)
        resource.setrlimit(resource.RLIMIT_CPU, (soft_cpu, hard_cpu))

        current_as = resource.getrlimit(resource.RLIMIT_AS)
        current_soft_as, hard_as = current_as
        soft_as = memory_bytes
        if current_soft_as != resource.RLIM_INFINITY:
            soft_as = min(soft_as, current_soft_as)
        if hard_as != resource.RLIM_INFINITY:
            soft_as = min(soft_as, hard_as)
        resource.setrlimit(resource.RLIMIT_AS, (soft_as, hard_as))

        for limit_name, value in (
            ("RLIMIT_FSIZE", 1 * 1024 * 1024),
            ("RLIMIT_CORE", 0),
        ):
            limit = getattr(resource, limit_name, None)
            if limit is None:
                continue
            current = resource.getrlimit(limit)
            current_soft, hard = current
            safe = value
            if current_soft != resource.RLIM_INFINITY:
                safe = min(safe, current_soft)
            if hard != resource.RLIM_INFINITY:
                safe = min(safe, hard)
            resource.setrlimit(limit, (safe, hard))

        nofile = getattr(resource, "RLIMIT_NOFILE", None)
        if nofile is not None:
            current = resource.getrlimit(nofile)
            current_soft, hard = current
            safe = 64
            if current_soft != resource.RLIM_INFINITY:
                safe = min(safe, current_soft)
            if hard != resource.RLIM_INFINITY:
                safe = min(safe, hard)
            resource.setrlimit(nofile, (safe, hard))
    except (ImportError, OSError, ValueError):
        # The parent still enforces the hard wall-clock and output bounds.  A
        # production composition must also attest its own resource limits.
        return


def _child_limits_satisfied(*, cpu_seconds: int, memory_bytes: int) -> bool:
    """Report whether the worker can observe the requested POSIX ceilings."""

    if os.name != "posix":
        # The parent wall-clock/process boundary remains active; POSIX rlimits
        # are not applicable on this platform.
        return True
    try:
        import resource

        cpu_soft, _cpu_hard = resource.getrlimit(resource.RLIMIT_CPU)
        as_soft, _as_hard = resource.getrlimit(resource.RLIMIT_AS)
        fsize_soft, _fsize_hard = resource.getrlimit(resource.RLIMIT_FSIZE)
        core_soft, _core_hard = resource.getrlimit(resource.RLIMIT_CORE)
        nofile = getattr(resource, "RLIMIT_NOFILE", None)
        nofile_soft = resource.getrlimit(nofile)[0] if nofile is not None else 64
        def finite_and_bounded(value: int, ceiling: int) -> bool:
            return value != resource.RLIM_INFINITY and value <= ceiling
        return (
            finite_and_bounded(cpu_soft, cpu_seconds)
            and finite_and_bounded(as_soft, memory_bytes)
            and fsize_soft != resource.RLIM_INFINITY
            and fsize_soft <= 1 * 1024 * 1024
            and core_soft != resource.RLIM_INFINITY
            and core_soft == 0
            and nofile_soft != resource.RLIM_INFINITY
            and nofile_soft <= 64
        )
    except (ImportError, OSError, ValueError):
        return False


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except OSError:
        pass
    try:
        process.wait(timeout=0.15)
    except subprocess.TimeoutExpired:
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except OSError:
            pass
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            pass


def _read_worker_bounded(process: subprocess.Popen[bytes], *, timeout: float) -> tuple[bytes, str]:
    """Read child stdout with a byte/deadline bound and no stderr capture."""

    stdout = process.stdout
    if stdout is None:
        _terminate_process(process)
        return b"", "protocol"
    selector = selectors.DefaultSelector()
    chunks: list[bytes] = []
    total = 0
    deadline = time.monotonic() + timeout
    try:
        os.set_blocking(stdout.fileno(), False)
        selector.register(stdout, selectors.EVENT_READ)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _terminate_process(process)
                return b"", "timeout"
            events = selector.select(remaining)
            if not events:
                _terminate_process(process)
                return b"", "timeout"
            for key, _mask in events:
                try:
                    chunk = os.read(key.fd, min(16 * 1024, MAX_WORKER_OUTPUT_BYTES + 1 - total))
                except BlockingIOError:
                    continue
                except OSError:
                    selector.unregister(key.fileobj)
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                total += len(chunk)
                if total > MAX_WORKER_OUTPUT_BYTES:
                    _terminate_process(process)
                    return b"", "overflow"
                chunks.append(chunk)
        try:
            process.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            _terminate_process(process)
            return b"", "timeout"
        return b"".join(chunks), "ok" if process.returncode == 0 else "process"
    finally:
        selector.close()
        try:
            stdout.close()
        except OSError:
            pass


def _run_worker(
    runtime_path: Path,
    *,
    operation: str,
    root: Path,
    timeout: float,
    memory_bytes: int,
    cpu_seconds: int,
    case: Mapping[str, object] | None = None,
) -> tuple[str, dict[str, object], str]:
    payload: dict[str, object] = {
        "run_id": uuid.uuid4().hex,
        "timeout_seconds": timeout,
        "memory_bytes": memory_bytes,
        "cpu_seconds": cpu_seconds,
    }
    if case is not None:
        payload["case"] = dict(case)
    try:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError):
        return FAIL, {}, "worker request could not be encoded"
    if len(encoded) > MAX_WORKER_INPUT_BYTES:
        return FAIL, {}, "worker request exceeded its bounded input limit"

    command = [
        sys.executable,
        "-u",
        str(Path(__file__).resolve()),
        "--worker",
        "--runtime-path",
        str(runtime_path),
        "--operation",
        operation,
    ]
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "RICK_FILE_SECURITY_WORKER": "1",
        }
    )
    existing_pythonpath = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = os.pathsep.join(
        item for item in (str(root), existing_pythonpath) if item
    )
    preexec = None
    if os.name == "posix":
        preexec = lambda: _apply_child_limits(cpu_seconds=cpu_seconds, memory_bytes=memory_bytes)
    try:
        process = subprocess.Popen(
            command,
            cwd=root,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
            preexec_fn=preexec,
        )
    except (OSError, ValueError):
        return FAIL, {}, "isolated worker could not be started"
    try:
        if process.stdin is None:
            _terminate_process(process)
            return FAIL, {}, "isolated worker input is unavailable"
        try:
            process.stdin.write(encoded)
            process.stdin.close()
        except (BrokenPipeError, OSError):
            _terminate_process(process)
            return FAIL, {}, "isolated worker input failed"
        raw, read_status = _read_worker_bounded(process, timeout=timeout)
    finally:
        try:
            if process.stdin is not None:
                process.stdin.close()
        except OSError:
            pass
    if read_status == "timeout":
        return FAIL, {}, "isolated worker exceeded its hard timeout"
    if read_status == "overflow":
        return FAIL, {}, "isolated worker output exceeded its hard bound"
    if read_status != "ok":
        return FAIL, {}, "isolated worker exited without a valid result"
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        return FAIL, {}, "isolated worker returned malformed JSON"
    if not isinstance(decoded, Mapping):
        return FAIL, {}, "isolated worker returned a non-object result"
    if decoded.get("status") == BLOCKED_EXTERNAL:
        return BLOCKED_EXTERNAL, {}, "external runtime authority was not available"
    if decoded.get("ok") is not True or not isinstance(decoded.get("observation"), Mapping):
        return FAIL, {}, "external runtime returned an invalid bounded observation"
    return PASS, dict(decoded["observation"]), "bounded observation received"


def _case_descriptor(case_id: str, run_id: str) -> dict[str, object]:
    marker = f"file-security-probe-{run_id}-{case_id}-{uuid.uuid4().hex[:12]}"
    return {
        "case_id": case_id,
        "probe_id": run_id,
        "leak_marker": marker,
        "expected": "reject_or_quarantine_without_persistence",
        "payload_spec": dict(_PAYLOAD_SPECS[case_id]),
    }


def _preflight_valid(observation: Mapping[str, object]) -> bool:
    if observation.get("status") not in _READY_STATUSES:
        return False
    return all(
        observation.get(field) is True
        for field in (
            "authorized",
            "external",
            "process_isolated",
            "hard_timeout",
            "resource_limits_applied",
            "output_bounded",
            "payloads_ephemeral",
            "worker_resource_limits_applied",
        )
    )


def _case_valid(case_id: str, observation: Mapping[str, object], *, timeout: float) -> tuple[bool, str]:
    allowed = observation.get("allowed")
    denied = observation.get("blocked") is True or observation.get("status") in _DENY_STATUSES
    if observation.get("case_id") != case_id:
        return False, "case observation identity did not match the requested probe"
    if allowed is True or not denied:
        return False, "malicious case was not explicitly rejected or quarantined"
    if observation.get("payload_persisted") is not False:
        return False, "payload persistence was not explicitly ruled out"
    if observation.get("secret_leak") is not False:
        return False, "secret/probe leakage was not explicitly ruled out"
    for field in (
        "process_isolated",
        "resource_limits_applied",
        "worker_resource_limits_applied",
        "output_bounded",
        "time_bounded",
        "case_executed",
        "probe_materialized",
    ):
        if observation.get(field) is not True:
            return False, f"{field} was not explicitly proven"
    output_bytes = observation.get("output_bytes")
    if type(output_bytes) is not int or not 0 <= output_bytes <= MAX_CASE_OUTPUT_BYTES:
        return False, "case output size was absent or exceeded its bound"
    duration_ms = observation.get("duration_ms")
    if not isinstance(duration_ms, (int, float)) or isinstance(duration_ms, bool):
        return False, "case duration was absent or invalid"
    if not math.isfinite(float(duration_ms)) or float(duration_ms) < 0 or float(duration_ms) > timeout * 1000 + 1000:
        return False, "case duration exceeded its bound"
    if case_id == "parser-hang" and not (
        observation.get("timed_out") is True and observation.get("terminated") is True
    ):
        return False, "parser hang did not prove timeout and process termination"
    return True, "mandatory malicious file-security case was rejected within bounds"


def _case_report(case_id: str, result: str, detail: str, observation: Mapping[str, object] | None = None) -> dict[str, object]:
    report: dict[str, object] = {"case_id": case_id, "result": result, "detail": detail}
    if observation is not None:
        report["observed"] = {
            key: observation.get(key)
            for key in (
                "blocked",
                "allowed",
                "status",
                "case_id",
                "payload_persisted",
                "secret_leak",
                "process_isolated",
                "resource_limits_applied",
                "worker_resource_limits_applied",
                "output_bounded",
                "time_bounded",
                "case_executed",
                "probe_materialized",
                "timed_out",
                "terminated",
                "output_bytes",
                "duration_ms",
            )
        }
    return report


def _base_report(*, status: str, detail: str, cases: Sequence[Mapping[str, object]], preflight: Mapping[str, object] | None = None) -> dict[str, object]:
    return {
        "schema_version": "phase11-file-security-runtime-gate.v1",
        "status": status,
        "runtime_claim": status == PASS,
        "production_safe": False,
        "preflight": dict(preflight or {}),
        "case_count": len(cases),
        "required_case_count": len(CASE_IDS),
        "cases": [dict(case) for case in cases],
        "limits": {
            "worker_process_isolation": True,
            "wall_clock_timeout": True,
            "bounded_worker_input_bytes": MAX_WORKER_INPUT_BYTES,
            "bounded_worker_output_bytes": MAX_WORKER_OUTPUT_BYTES,
            "posix_resource_limits": os.name == "posix",
            "payload_bytes_persisted_by_gate": False,
        },
        "detail": detail,
        "limitations": [
            "The gate sends metadata descriptors; the supplied external composition must materialize and exercise the real file boundary.",
            "A PASS covers only the ten mandatory cases executed by this composition and does not approve the whole product or deployment.",
            "POSIX limits are applied best-effort by the worker; container, seccomp, cgroup and sandbox policy remain deployment responsibilities.",
            "The gate does not retain payload bytes, external responses, exception text, paths, credentials or probe markers.",
        ],
    }


def run_gate(
    runtime_path: str | None = None,
    *,
    output: str = DEFAULT_OUTPUT,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    memory_bytes: int = DEFAULT_MEMORY_BYTES,
    cpu_seconds: int = DEFAULT_CPU_SECONDS,
    root: Path = ROOT,
) -> dict[str, object]:
    """Execute all mandatory file-security cases and write a safe report."""

    root = root.resolve()
    output_path = _safe_output(output, root=root)
    try:
        timeout = float(timeout_seconds)
    except (TypeError, ValueError):
        raise _InvalidConfiguration() from None
    if not math.isfinite(timeout) or not MIN_TIMEOUT_SECONDS <= timeout <= MAX_TIMEOUT_SECONDS:
        raise _InvalidConfiguration()
    if type(memory_bytes) is not int or not MIN_MEMORY_BYTES <= memory_bytes <= MAX_MEMORY_BYTES:
        raise _InvalidConfiguration()
    if type(cpu_seconds) is not int or not 1 <= cpu_seconds <= MAX_CPU_SECONDS:
        raise _InvalidConfiguration()

    selected_value = runtime_path or os.environ.get("RICK_FILE_SECURITY_RUNTIME_PATH", "")
    if not isinstance(selected_value, str):
        raise _InvalidConfiguration()
    selected_raw = selected_value.strip()
    if not selected_raw:
        report = _base_report(
            status=BLOCKED_EXTERNAL,
            detail="RICK_FILE_SECURITY_RUNTIME_PATH or --runtime-path is required",
            cases=(),
        )
        _safe_json_write(output_path, report)
        return report
    try:
        selected_path = _safe_path(selected_raw, root=root)
    except _BlockedExternal:
        report = _base_report(
            status=BLOCKED_EXTERNAL,
            detail="authorized external file-security composition is unavailable",
            cases=(),
        )
        _safe_json_write(output_path, report)
        return report

    preflight_status, preflight_observation, preflight_detail = _run_worker(
        selected_path,
        operation="preflight",
        root=root,
        timeout=timeout,
        memory_bytes=memory_bytes,
        cpu_seconds=cpu_seconds,
    )
    if preflight_status == BLOCKED_EXTERNAL:
        report = _base_report(
            status=BLOCKED_EXTERNAL,
            detail=preflight_detail,
            cases=(),
            preflight=preflight_observation,
        )
        _safe_json_write(output_path, report)
        return report
    if preflight_status != PASS or not _preflight_valid(preflight_observation):
        report = _base_report(
            status=FAIL,
            detail="external file-security composition failed the isolation preflight contract",
            cases=(),
            preflight=preflight_observation,
        )
        _safe_json_write(output_path, report)
        return report

    run_id = uuid.uuid4().hex[:16]
    cases: list[dict[str, object]] = []
    blocked_case = False
    for case_id in CASE_IDS[:MAX_CASES]:
        descriptor = _case_descriptor(case_id, run_id)
        worker_status, observation, detail = _run_worker(
            selected_path,
            operation="case",
            root=root,
            timeout=timeout,
            memory_bytes=memory_bytes,
            cpu_seconds=cpu_seconds,
            case=descriptor,
        )
        if worker_status == BLOCKED_EXTERNAL:
            blocked_case = True
            cases.append(_case_report(case_id, BLOCKED_EXTERNAL, detail))
            continue
        if worker_status != PASS:
            cases.append(_case_report(case_id, FAIL, detail))
            continue
        valid, case_detail = _case_valid(case_id, observation, timeout=timeout)
        cases.append(_case_report(case_id, PASS if valid else FAIL, case_detail, observation))

    if blocked_case:
        status = BLOCKED_EXTERNAL
        detail = "external file-security authority disappeared during the mandatory case matrix"
    else:
        status = PASS if len(cases) == len(CASE_IDS) and all(case["result"] == PASS for case in cases) else FAIL
        detail = (
            "all mandatory file-security and process-isolation cases passed"
            if status == PASS
            else "one or more mandatory file-security or process-isolation cases failed"
        )
    report = _base_report(
        status=status,
        detail=detail,
        cases=cases,
        preflight=preflight_observation,
    )
    report["production_safe"] = bool(status == PASS and preflight_observation.get("production_safe") is True)
    _safe_json_write(output_path, report)
    return report


def _fallback_report(status: str, detail: str) -> dict[str, object]:
    return _base_report(status=status, detail=detail, cases=())


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if "--worker" in argv:
        worker_args = [item for item in argv if item != "--worker"]
        return _worker_main(worker_args)

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-path", default=None)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--root", default=str(ROOT), help=argparse.SUPPRESS)
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--memory-mb", type=int, default=DEFAULT_MEMORY_BYTES // (1024 * 1024))
    parser.add_argument("--cpu-seconds", type=int, default=DEFAULT_CPU_SECONDS)
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    try:
        memory_bytes = args.memory_mb * 1024 * 1024
        report = run_gate(
            args.runtime_path,
            output=args.output,
            timeout_seconds=args.timeout_seconds,
            memory_bytes=memory_bytes,
            cpu_seconds=args.cpu_seconds,
            root=root,
        )
    except _BlockedExternal:
        report = _fallback_report(BLOCKED_EXTERNAL, "authorized external file-security composition is unavailable")
        try:
            _safe_json_write(_safe_output(args.output, root=root), report)
        except Exception:
            pass
    except (_InvalidConfiguration, OSError, ValueError):
        report = _fallback_report(FAIL, "file-security runtime gate configuration was rejected")
        try:
            _safe_json_write(_safe_output(args.output, root=root), report)
        except Exception:
            pass
    except Exception:
        report = _fallback_report(FAIL, "file-security runtime gate failed closed after an internal error")
        try:
            _safe_json_write(_safe_output(args.output, root=root), report)
        except Exception:
            pass
    print(
        json.dumps(
            {
                "output": args.output,
                "status": report["status"],
                "required_case_count": report["required_case_count"],
                "production_safe": report["production_safe"],
            },
            sort_keys=True,
        )
    )
    return 0 if report["status"] == PASS else 2 if report["status"] == BLOCKED_EXTERNAL else 1


if __name__ == "__main__":
    raise SystemExit(main())
