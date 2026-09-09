"""Small rate-limit primitives shared by public and authenticated routes."""

from __future__ import annotations

from collections import defaultdict, deque
import math
import inspect
import threading
import time
from typing import Any, Protocol


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


class InMemoryRateLimiter:
    """Thread-safe sliding-window limiter for hermetic/local execution.

    Production deployments must inject a distributed implementation through
    ``Providers.rate_limiter``. The local fallback is deliberately bounded by
    each configured window, but it is not a multi-replica security boundary.
    """

    def __init__(self, *, window_seconds: float = 60.0):
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, *, limit_per_min: int) -> bool:
        now = time.monotonic()
        with self._lock:
            events = self._events[key]
            while events and now - events[0] >= self.window_seconds:
                events.popleft()
            if len(events) >= limit_per_min:
                return False
            events.append(now)
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
        return bool(result)
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
        return bool(result)
    raise TypeError("configured rate limiter must expose check() or allow()")


async def check_rate_limit_async(
    limiter: Any,
    key: str,
    *,
    limit_per_min: int,
    request_id: str | None = None,
) -> bool:
    """Evaluate sync and async limiter ports without treating coroutines as truthy.

    The async package-owned Redis limiter uses allow(limit=...) while the
    local API limiter uses check(limit_per_min=...). This adapter keeps the
    route policy single-sourced and rejects malformed capabilities.
    """

    allow = getattr(limiter, "allow", None)
    if callable(allow):
        try:
            result = allow(
                key,
                limit=limit_per_min,
                window_seconds=60.0,
                request_id=request_id,
            )
        except TypeError:
            try:
                result = allow(key, limit=limit_per_min)
            except TypeError:
                result = allow(key, limit_per_min)
        if inspect.isawaitable(result):
            result = await result
        return bool(result)

    check = getattr(limiter, "check", None)
    if callable(check):
        try:
            result = check(key, limit_per_min=limit_per_min)
        except TypeError:
            result = check(key, limit_per_min)
        if inspect.isawaitable(result):
            result = await result
        return bool(result)
    raise TypeError("configured rate limiter must expose check() or allow()")


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
