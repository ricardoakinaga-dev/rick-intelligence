"""Caller cancellation remains visible after finite lifecycle work completes."""

import asyncio
import httpx
import pytest
from fastapi import FastAPI

from app import _application_lifespan, _shutdown_owned_resources, create_app
from apps.api.tests.support import make_settings
from dependencies.services import Providers
from services.chat_service import StubChatBackend
from services.identity_service import InMemoryIdentityProvider


class Port:
    def __init__(self):
        self.stops = self.closes = 0

    async def shutdown(self):
        self.stops += 1

    async def aclose(self):
        self.closes += 1


class FiniteClose(httpx.MockTransport):
    def __init__(self, mode, result=None):
        super().__init__(lambda _: httpx.Response(200))
        self.mode, self.result = mode, result
        self.entered = asyncio.Event()
        self.calls = self.completed = 0
        self.loops = []
        self.recovered = False

    async def aclose(self):
        self.calls += 1
        self.loops.append(asyncio.get_running_loop())
        self.entered.set()
        if self.mode != "healthy" and not self.recovered:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                if self.mode == "cooperative":
                    raise
                if self.mode == "acknowledged":
                    task = asyncio.current_task()
                    while task.cancelling():
                        task.uncancel()
                await asyncio.sleep(0)  # Finite cleanup on the caller's loop.
        if isinstance(self.result, Exception):
            raise self.result
        if self.result is False:
            return False
        self.completed += 1


async def run_lifespan(application, transport, mode, cancel_count=1):
    messages = iter([{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}])
    sent = []

    async def receive():
        return next(messages)

    async def send(message):
        sent.append(message)

    task = asyncio.create_task(application(
        {"type": "lifespan", "asgi": {"version": "3.0"}, "state": {}}, receive, send,
    ))
    if mode != "healthy":
        await asyncio.wait_for(transport.entered.wait(), .5)
        for _ in range(cancel_count):
            task.cancel()
    try:
        if mode in ("suppressed", "cooperative"):
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            await task
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    return task, sent


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["healthy", "cooperative", "suppressed", "acknowledged"])
@pytest.mark.parametrize("cancel_count", [1, 2])
async def test_owned_httpx_create_app_asgi_cancel_completion_and_retry(mode, cancel_count):
    first, last = Port(), Port()
    transport = FiniteClose(mode)
    client = httpx.AsyncClient(transport=transport, trust_env=False)
    settings = make_settings(environment="test")
    providers = Providers(settings=settings, identity=InMemoryIdentityProvider(),
                          chat_backend=StubChatBackend(), worker=first,
                          provider=client, lease=last)
    providers._composition_owned = True
    application = create_app(settings, providers)
    assert application.state.owned_resources == [first, client, last]
    task, sent = await run_lifespan(application, transport, mode, cancel_count)
    cancelled = mode in ("suppressed", "cooperative")
    completed = mode != "cooperative"
    assert [message["type"] for message in sent] == [
        "lifespan.startup.complete",
        "lifespan.shutdown.failed" if cancelled else "lifespan.shutdown.complete",
    ]
    assert task.cancelling() == (cancel_count if cancelled else 0)
    assert not application.state.lifecycle_shutdown_in_progress
    assert application.state.lifecycle_shutdown_complete is (not cancelled)
    assert application.state.lifecycle_shutdown_errors == (("shutdown_cancelled",) if cancelled else ())
    assert first.stops == first.closes == 1
    assert id(first) in application.state.lifecycle_closed_resources
    assert last.closes == (0 if cancelled else 1)
    obligation = application.state.lifecycle_client_close_obligations[id(client)]
    assert obligation.complete is completed
    assert (id(client) in application.state.lifecycle_closed_resources) is completed
    assert transport.calls == 1 and transport.completed == int(completed)
    transport.recovered = True
    await _shutdown_owned_resources(application)
    await _shutdown_owned_resources(application)
    assert application.state.lifecycle_shutdown_complete
    assert application.state.lifecycle_shutdown_errors == ()
    assert first.stops == first.closes == last.closes == 1
    assert transport.calls == (2 if mode == "cooperative" else 1)
    assert transport.completed == 1
    assert set(transport.loops) == {asyncio.get_running_loop()}
    assert application.state.lifecycle_client_close_obligations[id(client)] is obligation


