"""Small rate-limit primitives shared by public and authenticated routes."""

from __future__ import annotations

from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable
import hashlib
import json
import uuid
import math
import inspect
import threading
import time
from typing import Any, Protocol, TypeVar

from core.otel import record_safe_exception, stage_span
from starlette.concurrency import run_in_threadpool


T = TypeVar("T")


class AdmissionOffload(Protocol):
    async def run(self, function: Callable[..., T | Awaitable[T]], *args: object,
                  timeout: float, allow_awaitable: bool = False, **kwargs: object) -> T: ...


class RateLimiter(Protocol):
    """Synchronous limiter contract used by the API routes."""

    def check(self, key: str, *, limit_per_min: int) -> bool:
        """Consume one request from ``key`` and report whether it is allowed."""


class DistributedRateLimitBackend(Protocol):
    """Atomic shared-counter boundary for :class:`DistributedRateLimiter`.

    The implementation must increment ``key`` and establish or preserve its
    expiry as one atomic operation.  Redis, for example, can provide this
    with a Lua script or ``INCR`` plus an expiry set only on the first write.
    The API package intentionally does not construct a Redis client; callers
    inject an implementation at composition time.
    """

    def increment(self, key: str, *, window_seconds: float) -> int:
        """Return the counter value after the atomic increment."""


class DistributedRateLimiter:
    """Synchronous adapter over a shared, expiry-aware counter backend.

    Each key is counted in a fixed window whose duration is supplied to the
    backend.  The backend owns the cross-process atomicity and expiry; this
    adapter only applies the configured limit.  If the backend is unavailable,
    malformed, or raises for any other operational reason, the request is
    rejected.  It never silently falls back to local memory because that would
    bypass the distributed security boundary.

    Real Redis wiring remains external: inject a synchronous adapter that
    implements :class:`DistributedRateLimitBackend`.  Until that wiring is
    present, :class:`InMemoryRateLimiter` remains the explicit local fallback
    and is not a multi-replica boundary.
    """

    def __init__(
        self,
        backend: DistributedRateLimitBackend,
        *,
        window_seconds: float = 60.0,
    ) -> None:
        if not callable(getattr(backend, "increment", None)):
            raise ValueError("distributed rate-limit backend must expose increment()")
        if not isinstance(window_seconds, (int, float)) or isinstance(window_seconds, bool):
            raise ValueError("rate-limit window must be a positive finite number")
        if not math.isfinite(window_seconds) or window_seconds <= 0:
            raise ValueError("rate-limit window must be a positive finite number")
        self._backend = backend
        self.window_seconds = float(window_seconds)
        self.production_safe = False
        self.backend_kind = "distributed"

    def check(self, key: str, *, limit_per_min: int) -> bool:
        """Atomically count a request and fail closed if the backend is unsafe."""

        if not isinstance(limit_per_min, int) or isinstance(limit_per_min, bool):
            return False
        if limit_per_min <= 0:
            return False

        try:
            count = self._backend.increment(key, window_seconds=self.window_seconds)
        except Exception:
            # Backend failures must not expose connection details or turn the
            # rate-limit boundary into an accidental fail-open path.
            return False

        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            return False
        return count <= limit_per_min


