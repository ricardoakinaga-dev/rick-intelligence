"""Owner-generating lease client and cancellation-safe handles."""

from __future__ import annotations

import asyncio
import secrets
from contextlib import asynccontextmanager
from typing import AsyncIterator, Awaitable, Callable

from rick_locking.errors import LeaseError, LeaseOperation
from rick_locking.protocols import LeaseBackend
from rick_locking.validation import (
    DEFAULT_CLEANUP_TIMEOUT_SECONDS,
    correlation_id_for,
    validate_cleanup_timeout,
    validate_key,
    validate_owner,
    validate_ttl,
)

OwnerFactory = Callable[[], str]


def generate_owner_token() -> str:
    """Generate a cryptographically random, bounded owner token."""

    return secrets.token_urlsafe(32)


async def _drain_task(task: asyncio.Task[object]) -> None:
    """Consume a cancelled cleanup task so it cannot become background work."""

    try:
        await task
    except BaseException:
        return


class LeaseHandle:
    """An owner-bound lease with async context-manager cleanup.

    The owner token is available for explicit low-level diagnostics through
    ``owner`` but is intentionally absent from ``repr`` and all errors.
    """

    def __init__(
        self,
        client: "LeaseClient",
        key: str,
        owner: str,
        ttl_ms: int,
        correlation_id: str,
    ) -> None:
        self._client = client
        self._key = key
        self._owner = owner
        self._ttl_ms = ttl_ms
        self._correlation_id = correlation_id
        self._state_lock = asyncio.Lock()
        self._released = False
        self._lost = False

    @property
    def key(self) -> str:
        return self._key

    @property
    def owner(self) -> str:
        """The owner token used for owner-safe backend operations."""

        return self._owner

    @property
    def owner_token(self) -> str:
        return self._owner

    @property
    def ttl_ms(self) -> int:
        return self._ttl_ms

    @property
    def correlation_id(self) -> str:
        return self._correlation_id

    @property
    def released(self) -> bool:
        return self._released

    @property
    def active(self) -> bool:
        return not self._released and not self._lost

    def __repr__(self) -> str:
        state = "released" if self._released else "lost" if self._lost else "active"
        return f"LeaseHandle(state={state!r})"

    async def renew(
        self,
        ttl_ms: int | None = None,
        *,
        correlation_id: str | None = None,
    ) -> bool:
        """Renew only this handle's exact owner value."""

        async with self._state_lock:
            if self._released or self._lost:
                return False
            effective_ttl = self._ttl_ms if ttl_ms is None else ttl_ms
            renewed = await self._client._renew_handle(
                self,
                effective_ttl,
                correlation_id=correlation_id,
            )
            if renewed:
                self._ttl_ms = effective_ttl
            else:
                self._lost = True
            return renewed

    async def release(self, *, correlation_id: str | None = None) -> bool:
        """Release only this handle's exact owner value."""

        async with self._state_lock:
            if self._released:
                return False
            released = await self._client._release_handle(
                self,
                correlation_id=correlation_id,
            )
            # A false result means the lease is already expired or absent. It
            # is safe to make the handle terminal; a later owner cannot be
            # affected by another release attempt.
            self._released = True
            if not released:
                self._lost = True
            return released

    async def _release_for_context(self) -> tuple[bool, LeaseError | None, bool]:
        """Attempt release despite cancellation and await its completion.

        The final flag records cancellation that arrived while cleanup was in
        progress.  It lets ``__aexit__`` preserve cancellation instead of
        accidentally turning a cancelled caller into a successful one.
        """

        cleanup_task: asyncio.Task[object] = asyncio.create_task(
            self.release(), name="rick-lock-release"
        )
        try:
            try:
                return bool(
                    await asyncio.wait_for(
                        asyncio.shield(cleanup_task),
                        timeout=self._client.cleanup_timeout,
                    )
                ), None, False
            except LeaseError as error:
                return False, error, False
            except asyncio.TimeoutError:
                if not cleanup_task.done():
                    cleanup_task.cancel()
                await _drain_task(cleanup_task)
                return (
                    False,
                    LeaseError("timeout", "release", self._correlation_id),
                    False,
                )
            except asyncio.CancelledError:
                # The cancellation belongs to the surrounding operation.
                # Keep the owner-bound release alive, but keep it bounded and
                # drain the task before returning so no unowned background
                # task remains.
                try:
                    return bool(
                        await asyncio.wait_for(
                            asyncio.shield(cleanup_task),
                            timeout=self._client.cleanup_timeout,
                        )
                    ), None, True
                except LeaseError as error:
                    return False, error, True
                except asyncio.TimeoutError:
                    if not cleanup_task.done():
                        cleanup_task.cancel()
                    await _drain_task(cleanup_task)
                    return (
                        False,
                        LeaseError("timeout", "release", self._correlation_id),
                        True,
                    )
                except asyncio.CancelledError:
                    if not cleanup_task.done():
                        cleanup_task.cancel()
                    await _drain_task(cleanup_task)
                    return False, None, True
        finally:
            if not cleanup_task.done():
                cleanup_task.cancel()
                await _drain_task(cleanup_task)

    async def __aenter__(self) -> "LeaseHandle":
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> bool:
        cleanup_error: LeaseError | None = None
        cleanup_cancelled = False
        try:
            _, cleanup_error, cleanup_cancelled = await self._release_for_context()
        except asyncio.CancelledError:
            cleanup_cancelled = True

        if exc_type is None:
            if cleanup_error is not None:
                raise cleanup_error
            if cleanup_cancelled:
                raise asyncio.CancelledError
        # A failure in finally must not mask the original application error.
        return False

    def start_heartbeat(self, interval_ms: int | None = None):
        """Start an optional cancellable renewal heartbeat for this handle."""

        from rick_locking.heartbeat import start_heartbeat

        return start_heartbeat(self, interval_ms)

    def heartbeat(self, interval_ms: int | None = None):
        """Return a caller-owned heartbeat context for this handle."""

        from rick_locking.heartbeat import LeaseHeartbeat

        return LeaseHeartbeat(self, interval_ms)


