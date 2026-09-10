"""Explicit production composition for Postgres/S3/Qdrant/Redis/provider.

This module is a constructor graph, not a process launcher. It never reads a
driver pool from ambient state or opens a socket during import. The caller
supplies database, Redis, HTTP transports, and the approved identity policy;
that makes missing D01/D02 decisions fail at composition time.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import import_module
import inspect
import math
import os
import re
from threading import Event, Lock, Thread
from types import SimpleNamespace
import time
from typing import Callable

from core.config import ApiSettings
from core.otel import record_safe_exception, stage_span
from dependencies.services import Providers


class ExternalCompositionError(RuntimeError):
    """Safe construction failure for an incomplete external runtime."""

    def __init__(self, component: str) -> None:
        self.component = component
        super().__init__(f"external composition requires {component}")


_COMPOSITION_REFERENCE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*$")
_MAX_PROVIDER_TIMEOUT_SECONDS = 120.0


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
    rate_limiter: object | None = None
    rate_limit_namespace: object | None = None
    lease: object | None = None
    event_sink: object | None = None
    password_reset_delivery: object | None = None
    worker_temp_root: str | None = None
    worker_id: str | None = None
    worker_scope: tuple[str, str, str] | None = None
    # The API and worker are separate processes.  The API still exposes the
    # worker in Providers so contracts remain complete, but it must not claim
    # that an unstarted in-process worker is ready.  The worker composition
    # leaves this enabled and performs its own startup/readiness check.
    worker_health_check_required: bool = True
    parser_runner: object | None = None
    worker_max_concurrency: int = 4
    worker_timeout_seconds: float = 300.0


def load_external_providers(
    settings: ApiSettings,
    *,
    reference: str | None = None,
) -> Providers:
    """Load and build the explicit production composition from a module hook.

    The image cannot guess database, identity, broker or transport ownership.
    A deployment supplies ``module:factory`` through ``RICK_API_COMPOSITION``;
    the factory receives validated settings and must return
    :class:`ExternalCompositionInputs`.  This connects the Uvicorn entrypoint
    to the canonical graph while retaining fail-closed dependency injection.
    """

    raw_reference = (reference if reference is not None else os.getenv("RICK_API_COMPOSITION", "")).strip()
    if not raw_reference or len(raw_reference) > 256 or _COMPOSITION_REFERENCE.fullmatch(raw_reference) is None:
        raise ExternalCompositionError("RICK_API_COMPOSITION=module:factory")
    module_name, factory_name = raw_reference.split(":", 1)
    try:
        factory = getattr(import_module(module_name), factory_name)
    except (AttributeError, ImportError, TypeError, ValueError):
        raise ExternalCompositionError("RICK_API_COMPOSITION factory") from None
    if not callable(factory):
        raise ExternalCompositionError("RICK_API_COMPOSITION factory")
    try:
        inputs = factory(settings)
    except ExternalCompositionError:
        raise
    except Exception:
        raise ExternalCompositionError("external provider inputs") from None
    if not isinstance(inputs, ExternalCompositionInputs):
        raise ExternalCompositionError("ExternalCompositionInputs")
    providers = build_external_providers(settings, inputs)
    # Explicit deployment factories transfer lifecycle ownership to the API
    # process. Ordinary test/provider injection remains caller-owned.
    try:
        providers._composition_owned = True
        providers._composition_inputs = inputs
    except (AttributeError, TypeError):
        # A narrow test seam may return an immutable sentinel; the loader's
        # contract is still satisfied and the caller retains its ownership.
        pass
    return providers


class SyncEmbeddingAdapter:
    """Bridge the async provider embedding port to sync ingestion/retrieval."""

    def __init__(
        self,
        provider: object,
        *,
        model: str,
        dimensions: int,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not callable(getattr(provider, "get_embedding", None)):
            raise ExternalCompositionError("provider embeddings")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds))
            or not 0.001 <= float(timeout_seconds) <= _MAX_PROVIDER_TIMEOUT_SECONDS
        ):
            raise ExternalCompositionError("provider embedding timeout")
        self.provider = provider
        self.model = model
        self.dimensions = dimensions
        self.timeout_seconds = float(timeout_seconds)
        self._bridge: _AsyncLoopBridge | None = None
        self._bridge_lock = Lock()

    def _get_bridge(self) -> "_AsyncLoopBridge":
        with self._bridge_lock:
            if self._bridge is None:
                self._bridge = _AsyncLoopBridge()
            return self._bridge

    def _run(self, awaitable: object) -> object:
        if not inspect.isawaitable(awaitable):
            return awaitable

        return self._get_bridge().run(awaitable, timeout=self.timeout_seconds)

    def close(self) -> None:
        with self._bridge_lock:
            bridge, self._bridge = self._bridge, None
        if bridge is not None:
            closer = getattr(self.provider, "aclose", None)
            try:
                if callable(closer):
                    bridge.run(closer(), timeout=self.timeout_seconds)
            finally:
                bridge.close()

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not isinstance(texts, list) or not texts or len(texts) > 256:
            raise ValueError("embedding batch is out of range")
        vectors: list[list[float]] = []
        for text in texts:
            if not isinstance(text, str) or not text.strip():
                raise ValueError("embedding text is invalid")
            with stage_span("provider.embedding", attributes={"provider.operation": "embedding"}) as span:
                try:
                    result = self._run(self.provider.get_embedding(text, model=self.model))
                except Exception as exc:
                    record_safe_exception(span, exc)
                    raise
            vector = getattr(result, "vector", None)
            if not isinstance(vector, list) or len(vector) != self.dimensions:
                raise ValueError("embedding dimension mismatch")
            vectors.append(list(vector))
        return vectors


class _AsyncLoopBridge:
    """One owned event loop for sync ingestion calls into async providers."""

    def __init__(self) -> None:
        self._ready = Event()
        self._closed = False
        self._lock = Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread = Thread(target=self._serve, name="rick-sync-provider-loop", daemon=True)
        self._thread.start()
        if not self._ready.wait(2.0) or self._loop is None:
            self.close()
            raise ExternalCompositionError("provider event loop")

    def _serve(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()

    def run(self, awaitable: object, *, timeout: float) -> object:
        if not inspect.isawaitable(awaitable):
            return awaitable
        with self._lock:
            if self._closed or self._loop is None:
                raise ExternalCompositionError("provider event loop closed")
            loop = self._loop

        async def bounded() -> object:
            try:
                return await asyncio.wait_for(awaitable, timeout=timeout)
            except asyncio.TimeoutError:
                raise TimeoutError("provider embedding call timed out") from None

        future = asyncio.run_coroutine_threadsafe(bounded(), loop)
        try:
            return future.result(timeout + 0.25)
        except TimeoutError:
            future.cancel()
            raise TimeoutError("provider embedding call timed out") from None

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            loop = self._loop
        if loop is not None:
            loop.call_soon_threadsafe(loop.stop)
        self._thread.join(1.0)


def _canonical_job_result(job: object, result: object) -> JobResult:
    """Translate either the canonical ingestion dataclass or a mapping safely."""

    from rick_jobs import JobResult

    result_status = result.get("status") if isinstance(result, Mapping) else getattr(result, "status", None)
    if result_status != "published":
        raise RuntimeError("ingestion handler returned an invalid result")
    document_id = result.get("document_id") if isinstance(result, Mapping) else getattr(result, "document_id", None)
    if document_id is not None and not isinstance(document_id, str):
        raise RuntimeError("ingestion handler returned an invalid document")
    payload = getattr(job, "payload", {})
    output_refs = {}
    object_key = payload.get("object_key") if isinstance(payload, Mapping) else None
    if isinstance(object_key, str) and object_key:
        output_refs["object_key"] = object_key
    updated_at = getattr(job, "updated_at", 0.0)
    return JobResult(
        output_refs=output_refs,
        document_id=document_id,
        completed_at=max(time.time(), float(updated_at)),
    )


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
    from rick_locking import (
        RedisConfigurationError,
        RedisLeaseClient,
        RedisNamespace,
        RedisRateLimiter,
        validate_production_capability,
    )

    rate_limiter = inputs.rate_limiter
    rate_limit_namespace = inputs.rate_limit_namespace
    expected_environment = settings.environment
    if (
        not isinstance(rate_limiter, RedisRateLimiter)
        or rate_limiter.redis_client is not inputs.redis_client
        or not isinstance(rate_limit_namespace, RedisNamespace)
        or rate_limit_namespace.scope != "global"
        or rate_limit_namespace.environment != expected_environment
        or rate_limiter.namespace != rate_limit_namespace
    ):
        raise ExternalCompositionError(
            "production-safe Redis rate limiter bound to the injected client and global namespace"
        )
    if settings.environment == "production":
        try:
            validate_production_capability(rate_limiter)
        except RedisConfigurationError:
            raise ExternalCompositionError(
                "production-safe Redis rate limiter bound to the injected client and global namespace"
            ) from None

    from rick_ingestion import IngestionService, ProcessParserRunner
    from rick_jobs import JobResult, JobScope
    from rick_knowledge import PostgresKnowledgeStore
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
    canonical_module = canonical_queue_module = runtime_module = None
    try:
        worker_module = import_module("worker")
        external_worker_module = import_module("worker.external_ingestion")
    except ImportError:
        # A flattened worker image may put its modules directly on sys.path.
        worker_module = import_module("postgres_runner")
        external_worker_module = import_module("external_ingestion")
        canonical_module = import_module("postgres_jobs")
        canonical_queue_module = import_module("canonical_queue")
        runtime_module = import_module("runtime")
    try:
        PostgresJobQueue = worker_module.PostgresJobQueue
        CanonicalIngestionQueueAdapter = worker_module.CanonicalIngestionQueueAdapter
        WorkerRuntime = worker_module.WorkerRuntime
    except AttributeError:
        if canonical_module is None or canonical_queue_module is None or runtime_module is None:
            raise ExternalCompositionError("canonical worker runtime") from None
        PostgresJobQueue = canonical_module.PostgresJobQueue
        CanonicalIngestionQueueAdapter = canonical_queue_module.CanonicalIngestionQueueAdapter
        WorkerRuntime = runtime_module.WorkerRuntime
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

    if not isinstance(inputs.worker_scope, tuple) or len(inputs.worker_scope) != 3:
        raise ExternalCompositionError("worker scope")
    parser_runner = inputs.parser_runner or ProcessParserRunner()
    if (
        getattr(parser_runner, "production_safe", False) is not True
        or getattr(parser_runner, "process_isolated", False) is not True
        or not callable(getattr(parser_runner, "run", None))
    ):
        raise ExternalCompositionError("process-isolated parser runner")
    try:
        worker_scope = JobScope(*inputs.worker_scope)
    except (TypeError, ValueError) as exc:
        raise ExternalCompositionError("worker scope") from exc

    canonical_queue = PostgresJobQueue(
        inputs.connection_factory,
        max_pending=settings.max_pending_ingestion_jobs,
    )
    queue = CanonicalIngestionQueueAdapter(canonical_queue)
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
        timeout_seconds=max(0.1, settings.provider_timeout_ms / 1_000),
    )
    retrieval = RetrievalApplicationService(
        knowledge=knowledge,
        vectors=vectors,
        embeddings=embeddings,
        backend=QdrantBackend(vectors),
    )
    lease = inputs.lease
    if lease is None and settings.environment == "production":
        raise ExternalCompositionError("production-safe Redis lease")
    if lease is None:
        lease = RedisLeaseClient(inputs.redis_client, close_client=False)
    if settings.environment == "production":
        if not isinstance(lease, RedisLeaseClient) or lease.redis_client is not inputs.redis_client:
            raise ExternalCompositionError("production-safe Redis lease bound to the injected client")
        try:
            validate_production_capability(lease)
        except RedisConfigurationError:
            raise ExternalCompositionError("production-safe Redis lease bound to the injected client") from None
    professor = ProfessorChatBackend(
        retrieval=retrieval,
        provider=provider,
        lease=lease,
        knowledge=knowledge,
    )
    canonical_ingestion = IngestionService(
        knowledge=knowledge,
        vectors=vectors,
        embeddings=embeddings,
        max_jobs=settings.max_pending_ingestion_jobs,
        parser_runner=parser_runner,
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

    def canonical_ingestion_handler(job, lease, *, cancelled):
        record = SimpleNamespace(
            job_id=str(job.job_id),
            lease_token=str(lease.token),
            tenant_id=job.tenant_id,
            workspace_id=job.workspace_id,
            collection_id=job.collection_id,
            payload=dict(job.payload),
        )
        result = handler(record, lease_lost_check=cancelled)
        return _canonical_job_result(job, result)

    worker = WorkerRuntime(
        canonical_queue,
        worker_id=inputs.worker_id or settings.worker_id,
        scope=worker_scope,
        handlers={"ingest": canonical_ingestion_handler, "reindex": canonical_ingestion_handler},
        max_concurrency=inputs.worker_max_concurrency,
        handler_timeout_seconds=inputs.worker_timeout_seconds,
        event_sink=inputs.event_sink,
    )
    # The API composition remains lazy: the worker process calls startup before
    # polling, while construction only wires the reviewed graph.

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
        "redis": probe(rate_limiter.readiness_check),
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
        if name == "worker" and inputs.worker_health_check_required is not True:
            continue
        method_names = (
            ("health_check", "readiness_check", "check_readiness", "check_health")
            if name == "provider"
            else ("readiness_check", "health_check", "check_readiness", "check_health")
        )
        for method_name in method_names:
            method = getattr(component, method_name, None)
            if callable(method):
                health_checks[name] = probe(method)
                break
    providers = Providers(
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
        rate_limiter=rate_limiter,
        professor=professor,
        ingestion=ingestion,
        worker=worker,
        storage=knowledge,
        queue=queue,
        object_store=object_store,
        password_reset_delivery=inputs.password_reset_delivery,
    )
    # The sync retrieval bridge owns a persistent event loop for the async
    # provider client. Expose it only to the explicit composition owner so
    # application shutdown can stop that loop before closing the provider.
    providers._embedding_adapter = embeddings
    # The API process shares the complete provider graph with the worker but
    # does not own that worker's polling loop. Readiness must not synthesize a
    # worker probe from the merely-present object.
    providers._worker_health_check_required = inputs.worker_health_check_required
    return providers


__all__ = [
    "ExternalCompositionError", "ExternalCompositionInputs",
    "SyncEmbeddingAdapter", "build_external_providers", "load_external_providers",
]
