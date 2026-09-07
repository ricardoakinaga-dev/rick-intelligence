"""Lifecycle + safe readiness semantics.

Readiness is assembled from explicit custom checks plus selected runtime
components supplied by the integrator.  Liveness remains dependency-free.
Check failures become a safe dependency failure rather than exposing an
exception through the health route, and diagnostic details use a deliberately
small, non-sensitive format.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import inspect
import math
import re
import threading
from typing import Any, Awaitable, Callable, Mapping, Sequence


@dataclass
class DependencyState:
    name: str
    ok: bool
    required: bool = True
    detail: str | None = None

    def safe(self) -> "DependencyState":
        """Return a bounded state safe for an admin diagnostic response."""

        return safe_dependency_state(self)


@dataclass
class AppState:
    settings: object = None
    providers: object = None
    checks: dict[str, Callable[[], DependencyState | Awaitable[DependencyState]]] = field(default_factory=dict)


_SAFE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,63}$")
_SAFE_DETAIL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:/-]{0,127}$")
_UNSAFE_MARKERS = (
    "authorization",
    "bearer",
    "credential",
    "exception",
    "password",
    "provider response",
    "secret",
    "stack trace",
    "token",
    "traceback",
)
_SAFE_FAILURE_DETAIL = "unavailable"

# Process-wide admission limits, shared even by different request loops. There
# is no executor queue and daemon workers are never joined during shutdown.
READINESS_TIMEOUT_SECONDS = 1.0
MAX_READINESS_THREADS = 4
MAX_READINESS_TASKS = 8
_sync_slots = threading.BoundedSemaphore(MAX_READINESS_THREADS)
_task_slots = threading.BoundedSemaphore(MAX_READINESS_TASKS)
_active_tasks: set[asyncio.Task] = set()
_active_tasks_lock = threading.Lock()


class _CheckCapacityExceeded(Exception):
    pass


def _discard_result(result: object) -> None:
    # A sync factory can return a coroutine after its request has gone away.
    if inspect.iscoroutine(result):
        result.close()


async def _call_sync(check: Callable) -> object:
    if not _sync_slots.acquire(blocking=False):
        raise _CheckCapacityExceeded
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    def deliver(result: object, failed: bool) -> None:
        if future.done():
            _discard_result(result)
        elif failed:
            # Do not retain an adapter exception or its traceback.
            future.set_exception(RuntimeError("check_failed"))
        else:
            future.set_result(result)

    def worker() -> None:
        result: object = None
        failed = False
        try:
            try:
                result = check()
            except BaseException:
                failed = True
            if future.cancelled() or loop.is_closed():
                _discard_result(result)
            else:
                try:
                    loop.call_soon_threadsafe(deliver, result, failed)
                except RuntimeError:  # Request loop closed during handoff.
                    _discard_result(result)
        finally:
            _sync_slots.release()

    try:
        threading.Thread(target=worker, name="readiness-check", daemon=True).start()
    except BaseException:
        _sync_slots.release()
        raise
    try:
        return await future
    except asyncio.CancelledError:
        # Delivery can win the race with cancellation before this task resumes.
        if future.done() and not future.cancelled():
            if future.exception() is None:
                _discard_result(future.result())
        raise


async def _check_result(check: object) -> object:
    if callable(check):
        if inspect.iscoroutinefunction(check) or inspect.iscoroutinefunction(check.__call__):
            result = check()
        else:
            result = await _call_sync(check)
    else:
        result = check
    if inspect.isawaitable(result):
        result = await result
    return result


async def _run_check(check: object, name: object, required: bool) -> DependencyState:
    try:
        result = await _check_result(check)
        return _state_from_result(result, name=name, required=required)
    except _CheckCapacityExceeded:
        return DependencyState(safe_name(name), False, required, "check_capacity")
    except asyncio.CancelledError:
        raise
    except Exception:
        return _safe_check_failure(name, required=required)


def _check_finished(task: asyncio.Task) -> None:
    with _active_tasks_lock:
        _active_tasks.discard(task)
    _task_slots.release()
    # Retrieve late failures without logging adapter messages.
    if not task.cancelled():
        task.exception()


def safe_detail(detail: object, *, fallback: str | None = None) -> str | None:
    """Allow only short, human-readable diagnostic labels.

    URLs, structured provider payloads, control characters, exception text and
    credential-like labels are discarded.  Health responses never need those
    values to convey readiness truthfully.
    """

    if not isinstance(detail, str):
        return fallback
    candidate = detail.strip()
    lowered = candidate.lower()
    if (
        not candidate
        or len(candidate) > 128
        or not _SAFE_DETAIL_RE.fullmatch(candidate)
        or "://" in candidate
        or "@" in candidate
        or "?" in candidate
        or "=" in candidate
        or any(marker in lowered for marker in _UNSAFE_MARKERS)
    ):
        return fallback
    return candidate


def safe_name(name: object, *, fallback: str = "dependency") -> str:
    if isinstance(name, str) and _SAFE_NAME_RE.fullmatch(name):
        return name
    return fallback


def safe_dependency_state(state: DependencyState) -> DependencyState:
    """Normalize a state before it is serialized by a health route."""

    valid_ok = isinstance(state.ok, bool)
    valid_required = isinstance(state.required, bool)
    # Truthy strings/numbers are not health assertions; malformed policy must
    # never silently downgrade a dependency to optional.
    ok = state.ok is True and valid_required
    required = state.required if valid_required else True
    detail = safe_detail(state.detail) if valid_ok and valid_required else "invalid_check_state"
    if not ok and detail is None:
        detail = _SAFE_FAILURE_DETAIL
    return DependencyState(
        name=safe_name(state.name),
        ok=ok,
        required=required,
        detail=detail,
    )


def _safe_check_failure(name: object, *, required: bool = True) -> DependencyState:
    return DependencyState(name=safe_name(name), ok=False, required=required, detail="check_failed")


def _state_from_result(result: object, *, name: object, required: bool) -> DependencyState:
    if isinstance(result, DependencyState):
        state = result
        # A check's registration controls the dependency identity and policy;
        # custom state detail/health is retained only after safe normalization.
        return safe_dependency_state(
            DependencyState(
                name=state.name or name,
                ok=state.ok,
                required=state.required,
                detail=state.detail,
            )
        )
    if isinstance(result, bool):
        return DependencyState(
            name=safe_name(name), ok=result, required=required,
            detail="available" if result else _SAFE_FAILURE_DETAIL,
        )
    if isinstance(result, Mapping):
        return _state_from_result(
            DependencyState(
                name=result.get("name", name),
                ok=result.get("ok", False),
                required=result.get("required", required),
                detail=result.get("detail"),
            ),
            name=name,
            required=required,
        )
    return _safe_check_failure(name, required=required)


async def evaluate_checks(
    checks: Mapping[str, object],
    *,
    default_required: bool = True,
    timeout_seconds: float = READINESS_TIMEOUT_SECONDS,
) -> list[DependencyState]:
    """Evaluate in registration order within one finite, total wait budget.

    Cancellation is requested but never joined: a resistant async adapter keeps
    its admission slot until it actually finishes. See readiness-deadlines.md.
    """

    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("readiness timeout must be finite and positive")
    if not isinstance(default_required, bool):
        raise ValueError("default_required must be boolean")
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    states: list[DependencyState] = []
    for name, check in checks.items():
        required = default_required
        remaining = deadline - loop.time()
        if remaining <= 0:
            states.append(DependencyState(safe_name(name), False, required, "check_timeout"))
            continue
        if not _task_slots.acquire(blocking=False):
            states.append(DependencyState(safe_name(name), False, required, "check_capacity"))
            continue
        task = loop.create_task(_run_check(check, name, required))
        with _active_tasks_lock:
            _active_tasks.add(task)
        task.add_done_callback(_check_finished)
        try:
            done, _ = await asyncio.wait({task}, timeout=remaining)
            if not done:
                task.cancel()
                state = DependencyState(safe_name(name), False, required, "check_timeout")
            elif task.cancelled():
                state = _safe_check_failure(name, required=required)
            else:
                state = task.result()
        except asyncio.CancelledError:
            task.cancel()
            raise
        states.append(safe_dependency_state(state))
    return states


def _component_result(component: object, *, name: str, required: bool, allow_presence: bool = True) -> object:
    """Read an explicit local health method when a selected component offers one."""

    for method_name in ("readiness_check", "health_check", "check_readiness", "check_health"):
        method = getattr(component, method_name, None)
        if callable(method):
            return method()
    for attribute_name in ("is_ready", "ready", "healthy"):
        value = getattr(component, attribute_name, None)
        if isinstance(value, bool):
            return value
    if getattr(component, "is_shutdown", False) is True:
        return DependencyState(name=name, ok=False, required=required, detail="stopped")
    if allow_presence:
        # Presence is the only truthful local fact available for a local object
        # without a health method. External production dependencies must expose
        # an explicit reachability check instead of receiving a green by
        # construction.
        return DependencyState(name=name, ok=True, required=required, detail="configured")
    return DependencyState(name=name, ok=False, required=required, detail="health_check_missing")


def _required_component_result(result: object, *, name: str) -> object:
    """Keep a selected runtime component mandatory even if it self-reports optional."""

    # Validate the adapter's flags before applying the integrator's mandatory
    # policy. Replacing malformed required first would erase a failed check.
    state = _state_from_result(result, name=name, required=True)
    return DependencyState(name=state.name, ok=state.ok, required=True, detail=state.detail)


def build_readiness_checks(providers: object) -> dict[str, object]:
    """Build checks for custom hooks and selected runtime components.

    Existing ``health_checks`` are authoritative and remain in their original
    order.  The optional ``runtime_checks``/``readiness_checks`` mapping is an
    explicit integrator seam.  Component attributes are a compatibility
    fallback for the existing provider container: only non-``None`` selected
    components are represented, and no object is stringified.
    """

    checks: dict[str, object] = {}
    custom = getattr(providers, "health_checks", {})
    if isinstance(custom, Mapping):
        checks.update(custom)

    for attribute_name in ("runtime_checks", "readiness_checks"):
        registered = getattr(providers, attribute_name, None)
        if isinstance(registered, Mapping):
            for name, check in registered.items():
                safe_key = safe_name(name)
                checks.setdefault(safe_key, check)

    # These attributes are intentionally duck-typed so this module does not
    # need to import the provider container or any external service client.
    selected_components = (
        ("provider", "provider", True),
        ("lease", "lease", True),
        ("retrieval", "retrieval", True),
        ("ingestion", "ingestion", True),
        ("worker", "worker", True),
        ("vector_store", "vector_store", True),
        ("storage", "storage", True),
    )
    knowledge = getattr(providers, "knowledge", None)
    storage = getattr(providers, "storage", None) or knowledge
    production = getattr(getattr(providers, "settings", None), "environment", None) == "production"
    if production:
        # Missing production composition is a required negative signal. The
        # factory normally rejects it before serving, while this keeps the
        # readiness contract truthful for integrators that call this helper
        # directly.
        selected_components = selected_components + (
            ("identity", "identity", True),
            ("chat_backend", "chat_backend", True),
            ("audit_sink", "audit_sink", True),
            ("chat_history", "chat_history", True),
            ("job_journal", "job_journal", True),
            ("queue", "queue", True),
            ("object_store", "object_store", True),
        )
    for name, attribute_name, required in selected_components:
        component = storage if name == "storage" else getattr(providers, attribute_name, None)
        if component is None and production:
            checks.setdefault(name, lambda name=name: DependencyState(
                name=name, ok=False, required=True, detail="not_configured"
            ))
            continue
        if component is None:
            continue

        if name in checks:
            registered_check = checks[name]

            async def check_registered(registered_check=registered_check, name=name):
                result = await _check_result(registered_check)
                return _required_component_result(result, name=name)

            checks[name] = check_registered
            continue

        async def check(component=component, name=name, required=required):
            result = await _check_result(lambda: _component_result(
                component, name=name, required=required, allow_presence=not production,
            ))
            return _required_component_result(result, name=name)

        checks[name] = check
    return checks


async def collect_readiness_states(providers: object) -> list[DependencyState]:
    """Evaluate selected runtime checks, retaining the kernel fallback."""

    checks = build_readiness_checks(providers)
    if not checks:
        return [DependencyState(name="kernel", ok=True, required=True, detail="available")]
    states = await evaluate_checks(checks)
    return states or [DependencyState(name="kernel", ok=True, required=True, detail="available")]


def evaluate_readiness(states: Sequence[DependencyState]) -> tuple[str, int]:
    """Returns (status, http_code). ready→200, degraded→200, not_ready→503.

    Any required dependency down => not_ready (503). Optional down => degraded (200).
    """
    degraded = False
    for raw_state in states:
        state = safe_dependency_state(raw_state)
        if not state.ok:
            if state.required:
                return "not_ready", 503
            degraded = True
    return ("degraded", 200) if degraded else ("ready", 200)
