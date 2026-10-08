from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
STORAGE_SRC = ROOT / "packages" / "storage" / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
WORKER_SRC = ROOT / "apps"
if str(WORKER_SRC) not in sys.path:
    sys.path.insert(0, str(WORKER_SRC))
if str(STORAGE_SRC) not in sys.path:
    sys.path.insert(0, str(STORAGE_SRC))

import httpx
import pytest

from core.config import ApiSettings
import services.external_composition as external_composition
from services.external_composition import (
    ExternalCompositionError,
    ExternalCompositionInputs,
    _canonical_job_result,
    build_external_providers,
    load_external_providers,
)
from rick_locking import RedisLeaseClient, RedisLeaseStore, RedisNamespace, RedisRateLimiter
from rick_locking.redis_config import _PRODUCTION_CAPABILITY_TOKEN


class HttpTransport:
    def request(self, method, url, *, headers, body):
        raise AssertionError("composition must be lazy")


class Redis:
    async def set(self, *args, **kwargs):
        return True

    async def eval(self, *args, **kwargs):
        return 1

    async def ping(self):
        return True


class RateLimiter:
    production_safe = True
    backend_kind = "redis"

    async def allow(self, *args, **kwargs):
        return True

    async def readiness_check(self):
        return True

    async def health_check(self):
        return True


class Lease:
    production_safe = True
    backend_kind = "redis"

    async def acquire_owned(self, *args, **kwargs):
        return True

    async def renew_owned(self, *args, **kwargs):
        return True

    async def release_owned(self, *args, **kwargs):
        return True

    async def readiness_check(self):
        return True

    async def health_check(self):
        return True


def canonical_redis_capabilities(client, *, environment="production"):
    namespace = RedisNamespace.global_scope(environment=environment)
    limiter = RedisRateLimiter(client, namespace=namespace)
    limiter._mark_production_safe(_PRODUCTION_CAPABILITY_TOKEN)  # noqa: SLF001
    store = RedisLeaseStore(client, namespace=namespace)
    store._mark_production_safe(_PRODUCTION_CAPABILITY_TOKEN)  # noqa: SLF001
    lease = RedisLeaseClient(store=store)
    return namespace, limiter, lease


def settings():
    return ApiSettings(
        environment="production",
        cors_allowed_origins=("https://app.example.test",),
        session_cookie_secure=True,
        identity_mode="production",
        chat_backend_mode="professor",
        external_chat_api_key="provider-key",
        provider_kind="openai",
        locker_base_url="https://locker.example.test",
        external_database_dsn="postgresql://db.example.test/rick",
        redis_url="redis://redis.example.test/0",
        qdrant_url="https://qdrant.example.test",
        object_store_endpoint="https://objects.example.test",
        object_store_bucket="rick-documents",
        object_store_access_key="access-key",
        object_store_secret_key="secret-key",
    )


