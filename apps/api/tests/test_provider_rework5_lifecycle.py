"""Retained synchronous obligations and executed awaitable shutdown ports."""
import asyncio
from threading import Event, Lock
from types import SimpleNamespace

import pytest
import app as app_module
from app import _shutdown_owned_resources


def application(*, shutdown=(), close=()):
    return SimpleNamespace(state=SimpleNamespace(owned_shutdown_resources=shutdown, owned_resources=close))


class SyncClose:
    def __init__(self, result=True):
        self.result = result
        self.entered, self.release, self.finished = Event(), Event(), Event()
        self.lock = Lock()
        self.calls = self.active = self.maximum = 0

    def close(self):
        with self.lock:
            self.calls += 1; self.active += 1; self.maximum = max(self.maximum, self.active)
        self.entered.set()
        try:
            assert self.release.wait(2), 'test must release bounded synthetic closer'
            if isinstance(self.result, Exception): raise self.result
            return self.result
        finally:
            with self.lock: self.active -= 1
            self.finished.set()


async def wait_event(event):
    async with asyncio.timeout(1):
        while not event.is_set(): await asyncio.sleep(.001)


@pytest.mark.asyncio
@pytest.mark.parametrize('interrupt', ['cancel', 'timeout'])
@pytest.mark.parametrize('release_before_retry', [False, True])
async def test_i1_05_sync_close_reconciled_once(monkeypatch, interrupt, release_before_retry):
    # The cancel branch must observe CancelledError: a 40ms lifespan budget lets a
    # loaded event loop finish the shutdown first, so only the timeout branch keeps
    # the short budget it exists to exercise.
    monkeypatch.setattr(
        app_module,
        'APP_LIFESPAN_SHUTDOWN_TIMEOUT_SECONDS',
        5.0 if interrupt == 'cancel' else .04,
    )
    first, last = SyncClose(), SyncClose()
    last.release.set()
    app = application(close=[first, last])
    task = asyncio.create_task(_shutdown_owned_resources(app))
    try:
        await wait_event(first.entered)
        if interrupt == 'cancel':
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
        else: await task
        assert not app.state.lifecycle_shutdown_complete
        assert not app.state.lifecycle_shutdown_in_progress and last.calls == 0
        if release_before_retry:
            first.release.set(); await wait_event(first.finished)
        retry = asyncio.create_task(_shutdown_owned_resources(app))
        await asyncio.sleep(.01)
        assert first.calls == first.maximum == 1
        first.release.set()
        await retry
        await _shutdown_owned_resources(app)
        assert app.state.lifecycle_shutdown_complete and app.state.lifecycle_shutdown_errors == ()
        assert first.calls == first.maximum == last.calls == 1
    finally:
        first.release.set(); last.release.set()
        await wait_event(first.finished)
        if not task.done(): task.cancel()


@pytest.mark.asyncio
@pytest.mark.parametrize('failed_result', [False, RuntimeError('synthetic')])
async def test_i1_05_completed_failure_allows_serial_retry(monkeypatch, failed_result):
    monkeypatch.setattr(app_module, 'APP_LIFESPAN_SHUTDOWN_TIMEOUT_SECONDS', .03)
    resource = SyncClose(failed_result); app = application(close=[resource])
    try:
        await _shutdown_owned_resources(app)
        resource.release.set(); await wait_event(resource.finished)
        await _shutdown_owned_resources(app)
        assert not app.state.lifecycle_shutdown_complete and resource.calls == 1
        resource.result = True
        await _shutdown_owned_resources(app)
        assert app.state.lifecycle_shutdown_complete and resource.calls == 2 and resource.maximum == 1
    finally: resource.release.set()


@pytest.mark.asyncio
@pytest.mark.parametrize('async_method', [False, True])
@pytest.mark.parametrize('outcome', ['healthy', 'false', 'timed_out', 'stall', 'cancel', 'swallow_timeout'])
async def test_i1_06_shutdown_awaitable_executed(monkeypatch, async_method, outcome):
    monkeypatch.setattr(app_module, 'APP_LIFESPAN_SHUTDOWN_TIMEOUT_SECONDS', .03)
    executed, finalizers, closed, loops = [], [], [], []
    entered = asyncio.Event()
    async def stop():
        executed.append(True); loops.append(asyncio.get_running_loop()); entered.set()
        try:
            if outcome in ('stall', 'cancel', 'swallow_timeout'):
                try: await asyncio.Event().wait()
                except asyncio.CancelledError:
                    if outcome != 'swallow_timeout': raise
            if outcome == 'false': return False
            if outcome == 'timed_out': return SimpleNamespace(timed_out=True)
            return True
        finally: finalizers.append(True)
    class Port:
        async def aclose(self): closed.append(True)
    Port.shutdown = lambda self: stop()
    if async_method:
        async def shutdown(self): return await stop()
        Port.shutdown = shutdown
    resource = Port(); app = application(shutdown=[resource])
    task = asyncio.create_task(_shutdown_owned_resources(app))
    if outcome == 'cancel':
        await asyncio.wait_for(entered.wait(), .5); task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
    else: await task
    assert executed == finalizers == [True]
    assert loops == [asyncio.get_running_loop()]
    assert app.state.lifecycle_shutdown_complete == (outcome == 'healthy')
    assert closed == ([True] if outcome == 'healthy' else [])
    assert (id(resource) in app.state.lifecycle_stopped_resources) == (outcome == 'healthy')


@pytest.mark.asyncio
async def test_i1_05_repeated_timeouts_keep_single_pending_obligation(monkeypatch):
    monkeypatch.setattr(app_module, 'APP_LIFESPAN_SHUTDOWN_TIMEOUT_SECONDS', .02)
    resource = SyncClose(); app = application(close=[resource])
    try:
        for _ in range(3):
            await _shutdown_owned_resources(app)
            assert not app.state.lifecycle_shutdown_complete
            assert resource.calls == resource.maximum == resource.active == 1
        resource.release.set(); await wait_event(resource.finished)
        await _shutdown_owned_resources(app)
        assert app.state.lifecycle_shutdown_complete and resource.calls == 1
    finally: resource.release.set()


@pytest.mark.asyncio
async def test_i1_06_awaitable_shutdown_failure_then_healthy_retry(monkeypatch):
    monkeypatch.setattr(app_module, 'APP_LIFESPAN_SHUTDOWN_TIMEOUT_SECONDS', .05)
    results = iter([False, True]); calls, closed = [], []
    class Port:
        def shutdown(self):
            async def stop():
                calls.append(True)
                await asyncio.sleep(0)
                return next(results)
            return stop()
        def close(self): closed.append(True)
    resource = Port(); app = application(shutdown=[resource])
    await _shutdown_owned_resources(app)
    assert not app.state.lifecycle_shutdown_complete and closed == []
    await _shutdown_owned_resources(app)
    await _shutdown_owned_resources(app)
    assert app.state.lifecycle_shutdown_complete and calls == [True, True] and closed == [True]
