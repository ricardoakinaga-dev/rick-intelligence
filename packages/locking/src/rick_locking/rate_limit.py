"""Async distributed rate limiting for the locking package.

``RedisRateLimiter`` uses one atomic Lua script per decision.  It stores a
short-lived request decision alongside the bucket so an explicitly supplied
request ID can be replayed without double-counting after an uncertain network
response.  Backend errors return ``False``: a rate-limit boundary must fail
closed and must never silently fall back to process memory.
"""

from __future__ import annotations

from collections import OrderedDict, deque
from collections.abc import Callable
import hashlib
import math
import os
import re
import threading
import time
from typing import Protocol

from rick_locking.errors import LeaseError
from rick_locking.redis import (
    AsyncRedisLike,
    _RedisCommandExecutor,
    _script_result,
)
from rick_locking.redis_config import (
    _PRODUCTION_CAPABILITY_TOKEN,
    RedisCircuitBreaker,
    RedisNamespace,
    RedisRetryPolicy,
)
from rick_locking.validation import correlation_id_for, new_correlation_id, validate_key


MAX_RATE_LIMIT = 1_000_000
MAX_RATE_WINDOW_SECONDS = 86_400.0
MAX_RATE_KEYS = 100_000
_LOCAL_ENVIRONMENTS = frozenset({"test", "testing", "development", "dev", "local"})
_DEPLOYED_ENVIRONMENTS = frozenset({"production", "prod", "live", "staging"})
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class RateLimiter(Protocol):
    """Async rate-limit port owned by the package boundary."""

    async def allow(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: float = 60.0,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> bool: ...

    async def check(
        self,
        key: str,
        *,
        limit_per_min: int,
        correlation_id: str | None = None,
    ) -> bool: ...


RATE_LIMIT_SCRIPT = """
local previous = redis.call('get', KEYS[2])
if previous then
    return tonumber(previous)
end
local count = redis.call('incr', KEYS[1])
if count == 1 then
    redis.call('pexpire', KEYS[1], ARGV[1])
end
local allowed = 0
if count <= tonumber(ARGV[2]) then
    allowed = 1
end
redis.call('set', KEYS[2], allowed, 'PX', ARGV[1])
return allowed
"""


def _validated_window(value: object) -> int | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0.001 <= float(value) <= MAX_RATE_WINDOW_SECONDS
    ):
        return None
    milliseconds = int(round(float(value) * 1_000.0))
    return milliseconds if milliseconds >= 1 else None


def _validated_request_id(value: object) -> str | None:
    if not isinstance(value, str) or _REQUEST_ID.fullmatch(value) is None:
        return None
    return value


