"""Disposable production-shaped composition for the canonical API and worker.

This module is intentionally a composition root.  It reads only the explicit
environment contract, constructs no clients on import, and fails closed when a
required endpoint, credential or worker scope is absent.  The same factory is
copied into both application images so the API and Worker A/B processes use
the same adapters and ownership rules.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
import inspect
import os
from pathlib import Path
from typing import Any

from core.config import ApiSettings
from services.external_composition import (
    ExternalCompositionError,
    ExternalCompositionInputs,
    build_external_providers,
)
from services.object_store_transport import StdlibS3HttpTransport
from core.otel import OpenTelemetryRuntime, configure_process_otel


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value or len(value) > 512 or "\x00" in value:
        raise ExternalCompositionError(name)
    return value


def _connection_factory(dsn: str):
    def connect() -> object:
        try:
            import psycopg

            return psycopg.connect(dsn, connect_timeout=10)
        except Exception:
            # Store boundaries translate the failure into their typed
            # unavailable result.  Do not retain DSNs in a composition error.
            raise

    return connect


def _settings() -> ApiSettings:
    configured = ApiSettings.from_env()
    # The deployment module is for an explicitly selected external graph.  A
    # local/dev lab may use HTTP-compatible endpoints, while production keeps
    # the API settings' HTTPS and secure-cookie checks unchanged.
    return configured


def _worker_scope() -> tuple[str, str, str]:
    return (
        _required("RICK_WORKER_SCOPE_TENANT"),
        _required("RICK_WORKER_SCOPE_WORKSPACE"),
        _required("RICK_WORKER_SCOPE_COLLECTION"),
    )


def _build_inputs(settings: ApiSettings) -> ExternalCompositionInputs:
    from rick_locking import (
        RedisNamespace,
        RedisSettings,
        create_redis_client,
        create_redis_lease_client,
        create_redis_rate_limiter,
    )
    from services.postgres_identity import PostgresIdentityProvider

    if not settings.external_database_dsn:
        raise ExternalCompositionError("RICK_EXTERNAL_DATABASE_DSN")
    if not settings.object_store_endpoint:
        raise ExternalCompositionError("RICK_OBJECT_STORE_ENDPOINT")
    if not settings.object_store_access_key or not settings.object_store_secret_key:
        raise ExternalCompositionError("object store credentials")
    if not settings.redis_url:
        raise ExternalCompositionError("RICK_REDIS_URL")
    if not settings.qdrant_url:
        raise ExternalCompositionError("RICK_QDRANT_URL")

    redis_settings = RedisSettings.from_env()
    redis_client = create_redis_client(redis_settings)
    namespace = RedisNamespace.global_scope(
        prefix=redis_settings.namespace_prefix,
        environment=redis_settings.environment,
    )
    lease = create_redis_lease_client(redis_settings, namespace, client=redis_client)
    rate_limiter = create_redis_rate_limiter(redis_settings, namespace, client=redis_client)

    identity = PostgresIdentityProvider(
        _connection_factory(settings.external_database_dsn),
        production_safe=True,
    )
    object_transport = StdlibS3HttpTransport(
        settings.object_store_endpoint,
        timeout_seconds=max(1.0, settings.provider_timeout_ms / 1000),
        require_https=settings.environment == "production",
    )
    parser_root = os.environ.get("RICK_WORKER_TEMP_ROOT", "/tmp/rick-ingestion").strip()
    if not parser_root or len(parser_root) > 512 or "\x00" in parser_root:
        raise ExternalCompositionError("RICK_WORKER_TEMP_ROOT")
    Path(parser_root).mkdir(parents=True, exist_ok=True)

    return ExternalCompositionInputs(
        connection_factory=_connection_factory(settings.external_database_dsn),
        object_store_transport=object_transport,
        identity=identity,
        created_by=_required("RICK_COMPOSITION_CREATED_BY"),
        redis_client=redis_client,
        rate_limiter=rate_limiter,
        rate_limit_namespace=namespace,
        lease=lease,
        worker_temp_root=parser_root,
        worker_id=_required("RICK_WORKER_ID"),
        worker_scope=_worker_scope(),
    )


async def _await(value: object) -> object:
    if inspect.isawaitable(value):
        return await value
    return value


class DeploymentRuntime:
    """Lifecycle owner returned by the worker composition factory."""

    def __init__(self, providers: object, *, otel_runtime: OpenTelemetryRuntime | None = None) -> None:
        self.providers = providers
        self.worker = getattr(providers, "worker", None)
        if self.worker is None:
            raise ExternalCompositionError("worker runtime")
        self.otel_runtime = otel_runtime
        self._closed = False

    def start(self) -> object:
        starter = getattr(self.worker, "start", None)
        return starter() if callable(starter) else True

    def run_forever(self) -> object:
        return self.worker.run_forever()

    def health_check(self) -> bool:
        checks = getattr(self.providers, "health_checks", {})
        for check in checks.values():
            try:
                result = asyncio.run(_await(check()))
            except Exception:
                return False
            if result is not True and getattr(result, "ok", result) is not True:
                return False
        return bool(getattr(self.worker, "health_check", lambda: False)())

    readiness_check = health_check

    def shutdown(self, *, timeout: float | None = None, wait: bool = True) -> object:
        if self._closed:
            return True
        worker_shutdown = getattr(self.worker, "shutdown", None)
        worker_report = True
        if callable(worker_shutdown):
            worker_report = worker_shutdown(timeout=timeout if timeout is not None else 30.0)
            if worker_report is False or getattr(worker_report, "timed_out", False) is True:
                # A timed-out cooperative worker can still touch its queue,
                # object store or vector client.  Keep every dependent
                # resource open and make the incomplete shutdown observable
                # to the launcher/supervisor.
                self._closed = True
                return False
        self._closed = True

        resources = (
            getattr(self.providers, "ingestion", None),
            getattr(self.providers, "object_store", None),
            getattr(self.providers, "vector_store", None),
            getattr(self.providers, "knowledge", None),
            getattr(self.providers, "audit_sink", None),
            getattr(self.providers, "_embedding_adapter", None),
            getattr(self.providers, "chat_history", None),
        )
        seen: set[int] = set()
        for resource in resources:
            if resource is None or id(resource) in seen:
                continue
            seen.add(id(resource))
            close = getattr(resource, "close", None)
            if callable(close):
                close()

        provider = getattr(self.providers, "provider", None)
        if provider is not None and callable(getattr(provider, "aclose", None)):
            asyncio.run(provider.aclose())
        redis_client = getattr(getattr(self.providers, "rate_limiter", None), "redis_client", None)
        if redis_client is not None:
            close = getattr(redis_client, "aclose", None) or getattr(redis_client, "close", None)
            if callable(close):
                asyncio.run(_await(close()))
        if self.otel_runtime is not None:
            self.otel_runtime.close()
        return True


def build_api_inputs(settings: ApiSettings | None = None) -> ExternalCompositionInputs:
    """Return caller-owned inputs for ``load_external_providers``."""

    inputs = _build_inputs(settings or _settings())
    # The API process does not run the worker polling loop.  Its Providers
    # graph remains complete, while the separate worker process owns the
    # worker readiness signal.
    return replace(inputs, worker_health_check_required=False)


def build_worker() -> DeploymentRuntime:
    """Build the worker plus its explicit dependency ownership graph."""

    settings = _settings()
    providers = build_external_providers(settings, _build_inputs(settings))
    otel_runtime = configure_process_otel(service_name="rick-worker")
    return DeploymentRuntime(providers, otel_runtime=otel_runtime)


__all__ = ["DeploymentRuntime", "build_api_inputs", "build_worker"]
