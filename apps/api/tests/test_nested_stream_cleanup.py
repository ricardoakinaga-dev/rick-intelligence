import asyncio
import json
import threading
import anyio
import pytest
from app import create_app
from conftest import make_settings
from core import streaming
from services.chat_service import ChatApplicationService
from dependencies.identity import require_authenticated
from models import SessionSnapshot
from test_transport_observation import scope, total

def leaves(exc):
    return [leaf for child in exc.exceptions for leaf in leaves(child)] if isinstance(exc, BaseExceptionGroup) else [exc]

@pytest.mark.parametrize('path', ['/api/v1/chat', '/v1/chat/completions'])
@pytest.mark.parametrize('mixed', [False, True])
def test_nested_stream_ownership(monkeypatch, path, mixed):
    async def run():
        app = create_app(make_settings(compat_api_key='probe-key'))
        app.dependency_overrides[require_authenticated] = lambda: SessionSnapshot(
            authenticated=True, session_state='active', user_id='probe', role='KNOWLEDGE_MANAGER',
            canonical_role='KNOWLEDGE_MANAGER', permissions=['chat.query'], tenant_id='default')
        entered = asyncio.Event()
        closed = asyncio.Event()
        original = ValueError('real application failure')
        cleanup = RuntimeError('real cleanup failure')
        class Events:
            def __aiter__(self): return self
            async def __anext__(self):
                if mixed: raise original
                entered.set()
                await asyncio.Event().wait()
            async def aclose(self):
                if mixed: raise cleanup
                await asyncio.sleep(.001)
                closed.set()
        events = Events()
        monkeypatch.setattr(ChatApplicationService, 'stream_events', lambda *a, **k: events)
        request_scope = scope(path, 'POST')
        request_scope['headers'] = [(b'content-type', b'application/json'), (b'x-api-key', b'probe-key')]
        payload = {'message':'hello', 'stream':True} if path == '/api/v1/chat' else {'messages':[{'role':'user','content':'hello'}], 'stream':True}
        first = True
        async def receive():
            nonlocal first
            if first:
                first = False
                return {'type':'http.request', 'body':json.dumps(payload).encode(), 'more_body':False}
            await entered.wait()
            return {'type':'http.disconnect'}
        sent = []
        async def send(message): sent.append(message)
        if mixed:
            with pytest.raises(BaseException) as caught:
                await asyncio.wait_for(app(request_scope, receive, send), .5)
            errors = leaves(caught.value)
            assert total(app.state.telemetry, 'api.http.errors') == 1
            assert sum(m['type'] == 'http.response.start' for m in sent) == 1
            assert original in errors and cleanup in errors, f'propagated leaves={errors!r}'
        else:
            await asyncio.wait_for(app(request_scope, receive, send), .5)
            assert total(app.state.telemetry, 'api.http.disconnects') == 1
            assert closed.is_set(), f'nested cooperative close incomplete; active owners={len(streaming._active_tasks)}'
    asyncio.run(run())


@pytest.mark.parametrize('path', ['/api/v1/chat', '/v1/chat/completions'])
@pytest.mark.parametrize('ending', ['exhausted', 'error', 'disconnect', 'cancel'])
def test_nested_resistant_teardown_keeps_ownership_and_known_failure(monkeypatch, path, ending):
    monkeypatch.setattr(streaming, 'STREAM_CLEANUP_SECONDS', .02)
    monkeypatch.setattr(streaming, '_slots', threading.BoundedSemaphore(1))

    async def run():
        app = create_app(make_settings(compat_api_key='probe-key'))
        app.dependency_overrides[require_authenticated] = lambda: SessionSnapshot(
            authenticated=True, session_state='active', user_id='probe', role='KNOWLEDGE_MANAGER',
            canonical_role='KNOWLEDGE_MANAGER', permissions=['chat.query'], tenant_id='default')
        entered, cleaning, release, closed = (asyncio.Event() for _ in range(4))
        original = ValueError('iteration failure before resistant close')
        class Events:
            def __aiter__(self):
                return self
            async def __anext__(self):
                entered.set()
                if ending == 'error':
                    raise original
                if ending == 'exhausted':
                    raise StopAsyncIteration
                await asyncio.Event().wait()
            async def aclose(self):
                cleaning.set()
                while not release.is_set():
                    try:
                        with anyio.CancelScope(shield=True):
                            await release.wait()
                    except asyncio.CancelledError:
                        continue
                closed.set()
        retained = Events()
        monkeypatch.setattr(ChatApplicationService, 'stream_events', lambda *a, **k: retained)
        request_scope = scope(path, 'POST')
        request_scope['headers'] = [(b'content-type', b'application/json'), (b'x-api-key', b'probe-key')]
        payload = {'message':'hello', 'stream':True} if path == '/api/v1/chat' else {'messages':[{'role':'user','content':'hello'}], 'stream':True}
        first = True
        async def receive():
            nonlocal first
            if first:
                first = False
                return {'type':'http.request', 'body':json.dumps(payload).encode(), 'more_body':False}
            await entered.wait()
            if ending != 'disconnect':
                await asyncio.Event().wait()
            return {'type':'http.disconnect'}
        sent = []
        async def send(message):
            sent.append(message)
        baseline = set(streaming._active_tasks)
        task = asyncio.create_task(app(request_scope, receive, send))
        try:
            await asyncio.wait_for(entered.wait(), .5)
            if ending == 'cancel':
                task.cancel()
            await asyncio.wait_for(cleaning.wait(), .5)
            done, _ = await asyncio.wait([task], timeout=.15)
            assert task in done
            with pytest.raises(BaseException) as caught:
                await task
            errors = leaves(caught.value)
            assert any(isinstance(error, TimeoutError) for error in errors)
            if ending == 'error':
                assert original in errors
            assert not closed.is_set()
            assert len(streaming._active_tasks - baseline) == 1
            assert not streaming._slots.acquire(blocking=False)
            assert total(app.state.telemetry, 'api.http.errors') == 1
            before_release = len(sent)
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            remaining = streaming._active_tasks - baseline
            if remaining:
                await asyncio.wait_for(asyncio.gather(*remaining, return_exceptions=True), .5)
            await asyncio.sleep(0)
        assert closed.is_set()
        assert len(sent) == before_release
        assert streaming._active_tasks == baseline
        assert streaming._slots.acquire(blocking=False)
        streaming._slots.release()

    asyncio.run(run())
