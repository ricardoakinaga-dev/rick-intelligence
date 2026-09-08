"""Explicit production composition for Postgres/S3/Qdrant/Redis/provider.

This module is a constructor graph, not a process launcher. It never reads a
driver pool from ambient state or opens a socket during import. The caller
supplies database, Redis, HTTP transports, and the approved identity policy;
that makes missing D01/D02 decisions fail at composition time.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from importlib import import_module
import inspect
from threading import Thread
from typing import Callable

from core.config import ApiSettings
from dependencies.services import Providers


class ExternalCompositionError(RuntimeError):
    """Safe construction failure for an incomplete external runtime."""

    def __init__(self, component: str) -> None:
        self.component = component
        super().__init__(f"external composition requires {component}")


@dataclass(frozen=True, slots=True)
class ExternalCompositionInputs:
    """Caller-owned clients and policies needed to build the graph."""

    connection_factory: Callable[[], object]
    object_store_transport: object
    identity: object
    created_by: str
    qdrant_transport: object | None = None
    provider_transport: object | None = None
    provider_client: object | None = None
    redis_client: object | None = None
    event_sink: object | None = None
    password_reset_delivery: object | None = None
    worker_temp_root: str | None = None
    worker_id: str | None = None


class SyncEmbeddingAdapter:
    """Bridge the async provider embedding port to sync ingestion/retrieval."""

    def __init__(self, provider: object, *, model: str, dimensions: int) -> None:
        if not callable(getattr(provider, "get_embedding", None)):
            raise ExternalCompositionError("provider embeddings")
        self.provider = provider
        self.model = model
        self.dimensions = dimensions

    @staticmethod
    def _run(awaitable: object) -> object:
        if not inspect.isawaitable(awaitable):
            return awaitable
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(awaitable)

        # Retrieval is called from an async API request, while the canonical
        # package contract is synchronous. Execute the bounded provider call
        # on a short-lived helper thread rather than nesting event loops.
        result: dict[str, object] = {}

        def run() -> None:
            try:
                result["value"] = asyncio.run(awaitable)
            except BaseException as exc:
                result["error"] = exc

        thread = Thread(target=run, name="rick-sync-embedding", daemon=True)
        thread.start()
        thread.join()
        error = result.get("error")
        if isinstance(error, BaseException):
            raise error
        return result.get("value")

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not isinstance(texts, list) or not texts or len(texts) > 256:
            raise ValueError("embedding batch is out of range")
        vectors: list[list[float]] = []
        for text in texts:
            if not isinstance(text, str) or not text.strip():
                raise ValueError("embedding text is invalid")
            result = self._run(self.provider.get_embedding(text, model=self.model))
            vector = getattr(result, "vector", None)
            if not isinstance(vector, list) or len(vector) != self.dimensions:
                raise ValueError("embedding dimension mismatch")
            vectors.append(list(vector))
        return vectors


def build_external_providers(
    settings: ApiSettings,
    inputs: ExternalCompositionInputs,
) -> Providers:
    """Build one complete external provider container with explicit ownership."""

    if not isinstance(settings, ApiSettings):
        raise ExternalCompositionError("settings")
    settings.validate()
    for name, value in (
        ("connection factory", inputs.connection_factory),
        ("object store transport", inputs.object_store_transport),
        ("identity policy", inputs.identity),
        ("created_by", inputs.created_by),
    ):
        if value is None or (isinstance(value, str) and not value.strip()) or (callable(value) is False and name == "connection factory"):
            raise ExternalCompositionError(name)
    if not settings.external_database_dsn:
        raise ExternalCompositionError("RICK_EXTERNAL_DATABASE_DSN")
    if not settings.object_store_endpoint:
        raise ExternalCompositionError("RICK_OBJECT_STORE_ENDPOINT")
    if not settings.object_store_access_key or not settings.object_store_secret_key:
        raise ExternalCompositionError("object store credentials")
    if not settings.qdrant_url:
        raise ExternalCompositionError("RICK_QDRANT_URL")
    if not settings.redis_url or inputs.redis_client is None:
        raise ExternalCompositionError("Redis client and RICK_REDIS_URL")

    from rick_ingestion import IngestionService
    from rick_knowledge import PostgresKnowledgeStore
    from rick_locking import RedisLeaseClient
    from rick_providers import ProviderConfig, ResilientProvider, create_provider
    from rick_retrieval import QdrantBackend, QdrantHttpVectorStore
    from rick_storage import AwsCredentials, S3CompatibleObjectStore
    from services.postgres_audit import PostgresAuditStore
    from services.postgres_chat_history import PostgresChatHistoryStore
    from services.postgres_ingestion import PostgresIngestionApplicationService
    from services.professor_backend import ProfessorChatBackend
    from services.retrieval_service import RetrievalApplicationService
    # The worker distribution is placed on the process' import path by the
    # deployment image. Keeping this as a package-name boundary avoids making
    # the API source import the sibling ``apps`` namespace directly.
    try:
        worker_module = import_module("worker")
        external_worker_module = import_module("worker.external_ingestion")
    except ImportError:
        # A flattened worker image may put its modules directly on sys.path.
        worker_module = import_module("postgres_runner")
        queue_module = import_module("postgres_queue")
        external_worker_module = import_module("external_ingestion")
        worker_module.PostgresIngestionQueue = queue_module.PostgresIngestionQueue
    PostgresIngestionWorker = worker_module.PostgresIngestionWorker
    PostgresIngestionQueue = worker_module.PostgresIngestionQueue
    ExternalIngestionHandler = external_worker_module.ExternalIngestionHandler

    # Identity is supplied by the deployment policy. The type check is kept
    # intentionally duck-typed so an approved OIDC+admin facade can be used
    # without the API importing a provider-specific callback broker.
    if getattr(inputs.identity, "production_safe", False) is not True:
        raise ExternalCompositionError("production-safe identity provider")
    if callable(getattr(inputs.identity, "issue_password_reset", None)) and (
        inputs.password_reset_delivery is None
    ):
        raise ExternalCompositionError("password reset delivery")

    queue = PostgresIngestionQueue(
        inputs.connection_factory,
        max_pending=settings.max_pending_ingestion_jobs,
        event_sink=inputs.event_sink,
    )
    knowledge = PostgresKnowledgeStore(
        inputs.connection_factory,
        created_by=inputs.created_by,
    )
    chat_history = PostgresChatHistoryStore(inputs.connection_factory)
    audit_sink = PostgresAuditStore(inputs.connection_factory)
    object_store = S3CompatibleObjectStore(
        settings.object_store_endpoint,
        settings.object_store_bucket,
        settings.object_store_region,
        AwsCredentials(
            access_key_id=settings.object_store_access_key,
            secret_access_key=settings.object_store_secret_key,
        ),
        inputs.object_store_transport,
        require_https=settings.environment == "production",
    )
    vectors = QdrantHttpVectorStore(
        base_url=settings.qdrant_url,
        collection=settings.qdrant_collection,
        api_key=settings.qdrant_api_key or None,
        timeout=max(0.1, settings.provider_timeout_ms / 1_000),
        transport=inputs.qdrant_transport,
    )
    provider_config = ProviderConfig(
        base_url=settings.provider_base_url,
        api_key=settings.external_chat_api_key or None,
        chat_model=settings.provider_chat_model,
        embedding_model=settings.provider_embedding_model,
        embedding_dimensions=settings.provider_embedding_dimensions,
        timeout_ms=settings.provider_timeout_ms,
        environment=settings.environment,
        provider_kind=settings.selected_provider_kind,
    )
    provider = ResilientProvider(
        create_provider(
            provider_config,
            transport=inputs.provider_transport,
            client=inputs.provider_client,
        ),
        max_prompt_chars=max(1_000, settings.max_chat_message_chars * 8),
    )
    embeddings = SyncEmbeddingAdapter(
        provider,
        model=settings.provider_embedding_model,
        dimensions=settings.provider_embedding_dimensions,
    )
    retrieval = RetrievalApplicationService(
        knowledge=knowledge,
        vectors=vectors,
        embeddings=embeddings,
        backend=QdrantBackend(vectors),
    )
    lease = RedisLeaseClient(inputs.redis_client, close_client=False)
    professor = ProfessorChatBackend(retrieval=retrieval, provider=provider, lease=lease)
    canonical_ingestion = IngestionService(
        knowledge=knowledge,
        vectors=vectors,
        embeddings=embeddings,
        max_jobs=settings.max_pending_ingestion_jobs,
    )
    ingestion = PostgresIngestionApplicationService(
        queue=queue,
        object_store=object_store,
        knowledge=knowledge,
        vectors=vectors,
        max_bytes=settings.max_upload_bytes,
        max_jobs=settings.max_pending_ingestion_jobs,
        event_sink=inputs.event_sink,
    )
    handler = ExternalIngestionHandler(
        canonical_ingestion,
        object_store,
        max_bytes=settings.max_upload_bytes,
        temp_root=inputs.worker_temp_root,
        created_by=inputs.created_by,
    )
    worker = PostgresIngestionWorker(
        queue,
        handler,
        worker_id=inputs.worker_id or settings.worker_id,
        event_sink=inputs.event_sink,
    )

    # The queue is the durable job journal marker required by the current
    # Providers contract. It is injected-owned and is never closed by API
    # lifecycle code when the same container is shared with the worker.
    def probe(method):
        """Normalize adapter health records to the lifecycle boolean port."""

        def check():
            result = method()
            if inspect.isawaitable(result):
                async def await_result():
                    value = await result
                    ok = getattr(value, "ok", None)
                    return ok if isinstance(ok, bool) else value
                return await_result()
            ok = getattr(result, "ok", None)
            return ok if isinstance(ok, bool) else result
        return check

    health_checks = {
        "postgres": probe(knowledge.health_check),
        "qdrant": probe(vectors.health_check),
        "queue": probe(queue.health_check),
    }
    # Register checks at the same names used by the production lifecycle. A
    # component without an explicit probe remains not-ready through the
    # lifecycle's default-deny path; construction never turns presence into
    # a reachability claim.
    for name, component in (
        ("identity", inputs.identity),
        ("chat_backend", professor),
        ("audit_sink", audit_sink),
        ("chat_history", chat_history),
        ("job_journal", queue),
        ("object_store", object_store),
        ("retrieval", vectors),
        ("ingestion", ingestion),
        ("worker", worker),
        ("vector_store", vectors),
        ("storage", knowledge),
        ("provider", provider),
        ("lease", lease),
    ):
        for method_name in ("readiness_check", "health_check", "check_readiness", "check_health"):
            method = getattr(component, method_name, None)
            if callable(method):
                health_checks[name] = probe(method)
                break
    return Providers(
        settings=settings,
        identity=inputs.identity,
        chat_backend=professor,
        health_checks=health_checks,
        audit_sink=audit_sink,
        chat_history=chat_history,
        job_journal=queue,
        knowledge=knowledge,
        vector_store=vectors,
        retrieval=retrieval,
        provider=provider,
        lease=lease,
        professor=professor,
        ingestion=ingestion,
        worker=worker,
        storage=knowledge,
        queue=queue,
        object_store=object_store,
        password_reset_delivery=inputs.password_reset_delivery,
    )


__all__ = [
    "ExternalCompositionError", "ExternalCompositionInputs",
    "SyncEmbeddingAdapter", "build_external_providers",
]
