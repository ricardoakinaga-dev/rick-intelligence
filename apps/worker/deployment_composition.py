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
from threading import Event, Thread
from time import monotonic
from typing import Any

from core.config import ApiSettings
from services.external_composition import (
    ExternalCompositionError,
    ExternalCompositionInputs,
    _AsyncLoopBridge,
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


def _validate_identity_policy(settings: ApiSettings) -> None:
    """The built-in factory implements local PostgreSQL credentials only.

    An OIDC deployment must supply its reviewed identity composition. Merely
    configuring issuer/JWKS URLs must not approve the local-password facade.
    """
    if settings.environment != "production":
        return
    if settings.oidc_issuer or settings.oidc_audience or settings.oidc_jwks_url:
        raise ExternalCompositionError("reviewed OIDC identity composition required")
    if os.environ.get("RICK_IDENTITY_POLICY", "").strip() != "postgres-local-v1":
        raise ExternalCompositionError("explicit RICK_IDENTITY_POLICY=postgres-local-v1 required")


def _build_inputs(settings: ApiSettings) -> ExternalCompositionInputs:
    _validate_identity_policy(settings)
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
        production_safe=settings.environment == "production",
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

    def __init__(
        self,
        providers: object,
        *,
        otel_runtime: OpenTelemetryRuntime | None = None,
        admin_audit_reconciler: object | None = None,
        admin_audit_poll_interval: float = 1.0,
    ) -> None:
        self.providers = providers
        self.worker = getattr(providers, "worker", None)
        if self.worker is None:
            raise ExternalCompositionError("worker runtime")
        if not 0.05 <= admin_audit_poll_interval <= 60.0:
            raise ExternalCompositionError("admin audit poll interval")
        self.otel_runtime = otel_runtime
        self.admin_audit_reconciler = admin_audit_reconciler
        self.admin_audit_poll_interval = float(admin_audit_poll_interval)
        self._admin_audit_stop = Event()
        self._admin_audit_thread: Thread | None = None
        self._started = False
        self._closed = False
        self._async_bridge: _AsyncLoopBridge | None = None
        self._shutdown_complete = False
        self._worker_stopped = False
        self._closed_resources: set[int] = set()
        self._shutdown_errors: tuple[str, ...] = ()
        self._disposed = False
        self._client_close_obligations = {}

    def _run_async(self, awaitable: object, *, timeout: float = 120.0) -> object:
        if self._async_bridge is None:
            self._async_bridge = _AsyncLoopBridge()
        return self._async_bridge.run(awaitable, timeout=timeout)

    def start(self) -> object:
        if self._closed:
            return False
        if self._started:
            return True
        if self.admin_audit_reconciler is not None:
            health_check = getattr(self.admin_audit_reconciler, "health_check", None)
            if not callable(health_check) or health_check() is not True:
                return False
        starter = getattr(self.worker, "start", None)
        started = starter() if callable(starter) else True
        if started is False:
            return False
        if self.admin_audit_reconciler is not None:
            self._admin_audit_stop.clear()
            self._admin_audit_thread = Thread(
                target=self._run_admin_audit_reconciler,
                name="rick-admin-audit-reconciler",
                daemon=True,
            )
            self._admin_audit_thread.start()
        self._started = True
        return True

    def _run_admin_audit_reconciler(self) -> None:
        reconciler = self.admin_audit_reconciler
        process_once = getattr(reconciler, "process_once", None)
        if not callable(process_once):
            return
        while not self._admin_audit_stop.is_set():
            try:
                processed = process_once()
            except Exception:
                # The reconciler owns safe retry state and hides driver errors.
                # An unexpected programming failure stops the sidecar and makes
                # the lifecycle readiness check fail closed.
                return
            if processed == 0:
                self._admin_audit_stop.wait(self.admin_audit_poll_interval)

    def request_stop(self) -> None:
        self._admin_audit_stop.set()
        stopper = getattr(self.worker, "request_stop", None)
        if not callable(stopper):
            stopper = getattr(self.worker, "stop", None)
        if callable(stopper):
            try:
                stopper()
            except Exception:
                return None

    def run_forever(self) -> object:
        try:
            return self.worker.run_forever()
        finally:
            self._admin_audit_stop.set()

    def health_check(self) -> bool:
        if self._closed:
            return False
        checks = getattr(self.providers, "health_checks", {})
        for check in checks.values():
            try:
                result = self._run_async(_await(check()))
            except Exception:
                return False
            if result is not True and getattr(result, "ok", result) is not True:
                return False
        if self.admin_audit_reconciler is not None:
            check = getattr(self.admin_audit_reconciler, "health_check", None)
            if not callable(check):
                return False
            try:
                if check() is not True:
                    return False
            except Exception:
                return False
            thread = self._admin_audit_thread
            if self._started and (thread is None or not thread.is_alive()):
                return False
        return bool(getattr(self.worker, "health_check", lambda: False)())

    readiness_check = health_check

    def shutdown(self, *, timeout: float | None = None, wait: bool = True) -> object:
        if self._shutdown_complete:
            return True
        if self._disposed:
            return False
        self._closed = True
        deadline = monotonic() + (timeout if timeout is not None else 30.0)
        self._admin_audit_stop.set()
        thread = self._admin_audit_thread
        if thread is not None:
            thread.join(max(0.0, deadline - monotonic()))
            if thread.is_alive():
                self._shutdown_errors = ("admin_audit_shutdown_timeout",)
                return False
            self._admin_audit_thread = None
        worker_shutdown = getattr(self.worker, "shutdown", None)
        if not self._worker_stopped and callable(worker_shutdown):
            try:
                worker_report = worker_shutdown(timeout=max(0.001, deadline - monotonic()))
            except Exception:
                self._shutdown_errors = ("worker_shutdown_failed",)
                return False
            if worker_report is False or getattr(worker_report, "timed_out", False) is True:
                self._shutdown_errors = ("worker_shutdown_timeout",)
                return False
        self._worker_stopped = True
        # Successfully closed resources are never closed twice. Failed closers
        # remain eligible on a later call; closing admission is not completion.
        resources = (
            getattr(self.providers, "ingestion", None),
            getattr(self.providers, "object_store", None),
            getattr(self.providers, "vector_store", None),
            getattr(self.providers, "knowledge", None),
            getattr(self.providers, "audit_sink", None),
            getattr(self.providers, "_embedding_adapter", None),
            getattr(self.providers, "chat_history", None),
            getattr(self.providers, "provider", None),
            getattr(getattr(self.providers, "_composition_inputs", None), "provider_client", None),
            getattr(getattr(self.providers, "rate_limiter", None), "redis_client", None),
            self.otel_runtime,
        )
        errors: list[str] = []
        seen: set[int] = set()
        for resource in resources:
            if resource is None or id(resource) in seen or id(resource) in self._closed_resources:
                continue
            seen.add(id(resource))
            import httpx
            from rick_providers.cleanup import ClientCloseObligation

            closer = getattr(resource, "aclose", None) or getattr(resource, "close", None)
            if isinstance(resource, httpx.AsyncClient):
                if id(resource) not in self._client_close_obligations:
                    self._client_close_obligations[id(resource)] = ClientCloseObligation(resource)
                closer = self._client_close_obligations[id(resource)].aclose
            if not callable(closer):
                self._closed_resources.add(id(resource))
                continue
            remaining = deadline - monotonic()
            if remaining <= 0:
                errors.append("resource_shutdown_timeout")
                continue
            try:
                try:
                    accepts_timeout = "timeout" in inspect.signature(closer).parameters
                except (TypeError, ValueError):
                    accepts_timeout = False
                result = closer(**({"timeout": remaining} if accepts_timeout else {}))
                if inspect.isawaitable(result):
                    result = self._run_async(result, timeout=remaining)
                if result is False:
                    errors.append("resource_shutdown_incomplete")
                else:
                    self._closed_resources.add(id(resource))
            except Exception:
                errors.append("resource_shutdown_failed")
        # Keep the original owning loop alive when any close is incomplete.
        if not errors and self._async_bridge is not None:
            try:
                self._async_bridge.close()
                self._async_bridge = None
            except Exception:
                errors.append("provider_loop_disposal_incomplete")
        self._shutdown_errors = tuple(errors)
        self._shutdown_complete = not errors
        return self._shutdown_complete

    def dispose(self, *, timeout: float = 30.0) -> bool:
        """Final bounded attempt, then dispose loops with an honest result.

        The host supplies a finite retry budget before this explicit terminal
        action. A failed disposal never makes future shutdown return success.
        """
        complete = self.shutdown(timeout=timeout)
        if not self._worker_stopped:
            # An active worker may still hold provider references.
            return False
        errors = list(self._shutdown_errors)
        adapter = getattr(self.providers, "_embedding_adapter", None)
        if not complete and callable(getattr(adapter, "dispose", None)):
            try:
                adapter.dispose(timeout=0)
            except Exception:
                errors.append("embedding_disposal_incomplete")
        self._disposed = True
        if self._async_bridge is not None:
            try:
                self._async_bridge.close()
                self._async_bridge = None
            except Exception:
                errors.append("provider_loop_disposal_incomplete")
        self._shutdown_errors = tuple(errors)
        self._shutdown_complete = complete and not errors
        return self._shutdown_complete


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
    inputs = _build_inputs(settings)
    providers = build_external_providers(settings, inputs)
    providers._composition_inputs = inputs
    embedding_adapter = getattr(providers, "_embedding_adapter", None)
    if embedding_adapter is not None:
        embedding_adapter.transferred_client = getattr(inputs, "embedding_provider_client", None)
    from admin_audit_outbox import PostgresAdminAuditReconciler

    admin_audit_reconciler = PostgresAdminAuditReconciler(inputs.connection_factory)
    otel_runtime = configure_process_otel(service_name="rick-worker")
    return DeploymentRuntime(
        providers,
        otel_runtime=otel_runtime,
        admin_audit_reconciler=admin_audit_reconciler,
    )


__all__ = ["DeploymentRuntime", "build_api_inputs", "build_worker"]