class RedisRateLimiter:
    """Atomic fixed-window Redis rate limiter with tenant-safe keying."""

    def __init__(
        self,
        client: AsyncRedisLike,
        *,
        namespace: RedisNamespace,
        timeout: float = 5.0,
        close_client: bool = False,
        retry_policy: RedisRetryPolicy | None = None,
        circuit_breaker: RedisCircuitBreaker | None = None,
    ) -> None:
        if client is None or not callable(getattr(client, "eval", None)):
            raise ValueError("invalid redis client")
        if not isinstance(namespace, RedisNamespace):
            raise ValueError("invalid redis namespace")
        self._client = client
        self.namespace = namespace
        self._executor = _RedisCommandExecutor(
            client,
            timeout=timeout,
            retry_policy=retry_policy,
            circuit_breaker=circuit_breaker,
            close_client=close_client,
        )
        self.production_safe = False
        self.backend_kind = "redis"

    def _mark_production_safe(self, token: object) -> None:
        if token is _PRODUCTION_CAPABILITY_TOKEN:
            self.production_safe = True

    async def allow(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: float = 60.0,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> bool:
        """Consume one token, returning ``False`` for invalid/unavailable paths."""

        try:
            correlation = correlation_id_for("acquire", correlation_id)
            checked_key = validate_key(key, "acquire", correlation)
        except LeaseError:
            return False
        if type(limit) is not int or not 1 <= limit <= MAX_RATE_LIMIT:
            return False
        window_ms = _validated_window(window_seconds)
        if window_ms is None:
            return False
        if request_id is None:
            checked_request_id = new_correlation_id()
        else:
            checked_request_id = _validated_request_id(request_id)
            if checked_request_id is None:
                return False
        try:
            bucket_material = hashlib.sha256(
                f"{checked_key}\x1f{window_ms}".encode("utf-8")
            ).hexdigest()
            bucket_key = self.namespace.key("rate-bucket", bucket_material)
            # Include the bucket fingerprint in the request key so reusing a
            # request ID for a different logical limiter cannot collide.
            request_material = (
                bucket_material
                + ":"
                + checked_request_id
            )
            request_key = self.namespace.key("rate-request", request_material)
        except Exception:
            return False

        try:
            # INCR changes accounting, so this script is intentionally one
            # attempt.  Its request marker makes caller-level replay safe when
            # the same request ID is supplied; retrying an unmarked counter
            # would turn an outage into a burst of extra tokens.
            result = await self._executor.call(
                "acquire",
                correlation,
                lambda: self._client.eval(
                    RATE_LIMIT_SCRIPT,
                    2,
                    bucket_key,
                    request_key,
                    window_ms,
                    limit,
                ),
                retry=False,
            )
            return _script_result(result, "acquire", correlation)
        except LeaseError:
            return False

    async def check(
        self,
        key: str,
        *,
        limit_per_min: int,
        correlation_id: str | None = None,
    ) -> bool:
        """Compatibility spelling for a one-minute fixed-window decision."""

        return await self.allow(
            key,
            limit=limit_per_min,
            window_seconds=60.0,
            correlation_id=correlation_id,
        )

    async def health_check(self) -> bool:
        ping = getattr(self._client, "ping", None)
        if not callable(ping):
            return False
        correlation = correlation_id_for("acquire", None)
        try:
            result = await self._executor.call("acquire", correlation, lambda: ping())
        except LeaseError:
            return False
        return result is True or result == "PONG" or result == b"PONG"

    async def readiness_check(self) -> bool:
        return self.production_safe and await self.health_check()

    async def close(self) -> None:
        await self._executor.close()

    async def __aenter__(self) -> "RedisRateLimiter":
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        await self.close()


class InMemoryRateLimiter:
    """Bounded local limiter explicitly restricted to test/development use."""

    production_safe = False
    backend_kind = "memory"

    def __init__(
        self,
        *,
        window_seconds: float = 60.0,
        max_keys: int = 10_000,
        mode: str = "test",
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if mode not in _LOCAL_ENVIRONMENTS or os.environ.get(
            "RICK_ENV", ""
        ).strip().lower() in _DEPLOYED_ENVIRONMENTS:
            raise ValueError("in-memory rate limiter is local-only")
        if _validated_window(window_seconds) is None:
            raise ValueError("invalid rate-limit window")
        if type(max_keys) is not int or not 1 <= max_keys <= MAX_RATE_KEYS:
            raise ValueError("invalid rate-limit key bound")
        if not callable(clock):
            raise ValueError("invalid rate-limit clock")
        self.window_seconds = float(window_seconds)
        self.max_keys = max_keys
        self.mode = mode
        self._clock = clock
        self._events: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    async def allow(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: float | None = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
    ) -> bool:
        try:
            correlation = correlation_id_for("acquire", correlation_id)
            checked_key = validate_key(key, "acquire", correlation)
        except LeaseError:
            return False
        if type(limit) is not int or not 1 <= limit <= MAX_RATE_LIMIT:
            return False
        effective_window = self.window_seconds if window_seconds is None else window_seconds
        if _validated_window(effective_window) is None:
            return False
        try:
            now = float(self._clock())
        except Exception:
            return False
        if not math.isfinite(now):
            return False
        with self._lock:
            events = self._events.get(checked_key)
            if events is None:
                if len(self._events) >= self.max_keys:
                    self._events.popitem(last=False)
                events = deque()
                self._events[checked_key] = events
            cutoff = now - float(effective_window)
            while events and events[0] <= cutoff:
                events.popleft()
            self._events.move_to_end(checked_key)
            if len(events) >= limit:
                return False
            events.append(now)
            return True

    async def check(
        self,
        key: str,
        *,
        limit_per_min: int,
        correlation_id: str | None = None,
    ) -> bool:
        return await self.allow(
            key,
            limit=limit_per_min,
            window_seconds=self.window_seconds,
            correlation_id=correlation_id,
        )

    async def health_check(self) -> bool:
        return False

    async def readiness_check(self) -> bool:
        return False

    async def close(self) -> None:
        return None


__all__ = [
    "InMemoryRateLimiter",
    "MAX_RATE_KEYS",
    "MAX_RATE_LIMIT",
    "MAX_RATE_WINDOW_SECONDS",
    "RATE_LIMIT_SCRIPT",
    "RateLimiter",
    "RedisRateLimiter",
]