@pytest.mark.parametrize("provider_kind", ["openai", "anthropic", "independent-no-auth"])
def test_external_composition_builds_the_complete_graph_without_network_io(tmp_path, provider_kind, monkeypatch):
    calls = []
    provider_requests = []

    def provider_handler(request):
        provider_requests.append(request)
        return httpx.Response(500, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(provider_handler))
    redis_client = Redis()
    namespace, rate_limiter, lease = canonical_redis_capabilities(redis_client)
    identity = SimpleNamespace(
        production_safe=True,
        health_check=lambda: True,
        validate_token=lambda token: None,
        # This graph-construction test never authenticates a request. Returning
        # None keeps the placeholder callback fail-closed if accidentally used.
        refresh_authorization_context=lambda *, context: None,
    )
    inputs = ExternalCompositionInputs(
        connection_factory=lambda: calls.append("database"),
        object_store_transport=HttpTransport(),
        identity=identity,
        created_by="bootstrap-user",
        qdrant_transport=HttpTransport(),
        provider_client=client,
        redis_client=redis_client,
        rate_limiter=rate_limiter,
        rate_limit_namespace=namespace,
        lease=lease,
        worker_temp_root=str(tmp_path),
        worker_scope=("tenant-a", "workspace-a", "collection-a"),
    )

    selected_settings = settings()
    if provider_kind == "independent-no-auth":
        selected_settings = replace(selected_settings,
            embedding_provider_kind="openai_compatible",
            embedding_base_url="https://independent.example.test/v1", embedding_api_key="")
    if provider_kind == "anthropic":
        selected_settings = replace(
            selected_settings,
            provider_kind="anthropic",
            provider_base_url="https://api.anthropic.com/v1",
            provider_chat_model="claude-opus-5-5",
            embedding_provider_kind="openai",
            embedding_base_url="https://api.openai.com/v1",
            embedding_api_key="embedding-key",
        )
    providers = build_external_providers(selected_settings, inputs)

    assert calls == []
    for name in (
        "identity", "chat_backend", "knowledge", "vector_store", "retrieval",
        "ingestion", "worker", "audit_sink", "chat_history", "job_journal",
        "queue", "object_store", "provider", "lease",
    ):
        assert getattr(providers, name) is not None
    assert callable(providers.chat_backend.evidence_gate.authorization_revalidator)
    assert callable(providers.worker.queue.publication_reconciler)
    captured = []
    from rick_jobs import Job, JobFailure, JobState
    handler_type = type(providers.worker.queue.publication_reconciler.__self__)
    monkeypatch.setattr(handler_type, "__call__",
        lambda self, record, **kwargs: captured.append(record) or
        SimpleNamespace(status="published", document_id="callback-document", finished_at=17.0))
    retry = Job.create(job_id="callback-retry", tenant_id="tenant-a", workspace_id="workspace-a",
        collection_id="collection-a", operation="ingest", idempotency_key="callback-idem",
        payload={"object_key": "uploads/source"}, now=10, max_attempts=3)
    retry = retry.transition(JobState.QUEUED, now=11).start_attempt(worker_id="worker-a", now=12)
    retry = retry.finish_attempt(JobState.FAILED, now=13,
        failure=JobFailure(code="handler_failed", retryable=True, message="synthetic", occurred_at=13,
            attempt=retry.attempt_count))
    retry = retry.transition(JobState.RETRYING, now=14).transition(JobState.QUEUED, now=15)
    retry = retry.start_attempt(worker_id="worker-b", now=16)
    providers.worker.registry.get("ingest")(retry, SimpleNamespace(token="retry-token"), cancelled=lambda: False)
    assert captured[0].attempt_count == 2
    assert captured[0].created_at == retry.created_at
    assert captured[0].updated_at == retry.updated_at
    assert providers._embedding_adapter.provider is not providers.provider
    assert providers._embedding_adapter.provider.provider._client is not client
    if provider_kind == "independent-no-auth":
        assert providers._embedding_adapter.provider.provider.config.api_key is None
        assert providers._embedding_adapter.provider.provider.config.base_url == "https://independent.example.test/v1"
    assert set(providers.health_checks) >= {
        "postgres", "qdrant", "queue", "identity", "chat_backend",
        "audit_sink", "chat_history", "object_store", "retrieval", "worker", "provider",
    }
    assert asyncio.run(providers.health_checks["provider"]()) is False
    assert provider_requests[-1].method == "GET"
    request = provider_requests[-1]
    if provider_kind == "anthropic":
        assert request.url.host == "api.anthropic.com"
        assert request.url.path == "/v1/models/claude-opus-5-5"
        assert request.headers["x-api-key"] == "provider-key"
        assert "authorization" not in request.headers
    else:
        assert request.url.path.endswith("/models")

    asyncio.run(client.aclose())
    providers._embedding_adapter.close()
    providers.object_store.close()
    providers.vector_store.close()
    providers.worker.close()
    providers.queue.close()


def test_canonical_worker_accepts_ingestion_job_result_dataclass():
    job = SimpleNamespace(payload={"object_key": "objects/source.txt"}, updated_at=10.0)
    result = SimpleNamespace(status="published", document_id="document-1", finished_at=12.0)

    translated = _canonical_job_result(job, result)

    assert translated.document_id == "document-1"
    assert translated.completed_at == 12.0
    assert dict(translated.output_refs) == {"object_key": "objects/source.txt"}


def test_external_composition_loader_requires_a_deployment_factory(monkeypatch):
    with pytest.raises(ExternalCompositionError, match="RICK_API_COMPOSITION"):
        load_external_providers(settings(), reference="")

    inputs = ExternalCompositionInputs(
        connection_factory=lambda: None,
        object_store_transport=HttpTransport(),
        identity=SimpleNamespace(production_safe=True),
        created_by="bootstrap-user",
    )
    module = ModuleType("test_api_external_composition")
    module.factory = lambda configured: inputs
    monkeypatch.setitem(sys.modules, "test_api_external_composition", module)
    marker = object()
    monkeypatch.setattr(external_composition, "build_external_providers", lambda configured, received: marker)

    assert load_external_providers(
        settings(), reference="test_api_external_composition:factory",
    ) is marker


