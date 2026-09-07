"""Optional cancellable lease renewal heartbeat."""

from __future__ import annotations

import asyncio

from rick_locking.client import LeaseHandle
from rick_locking.errors import LeaseError
from rick_locking.validation import MAX_TTL_MS


class LeaseHeartbeat:
    """A caller-owned, single-task periodic renewal loop.

    The heartbeat renews the captured handle only.  It never performs a raw
    release and cancellation drains its one task before returning.
    """

    def __init__(self, handle: LeaseHandle, interval_ms: int | None = None) -> None:
        if not isinstance(handle, LeaseHandle):
            raise ValueError("invalid lease handle")
        interval = handle.ttl_ms // 3 if interval_ms is None else interval_ms
        if isinstance(interval, bool) or not isinstance(interval, int) or not 0 < interval <= MAX_TTL_MS:
            raise ValueError("invalid heartbeat interval")
        self._handle = handle
        self._interval_ms = max(1, interval)
        self._task: asyncio.Task[None] | None = None
        self._stopped = False
        self._failure: LeaseError | None = None

    @property
    def interval_ms(self) -> int:
        return self._interval_ms

    @property
    def failure(self) -> LeaseError | None:
        return self._failure

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> "LeaseHeartbeat":
        if self._task is not None:
            return self
        if self._stopped:
            raise RuntimeError("heartbeat stopped")
        self._task = asyncio.create_task(self._run(), name="rick-lock-heartbeat")
        return self

    async def _run(self) -> None:
        try:
            while not self._stopped and self._handle.active:
                await asyncio.sleep(self._interval_ms / 1000.0)
                if self._stopped or not self._handle.active:
                    return
                renewed = await self._handle.renew()
                if not renewed:
                    self._failure = LeaseError(
                        "not_owner", "renew", self._handle.correlation_id
                    )
                    return
        except asyncio.CancelledError:
            raise
        except LeaseError as error:
            self._failure = error

    async def stop(self) -> None:
        self._stopped = True
        task = self._task
        if task is None:
            return
        if not task.done():
            task.cancel()
        try:
            await task
        except BaseException:
            return

    async def wait(self) -> None:
        """Wait for natural completion and surface only typed failures."""

        if self._task is None:
            self.start()
        assert self._task is not None
        try:
            await self._task
        except asyncio.CancelledError:
            raise
        if self._failure is not None:
            raise self._failure

    async def __aenter__(self) -> "LeaseHeartbeat":
        return self.start()

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        await self.stop()


def start_heartbeat(
    handle: LeaseHandle, interval_ms: int | None = None
) -> LeaseHeartbeat:
    """Start one cancellable renewal task owned by the caller."""

    return LeaseHeartbeat(handle, interval_ms).start()


__all__ = ["LeaseHeartbeat", "start_heartbeat"]
