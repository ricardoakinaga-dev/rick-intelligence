"""Retry failed provider cleanup on its original loop; dispose explicitly."""
import asyncio
from types import SimpleNamespace

import pytest

from deployment_composition import DeploymentRuntime
from services.external_composition import SyncEmbeddingAdapter
from worker.tests.test_deployment_composition import _Worker


class Resource:
    def __init__(self, failures=1, stall=False):
        self.calls = 0
        self.failures, self.stall = failures, stall
        self.loops = []
    async def health_check(self):
        self.loops.append(asyncio.get_running_loop())
        return True
    async def get_embedding(self, text, *, model):
        self.loops.append(asyncio.get_running_loop())
        return SimpleNamespace(vector=[1.0])
    async def aclose(self):
        self.calls += 1
        self.loops.append(asyncio.get_running_loop())
        assert self.loops[-1] is self.loops[0]
        if self.calls <= self.failures:
            if self.stall:
                await asyncio.Event().wait()
            raise RuntimeError('synthetic close failure')


@pytest.mark.parametrize('stall', [False, True])
def test_f3_worker_retains_loop_retries_only_failed_resources(stall):
    first, failed = Resource(0), Resource(2, stall=stall)
    runtime = DeploymentRuntime(SimpleNamespace(worker=_Worker(), provider=failed, audit_sink=first,
        health_checks={'provider':failed.health_check,'audit':first.health_check}))
    runtime.start()
    assert runtime.health_check()
    bridge = runtime._async_bridge
    try:
        for _ in range(2):
            assert runtime.shutdown(timeout=.05) is False
            assert runtime._shutdown_errors and not bridge._loop.is_closed()
            assert runtime._async_bridge is bridge and first.calls == 1
        assert runtime.shutdown(timeout=.05) is True
        assert runtime.shutdown(timeout=.05) is True
        assert failed.calls == 3 and first.calls == 1
        assert set(failed.loops + first.loops) == {bridge._loop}
        assert bridge._loop.is_closed()
    finally:
        disposer = getattr(runtime, 'dispose', None)
        if callable(disposer):
            disposer(timeout=0)
        else:
            runtime.shutdown(timeout=.05)


def test_f1_embedding_worker_shutdown_cannot_forget_failed_cleanup():
    resource = Resource(2)
    adapter = SyncEmbeddingAdapter(resource, model='model', dimensions=1, timeout_seconds=.02)
    adapter.embed(['input'])
    owning_loop = resource.loops[0]
    runtime = DeploymentRuntime(SimpleNamespace(worker=_Worker(), _embedding_adapter=adapter, health_checks={}))
    try:
        assert runtime.shutdown(timeout=.05) is False
        assert runtime.shutdown(timeout=.05) is False
        assert runtime._shutdown_errors and not owning_loop.is_closed()
        assert runtime.shutdown(timeout=.05) is True
        assert runtime.shutdown(timeout=.05) is True
        assert resource.calls == 3 and set(resource.loops) == {owning_loop}
        assert owning_loop.is_closed()
    finally:
        disposer = getattr(runtime, 'dispose', None)
        if callable(disposer):
            disposer(timeout=0)
        else:
            runtime.shutdown(timeout=.05)


def test_f3_unrecoverable_worker_explicit_disposal_preserves_failure_and_releases_loop():
    resource = Resource(100)
    runtime = DeploymentRuntime(SimpleNamespace(worker=_Worker(), provider=resource,
        health_checks={'provider':resource.health_check}))
    runtime.start()
    assert runtime.health_check()
    loop = resource.loops[0]
    assert runtime.shutdown(timeout=.05) is False
    assert runtime.dispose(timeout=.05) is False
    assert loop.is_closed() and runtime._async_bridge is None
    assert runtime.shutdown(timeout=.05) is False and runtime._shutdown_errors
    assert resource.calls == 2