def test_api_entrypoint_connects_production_to_external_composition(monkeypatch):
    import main

    marker = object()
    monkeypatch.setattr(main, "load_external_providers", lambda configured: marker)
    monkeypatch.setattr(main, "create_app", lambda configured, providers=None: (configured, providers))

    configured = settings()
    assert main.create_entrypoint_app(configured) == (configured, marker)


def test_external_composition_requires_delivery_for_local_reset_capability(tmp_path):
    identity = SimpleNamespace(
        production_safe=True,
        issue_password_reset=lambda **kwargs: "opaque-token",
    )
    redis_client = Redis()
    namespace, rate_limiter, lease = canonical_redis_capabilities(redis_client)
    inputs = ExternalCompositionInputs(
        connection_factory=lambda: None,
        object_store_transport=HttpTransport(),
        identity=identity,
        created_by="bootstrap-user",
        qdrant_transport=HttpTransport(),
        redis_client=redis_client,
        rate_limiter=rate_limiter,
        rate_limit_namespace=namespace,
        lease=lease,
        worker_temp_root=str(tmp_path),
    )

    from services.external_composition import ExternalCompositionError

    try:
        build_external_providers(settings(), inputs)
    except ExternalCompositionError as exc:
        assert exc.component == "password reset delivery"
    else:
        raise AssertionError("password reset delivery must be explicit for external composition")


def test_external_composition_rejects_structural_rate_limiter_spoof(tmp_path):
    redis_client = Redis()
    namespace = RedisNamespace.global_scope(environment="production")
    inputs = ExternalCompositionInputs(
        connection_factory=lambda: None,
        object_store_transport=HttpTransport(),
        identity=SimpleNamespace(production_safe=True),
        created_by="bootstrap-user",
        qdrant_transport=HttpTransport(),
        redis_client=redis_client,
        rate_limiter=RateLimiter(),
        rate_limit_namespace=namespace,
        lease=Lease(),
        worker_temp_root=str(tmp_path),
    )

    with pytest.raises(ExternalCompositionError, match="bound to the injected client"):
        build_external_providers(settings(), inputs)


@pytest.mark.parametrize("inside_event_loop", [False, True])
def test_sync_embedding_adapter_enforces_a_bounded_provider_call(inside_event_loop):
    import asyncio
    import time

    class SlowProvider:
        async def get_embedding(self, text, *, model):
            await asyncio.sleep(0.2)
            return SimpleNamespace(vector=[1.0])

    adapter = external_composition.SyncEmbeddingAdapter(
        SlowProvider(),
        model="embedding-model",
        dimensions=1,
        timeout_seconds=0.02,
    )

    def invoke():
        started = time.monotonic()
        with pytest.raises(TimeoutError, match="embedding call timed out"):
            adapter.embed(["bounded input"])
        assert time.monotonic() - started < 1.0

    if inside_event_loop:
        async def run_inside_loop():
            invoke()

        asyncio.run(run_inside_loop())
    else:
        invoke()
    adapter.close()


