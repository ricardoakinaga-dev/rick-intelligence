"""Deterministic application factory: production, unit, and integration runtimes via DI."""

from __future__ import annotations

from copy import copy
from collections.abc import Mapping
from contextlib import asynccontextmanager
import asyncio
import inspect
from itertools import islice
from threading import Event, RLock, Thread
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import ApiSettings
from core.errors import register_error_handlers
from core.lifecycle import DependencyState
from core.middleware import (
    CSRFProtectionMiddleware,
    MetricsMiddleware,
    RequestContextMiddleware,
    RequestIdMiddleware,
    RequestSizeLimitMiddleware,
    SecurityHeadersMiddleware,
)
from core.streaming import ClosingStreamingRoute
from core.telemetry import ApiTelemetry


MAX_POINT_REFRESH = 100_000
APP_LIFESPAN_SHUTDOWN_TIMEOUT_SECONDS = 5.0


def _bounded_point_refresh(reader) -> list[dict]:
    try:
        points = reader(limit=MAX_POINT_REFRESH)
    except TypeError:
        points = reader()
    snapshot = list(islice(points, MAX_POINT_REFRESH + 1))
    if len(snapshot) > MAX_POINT_REFRESH:
        raise ValueError("complete point snapshot exceeds read limit")
    return snapshot
from dependencies.services import Providers
from routes import ROUTERS


def _default_health_checks(settings: ApiSettings) -> dict:
    def kernel() -> DependencyState:
        return DependencyState(name="kernel", ok=True, required=True)

    checks = {"kernel": kernel}
    if settings.use_legacy_health_checks:
        def legacy_bridge() -> DependencyState:
            try:
                import sys
                from pathlib import Path

                src = str(Path(__file__).resolve().parents[4].parent.parent / "cvg-master-rag-v2" / "src")
                # NOTE: health check only; never imported at module scope.
                return DependencyState(name="legacy-bridge", ok=True, required=False,
                                       detail="legacy checks deferred to Phase 1.4")
            except Exception:
                return DependencyState(name="legacy-bridge", ok=False, required=False)

        checks["legacy-bridge"] = legacy_bridge
    return checks


def _build_root_ingestion(*, settings: ApiSettings, knowledge: object,
                          retrieval: object, vectors: object, embeddings: object,
                          job_journal: object | None = None,
                          staging_root: str | None = None,
                          event_sink: object | None = None):
    """Build the local root ingestion lifecycle without external side effects.

    The package pipeline remains a synchronous domain operation, while the
    application boundary exposes it through a bounded process-local worker
    queue. A later durable worker can replace this wiring without changing the
    public lifecycle routes.
    """
    if settings.environment == "production":
        # A real production embedding/storage adapter is a subsequent rollout
        # gate; do not silently index production documents with a hash fixture.
        return None
    from rick_ingestion import IngestionService
    from services.ingestion_service import IngestionApplicationService

    staging_root = staging_root or settings.ingestion_staging_path or None

    canonical = IngestionService(
        knowledge=knowledge,
        vectors=vectors,
        embeddings=embeddings,
        max_jobs=settings.max_pending_ingestion_jobs,
    )

    def refresh() -> None:
        attach = getattr(retrieval, "attach_points", None)
        all_points = getattr(vectors, "all_points", None)
        if callable(attach) and callable(all_points):
            attach(_bounded_point_refresh(all_points))

    return IngestionApplicationService(
        canonical,
        refresh_callback=refresh,
        max_bytes=min(settings.max_upload_bytes, 50 * 1024 * 1024),
        max_jobs=settings.max_pending_ingestion_jobs,
        max_staged_bytes=min(settings.max_upload_bytes, 50 * 1024 * 1024) * 2,
        staging_root=staging_root,
        job_journal=job_journal,
        event_sink=event_sink,
    )


class _TransportObservedFastAPI(FastAPI):
    def build_middleware_stack(self):
        return MetricsMiddleware(super().build_middleware_stack(), telemetry=self.state.telemetry)


