from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

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

from core.config import ApiSettings
from services.external_composition import ExternalCompositionInputs, build_external_providers


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
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(500)))
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
        redis_client=Redis(),
        worker_temp_root=str(tmp_path),
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
        "audit_sink", "chat_history", "object_store", "retrieval", "worker",
    }

    import asyncio

    asyncio.run(client.aclose())
    providers.object_store.close()
    providers.vector_store.close()
    providers.worker.close()
    providers.queue.close()


def test_external_composition_requires_delivery_for_local_reset_capability(tmp_path):
    identity = SimpleNamespace(
        production_safe=True,
        issue_password_reset=lambda **kwargs: "opaque-token",
    )
    inputs = ExternalCompositionInputs(
        connection_factory=lambda: None,
        object_store_transport=HttpTransport(),
        identity=identity,
        created_by="bootstrap-user",
        qdrant_transport=HttpTransport(),
        redis_client=Redis(),
        worker_temp_root=str(tmp_path),
    )

    from services.external_composition import ExternalCompositionError

    try:
        build_external_providers(settings(), inputs)
    except ExternalCompositionError as exc:
        assert exc.component == "password reset delivery"
    else:
        raise AssertionError("password reset delivery must be explicit for external composition")
