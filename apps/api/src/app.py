"""Deterministic application factory: production, unit, and integration runtimes via DI."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import ApiSettings
from core.errors import register_error_handlers
from core.lifecycle import DependencyState
from core.middleware import (
    MetricsMiddleware,
    RequestContextMiddleware,
    RequestIdMiddleware,
    RequestSizeLimitMiddleware,
    SecurityHeadersMiddleware,
)
from dependencies.services import Providers, set_providers
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


def create_app(settings: ApiSettings | None = None, providers: Providers | None = None) -> FastAPI:
    """Create the canonical API app. No Qdrant/OpenAI/Redis init at import time."""
    settings = settings or ApiSettings.from_env()

    if providers is None:
        from services.audit import InMemoryAuditSink
        from services.chat_service import StubChatBackend
        from services.identity_service import InMemoryIdentityProvider

        identity = InMemoryIdentityProvider()
        if settings.use_legacy_adapters:
            try:
                from adapters.legacy.cvg import LegacyProfessorAdapter  # noqa (adapter boundary)

                backend = LegacyProfessorAdapter()  # type: ignore[assignment]
            except Exception:
                from services.chat_service import StubChatBackend as _Stub

                backend = _Stub()  # type: ignore[assignment]
        else:
            backend = StubChatBackend()
        providers = Providers(
            settings=settings, identity=identity, chat_backend=backend,
            health_checks=_default_health_checks(settings), audit_sink=InMemoryAuditSink(),
        )
    else:
        providers.settings = settings
        if not providers.health_checks:
            providers.health_checks = _default_health_checks(settings)

    set_providers(providers)

    app = FastAPI(
        title="RICK Intelligence API",
        description="Canonical platform HTTP boundary (Phase 1.3). Permissions documented per endpoint.",
        version="1.3.0",
        openapi_tags=[
            {"name": "Auth"}, {"name": "Clinical"}, {"name": "Knowledge"},
            {"name": "Admin"}, {"name": "Compatibility"}, {"name": "System"},
        ],
    )
    app.state.providers = providers
    app.state.settings = settings

    # CORS first (outermost), then explicit stack per middleware docstring.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_allowed_origins),
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-Correlation-ID", "X-API-Key"],
    )
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(RequestContextMiddleware, trust_forwarded=settings.trust_forwarded_headers,
                       api_version=settings.api_version)
    app.add_middleware(RequestSizeLimitMiddleware, max_bytes=settings.max_json_bytes)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIdMiddleware)

    register_error_handlers(app)
    for router in ROUTERS:
        app.include_router(router)
    return app
