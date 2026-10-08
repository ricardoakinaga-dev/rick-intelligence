"""Finite, awaited cleanup for cancellation-cooperative async resources.

One response has a 0.25 s close budget, plus at most 0.125 s to drain an
interrupted read. The facade reserves 0.5 s each for draining a delegated read and closing
its iterator/stream (1.0 s total). Cleanup runs in one owned task, shielded from caller cancellation and always joined.
No fire-and-forget generator close or wait_for cancellation tail is used.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

import httpx
from httpx._client import BoundAsyncStream

RESPONSE_CLEANUP_SECONDS = 0.25
READ_DRAIN_SECONDS = 0.125
FACADE_CLEANUP_SECONDS = 0.5
_LOG = logging.getLogger(__name__)


class CleanupError(RuntimeError):
    def __init__(self):
        super().__init__('Provider resource cleanup failed.')


class _OwnedTransport(httpx.AsyncBaseTransport):
    """Remember completion independently of HTTPX's client CLOSED flag."""

    def __init__(self, transport: httpx.AsyncBaseTransport):
        self.transport = transport
        self.closed = False

    async def handle_async_request(self, request):
        return await self.transport.handle_async_request(request)

    async def aclose(self):
        if not self.closed:
            if await self.transport.aclose() is False:
                raise CleanupError()
            self.closed = True


class ClientCloseObligation:
    """For owned clients only; retry unfinished transports, never CLOSED clients.

    HTTPX 0.27.0 sets CLOSED before awaiting its transports. Wrap each owned
    transport before the first close so successes occur once and failures
    remain observable. Callers provide a bounded budget and the owning loop.
    Non-HTTPX test ports keep their ordinary retryable aclose contract.
    """

    def __init__(self, client):
        self.client = client
        self.started = False
        self.complete = False
        self._loop = None
        self._lock = asyncio.Lock()
        self.transports = []
        if isinstance(client, httpx.AsyncClient):
            wrappers = {}

            def own(transport):
                if transport is None:
                    return None
                if id(transport) not in wrappers:
                    wrappers[id(transport)] = _OwnedTransport(transport)
                return wrappers[id(transport)]

            # Pinned HTTPX transport ownership includes proxy mounts.
            client._transport = own(client._transport)
            client._mounts = {key: own(value) for key, value in client._mounts.items()}
            self.transports = list(wrappers.values())

    async def aclose(self):
        if self.complete:
            return
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        if self._loop is not loop:
            raise CleanupError()
        async with self._lock:
            if self.complete:
                return
            await self._close()
            self.complete = True

    async def _close(self):
        if not self.started or not self.transports:
            self.started = True
            if await self.client.aclose() is False:
                raise CleanupError()
            return
        failed = False
        for transport in self.transports:
            try:
                await transport.aclose()
            except Exception:
                failed = True
        if failed:
            raise CleanupError()


async def bounded_cleanup(closers: list[Callable[[], Awaitable[object]]], *, budget=RESPONSE_CLEANUP_SECONDS):
    async def close_all():
        failed = False
        deadline = asyncio.get_running_loop().time() + budget
        for index, close in enumerate(closers):
            # Reserve time for later resources even when the first close stalls.
            slot = max(0, deadline - asyncio.get_running_loop().time()) / (len(closers) - index)
            try:
                limit = asyncio.timeout(slot)
                async with limit:
                    if await close() is False:
                        raise CleanupError()
                # A closer may swallow cancellation and return. Expiring the
                # budget still means cleanup failed, even without an exception.
                if limit.expired():
                    raise CleanupError()
            except (Exception, asyncio.CancelledError):
                if not failed:
                    _LOG.error('provider_cleanup_failed component=%d', index)
                failed = True
        if failed:
            raise CleanupError()
    task = asyncio.create_task(close_all(), name='provider-cleanup')
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            break
    # Retrieve every exception; cancellation remains control flow.
    if cancelled:
        if not task.cancelled():
            task.exception()
        raise asyncio.CancelledError
    return task.result()


async def await_io(awaitable: Awaitable, deadline: float | None, *, drain_budget=READ_DRAIN_SECONDS):
    """Bound a read and await its cancellation finalizer before returning."""
    task = asyncio.ensure_future(awaitable)
    interrupted = None
    try:
        done, _ = await asyncio.wait({task}, timeout=None if deadline is None else max(0, deadline - asyncio.get_running_loop().time()))
        if done:
            return task.result()
        interrupted = TimeoutError()
    except asyncio.CancelledError as exc:
        interrupted = exc
    task.cancel()

    async def drain():
        try:
            await task
        except asyncio.CancelledError:
            pass
    try:
        await bounded_cleanup([drain], budget=drain_budget)
    except CleanupError:
        _LOG.error('provider_read_cleanup_after_failure code=%s', type(interrupted).__name__)
        if isinstance(interrupted, asyncio.CancelledError):
            raise interrupted
        raise
    raise interrupted


class _TrackedStream(httpx.AsyncByteStream):
    def __init__(self, stream, owner, *, defer_close=False):
        self.stream, self.owner, self.defer_close = stream, owner, defer_close
    def __aiter__(self):
        return self.owner.track(aiter(self.stream))
    async def aclose(self):
        if not self.defer_close:
            await self.stream.aclose()


class ResponseCleanup:
    """Retain original iterators behind HTTPX's decoding and byte wrappers.

    HTTPX 0.27's BoundAsyncStream uses async-for without aclosing. Capture its
    inner iterator too; closing only the outer generator schedules inner
    finalization after return. Keep HTTPX's native decoder/elapsed behavior.
    """
    def __init__(self, response):
        self.response = response
        self.iterators = []
        self.stream = response.stream
        if isinstance(self.stream, BoundAsyncStream):
            self.stream._stream = _TrackedStream(self.stream._stream, self)
        response.stream = _TrackedStream(self.stream, self, defer_close=True)
        self.original_raw = response.aiter_raw
        self.original_bytes = response.aiter_bytes
        response.aiter_raw = lambda *a, **kw: self.track(self.original_raw(*a, **kw))
        response.aiter_bytes = lambda *a, **kw: self.track(self.original_bytes(*a, **kw))

    def track(self, iterator):
        self.iterators.append(iterator)
        return iterator

    async def close(self):
        closers = [iterator.aclose for iterator in reversed(self.iterators)
                   if callable(getattr(iterator, 'aclose', None))]
        closers.append(self.stream.aclose)
        try:
            await bounded_cleanup(closers)
        finally:
            self.response.is_closed = True
            # Restore public response methods and break retained bound-method
            # references after all generators have been awaited.
            self.response.aiter_raw = self.original_raw
            self.response.aiter_bytes = self.original_bytes
            self.iterators.clear()
