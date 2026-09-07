"""Close response-owned async iterators explicitly, not through finalization."""
from __future__ import annotations

import asyncio
import threading
import time
from collections import Counter
from contextlib import asynccontextmanager

import anyio
from fastapi.routing import APIRoute
from starlette.responses import Response, StreamingResponse

from core.errors import ApiError

STREAM_CLEANUP_SECONDS = 1.0
MAX_STREAM_OPERATIONS = 64
_slots = threading.BoundedSemaphore(MAX_STREAM_OPERATIONS)
_active_tasks: set[asyncio.Task] = set()
_tasks_lock = threading.Lock()
# Fixed vocabulary; no exception text, request data or identity labels.
cleanup_outcomes: Counter = Counter()


@asynccontextmanager
async def closing_stream(events, scope):
    """Own nested service teardown inside the response's bounded task.

    Plain aclosing can replace an iteration error and is interrupted by an
    already-cancelled native response task group. Neither loses ownership here.
    """
    failure = None
    try:
        yield events
    except BaseException as exc:
        failure = exc
    begin_cleanup = scope.get("rick.start_stream_cleanup")
    if begin_cleanup is not None:
        begin_cleanup(failure)
    try:
        with anyio.fail_after(STREAM_CLEANUP_SECONDS, shield=True):
            await events.aclose()
    except BaseException as cleanup_error:
        if failure is not None:
            raise BaseExceptionGroup("stream and nested cleanup failed", [failure, cleanup_error])
        raise
    if failure is not None:
        raise failure


class _Lease:
    def __init__(self):
        self.slots = _slots
        self.released = False
        if not self.slots.acquire(blocking=False):
            raise ApiError("provider_unavailable")

    def release(self):
        with _tasks_lock:
            if not self.released:
                self.released = True
                self.slots.release()


class _ClosingResponse(Response):
    def __init__(self, response: StreamingResponse, lease: _Lease):
        self.response = response
        self.lease = lease
        self.status_code = response.status_code
        self.raw_headers = response.raw_headers
        self.background = response.background
        self.media_type = response.media_type

    async def __call__(self, scope, receive, send):
        from core.transport import get_transport

        transport = get_transport(scope)
        cleanup_started = asyncio.Event()
        cleanup_at = None
        failure = None
        nested_failure = None
        cancellation = None
        detached = False
        completion_recorded = False

        def begin_cleanup(error=None):
            nonlocal cleanup_at, nested_failure
            if error is not None:
                nested_failure = error
            if cleanup_at is None:
                cleanup_at = time.monotonic()
                cleanup_started.set()

        # Private ownership signal, never a transport-disconnect assertion.
        previous_cleanup = scope.get("rick.start_stream_cleanup")
        scope["rick.start_stream_cleanup"] = begin_cleanup

        async def observed_receive():
            message = await receive()
            if message["type"] == "http.disconnect":
                transport.disconnect()
            return message

        async def observed_send(message):
            if detached:
                return
            try:
                await send(message)
            except OSError:
                transport.disconnect()
                raise
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                begin_cleanup()

        async def run_owned():
            nonlocal failure
            try:
                await self.response(scope, observed_receive, observed_send)
            except BaseException as exc:
                failure = exc
            begin_cleanup()
            close = getattr(self.response.body_iterator, "aclose", None)
            if callable(close):
                try:
                    with anyio.fail_after(STREAM_CLEANUP_SECONDS, shield=True):
                        await close()
                except BaseException as cleanup_error:
                    if failure is not None:
                        raise BaseExceptionGroup("response and cleanup failed", [failure, cleanup_error])
                    raise
            if failure is not None:
                raise failure

        task = asyncio.create_task(run_owned(), name="api-stream-owner")
        with _tasks_lock:
            _active_tasks.add(task)

        def completed(done):
            nonlocal completion_recorded
            if completion_recorded:
                return
            completion_recorded = True
            # Retrieve exceptions even after request timeout; never log their text.
            error = None if done.cancelled() else done.exception()
            with _tasks_lock:
                _active_tasks.discard(done)
                if detached:
                    cleanup_outcomes["late_failure" if error is not None else "late_completion"] += 1
            self.lease.release()

        task.add_done_callback(completed)
        disconnected = asyncio.create_task(transport.disconnected.wait())
        cleaning = asyncio.create_task(cleanup_started.wait())
        deadline = None
        try:
            while not task.done():
                if deadline is None:
                    times = [x for x in (transport.disconnected_at, cleanup_at) if x is not None]
                    if times:
                        deadline = min(times) + STREAM_CLEANUP_SECONDS
                remaining = None if deadline is None else max(0, deadline - time.monotonic())
                try:
                    watched = [task, disconnected, cleaning] if deadline is None else [task]
                    await asyncio.wait(watched, timeout=remaining, return_when=asyncio.FIRST_COMPLETED)
                except asyncio.CancelledError as exc:
                    if cancellation is None:
                        cancellation = exc
                        task.cancel()
                    limit = time.monotonic() + STREAM_CLEANUP_SECONDS
                    deadline = limit if deadline is None else min(deadline, limit)
                if task.done():
                    break
                if deadline is not None and time.monotonic() >= deadline:
                    detached = True
                    # A cooperative owner may finish now; resistant work stays
                    # tracked and consumes capacity until it actually completes.
                    task.cancel()
                    timeout = TimeoutError("stream teardown deadline exceeded")
                    known_failure = failure if failure is not None else nested_failure
                    errors = [x for x in (known_failure, cancellation) if x is not None]
                    if errors:
                        raise BaseExceptionGroup("response teardown incomplete", [*errors, timeout])
                    raise timeout
            # Completion callbacks run on the next loop turn. Reconcile here
            # too so a finished operation cannot spuriously deny the next call.
            completed(task)
            result = task.result()
            if cancellation is not None:
                raise cancellation
            return result
        finally:
            if previous_cleanup is None:
                scope.pop("rick.start_stream_cleanup", None)
            else:
                scope["rick.start_stream_cleanup"] = previous_cleanup
            # These tasks only wait on local Events; cancel without a new
            # suspension point that could replace a pending real exception.
            disconnected.cancel()
            cleaning.cancel()


class ClosingStreamingRoute(APIRoute):
    """Keep framework/custom response behavior while owning iterator teardown."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handle(request):
            lease = _Lease()
            try:
                response = await original(request)
                if isinstance(response, StreamingResponse):
                    return _ClosingResponse(response, lease)
            except BaseException:
                lease.release()
                raise
            lease.release()
            return response

        return handle