def _default_owned_resources(providers: Providers) -> tuple[object, ...]:
    """Return only resources constructed by the default application factory.

    Explicit provider injection is an ownership boundary: the caller may be
    sharing those objects with another app or process and remains responsible
    for their lifecycle. The default factory, by contrast, must release its
    local resources when the ASGI application stops.
    """

    resources = (
        providers.ingestion,
        providers.job_journal,
        providers.audit_sink,
        providers.vector_store,
        providers.knowledge,
        providers.chat_history,
        providers.case_store,
        providers.provider,
        providers.lease,
    )
    result: list[object] = []
    seen: set[int] = set()
    for resource in resources:
        if resource is None or id(resource) in seen:
            continue
        seen.add(id(resource))
        result.append(resource)
    return tuple(result)


async def _close_owned_resource(resource: object, *, timeout: float | None = None) -> bool:
    """Close one factory-owned resource with a real wall-clock bound."""

    deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)

    def invoke(callable_object, **kwargs):
        return callable_object(**kwargs)

    async def invoke_bounded(callable_object, **kwargs):
        if timeout is None:
            return invoke(callable_object, **kwargs)
        finished = Event()
        result_box: dict[str, object] = {}

        def run() -> None:
            try:
                result_box["result"] = invoke(callable_object, **kwargs)
            except BaseException as exc:  # pragma: no cover - adapter boundary
                result_box["error"] = exc
            finally:
                finished.set()

        try:
            Thread(
                target=run,
                name="rick-lifecycle-close",
                daemon=True,
            ).start()
        except RuntimeError:  # pragma: no cover - interpreter boundary
            return False
        remaining = max(0.0, deadline - time.monotonic()) if deadline is not None else None
        await asyncio.to_thread(finished.wait, remaining)
        if not finished.is_set():
            return False
        error = result_box.get("error")
        if isinstance(error, BaseException):
            raise error
        return result_box.get("result")

    async def await_bounded(result: object) -> object:
        if not inspect.isawaitable(result):
            return result
        if deadline is None:
            return await result
        remaining = max(0.0, deadline - time.monotonic())
        if remaining <= 0:
            return False
        try:
            return await asyncio.wait_for(result, timeout=remaining)
        except asyncio.TimeoutError:
            return False

    async_closer = getattr(resource, "aclose", None)
    if callable(async_closer):
        result = await invoke_bounded(async_closer)
        result = await await_bounded(result)
        return result is not False
    closer = getattr(resource, "close", None)
    if callable(closer):
        if timeout is not None:
            try:
                parameters = inspect.signature(closer).parameters.values()
                accepts_timeout = any(
                    parameter.name == "timeout"
                    or parameter.kind is inspect.Parameter.VAR_KEYWORD
                    for parameter in parameters
                )
            except (TypeError, ValueError):
                accepts_timeout = False
        else:
            accepts_timeout = False
        result = await invoke_bounded(
            closer,
            **({"timeout": timeout} if accepts_timeout else {}),
        )
        result = await await_bounded(result)
        return result is not False
    return True