class LeaseClient:
    """Create owner-safe handles over an async :class:`LeaseBackend`."""

    def __init__(
        self,
        backend: LeaseBackend,
        *,
        owner_factory: OwnerFactory = generate_owner_token,
        cleanup_timeout: float = DEFAULT_CLEANUP_TIMEOUT_SECONDS,
    ) -> None:
        if not callable(owner_factory):
            raise ValueError("invalid owner factory")
        self._backend = backend
        self._owner_factory = owner_factory
        self.cleanup_timeout = validate_cleanup_timeout(cleanup_timeout)

    @property
    def backend(self) -> LeaseBackend:
        return self._backend

    async def _call_backend(
        self,
        operation: LeaseOperation,
        correlation_id: str,
        call: Callable[[], Awaitable[object]],
    ) -> object:
        result: object | None = None
        failure: LeaseError | None = None
        try:
            result = await call()  # type: ignore[misc]
        except LeaseError as error:
            failure = LeaseError(error.code, operation, correlation_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            failure = LeaseError("internal_error", operation, correlation_id)
        if failure is not None:
            raise failure from None
        return result

    async def acquire(
        self,
        key: str,
        ttl_ms: int,
        *,
        correlation_id: str | None = None,
    ) -> LeaseHandle | None:
        operation: LeaseOperation = "acquire"
        corr = correlation_id_for(operation, correlation_id)
        checked_key = validate_key(key, operation, corr)
        checked_ttl = validate_ttl(ttl_ms, operation, corr)

        owner: str
        factory_failure = False
        generated_owner: str | None = None
        try:
            generated_owner = self._owner_factory()
        except Exception:
            factory_failure = True
        if factory_failure:
            raise LeaseError("internal_error", operation, corr)
        assert generated_owner is not None
        owner = validate_owner(generated_owner, operation, corr)

        result = await self._call_backend(
            operation,
            corr,
            lambda: self._backend.acquire(
                checked_key,
                owner,
                checked_ttl,
                correlation_id=corr,
            ),
        )
        if type(result) is not bool:
            raise LeaseError("internal_error", operation, corr)
        if not result:
            return None
        return LeaseHandle(self, checked_key, owner, checked_ttl, corr)

    async def _renew_handle(
        self,
        handle: LeaseHandle,
        ttl_ms: int,
        *,
        correlation_id: str | None,
    ) -> bool:
        operation: LeaseOperation = "renew"
        corr = correlation_id_for(operation, correlation_id)
        self._assert_owned_handle(handle, operation, corr)
        checked_ttl = validate_ttl(ttl_ms, operation, corr)
        result = await self._call_backend(
            operation,
            corr,
            lambda: self._backend.renew(
                handle._key,
                handle._owner,
                checked_ttl,
                correlation_id=corr,
            ),
        )
        if type(result) is not bool:
            raise LeaseError("internal_error", operation, corr)
        return result

    async def _release_handle(
        self,
        handle: LeaseHandle,
        *,
        correlation_id: str | None,
    ) -> bool:
        operation: LeaseOperation = "release"
        corr = correlation_id_for(operation, correlation_id)
        self._assert_owned_handle(handle, operation, corr)
        result = await self._call_backend(
            operation,
            corr,
            lambda: self._backend.release(
                handle._key,
                handle._owner,
                correlation_id=corr,
            ),
        )
        if type(result) is not bool:
            raise LeaseError("internal_error", operation, corr)
        return result

    def _assert_owned_handle(
        self, handle: LeaseHandle, operation: LeaseOperation, correlation_id: str
    ) -> None:
        if not isinstance(handle, LeaseHandle) or handle._client is not self:
            raise LeaseError("invalid_request", operation, correlation_id)

    async def renew(
        self,
        handle: LeaseHandle,
        ttl_ms: int | None = None,
        *,
        correlation_id: str | None = None,
    ) -> bool:
        """Renew a handle, retaining its original TTL when omitted."""

        if not isinstance(handle, LeaseHandle):
            operation: LeaseOperation = "renew"
            corr = correlation_id_for(operation, correlation_id)
            raise LeaseError("invalid_request", operation, corr)
        operation: LeaseOperation = "renew"
        corr = correlation_id_for(operation, correlation_id)
        self._assert_owned_handle(handle, operation, corr)
        effective_ttl = handle.ttl_ms if ttl_ms is None else ttl_ms
        return await handle.renew(effective_ttl, correlation_id=corr)

    async def release(
        self,
        handle: LeaseHandle,
        *,
        correlation_id: str | None = None,
    ) -> bool:
        """Release a handle using its captured owner token."""

        if not isinstance(handle, LeaseHandle):
            operation: LeaseOperation = "release"
            corr = correlation_id_for(operation, correlation_id)
            raise LeaseError("invalid_request", operation, corr)
        operation: LeaseOperation = "release"
        corr = correlation_id_for(operation, correlation_id)
        self._assert_owned_handle(handle, operation, corr)
        return await handle.release(correlation_id=corr)

    async def acquire_owned(
        self,
        key: str,
        owner: str,
        ttl_ms: int,
        *,
        correlation_id: str | None = None,
    ) -> bool:
        """Use the backend directly for adapters that already own a token."""

        operation: LeaseOperation = "acquire"
        corr = correlation_id_for(operation, correlation_id)
        checked_key = validate_key(key, operation, corr)
        checked_owner = validate_owner(owner, operation, corr)
        checked_ttl = validate_ttl(ttl_ms, operation, corr)
        result = await self._call_backend(
            operation,
            corr,
            lambda: self._backend.acquire(
                checked_key,
                checked_owner,
                checked_ttl,
                correlation_id=corr,
            ),
        )
        if type(result) is not bool:
            raise LeaseError("internal_error", operation, corr)
        return result

    async def renew_owned(
        self,
        key: str,
        owner: str,
        ttl_ms: int,
        *,
        correlation_id: str | None = None,
    ) -> bool:
        operation: LeaseOperation = "renew"
        corr = correlation_id_for(operation, correlation_id)
        checked_key = validate_key(key, operation, corr)
        checked_owner = validate_owner(owner, operation, corr)
        checked_ttl = validate_ttl(ttl_ms, operation, corr)
        result = await self._call_backend(
            operation,
            corr,
            lambda: self._backend.renew(
                checked_key,
                checked_owner,
                checked_ttl,
                correlation_id=corr,
            ),
        )
        if type(result) is not bool:
            raise LeaseError("internal_error", operation, corr)
        return result

    async def release_owned(
        self,
        key: str,
        owner: str,
        *,
        correlation_id: str | None = None,
    ) -> bool:
        operation: LeaseOperation = "release"
        corr = correlation_id_for(operation, correlation_id)
        checked_key = validate_key(key, operation, corr)
        checked_owner = validate_owner(owner, operation, corr)
        result = await self._call_backend(
            operation,
            corr,
            lambda: self._backend.release(
                checked_key,
                checked_owner,
                correlation_id=corr,
            ),
        )
        if type(result) is not bool:
            raise LeaseError("internal_error", operation, corr)
        return result

    @asynccontextmanager
    async def lease(
        self,
        key: str,
        ttl_ms: int,
        *,
        correlation_id: str | None = None,
    ) -> AsyncIterator[LeaseHandle | None]:
        """Acquire and release a lease around an async context body."""

        handle = await self.acquire(key, ttl_ms, correlation_id=correlation_id)
        if handle is None:
            yield None
            return
        async with handle:
            yield handle

    async def close(self) -> None:
        """No-op for local clients; HTTP clients override this hook."""

        return None

    async def __aenter__(self) -> "LeaseClient":
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        await self.close()


# A name that reads naturally in dependency declarations.
LeaseManager = LeaseClient


__all__ = ["LeaseClient", "LeaseHandle", "LeaseManager", "generate_owner_token"]
