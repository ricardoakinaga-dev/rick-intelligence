from __future__ import annotations

import asyncio
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


def canonical_redis_capabilities(client):
    namespace = RedisNamespace.global_scope(environment="production")
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


def test_external_composition_builds_the_complete_graph_without_network_io(tmp_path):
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

    providers = build_external_providers(settings(), inputs)

    assert calls == []
    for name in (
        "identity", "chat_backend", "knowledge", "vector_store", "retrieval",
        "ingestion", "worker", "audit_sink", "chat_history", "job_journal",
        "queue", "object_store", "provider", "lease",
    ):
        assert getattr(providers, name) is not None
    assert set(providers.health_checks) >= {
        "postgres", "qdrant", "queue", "identity", "chat_backend",
        "audit_sink", "chat_history", "object_store", "retrieval", "worker", "provider",
    }
    assert asyncio.run(providers.health_checks["provider"]()) is False
    assert provider_requests[-1].method == "GET"
    assert provider_requests[-1].url.path.endswith("/models")

    asyncio.run(client.aclose())
    providers.object_store.close()
    providers.vector_store.close()
    providers.worker.close()
    providers.queue.close()


def test_canonical_worker_accepts_ingestion_job_result_dataclass():
    job = SimpleNamespace(payload={"object_key": "objects/source.txt"}, updated_at=10.0)
    result = SimpleNamespace(status="published", document_id="document-1")

    translated = _canonical_job_result(job, result)

    assert translated.document_id == "document-1"
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
