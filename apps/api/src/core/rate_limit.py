"""Small rate-limit primitives shared by public and authenticated routes."""

from __future__ import annotations

from collections import defaultdict, deque
import threading
import time
from typing import Any


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
            return bool(check(key, limit_per_min=limit_per_min))
        except TypeError:
            return bool(check(key, limit_per_min))
    allow = getattr(limiter, "allow", None)
    if callable(allow):
        try:
            return bool(allow(key, limit_per_min=limit_per_min))
        except TypeError:
            return bool(allow(key, limit_per_min))
    raise TypeError("configured rate limiter must expose check() or allow()")
