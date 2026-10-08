"""Cancellation releases API shutdown admission and retains close obligations."""
import asyncio
from types import SimpleNamespace

import httpx
import pytest

from app import _shutdown_owned_resources


class Resource:
    def __init__(self, stall=False):
        self.stall, self.calls, self.stops = stall, 0, 0
        self.entered = asyncio.Event()
        self.finalizers, self.loops = [], []

    def shutdown(self, *, timeout):
        self.stops += 1
        return True

    async def aclose(self):
        self.calls += 1
        self.loops.append(asyncio.get_running_loop())
        self.entered.set()
        try:
            if self.stall: await asyncio.Event().wait()
        finally: self.finalizers.append(True)


@pytest.mark.asyncio
@pytest.mark.parametrize('httpx_client', [False, True])
@pytest.mark.parametrize('cancel', [False, True])
async def test_f6_shutdown_cancellation_and_healthy_retry(httpx_client, cancel):
    first, pending, last = Resource(), Resource(stall=cancel), Resource()
    if httpx_client:
        class Transport(httpx.MockTransport):
            async def aclose(self): await pending.aclose()
        resource = httpx.AsyncClient(transport=Transport(lambda _: httpx.Response(200)), trust_env=False)
    else: resource = pending
    app = SimpleNamespace(state=SimpleNamespace(owned_shutdown_resources=[first], owned_resources=[first, resource, last]))
    task = asyncio.create_task(_shutdown_owned_resources(app))
    if cancel:
        await asyncio.wait_for(pending.entered.wait(), .5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        assert app.state.lifecycle_shutdown_in_progress is False
        assert app.state.lifecycle_shutdown_complete is False
        assert app.state.lifecycle_shutdown_errors == ('shutdown_cancelled',)
        assert pending.finalizers == [True]
        assert first.calls == first.stops == 1 and last.calls == 0
        assert id(first) in app.state.lifecycle_closed_resources
        if httpx_client:
            obligation = app.state.lifecycle_client_close_obligations[id(resource)]
            assert obligation.started and not obligation.complete
        pending.stall = False
    else: await task
    await _shutdown_owned_resources(app)
    await _shutdown_owned_resources(app)
    assert app.state.lifecycle_shutdown_complete and not app.state.lifecycle_shutdown_in_progress
    assert app.state.lifecycle_shutdown_errors == ()
    assert first.calls == first.stops == last.calls == 1
    assert pending.calls == (2 if cancel else 1)
    assert set(first.loops + pending.loops + last.loops) == {asyncio.get_running_loop()}
    if httpx_client:
        assert app.state.lifecycle_client_close_obligations[id(resource)].complete
        if cancel: assert app.state.lifecycle_client_close_obligations[id(resource)] is obligation
