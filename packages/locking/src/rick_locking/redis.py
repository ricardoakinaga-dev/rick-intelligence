"""Optional Redis-backed owner-safe lease backend.

The package deliberately does not depend on or construct a Redis client.  A
caller injects an async Redis-like client, such as ``redis.asyncio.Redis``.
This keeps importing the locking package side-effect free and makes the
adapter deterministic to exercise with a small local double.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import Protocol

from rick_locking.client import LeaseClient, OwnerFactory
from rick_locking.errors import LeaseError, LeaseErrorCode, LeaseOperation
from rick_locking.validation import (
    correlation_id_for,
    validate_key,
    validate_owner,
    validate_timeout,
    validate_ttl,
)


class AsyncRedisLike(Protocol):
    """The smallest async Redis surface required by :class:`RedisLeaseStore`.

    ``redis.asyncio.Redis`` satisfies this protocol, but importing that
    optional dependency remains the caller's responsibility.
    """

    async def set(
        self,
        name: str,
        value: str,
        *,
        nx: bool,
        px: int,
    ) -> object: ...

    async def eval(self, script: str, numkeys: int, *keys_and_args: object) -> object: ...


RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""

RENEW_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('pexpire', KEYS[1], ARGV[2])
end
return 0
"""


def _redis_error_code(error: Exception) -> LeaseErrorCode:
    """Map backend failures without inspecting or exposing their messages."""

    if isinstance(error, LeaseError):
        return error.code

    error_type = type(error)
    type_name = error_type.__name__.lower()
    module_name = error_type.__module__.lower()

    # Redis clients commonly expose their own TimeoutError type, so classify
    # by the stable type name in addition to the stdlib exception hierarchy.
    if isinstance(error, TimeoutError) or "timeout" in type_name:
        return LeaseErrorCode.TIMEOUT

    # ConnectionError/OSError covers the stdlib network failures used by
    # Redis clients.  The named Redis transient failures do not reveal their
    # exception text and are safe to present as unavailable.
    if isinstance(error, (ConnectionError, OSError)) or type_name in {
        "busyloadingerror",
        "clusterdownerror",
        "connectionerror",
        "loadingerror",
        "readonlyerror",
        "rediserror",
        "tryagainerror",
    }:
        return LeaseErrorCode.UNAVAILABLE

    # Do not turn Redis command/script/data errors into a retryable outage.
    # This module check also supports compatible clients that expose a
    # RedisError hierarchy without being importable by this optional package.
    if module_name.startswith("redis.") and type_name.endswith("error"):
        return LeaseErrorCode.INTERNAL_ERROR

    return LeaseErrorCode.INTERNAL_ERROR


def _set_result(result: object, operation: LeaseOperation, correlation_id: str) -> bool:
    """Accept only the bounded success values emitted by Redis SET NX."""

    if result is None or result is False:
        return False
    if result is True:
        return True
    if type(result) is str and result == "OK":
        return True
    if type(result) is bytes and result == b"OK":
        return True
    raise LeaseError("internal_error", operation, correlation_id)


def _script_result(result: object, operation: LeaseOperation, correlation_id: str) -> bool:
    """Accept only Redis' integer 0/1 result for the Lua scripts."""

    if type(result) is int and result in {0, 1}:
        return result == 1
    raise LeaseError("internal_error", operation, correlation_id)