def test_graph_keeps_chat_and_embedding_connection_pools_on_their_own_loops(tmp_path):
    import json
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args):
            pass

        def reply(self, payload):
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self.reply({"object": "list", "data": [
                {"id": "embedding-model", "object": "model"},
                {"id": "gpt-4o-mini", "object": "model"}]})

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.reply({"object": "list", "model": "embedding-model", "data": [
                {"object": "embedding", "index": 0, "embedding": [1.0]}],
                "usage": {"prompt_tokens": 1, "total_tokens": 1}})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    redis_client = Redis()
    namespace, limiter, lease = canonical_redis_capabilities(redis_client, environment="test")
    client = httpx.AsyncClient()
    inputs = ExternalCompositionInputs(
        connection_factory=lambda: None, object_store_transport=HttpTransport(),
        qdrant_transport=HttpTransport(),
        identity=SimpleNamespace(production_safe=True, health_check=lambda: True,
            refresh_authorization_context=lambda *, context: None),
        created_by="bootstrap-user", provider_client=client,
        redis_client=redis_client, rate_limiter=limiter,
        rate_limit_namespace=namespace, lease=lease,
        worker_temp_root=str(tmp_path), worker_scope=("tenant-a", "workspace-a", "collection-a"),
    )
    selected = replace(settings(), environment="test", provider_kind="openai_compatible",
        provider_base_url=f"http://127.0.0.1:{server.server_port}/v1",
        provider_embedding_model="embedding-model", provider_embedding_dimensions=1,
        provider_timeout_ms=1000, provider_max_attempts=1,
        provider_retry_delay_ms=0, provider_max_backoff_ms=0)
    providers = build_external_providers(selected, inputs)
    adapter = providers._embedding_adapter

    async def verify():
        for _ in range(3):
            assert await providers.health_checks["provider"]() is True
            assert adapter.embed(["persistent HTTP pool"]) == [[1.0]]
            assert await providers.health_checks["embedding_provider"]() is True
        # Close the dedicated embedding pool on its bridge before the API pool.
        await asyncio.to_thread(adapter.close)
        await providers.provider.aclose()
        assert not client.is_closed  # direct construction retains caller ownership
        await client.aclose()

    try:
        asyncio.run(verify())
        assert not any(t.name == "rick-sync-provider-loop" and t.is_alive()
                       for t in __import__("threading").enumerate())
    finally:
        adapter.close()
        providers.worker.close()
        providers.queue.close()
        providers.object_store.close()
        providers.vector_store.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_transferred_embedding_client_is_closed_once_on_its_owned_loop():
    loops = []

    class Provider:
        async def get_embedding(self, text, *, model):
            loops.append(asyncio.get_running_loop())
            return SimpleNamespace(vector=[1.0])

        async def aclose(self):
            loops.append(asyncio.get_running_loop())

    class Client:
        closes = 0

        async def aclose(self):
            loops.append(asyncio.get_running_loop())
            self.closes += 1

    client = Client()
    adapter = external_composition.SyncEmbeddingAdapter(Provider(), model="model", dimensions=1)
    adapter.transferred_client = client
    assert adapter.embed(["input"]) == [[1.0]]
    adapter.close()
    adapter.close()
    assert client.closes == 1
    assert len({id(loop) for loop in loops}) == 1
    assert loops[0].is_closed()
    with pytest.raises(ExternalCompositionError, match="closed"):
        adapter.embed(["after close"])

class SyntheticPort:
    """Custom port: valid chat/embedding contract, but no live probe at all."""

    provider_kind = "synthetic"
    is_test_provider = False

    async def chat_completion(self, *args, **kwargs):
        raise AssertionError("admission never runs inference")

    async def get_embedding(self, *args, **kwargs):
        raise AssertionError("admission never runs inference")


def _build_composition(tmp_path, monkeypatch, handler, *, provider_factory=None):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    redis_client = Redis()
    namespace, rate_limiter, lease = canonical_redis_capabilities(redis_client)
    identity = SimpleNamespace(
        production_safe=True,
        health_check=lambda: True,
        validate_token=lambda token: None,
        refresh_authorization_context=lambda *, context: None,
    )
    inputs = ExternalCompositionInputs(
        connection_factory=lambda: None,
        object_store_transport=HttpTransport(),
        identity=identity,
        created_by="bootstrap-user",
        qdrant_transport=HttpTransport(),
        provider_client=client,
        redis_client=redis_client,
        rate_limiter=rate_limiter,
        rate_limit_namespace=namespace,
        lease=lease,
        worker_temp_root=str(tmp_path),
        worker_scope=("tenant-a", "workspace-a", "collection-a"),
    )
    if provider_factory is not None:
        monkeypatch.setattr("rick_providers.create_provider", provider_factory)
    providers = build_external_providers(settings(), inputs)
    return providers, client


def _close_composition(providers, client) -> None:
    asyncio.run(client.aclose())
    providers._embedding_adapter.close()
    providers.object_store.close()
    providers.vector_store.close()
    providers.worker.close()
    providers.queue.close()


def test_composition_admits_the_official_provider_through_its_live_probe(tmp_path, monkeypatch):
    model = settings().provider_chat_model

    def handler(request):
        return httpx.Response(200, request=request, json={
            "object": "list",
            "data": [{"id": model, "object": "model", "created": 0, "owned_by": "test"}],
        })

    providers, client = _build_composition(tmp_path, monkeypatch, handler)
    try:
        assert providers.provider.production_safe is True
        assert asyncio.run(providers.health_checks["provider"]()) is True
    finally:
        _close_composition(providers, client)


def test_composition_refuses_a_provider_port_without_a_probe(tmp_path, monkeypatch):
    def handler(request):  # pragma: no cover - the synthetic port never reaches it
        return httpx.Response(200, request=request, json={})

    def synthetic_factory(config=None, **kwargs):
        return SyntheticPort()

    providers, client = _build_composition(
        tmp_path, monkeypatch, handler, provider_factory=synthetic_factory
    )
    try:
        # Fail closed at both levels: the wrapped port and the readiness probe
        # the composition registers for it.
        assert providers.provider.production_safe is False
        assert asyncio.run(providers.health_checks["provider"]()) is False
    finally:
        _close_composition(providers, client)