def rate_limit_key(namespace: str, *scope: str | None) -> str:
    """Hash typed scope segments without delimiter collisions or identity labels."""
    material = json.dumps((namespace, *scope), ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def server_rate_request_id(request: Any) -> str:
    """Own Redis dedup identity; a caller-controlled X-Request-ID is not authority.

    Reuse this nonce across buckets/internal retries in one HTTP request, never
    across HTTP requests, while keeping the public tracing ID unchanged.
    """
    nonce = getattr(request.state, "rate_limit_request_id", None)
    if nonce is None:
        nonce = uuid.uuid4().hex
        request.state.rate_limit_request_id = nonce
    return nonce


class InMemoryRateLimiter:
    """Bounded, fail-closed local sliding windows, NOT multi-replica authority.

    The defaults below are local memory safety caps, not approved production
    throughput/SLO budgets. Production must inject the distributed capability.
    Live keys are never evicted to make room, which would reset attackers' quotas.
    """

    def __init__(self, *, window_seconds: float = 60.0, max_keys: int = 4096, max_events: int = 65536):
        if isinstance(window_seconds, bool) or not isinstance(window_seconds, (int, float)) or not math.isfinite(window_seconds) or window_seconds <= 0:
            raise ValueError("window_seconds must be finite and positive")
        if type(max_keys) is not int or max_keys <= 0 or type(max_events) is not int or max_events <= 0:
            raise ValueError("local capacities must be positive integers")
        self.window_seconds = float(window_seconds)
        self.max_keys = max_keys
        self.max_events = max_events
        self._events: OrderedDict[str, deque[float]] = OrderedDict()
        self._event_count = 0
        self._lock = threading.Lock()

    def _prune_key(self, key: str, now: float) -> None:
        events = self._events.get(key)
        if events is None:
            return
        while events and now - events[0] >= self.window_seconds:
            events.popleft()
            self._event_count -= 1
        if not events:
            del self._events[key]

    def check(self, key: str, *, limit_per_min: int) -> bool:
        if not isinstance(key, str) or not key or len(key) > 512 or type(limit_per_min) is not int or limit_per_min <= 0:
            return False
        with self._lock:
            # Admission order, deque order and last-event key order must share
            # the same serialized clock sample; a pre-lock sample can go stale.
            now = time.monotonic()
            # Keys are ordered by their last accepted event. Prune entirely cold
            # windows without scanning every live bucket on every request.
            while self._events:
                oldest = next(iter(self._events))
                if now - self._events[oldest][-1] < self.window_seconds:
                    break
                self._event_count -= len(self._events.pop(oldest))
            self._prune_key(key, now)
            if self._event_count >= self.max_events:
                # Partial expiration can free capacity inside otherwise live
                # buckets. Only scan the bounded map when capacity is exhausted.
                for existing in tuple(self._events):
                    self._prune_key(existing, now)
            events = self._events.get(key)
            if events is not None and len(events) >= limit_per_min:
                return False
            if self._event_count >= self.max_events or events is None and len(self._events) >= self.max_keys:
                return False
            if events is None:
                events = deque()
                self._events[key] = events
            events.append(now)
            self._event_count += 1
            self._events.move_to_end(key)
            return True


_rate_limiter_init_lock = threading.Lock()


def ensure_rate_limiter(owner: Any) -> Any:
    """Return an injected limiter or atomically install the local fallback."""

    limiter = getattr(owner, "rate_limiter", None)
    if limiter is not None:
        return limiter
    with _rate_limiter_init_lock:
        limiter = getattr(owner, "rate_limiter", None)
        if limiter is None:
            limiter = InMemoryRateLimiter()
            owner.rate_limiter = limiter
    return limiter


def check_rate_limit(limiter: Any, key: str, *, limit_per_min: int) -> bool:
    """Adapt the canonical ``check`` contract and legacy ``allow`` adapters."""

    check = getattr(limiter, "check", None)
    if callable(check):
        try:
            result = check(key, limit_per_min=limit_per_min)
        except TypeError:
            result = check(key, limit_per_min)
        if inspect.isawaitable(result):
            close = getattr(result, "close", None)
            if callable(close):
                close()
            raise TypeError("asynchronous rate limiter requires check_rate_limit_async()")
        return result is True
    allow = getattr(limiter, "allow", None)
    if callable(allow):
        try:
            result = allow(key, limit_per_min=limit_per_min)
        except TypeError:
            result = allow(key, limit_per_min)
        if inspect.isawaitable(result):
            close = getattr(result, "close", None)
            if callable(close):
                close()
            raise TypeError("asynchronous rate limiter requires check_rate_limit_async()")
        return result is True
    raise TypeError("configured rate limiter must expose check() or allow()")


async def ensure_rate_limiter_async(owner: Any, *, offload: AdmissionOffload | None = None,
                                    timeout_seconds: float | None = None) -> Any:
    """Resolve lazy initialization through the caller's admission/deadline."""
    if offload is not None:
        if timeout_seconds is None:
            raise ValueError("admission requires an explicit deadline")
        return await offload.run(ensure_rate_limiter, owner, timeout=timeout_seconds)
    return await run_in_threadpool(ensure_rate_limiter, owner)


async def _check_rate_limit_async(
    limiter: Any,
    key: str,
    *,
    limit_per_min: int,
    request_id: str | None = None,
    offload: AdmissionOffload | None = None,
    timeout_seconds: float | None = None,
) -> bool:
    """Evaluate sync and async limiter ports without treating coroutines as truthy.

    The async package-owned Redis limiter uses allow(limit=...) while the
    local API limiter uses check(limit_per_min=...). This adapter keeps the
    route policy single-sourced, carries the request identity across retries,
    and rejects malformed capabilities.
    """

    def invoke() -> object:
        # Resolve and bind a port BEFORE invoking it. Catching a TypeError from
        # inside a port and retrying would consume an allowance multiple times.
        allow = getattr(limiter, "allow", None)
        check = getattr(limiter, "check", None)
        candidates: list[tuple[tuple[object, ...], dict[str, object]]]
        if callable(allow):
            method = allow
            candidates = [
                ((key,), {"limit": limit_per_min, "window_seconds": 60.0, "request_id": request_id}),
                ((key,), {"limit": limit_per_min}),
                ((key,), {"limit_per_min": limit_per_min}),
                ((key, limit_per_min), {}),
            ]
        elif callable(check):
            method = check
            candidates = [((key,), {"limit_per_min": limit_per_min}), ((key, limit_per_min), {})]
        else:
            raise TypeError("configured rate limiter must expose check() or allow()")
        signature = inspect.signature(method)
        for args, kwargs in candidates:
            try:
                signature.bind(*args, **kwargs)
            except TypeError:
                continue
            return method(*args, **kwargs)
        raise TypeError("unsupported rate limiter signature")

    if offload is not None:
        if timeout_seconds is None:
            raise ValueError("admission requires an explicit deadline")
        # Authentication includes quota IO in its zero-queue, absolute request
        # budget. Sync ports never occupy the shared AnyIO pool; async ports
        # retain the same slot until real completion after cancellation.
        result = await offload.run(invoke, timeout=timeout_seconds, allow_awaitable=True)
        return result is True
    # Other callers retain their existing compatibility boundary.
    result = await run_in_threadpool(invoke)
    if inspect.isawaitable(result):
        result = await result
    return result is True


async def check_rate_limit_async(
    limiter: Any,
    key: str,
    *,
    limit_per_min: int,
    request_id: str | None = None,
    offload: AdmissionOffload | None = None,
    timeout_seconds: float | None = None,
) -> bool:
    """Evaluate the rate-limit backend inside a bounded Redis stage span."""

    with stage_span(
        "redis.rate_limit",
        attributes={"redis.operation": "rate_limit"},
    ) as span:
        try:
            return await _check_rate_limit_async(
                limiter,
                key,
                limit_per_min=limit_per_min,
                request_id=request_id,
                offload=offload,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            record_safe_exception(span, exc)
            raise


def is_production_rate_limiter(limiter: object) -> bool:
    """Return whether a limiter carries an explicit distributed capability mark."""

    return (
        limiter is not None
        and getattr(limiter, "production_safe", False) is True
        and getattr(limiter, "backend_kind", None) in {"redis", "distributed"}
        and (
            callable(getattr(limiter, "allow", None))
            or callable(getattr(limiter, "check", None))
        )
    )