class RedisLeaseStore:
    """Low-level owner-safe lease backend over an injected async Redis client.

    Acquisition uses ``SET key owner NX PX ttl``.  Renewal and release each
    execute one Lua script that compares the stored owner and changes the key
    only when it matches.  The adapter never creates a connection itself.
    """

    def __init__(
        self,
        client: AsyncRedisLike,
        *,
        timeout: float = 5.0,
        close_client: bool = False,
    ) -> None:
        if client is None:
            raise ValueError("invalid redis client")
        if not callable(getattr(client, "set", None)) or not callable(
            getattr(client, "eval", None)
        ):
            raise ValueError("invalid redis client")

        constructor_corr = correlation_id_for("acquire", None)
        self._timeout = validate_timeout(timeout, "acquire", constructor_corr)
        self._client = client
        self._close_client = close_client
        self._closed = False

    async def _call(
        self,
        operation: LeaseOperation,
        correlation_id: str,
        call: Callable[[], Awaitable[object]],
    ) -> object:
        if self._closed:
            raise LeaseError("unavailable", operation, correlation_id)

        result: object | None = None
        failure_code: LeaseErrorCode | None = None
        try:
            async with asyncio.timeout(self._timeout):
                result = await call()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            failure_code = _redis_error_code(error)

        # Raise after leaving the except block so the backend exception is not
        # retained as a public error context.  Its text may contain a token or
        # a connection URL, neither of which belongs at this boundary.
        if failure_code is not None:
            raise LeaseError(failure_code, operation, correlation_id) from None
        return result

    def _validate(
        self,
        operation: LeaseOperation,
        key: str,
        owner: str,
        ttl_ms: int | None,
        correlation_id: str | None,
    ) -> tuple[str, str, int | None, str]:
        corr = correlation_id_for(operation, correlation_id)
        checked_key = validate_key(key, operation, corr)
        checked_owner = validate_owner(owner, operation, corr)
        checked_ttl = None if ttl_ms is None else validate_ttl(ttl_ms, operation, corr)
        return checked_key, checked_owner, checked_ttl, corr

    async def acquire(
        self,
        key: str,
        owner: str,
        ttl_ms: int,
        *,
        correlation_id: str | None = None,
    ) -> bool:
        checked_key, checked_owner, checked_ttl, corr = self._validate(
            "acquire", key, owner, ttl_ms, correlation_id
        )
        assert checked_ttl is not None
        result = await self._call(
            "acquire",
            corr,
            lambda: self._client.set(
                checked_key,
                checked_owner,
                nx=True,
                px=checked_ttl,
            ),
        )
        return _set_result(result, "acquire", corr)

    async def renew(
        self,
        key: str,
        owner: str,
        ttl_ms: int,
        *,
        correlation_id: str | None = None,
    ) -> bool:
        checked_key, checked_owner, checked_ttl, corr = self._validate(
            "renew", key, owner, ttl_ms, correlation_id
        )
        assert checked_ttl is not None
        result = await self._call(
            "renew",
            corr,
            lambda: self._client.eval(
                RENEW_SCRIPT,
                1,
                checked_key,
                checked_owner,
                checked_ttl,
            ),
        )
        return _script_result(result, "renew", corr)

    async def release(
        self,
        key: str,
        owner: str,
        *,
        correlation_id: str | None = None,
    ) -> bool:
        checked_key, checked_owner, _, corr = self._validate(
            "release", key, owner, None, correlation_id
        )
        result = await self._call(
            "release",
            corr,
            lambda: self._client.eval(
                RELEASE_SCRIPT,
                1,
                checked_key,
                checked_owner,
            ),
        )
        return _script_result(result, "release", corr)

    async def health_check(self) -> bool:
        """Check Redis liveness without changing a lease key."""

        ping = getattr(self._client, "ping", None)
        if not callable(ping):
            return False
        correlation = correlation_id_for("acquire", None)
        try:
            result = await self._call("acquire", correlation, lambda: ping())
        except LeaseError:
            return False
        return result is True or result == "PONG" or result == b"PONG"

    async def close(self) -> None:
        """Close the injected client only when ownership was explicitly given."""

        if self._closed:
            return
        self._closed = True
        if not self._close_client:
            return

        closer = getattr(self._client, "aclose", None)
        if not callable(closer):
            closer = getattr(self._client, "close", None)
        if not callable(closer):
            return

        try:
            async with asyncio.timeout(self._timeout):
                result = closer()
                if inspect.isawaitable(result):
                    await result
        except asyncio.CancelledError:
            raise
        except Exception:
            # Closing is best effort and must not disclose client details.
            return

    async def __aenter__(self) -> "RedisLeaseStore":
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        await self.close()


class RedisLeaseClient(LeaseClient):
    """Owner-generating :class:`LeaseClient` backed by :class:`RedisLeaseStore`."""

    def __init__(
        self,
        client: AsyncRedisLike,
        *,
        timeout: float = 5.0,
        close_client: bool = False,
        owner_factory: OwnerFactory | None = None,
        cleanup_timeout: float = 2.0,
    ) -> None:
        store = RedisLeaseStore(
            client,
            timeout=timeout,
            close_client=close_client,
        )
        kwargs: dict[str, object] = {"cleanup_timeout": cleanup_timeout}
        if owner_factory is not None:
            kwargs["owner_factory"] = owner_factory
        super().__init__(store, **kwargs)
        self.store = store

    async def close(self) -> None:
        await self.store.close()

    async def health_check(self) -> bool:
        return await self.store.health_check()


RedisLeaseBackend = RedisLeaseStore
RedisStore = RedisLeaseStore
RedisClient = RedisLeaseClient


__all__ = [
    "AsyncRedisLike",
    "RELEASE_SCRIPT",
    "RENEW_SCRIPT",
    "RedisClient",
    "RedisLeaseBackend",
    "RedisLeaseClient",
    "RedisLeaseStore",
    "RedisStore",
]
