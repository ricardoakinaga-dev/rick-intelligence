"""Redis-backed owner-safe leases with bounded resilience semantics.

The low-level adapter accepts an injected async client so deterministic tests
remain dependency-free.  The production composition helpers in
``redis_config`` construct the real ``redis.asyncio`` client with a bounded
pool.  Lease writes use owner-safe Redis primitives; acquisition and renewal
may be retried within a total operation deadline, while release remains a
single attempt because replaying an ambiguous delete cannot distinguish a
successful release from an already-expired lease.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import Protocol

from rick_locking.client import LeaseClient, OwnerFactory
from rick_locking.errors import LeaseError, LeaseErrorCode, LeaseOperation
from rick_locking.redis_config import (
    _PRODUCTION_CAPABILITY_TOKEN,
    RedisCircuitBreaker,
    RedisNamespace,
    RedisRetryPolicy,
)
from rick_locking.validation import (
    correlation_id_for,
    validate_key,
    validate_owner,
    validate_timeout,
    validate_ttl,
)


_NO_RECONCILIATION = object()


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

    async def get(self, name: str) -> object: ...


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


class _RedisCommandExecutor:
    """Shared bounded timeout, retry, circuit, and close policy."""

    def __init__(
        self,
        client: AsyncRedisLike,
        *,
        timeout: float,
        retry_policy: RedisRetryPolicy | None = None,
        circuit_breaker: RedisCircuitBreaker | None = None,
        close_client: bool = False,
    ) -> None:
        self.client = client
        self.timeout = validate_timeout(
            timeout, "acquire", correlation_id_for("acquire", None)
        )
        self.retry_policy = retry_policy or RedisRetryPolicy.single_attempt()
        if not isinstance(self.retry_policy, RedisRetryPolicy):
            raise ValueError("invalid redis retry policy")
        self.circuit_breaker = circuit_breaker or RedisCircuitBreaker()
        if not isinstance(self.circuit_breaker, RedisCircuitBreaker):
            raise ValueError("invalid redis circuit breaker")
        self.close_client = close_client
        self.closed = False

    async def call(
        self,
        operation: LeaseOperation,
        correlation_id: str,
        call: Callable[[], Awaitable[object]],
        *,
        retry: bool = True,
        reconcile: Callable[[], Awaitable[object]] | None = None,
    ) -> object:
        if self.closed:
            raise LeaseError("unavailable", operation, correlation_id)
        generation = self.circuit_breaker.begin_call()
        if generation is None:
            raise LeaseError("unavailable", operation, correlation_id)

        policy = self.retry_policy if retry else RedisRetryPolicy.single_attempt()
        deadline = asyncio.get_running_loop().time() + self.timeout
        failure_code: LeaseErrorCode | None = None
        for attempt in range(policy.max_attempts):
            try:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0.0:
                    raise asyncio.TimeoutError
                async with asyncio.timeout(remaining):
                    result = await call()
            except asyncio.CancelledError:
                self.circuit_breaker.release_call(generation)
                raise
            except Exception as error:
                failure_code = _redis_error_code(error)
            else:
                self.circuit_breaker.record_success(generation)
                return result

            if (
                failure_code not in {LeaseErrorCode.TIMEOUT, LeaseErrorCode.UNAVAILABLE}
                or attempt + 1 >= policy.max_attempts
            ):
                break
            if reconcile is not None:
                try:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining > 0.0:
                        async with asyncio.timeout(remaining):
                            reconciled = await reconcile()
                        if reconciled is not _NO_RECONCILIATION:
                            self.circuit_breaker.record_success(generation)
                            return reconciled
                except asyncio.CancelledError:
                    self.circuit_breaker.release_call(generation)
                    raise
                except Exception:
                    # A failed reconciliation leaves the original transient
                    # failure in force; the bounded retry may still proceed.
                    pass
            delay = policy.delay_seconds(attempt + 1)
            remaining = deadline - asyncio.get_running_loop().time()
            if delay > remaining:
                break
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                self.circuit_breaker.release_call(generation)
                raise

        if failure_code in {LeaseErrorCode.TIMEOUT, LeaseErrorCode.UNAVAILABLE}:
            self.circuit_breaker.record_failure(generation)
        else:
            self.circuit_breaker.release_call(generation)
        raise LeaseError(
            failure_code or LeaseErrorCode.INTERNAL_ERROR,
            operation,
            correlation_id,
        ) from None

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if not self.close_client:
            return
        closer = getattr(self.client, "aclose", None)
        if not callable(closer):
            closer = getattr(self.client, "close", None)
        if not callable(closer):
            return
        try:
            async with asyncio.timeout(self.timeout):
                result = closer()
                if inspect.isawaitable(result):
                    await result
        except asyncio.CancelledError:
            raise
        except Exception:
            return


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
        namespace: RedisNamespace | None = None,
        retry_policy: RedisRetryPolicy | None = None,
        circuit_breaker: RedisCircuitBreaker | None = None,
    ) -> None:
        if client is None:
            raise ValueError("invalid redis client")
        if not callable(getattr(client, "set", None)) or not callable(
            getattr(client, "eval", None)
        ):
            raise ValueError("invalid redis client")

        if namespace is not None and not isinstance(namespace, RedisNamespace):
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

    @property
    def redis_client(self) -> AsyncRedisLike:
        """Return the exact injected client for composition identity checks."""

        return self._client

    def _mark_production_safe(self, token: object) -> None:
        """Mark only a validated package factory product as production-safe."""

        if token is _PRODUCTION_CAPABILITY_TOKEN:
            self.production_safe = True

    @property
    def _timeout(self) -> float:
        return self._executor.timeout

    @property
    def _closed(self) -> bool:
        return self._executor.closed

    def _redis_key(
        self,
        operation: LeaseOperation,
        key: str,
        correlation_id: str,
    ) -> str:
        checked_key = validate_key(key, operation, correlation_id)
        if self.namespace is None:
            return checked_key
        try:
            return self.namespace.key("lease", checked_key)
        except Exception:
            raise LeaseError("invalid_request", operation, correlation_id) from None

    async def _reconcile_acquire(
        self,
        redis_key: str,
        owner: str,
    ) -> object:
        """Disambiguate a lost SET response when the injected client supports GET."""

        getter = getattr(self._client, "get", None)
        if not callable(getter):
            return _NO_RECONCILIATION
        value = await getter(redis_key)
        if value is None:
            return _NO_RECONCILIATION
        if isinstance(value, bytes):
            matches_owner = value == owner.encode("utf-8")
        else:
            matches_owner = value == owner
        if matches_owner:
            return True
        return False

    async def _call(
        self,
        operation: LeaseOperation,
        correlation_id: str,
        call: Callable[[], Awaitable[object]],
        *,
        retry: bool = True,
        reconcile: Callable[[], Awaitable[object]] | None = None,
    ) -> object:
        return await self._executor.call(
            operation,
            correlation_id,
            call,
            retry=retry,
            reconcile=reconcile,
        )

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
        redis_key = self._redis_key("acquire", checked_key, corr)
        result = await self._call(
            "acquire",
            corr,
            lambda: self._client.set(
                redis_key,
                checked_owner,
                nx=True,
                px=checked_ttl,
            ),
            reconcile=lambda: self._reconcile_acquire(redis_key, checked_owner),
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
        redis_key = self._redis_key("renew", checked_key, corr)
        result = await self._call(
            "renew",
            corr,
            lambda: self._client.eval(
                RENEW_SCRIPT,
                1,
                redis_key,
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
        redis_key = self._redis_key("release", checked_key, corr)
        result = await self._call(
            "release",
            corr,
            lambda: self._client.eval(
                RELEASE_SCRIPT,
                1,
                redis_key,
                checked_owner,
            ),
            # A lost release response is ambiguous: retrying could report a
            # different result after expiry.  Cleanup remains bounded and
            # owner-safe, but this mutation is intentionally at-most-once.
            retry=False,
        )
        return _script_result(result, "release", corr)

    async def health_check(self) -> bool:
        """Check Redis liveness without changing a lease key."""

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
        """Require both a package-approved production mark and live Redis."""

        return self.production_safe and await self.health_check()

    async def close(self) -> None:
        """Close the injected client only when ownership was explicitly given."""

        await self._executor.close()

    async def __aenter__(self) -> "RedisLeaseStore":
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        await self.close()


class RedisLeaseClient(LeaseClient):
    """Owner-generating :class:`LeaseClient` backed by :class:`RedisLeaseStore`."""

    def __init__(
        self,
        client: AsyncRedisLike | None = None,
        *,
        timeout: float = 5.0,
        close_client: bool = False,
        owner_factory: OwnerFactory | None = None,
        cleanup_timeout: float = 2.0,
        namespace: RedisNamespace | None = None,
        retry_policy: RedisRetryPolicy | None = None,
        circuit_breaker: RedisCircuitBreaker | None = None,
        store: RedisLeaseStore | None = None,
    ) -> None:
        if store is not None:
            if client is not None or not isinstance(store, RedisLeaseStore):
                raise ValueError("invalid redis lease store")
            actual_store = store
        else:
            if client is None:
                raise ValueError("invalid redis client")
            actual_store = RedisLeaseStore(
                client,
                timeout=timeout,
                close_client=close_client,
                namespace=namespace,
                retry_policy=retry_policy,
                circuit_breaker=circuit_breaker,
            )
        kwargs: dict[str, object] = {"cleanup_timeout": cleanup_timeout}
        if owner_factory is not None:
            kwargs["owner_factory"] = owner_factory
        super().__init__(actual_store, **kwargs)
        self.store = actual_store
        self.production_safe = actual_store.production_safe
        self.backend_kind = "redis"

    @property
    def redis_client(self) -> AsyncRedisLike:
        """Return the exact client owned by the wrapped Redis store."""

        return self.store.redis_client

    @property
    def namespace(self) -> RedisNamespace | None:
        """Return the store namespace without exposing secret configuration."""

        return self.store.namespace

    async def close(self) -> None:
        await self.store.close()

    async def health_check(self) -> bool:
        return await self.store.health_check()

    async def readiness_check(self) -> bool:
        return await self.store.readiness_check()


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
