"""Provider loop ownership, close-once API lifecycle and local graph admission."""
import asyncio
from dataclasses import replace
from threading import RLock
from types import SimpleNamespace

import pytest

from app import _shutdown_owned_resources, create_app
from apps.api.tests.support import make_settings
from services.external_composition import SyncEmbeddingAdapter, ExternalCompositionError, build_external_providers
from test_external_composition import settings, canonical_redis_capabilities, Redis, HttpTransport


class RetryEmbedding:
    def __init__(self, failures=1, stall=False):
        self.failures, self.stall = failures, stall
        self.calls = 0
        self.loops = []

    async def get_embedding(self, text, *, model):
        self.loops.append(asyncio.get_running_loop())
        return SimpleNamespace(vector=[1.0])

    async def aclose(self):
        self.loops.append(asyncio.get_running_loop())
        self.calls += 1
        if self.calls <= self.failures:
            if self.stall:
                await asyncio.Event().wait()
            raise RuntimeError('synthetic failure')


@pytest.mark.parametrize('stall', [False, True])
def test_f1_embedding_close_failure_is_retryable_on_original_loop(stall):
    provider = RetryEmbedding(failures=2, stall=stall)
    adapter = SyncEmbeddingAdapter(provider, model='model', dimensions=1, timeout_seconds=.02)
    transferred = RetryEmbedding(failures=0)
    adapter.transferred_client = transferred
    assert adapter.embed(['input']) == [[1.0]]
    owning_loop = provider.loops[0]
    try:
        for attempt in (1, 2):
            with pytest.raises(ExternalCompositionError, match='incomplete'):
                adapter.close()
            assert provider.calls == attempt and transferred.calls == 1
            assert adapter._bridge._loop is owning_loop and not owning_loop.is_closed()
            with pytest.raises(ExternalCompositionError, match='closed'):
                adapter.embed(['after shutdown admission'])
        adapter.close()
        adapter.close()
        assert provider.calls == 3 and transferred.calls == 1
        assert set(provider.loops + transferred.loops) == {owning_loop}
        assert owning_loop.is_closed()
    finally:
        disposer = getattr(adapter, 'dispose', None)
        if callable(disposer):
            try:
                disposer(timeout=0)
            except ExternalCompositionError:
                pass  # Cleanup after an assertion failure must not hide it.
        else:
            adapter.close()


def test_f1_unrecoverable_adapter_explicit_disposal_never_falsely_succeeds():
    provider = RetryEmbedding(failures=100)
    adapter = SyncEmbeddingAdapter(provider, model='model', dimensions=1, timeout_seconds=.02)
    adapter.embed(['input'])
    loop = provider.loops[0]
    with pytest.raises(ExternalCompositionError, match='incomplete'):
        adapter.close()
    with pytest.raises(ExternalCompositionError, match='incomplete'):
        adapter.dispose(timeout=.02)
    assert loop.is_closed() and adapter._bridge is None
    for _ in range(2):
        with pytest.raises(ExternalCompositionError, match='incomplete after disposal'):
            adapter.close()
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_f8_api_successful_closes_and_stops_occur_once_on_retry():
    class Resource:
        def __init__(self, failures=0):
            self.failures = failures
            self.close_calls = self.stop_calls = 0
            self.loops = []
        def shutdown(self, *, timeout):
            self.stop_calls += 1
            return True
        async def aclose(self):
            self.close_calls += 1
            self.loops.append(asyncio.get_running_loop())
            if self.close_calls <= self.failures:
                raise RuntimeError('synthetic failure')
    first, failed = Resource(), Resource(2)
    app = SimpleNamespace(state=SimpleNamespace(
        lifecycle_shutdown_lock=RLock(), lifecycle_shutdown_complete=False,
        owned_shutdown_resources=[first], owned_resources=[first,failed,failed]))
    for _ in range(2):
        await _shutdown_owned_resources(app)
        assert not app.state.lifecycle_shutdown_complete and app.state.lifecycle_shutdown_errors
    await _shutdown_owned_resources(app)
    await _shutdown_owned_resources(app)
    assert app.state.lifecycle_shutdown_complete and app.state.lifecycle_shutdown_errors == ()
    assert first.close_calls == first.stop_calls == 1 and failed.close_calls == 3
    assert set(first.loops + failed.loops) == {asyncio.get_running_loop()}