@pytest.mark.asyncio
@pytest.mark.parametrize("async_method", [False, True])
@pytest.mark.parametrize("mode", ["healthy", "cooperative", "suppressed", "acknowledged"])
async def test_completed_shutdown_port_is_recorded_before_caller_cancel(async_method, mode):
    first, pending, last = Port(), Port(), Port()
    work = FiniteClose(mode)
    if async_method:
        async def shutdown():
            return await work.aclose()
    else:
        def shutdown():
            return work.aclose()
    pending.shutdown = shutdown
    application = FastAPI(lifespan=_application_lifespan)
    application.state.owned_shutdown_resources = [first, pending, last]
    task, sent = await run_lifespan(application, work, mode)
    cancelled = mode in ("suppressed", "cooperative")
    assert task.cancelling() == int(cancelled)
    assert sent[-1]["type"] == ("lifespan.shutdown.failed" if cancelled else "lifespan.shutdown.complete")
    assert (id(pending) in application.state.lifecycle_stopped_resources) is (mode != "cooperative")
    assert first.stops == 1 and last.stops == (0 if cancelled else 1)
    assert first.closes == pending.closes == last.closes == (0 if cancelled else 1)
    assert not application.state.lifecycle_shutdown_in_progress
    work.recovered = True
    await _shutdown_owned_resources(application)
    await _shutdown_owned_resources(application)
    assert first.stops == last.stops == 1
    assert work.calls == (2 if mode == "cooperative" else 1)
    assert work.completed == 1
    assert first.closes == pending.closes == last.closes == 1
    assert application.state.lifecycle_shutdown_complete and application.state.lifecycle_shutdown_errors == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [False, RuntimeError("finite close failure")])
@pytest.mark.parametrize("httpx_client", [False, True])
async def test_cancelled_failed_port_retains_unfinished_obligation(result, httpx_client):
    first, last = Port(), Port()
    pending = FiniteClose("suppressed", result)
    resource = httpx.AsyncClient(transport=pending, trust_env=False) if httpx_client else pending
    application = FastAPI(lifespan=_application_lifespan)
    application.state.owned_resources = [first, resource, last]
    task, sent = await run_lifespan(application, pending, "suppressed")
    assert task.cancelling() == 1 and sent[-1]["type"] == "lifespan.shutdown.failed"
    assert id(resource) not in application.state.lifecycle_closed_resources
    assert pending.completed == 0 and last.closes == 0
    assert application.state.lifecycle_shutdown_errors[-1] == "shutdown_cancelled"
    if httpx_client:
        obligation = application.state.lifecycle_client_close_obligations[id(resource)]
        assert obligation.started and not obligation.complete
    pending.recovered, pending.result = True, None
    await _shutdown_owned_resources(application)
    assert application.state.lifecycle_shutdown_complete
    assert first.closes == last.closes == 1
    assert pending.calls == 2 and pending.completed == 1


@pytest.mark.asyncio
async def test_first_shutdown_failure_survives_later_suppressed_cancellation():
    first, pending, last = Port(), Port(), Port()
    work = FiniteClose("suppressed")
    fail = True

    async def first_stop():
        first.stops += 1
        return False if fail else True

    first.shutdown = first_stop
    pending.shutdown = work.aclose
    application = FastAPI(lifespan=_application_lifespan)
    application.state.owned_shutdown_resources = [first, pending, last]
    task, sent = await run_lifespan(application, work, "suppressed")
    assert task.cancelling() == 1 and sent[-1]["type"] == "lifespan.shutdown.failed"
    assert application.state.lifecycle_shutdown_errors == ("ingestion_shutdown_timeout", "shutdown_cancelled")
    assert id(first) not in application.state.lifecycle_stopped_resources
    assert id(pending) in application.state.lifecycle_stopped_resources
    assert last.stops == first.closes == pending.closes == last.closes == 0
    fail = False
    await _shutdown_owned_resources(application)
    assert application.state.lifecycle_shutdown_complete
    assert first.stops == 2 and last.stops == work.calls == 1
    assert first.closes == pending.closes == last.closes == 1


@pytest.mark.asyncio
async def test_preexisting_unacknowledged_cancellation_stops_new_lifecycle_effects():
    port = Port()
    application = FastAPI(lifespan=_application_lifespan)
    application.state.owned_resources = [port]

    async def shutdown_with_pending_cancel():
        task = asyncio.current_task()
        task.cancel()
        try:
            await asyncio.sleep(0)
        except asyncio.CancelledError:
            pass
        await _shutdown_owned_resources(application)

    task = asyncio.create_task(shutdown_with_pending_cancel())
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelling() == 1
    assert port.closes == 0 and not application.state.lifecycle_shutdown_in_progress
    assert not application.state.lifecycle_shutdown_complete
    assert application.state.lifecycle_shutdown_errors == ("shutdown_cancelled",)
    await _shutdown_owned_resources(application)
    assert port.closes == 1 and application.state.lifecycle_shutdown_complete
