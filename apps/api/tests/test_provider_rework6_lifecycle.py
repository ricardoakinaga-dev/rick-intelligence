"""Actual ASGI receive/send outcomes with owned native transport obligations."""
import asyncio
import time

import httpx
import pytest
from fastapi import FastAPI

import app as app_module
from app import _application_lifespan, _shutdown_owned_resources
from rick_providers import OpenAICompatibleClient, ProviderConfig, ResilientProvider


@pytest.mark.asyncio
@pytest.mark.parametrize('fault', ['healthy', 'false', 'raise', 'stall'])
async def test_i1_04_lifespan_reports_incomplete_cleanup_and_retains_retry(monkeypatch, fault):
    monkeypatch.setattr(app_module, 'APP_LIFESPAN_SHUTDOWN_TIMEOUT_SECONDS', .04)
    class Transport(httpx.MockTransport):
        def __init__(self):
            super().__init__(lambda _: httpx.Response(200, json={}))
            self.calls = self.finalizers = 0
            self.recovered = False
        async def aclose(self):
            self.calls += 1
            try:
                if not self.recovered:
                    if fault == 'false': return False
                    if fault == 'raise': raise RuntimeError('private transport detail')
                    if fault == 'stall': await asyncio.Event().wait()
            finally: self.finalizers += 1
    class Last:
        calls = 0
        async def aclose(self): self.calls += 1
    transport, first, last = Transport(), Last(), Last()
    native = OpenAICompatibleClient(ProviderConfig(environment='test', timeout=1), transport=transport)
    native._ensure_client()
    provider = ResilientProvider(native)
    application = FastAPI(lifespan=_application_lifespan)
    application.state.owned_resources = [first, provider, last]
    received, sent = [], []
    messages = iter([{'type': 'lifespan.startup'}, {'type': 'lifespan.shutdown'}])
    async def receive():
        message = next(messages); received.append(message); return message
    async def send(message): sent.append(message)
    began = time.monotonic()
    if fault == 'healthy':
        await application({'type': 'lifespan', 'asgi': {'version': '3.0'}, 'state': {}}, receive, send)
    else:
        with pytest.raises(RuntimeError, match='^Application shutdown incomplete\\.$'):
            await application({'type': 'lifespan', 'asgi': {'version': '3.0'}, 'state': {}}, receive, send)
    assert time.monotonic() - began < .7
    assert [message['type'] for message in received] == ['lifespan.startup', 'lifespan.shutdown']
    assert [message['type'] for message in sent] == [
        'lifespan.startup.complete', 'lifespan.shutdown.complete' if fault == 'healthy' else 'lifespan.shutdown.failed']
    assert 'private transport detail' not in str(sent)
    assert application.state.lifecycle_shutdown_complete is (fault == 'healthy')
    assert transport.calls == transport.finalizers == 1 and last.calls == (1 if fault == 'healthy' else 0)
    assert first.calls == 1 and id(first) in application.state.lifecycle_closed_resources
    assert not application.state.lifecycle_shutdown_in_progress
    transport.recovered = True
    await _shutdown_owned_resources(application)
    await _shutdown_owned_resources(application)
    assert application.state.lifecycle_shutdown_complete and application.state.lifecycle_shutdown_errors == ()
    assert transport.calls == transport.finalizers == (1 if fault == 'healthy' else 2)
    assert first.calls == last.calls == 1