def test_local_builtin_postgres_inputs_compose_and_production_identity_guard_is_exact(tmp_path, monkeypatch):
    import deployment_composition as deployment
    import rick_locking
    from services.postgres_identity import PostgresIdentityProvider

    local_settings = replace(settings(), environment='dev', identity_mode='dev')
    client = Redis()
    namespace, limiter, lease = canonical_redis_capabilities(client, environment='dev')
    monkeypatch.setattr(rick_locking.RedisSettings, 'from_env', classmethod(lambda cls: SimpleNamespace(
        namespace_prefix='rick', environment='dev')))
    monkeypatch.setattr(rick_locking, 'create_redis_client', lambda *a, **k: client)
    monkeypatch.setattr(rick_locking, 'create_redis_rate_limiter', lambda *a, **k: limiter)
    monkeypatch.setattr(rick_locking, 'create_redis_lease_client', lambda *a, **k: lease)
    monkeypatch.setattr(deployment, 'StdlibS3HttpTransport', lambda *a, **k: HttpTransport())
    database_calls = []
    monkeypatch.setattr(deployment, '_connection_factory', lambda dsn: lambda: database_calls.append('unexpected DB call'))
    for name,value in {'RICK_WORKER_TEMP_ROOT':str(tmp_path), 'RICK_COMPOSITION_CREATED_BY':'local-user',
        'RICK_WORKER_ID':'local-worker', 'RICK_WORKER_SCOPE_TENANT':'tenant',
        'RICK_WORKER_SCOPE_WORKSPACE':'workspace', 'RICK_WORKER_SCOPE_COLLECTION':'collection'}.items():
        monkeypatch.setenv(name,value)
    inputs = deployment.build_api_inputs(local_settings)
    assert isinstance(inputs.identity, PostgresIdentityProvider)
    assert inputs.identity.production_safe is False
    inputs = replace(inputs, qdrant_transport=HttpTransport())
    providers = build_external_providers(local_settings, inputs)
    assert database_calls == []
    assert providers.identity is inputs.identity and providers.provider is not None
    # Preserve production capability checks to reach the production identity gate.
    prod_namespace, prod_limiter, prod_lease = canonical_redis_capabilities(client)
    prod_inputs = replace(inputs, rate_limit_namespace=prod_namespace, rate_limiter=prod_limiter, lease=prod_lease)
    with pytest.raises(ExternalCompositionError, match='production-safe identity'):
        build_external_providers(settings(), prod_inputs)
    production_injected = replace(local_settings, environment='production', identity_mode='production')
    with pytest.raises(RuntimeError, match='external identity'):
        create_app(production_injected, providers)
    providers._embedding_adapter.close()
    providers.worker.close()
    providers.queue.close()
    providers.object_store.close()
    providers.vector_store.close()


@pytest.mark.asyncio
async def test_api_owned_httpx_mounts_retry_incomplete_transport_closes_once():
    import httpx
    class Transport(httpx.MockTransport):
        def __init__(self, failures=0):
            super().__init__(lambda _: httpx.Response(200, text='ok'))
            self.failures, self.calls = failures, 0
            self.loops = []
        async def aclose(self):
            self.calls += 1
            self.loops.append(asyncio.get_running_loop())
            if self.calls <= self.failures:
                raise RuntimeError('synthetic close failure')
    first, failed, last = Transport(), Transport(2), Transport()
    client = httpx.AsyncClient(transport=first, mounts={'https://failed.invalid':failed, 'https://last.invalid':last}, trust_env=False)
    assert (await client.get('https://first.invalid')).text == 'ok'
    app = SimpleNamespace(state=SimpleNamespace(owned_resources=[client]))
    for attempt in (1,2):
        await _shutdown_owned_resources(app)
        assert app.state.lifecycle_shutdown_complete is False
        assert client.is_closed and failed.calls == attempt and first.calls == 1
    await _shutdown_owned_resources(app)
    await _shutdown_owned_resources(app)
    assert app.state.lifecycle_shutdown_complete and app.state.lifecycle_shutdown_errors == ()
    assert (first.calls,failed.calls,last.calls) == (1,3,1)
    assert set(first.loops+failed.loops+last.loops) == {asyncio.get_running_loop()}