async def _shutdown_owned_resources(app: FastAPI) -> None:
    """Stop the app-owned worker before releasing the stores it can touch."""

    lifecycle_lock = getattr(app.state, "lifecycle_shutdown_lock", None)
    if lifecycle_lock is None:
        lifecycle_lock = RLock()
        app.state.lifecycle_shutdown_lock = lifecycle_lock
    with lifecycle_lock:
        if getattr(app.state, "lifecycle_shutdown_complete", False):
            return
        if getattr(app.state, "lifecycle_shutdown_in_progress", False):
            return
        app.state.lifecycle_shutdown_started = True
        app.state.lifecycle_shutdown_in_progress = True
    deadline = time.monotonic() + APP_LIFESPAN_SHUTDOWN_TIMEOUT_SECONDS
    errors: list[str] = []

    shutdown_resources: list[object] = []
    seen_shutdown: set[int] = set()
    for resource in (
        *getattr(app.state, "owned_shutdown_resources", ()),
        getattr(app.state, "owned_ingestion", None),
        *getattr(app.state, "owned_runtime_resources", ()),
    ):
        if resource is None or id(resource) in seen_shutdown:
            continue
        seen_shutdown.add(id(resource))
        shutdown_resources.append(resource)

    for resource in shutdown_resources:
        shutdown = getattr(resource, "shutdown", None)
        if not callable(shutdown):
            continue
        try:
            # A clean app stop must join the local worker before SQLite or
            # other local stores are closed. The service cancels queued
            # futures and running work remains cooperatively cancellable. A
            # resistant worker is bounded and leaves dependent resources open
            # rather than creating a use-after-close race.
            remaining = max(0.0, deadline - time.monotonic())
            completed = shutdown(
                wait=True,
                timeout=remaining,
            )
            if completed is False:
                errors.append("ingestion_shutdown_timeout")
        except Exception as exc:  # pragma: no cover - defensive boundary
            errors.append(type(exc).__name__)

    # Never close a store if an owned worker failed to stop. The worker may
    # still hold references to it; the lifecycle result remains explicitly
    # incomplete for the host/supervisor to observe.
    if errors:
        app.state.lifecycle_shutdown_errors = tuple(errors)
        app.state.lifecycle_shutdown_complete = False
        app.state.lifecycle_shutdown_in_progress = False
        return

    close_resources: list[object] = []
    seen_close: set[int] = set()
    for resource in (
        *shutdown_resources,
        *getattr(app.state, "owned_resources", ()),
    ):
        if resource is None or id(resource) in seen_close:
            continue
        seen_close.add(id(resource))
        close_resources.append(resource)

    for resource in close_resources:
        try:
            remaining = max(0.0, deadline - time.monotonic())
            if remaining <= 0:
                errors.append("lifecycle_shutdown_timeout")
                continue
            if not await _close_owned_resource(resource, timeout=remaining):
                errors.append("resource_close_incomplete")
                # A bounded close may still be running in a daemon adapter
                # thread. Do not close later resources behind an incomplete
                # dependency, and leave the lifecycle explicitly retryable.
                break
            if time.monotonic() > deadline:
                errors.append("lifecycle_shutdown_timeout")
                break
        except Exception as exc:  # pragma: no cover - defensive boundary
            errors.append(type(exc).__name__)
            break

    app.state.lifecycle_shutdown_errors = tuple(errors)
    app.state.lifecycle_shutdown_complete = not errors
    app.state.lifecycle_shutdown_in_progress = False


@asynccontextmanager
async def _application_lifespan(app: FastAPI):
    try:
        yield
    finally:
        await _shutdown_owned_resources(app)


def create_app(settings: ApiSettings | None = None, providers: Providers | None = None) -> FastAPI:
    """Create the canonical API app. No Qdrant/OpenAI/Redis init at import time."""
    settings = settings or ApiSettings.from_env()
    settings.validate()
    factory_owns_resources = providers is None
    # Construct the application-owned sink before default providers so the
    # real root ingestion executor can publish local lifecycle events without
    # introducing a process-global telemetry dependency.
    telemetry = ApiTelemetry()

    if settings.environment == "production":
        if providers is None:
            raise RuntimeError("Production API requires an injected external identity provider.")
        if getattr(getattr(providers, "identity", None), "production_safe", False) is not True:
            raise RuntimeError("Production API requires an external identity provider.")
        required = [
            "identity", "chat_backend", "knowledge", "vector_store", "retrieval",
            "ingestion", "worker", "audit_sink", "chat_history", "job_journal",
            "queue", "object_store",
        ]
        if settings.chat_backend_mode == "professor" or not settings.use_legacy_adapters:
            required.extend(("provider", "lease"))
        if settings.clinical_cases_feature_enabled:
            required.append("case_store")
        missing = [name for name in required if getattr(providers, name, None) is None]
        if missing:
            raise RuntimeError(
                "Production API composition incomplete; required external components missing: "
                + ", ".join(missing)
            )

    if providers is None:
        from services.audit import InMemoryAuditSink
        from services.case_store import InMemoryClinicalCaseStore, SQLiteClinicalCaseStore
        from services.chat_history import InMemoryChatHistoryStore, SQLiteChatHistoryStore
        from services.chat_service import StubChatBackend
        from services.identity_service import InMemoryIdentityProvider
        from services.knowledge_service import seed_demo_corpus, seed_demo_points
        from services.retrieval_service import RetrievalApplicationService
        from rick_retrieval import DeterministicHashEmbedding, InMemoryVectorStore, SQLiteVectorStore

        identity = InMemoryIdentityProvider(mode=settings.identity_mode)
        knowledge = None
        retrieval = None
        vectors = None
        embeddings = None
        try:
            from rick_knowledge import InMemoryKnowledgeStore, SQLiteKnowledgeStore

            if settings.knowledge_sqlite_path:
                knowledge = SQLiteKnowledgeStore(settings.knowledge_sqlite_path)
            else:
                knowledge = InMemoryKnowledgeStore()
            if settings.vector_sqlite_path:
                vectors = SQLiteVectorStore(
                    settings.vector_sqlite_path,
                    mode="test" if settings.environment == "test" else "local",
                )
            else:
                vectors = InMemoryVectorStore()
            embeddings = DeterministicHashEmbedding()
            if settings.environment != "production":
                seed_demo_corpus(knowledge)
            retrieval = RetrievalApplicationService(knowledge=knowledge, vectors=vectors, embeddings=embeddings)
            if settings.environment != "production":
                demo_points = seed_demo_points(knowledge, embeddings)
                vectors.upsert_points(demo_points)
                retrieval.attach_points(demo_points)
        except ImportError:
            knowledge, retrieval = None, None
            vectors, embeddings = None, None
        audit_sink = InMemoryAuditSink()
        chat_history = (
            SQLiteChatHistoryStore(settings.chat_history_sqlite_path)
            if settings.chat_history_sqlite_path
            else InMemoryChatHistoryStore()
        )
        case_store = None
        if settings.clinical_cases_feature_enabled:
            case_store = (
                SQLiteClinicalCaseStore(settings.clinical_case_sqlite_path)
                if settings.clinical_case_sqlite_path
                else InMemoryClinicalCaseStore()
            )
        job_journal = None
        ingestion_staging_path = settings.ingestion_staging_path or None
        if settings.ingestion_journal_path:
            from services.job_journal import JobJournal

            journal_path = settings.ingestion_journal_path
            staging_path = settings.ingestion_staging_path
            if not staging_path:
                from pathlib import Path

                journal = Path(journal_path)
                staging_path = str(journal.with_name(f"{journal.stem}-staging"))
            # Keep the derived path within the same private runtime parent;
            # JobJournal and IngestionApplicationService harden both sides.
            job_journal = JobJournal(journal_path, max_rows=settings.ingestion_journal_max_rows)
            ingestion_staging_path = staging_path
        if settings.audit_sqlite_path:
            from services.sqlite_audit import SQLiteAuditSink

            audit_sink = SQLiteAuditSink(
                settings.audit_sqlite_path,
                max_events=settings.audit_retention,
            )

        provider = None
        lease = None
        professor = None
        ingestion = None
        worker = None
        selected_mode = settings.selected_chat_backend
        if selected_mode == "professor":
            if retrieval is None:
                raise RuntimeError("Professor backend requires root retrieval dependencies")
            from rick_locking import InMemoryLeaseClient, LockerClient
            from rick_providers import ProviderConfig, ResilientProvider, create_provider
            from services.professor_backend import ProfessorChatBackend

            local_provider = settings.environment in {"test", "dev", "local"}
            provider_kind = settings.selected_provider_kind
            provider_config = ProviderConfig(
                base_url=settings.provider_base_url,
                api_key=settings.external_chat_api_key or None,
                chat_model=settings.provider_chat_model,
                embedding_model=settings.provider_embedding_model,
                embedding_dimensions=settings.provider_embedding_dimensions,
                timeout_ms=settings.provider_timeout_ms,
                environment=settings.environment,
                provider_kind=provider_kind,
            )
            provider = ResilientProvider(
                create_provider(provider_config),
                max_prompt_chars=max(1_000, settings.max_chat_message_chars * 8),
            )
            if settings.locker_base_url.strip():
                lease = LockerClient(settings.locker_base_url)
            elif local_provider:
                lease = InMemoryLeaseClient()
            else:
                raise RuntimeError("Professor backend requires a configured lease service")
            professor = ProfessorChatBackend(retrieval=retrieval, provider=provider, lease=lease)
            backend = professor
        elif selected_mode == "legacy":
            # Legacy is an explicit rollback mode. A configured adapter that
            # cannot start must fail startup visibly; silently serving the
            # ungrounded stub would turn a configuration failure into an
            # integrity failure.
            from adapters.legacy.cvg import LegacyProfessorAdapter  # noqa (adapter boundary)

            backend = LegacyProfessorAdapter()  # type: ignore[assignment]
        else:
            from services.retrieval_service import root_retrieval_enabled

            backend = StubChatBackend(
                retrieval=retrieval if root_retrieval_enabled() else None
            )

        if knowledge is not None and retrieval is not None and vectors is not None and embeddings is not None:
            ingestion = _build_root_ingestion(
                settings=settings, knowledge=knowledge, retrieval=retrieval,
                vectors=vectors, embeddings=embeddings, job_journal=job_journal,
                staging_root=ingestion_staging_path,
                event_sink=telemetry,
            )
        providers = Providers(
            settings=settings, identity=identity, chat_backend=backend,
            health_checks=_default_health_checks(settings), audit_sink=audit_sink, chat_history=chat_history,
            case_store=case_store,
            knowledge=knowledge, vector_store=vectors, retrieval=retrieval, provider=provider, lease=lease, professor=professor,
            ingestion=ingestion, worker=worker, job_journal=job_journal,
        )
    else:
        # The container and registration maps belong to this app, while explicit
        # injected service/client objects retain their caller-owned identities.
        providers = copy(providers)
        providers.settings = settings
        for attribute in ("health_checks", "runtime_checks", "readiness_checks"):
            checks = getattr(providers, attribute, None)
            if isinstance(checks, Mapping):
                setattr(providers, attribute, dict(checks))
        if not providers.health_checks:
            providers.health_checks = _default_health_checks(settings)

    app = _TransportObservedFastAPI(
        title="RICK Intelligence API",
        description="Canonical platform HTTP boundary with an evidence-gated Professor slice.",
        version="1.6.0",
        lifespan=_application_lifespan,
        openapi_tags=[
            {"name": "Auth"}, {"name": "Clinical"}, {"name": "Knowledge"},
            {"name": "Admin"}, {"name": "Compatibility"}, {"name": "System"},
        ],
    )
    app.router.route_class = ClosingStreamingRoute
    app.state.providers = providers
    app.state.settings = settings
    # A composition fact, not a health claim. Injected implementations cannot
    # be inferred from configured names, class reprs or secret-bearing URLs.
    app.state.runtime_diagnostics = {
        "composition": "factory" if factory_owns_resources else "injected",
        "environment": settings.environment,
        "configured_chat_backend": settings.selected_chat_backend,
        "active_chat_backend": settings.selected_chat_backend if factory_owns_resources else "externally_managed",
        "active_chat_provider": (
            settings.selected_provider_kind if factory_owns_resources and settings.selected_chat_backend == "professor"
            else "not_used" if factory_owns_resources else "externally_managed"
        ),
        "embedding": ("deterministic_local" if embeddings is not None else "not_configured") if factory_owns_resources else "externally_managed",
        "active_chat_model": settings.provider_chat_model if factory_owns_resources and settings.selected_chat_backend == "professor" else None,
        "provider_credentials_configured": bool(settings.external_chat_api_key.strip()),
        "production_verified": False,
    }
    app.state.telemetry = telemetry
    app.state.owned_ingestion = providers.ingestion if factory_owns_resources else None
    app.state.owned_resources = list(_default_owned_resources(providers)) if factory_owns_resources else []
    app.state.owned_runtime_resources = []
    app.state.owned_shutdown_resources = (
        [providers.ingestion] if factory_owns_resources and providers.ingestion is not None else []
    )
    app.state.lifecycle_shutdown_started = False
    app.state.lifecycle_shutdown_in_progress = False
    app.state.lifecycle_shutdown_lock = RLock()
    app.state.lifecycle_shutdown_complete = False
    app.state.lifecycle_shutdown_errors = ()

    # Register inner policies first; the last wrapper runs outermost.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_allowed_origins),
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization", "Content-Type", "X-Request-ID", "X-Correlation-ID", "X-API-Key", "Idempotency-Key",
            settings.csrf_header_name,
        ],
    )
    app.add_middleware(
        RequestContextMiddleware,
        trust_forwarded=settings.trust_forwarded_headers,
        trusted_proxies=settings.trusted_proxies,
        api_version=settings.api_version,
    )
    app.add_middleware(RequestSizeLimitMiddleware, max_bytes=settings.max_json_bytes,
                       upload_max_bytes=settings.max_upload_bytes)
    app.add_middleware(
        CSRFProtectionMiddleware,
        environment=settings.environment,
        allowed_origins=settings.cors_allowed_origins,
        session_cookie_name=settings.session_cookie_name,
        csrf_token=settings.csrf_token,
        csrf_header_name=settings.csrf_header_name,
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIdMiddleware)
    # The app's stack builder observes all policies and native outer500 sends.

    register_error_handlers(app)
    for router in ROUTERS:
        app.include_router(router)
    return app
