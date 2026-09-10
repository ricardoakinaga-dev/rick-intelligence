"""ASGI ownership and shutdown checks for the canonical root application."""

from __future__ import annotations

import asyncio
import io
import sqlite3
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import _shutdown_owned_resources, create_app
from conftest import make_settings
from dependencies.services import Providers
from services.audit import InMemoryAuditSink
from services.chat_service import StubChatBackend
from services.identity_service import InMemoryIdentityProvider
from services.ingestion_service import IngestionApplicationError, IngestionApplicationService


class _HealthyProductionComponent:
    production_safe = True
    backend_kind = "redis"

    def __init__(self, ready: bool = True) -> None:
        self.ready = ready

    def health_check(self):
        return self.ready

    def readiness_check(self):
        return self.ready

    async def allow(self, *_args, **_kwargs):
        return self.ready


def _production_admission_app(*, redis_ready: bool):
    settings = make_settings(
        environment="production",
        identity_mode="production",
        chat_backend_mode="legacy",
        use_legacy_adapters=True,
        session_cookie_secure=True,
    )
    component = _HealthyProductionComponent()
    identity = SimpleNamespace(production_safe=True, health_check=lambda: True)
    providers = Providers(
        settings=settings,
        identity=identity,
        chat_backend=component,
        provider=component,
        health_checks={"kernel": lambda: True, "identity": lambda: True},
        audit_sink=component,
        chat_history=component,
        knowledge=component,
        vector_store=component,
        retrieval=component,
        ingestion=component,
        worker=component,
        job_journal=component,
        queue=component,
        object_store=component,
        rate_limiter=_HealthyProductionComponent(redis_ready),
        lease=component,
    )
    return create_app(settings, providers)


def test_production_admission_refuses_to_start_when_redis_is_not_ready():
    app = _production_admission_app(redis_ready=False)

    with pytest.raises(RuntimeError, match="readiness gate failed"):
        with TestClient(app):
            pass


def test_production_admission_starts_only_after_required_checks_are_ready():
    app = _production_admission_app(redis_ready=True)

    with TestClient(app) as client:
        assert client.get("/health/live").json() == {"status": "live"}
    assert app.state.admission_status == "ready"


def test_default_factory_closes_worker_and_local_sqlite_resources(tmp_path: Path) -> None:
    settings = make_settings(
        knowledge_sqlite_path=str(tmp_path / "knowledge.sqlite"),
        vector_sqlite_path=str(tmp_path / "vectors.sqlite"),
        audit_sqlite_path=str(tmp_path / "audit.sqlite"),
        ingestion_journal_path=str(tmp_path / "jobs.sqlite"),
        ingestion_staging_path=str(tmp_path / "staging"),
    )
    app = create_app(settings)
    providers = app.state.providers
    ingestion = providers.ingestion
    executor = ingestion._executor

    with TestClient(app) as client:
        assert client.get("/health/live").json() == {"status": "live"}
        assert executor._shutdown is False

    assert executor._shutdown is True
    assert all(not thread.is_alive() for thread in executor._threads)
    assert app.state.lifecycle_shutdown_complete is True
    assert app.state.lifecycle_shutdown_errors == ()
    assert providers.vector_store._closed is True
    assert providers.audit_sink._closed is True
    with pytest.raises(sqlite3.ProgrammingError):
        providers.knowledge._connection.execute("SELECT 1")
    with pytest.raises(sqlite3.ProgrammingError):
        providers.job_journal._connection.execute("SELECT 1")


def test_injected_provider_resources_remain_caller_owned() -> None:
    class Probe:
        def __init__(self) -> None:
            self.close_calls = 0
            self.shutdown_calls = 0

        def close(self) -> None:
            self.close_calls += 1

        def shutdown(self, **_kwargs) -> None:
            self.shutdown_calls += 1

    probe = Probe()
    settings = make_settings()
    providers = Providers(
        settings=settings,
        identity=InMemoryIdentityProvider(),
        chat_backend=StubChatBackend(),
        health_checks={},
        audit_sink=probe,
        chat_history=probe,
        job_journal=probe,
        knowledge=probe,
        vector_store=probe,
        ingestion=probe,
    )
    app = create_app(settings, providers)

    with TestClient(app) as client:
        assert client.get("/health/live").json() == {"status": "live"}

    assert probe.close_calls == 0
    assert probe.shutdown_calls == 0
    assert app.state.owned_resources == []
    assert app.state.owned_ingestion is None


def test_concurrent_app_shutdown_is_single_owner_and_idempotent() -> None:
    app = create_app(make_settings())
    failures: list[BaseException] = []

    def shutdown() -> None:
        try:
            asyncio.run(_shutdown_owned_resources(app))
        except BaseException as exc:  # pragma: no cover - assertion below
            failures.append(exc)

    threads = [threading.Thread(target=shutdown) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(2)

    assert failures == []
    assert all(not thread.is_alive() for thread in threads)
    assert app.state.lifecycle_shutdown_complete is True
    assert app.state.lifecycle_shutdown_errors == ()


def test_failed_app_shutdown_can_be_retried_after_worker_timeout() -> None:
    class EventuallyStops:
        def __init__(self) -> None:
            self.shutdown_calls = 0
            self.close_calls = 0

        def shutdown(self, **_kwargs) -> bool:
            self.shutdown_calls += 1
            return self.shutdown_calls > 1

        def close(self) -> None:
            self.close_calls += 1

    resource = EventuallyStops()
    app = SimpleNamespace(
        state=SimpleNamespace(
            lifecycle_shutdown_lock=threading.RLock(),
            lifecycle_shutdown_complete=False,
            lifecycle_shutdown_in_progress=False,
            lifecycle_shutdown_started=False,
            owned_shutdown_resources=[resource],
            owned_ingestion=None,
            owned_runtime_resources=[],
            owned_resources=[resource],
        )
    )

    asyncio.run(_shutdown_owned_resources(app))

    assert app.state.lifecycle_shutdown_complete is False
    assert app.state.lifecycle_shutdown_errors == ("ingestion_shutdown_timeout",)
    assert resource.close_calls == 0

    asyncio.run(_shutdown_owned_resources(app))

    assert app.state.lifecycle_shutdown_complete is True
    assert app.state.lifecycle_shutdown_errors == ()
    assert resource.shutdown_calls == 2
    assert resource.close_calls == 1


def test_lazy_wrapper_for_injected_canonical_service_is_app_owned(tmp_path: Path) -> None:
    from starlette.requests import Request

    class CanonicalOnly:
        def ingest(self, _path, **_kwargs):
            raise AssertionError("the ownership probe must not execute ingestion")

    canonical = CanonicalOnly()
    settings = make_settings()
    providers = Providers(
        settings=settings,
        identity=InMemoryIdentityProvider(),
        chat_backend=StubChatBackend(),
        health_checks={},
        audit_sink=InMemoryAuditSink(),
        ingestion=canonical,
    )
    app = create_app(settings, providers)

    from routes.knowledge import _ingestion_service

    wrapper = _ingestion_service(Request({"type": "http", "app": app}))
    staging_root = wrapper.staging_root
    assert staging_root.exists()
    assert app.state.owned_runtime_resources == [wrapper]
    assert app.state.providers.ingestion is canonical

    with TestClient(app) as client:
        assert client.get("/health/live").json() == {"status": "live"}

    assert wrapper._executor._shutdown is True
    assert all(not thread.is_alive() for thread in wrapper._executor._threads)
    assert not staging_root.exists()
    assert app.state.providers.ingestion is canonical
    assert _ingestion_service(Request({"type": "http", "app": app})) is None


def test_shutdown_cancels_queued_uploads_and_is_idempotent(tmp_path: Path) -> None:
    started = threading.Event()
    release = threading.Event()

    class BlockingIngestion:
        def ingest(self, _path, **kwargs):
            started.set()
            release.wait(2)
            cancelled = kwargs.get("cancel_check")
            if callable(cancelled) and cancelled():
                return {
                    "job_id": kwargs["job_id"],
                    "document_id": None,
                    "status": "cancelled",
                    "stage": "cancelled",
                    "progress": 0.0,
                    "attempt": 1,
                    "error_code": None,
                    "tenant_id": kwargs["tenant_id"],
                    "workspace_id": kwargs["workspace_id"],
                    "collection_id": kwargs["collection_id"],
                }
            return {
                "job_id": kwargs["job_id"],
                "document_id": "doc-1",
                "status": "published",
                "stage": "published",
                "progress": 1.0,
                "attempt": 1,
                "error_code": None,
                "tenant_id": kwargs["tenant_id"],
                "workspace_id": kwargs["workspace_id"],
                "collection_id": kwargs["collection_id"],
            }

        def cancel(self, _job_id: str) -> bool:
            return True

    service = IngestionApplicationService(
        BlockingIngestion(),
        staging_root=tmp_path / "staging",
        max_jobs=2,
    )
    first = service.submit_upload(
        io.BytesIO(b"first"),
        filename="first.txt",
        collection_id="collection-a",
        workspace_id="workspace-a",
        tenant_id="tenant-a",
    )
    assert started.wait(1)
    second = service.submit_upload(
        io.BytesIO(b"second"),
        filename="second.txt",
        collection_id="collection-a",
        workspace_id="workspace-a",
        tenant_id="tenant-a",
    )

    service.shutdown(wait=False)
    queued = service._jobs[second["job_id"]]
    assert queued["status"] == "cancelled"
    assert second["job_id"] not in service._job_paths
    assert service._async_pending == 1

    release.set()
    service.shutdown(wait=True)
    service.shutdown(wait=True)

    assert first["job_id"] in service._jobs
    assert service._async_pending == 0
    assert service._scheduled_futures == {}
    assert all(not thread.is_alive() for thread in service._executor._threads)
    assert list((tmp_path / "staging").iterdir()) == []
    with pytest.raises(IngestionApplicationError) as stopped:
        service.submit_upload(
            io.BytesIO(b"after-stop"),
            filename="after.txt",
            collection_id="collection-a",
            workspace_id="workspace-a",
            tenant_id="tenant-a",
        )
    assert stopped.value.code == "storage_unavailable"


def test_shutdown_timeout_preserves_queued_future_reconciliation(tmp_path: Path) -> None:
    started = threading.Event()
    release = threading.Event()

    class CooperativeIngestion:
        def ingest(self, _path, **kwargs):
            started.set()
            release.wait(2)
            cancelled = kwargs.get("cancel_check")
            is_cancelled = callable(cancelled) and cancelled()
            return {
                "job_id": kwargs["job_id"],
                "document_id": None if is_cancelled else f"doc-{kwargs['job_id']}",
                "status": "cancelled" if is_cancelled else "published",
                "stage": "cancelled" if is_cancelled else "published",
                "progress": 0.0 if is_cancelled else 1.0,
                "attempt": 1,
                "error_code": None,
                "tenant_id": kwargs["tenant_id"],
                "workspace_id": kwargs["workspace_id"],
                "collection_id": kwargs["collection_id"],
            }

    service = IngestionApplicationService(
        CooperativeIngestion(),
        staging_root=tmp_path / "staging",
        max_jobs=2,
    )
    first = service.submit_upload(
        io.BytesIO(b"first"),
        filename="first.txt",
        collection_id="collection-a",
        workspace_id="workspace-a",
        tenant_id="tenant-a",
    )
    assert started.wait(1)
    second = service.submit_upload(
        io.BytesIO(b"second"),
        filename="second.txt",
        collection_id="collection-a",
        workspace_id="workspace-a",
        tenant_id="tenant-a",
    )

    # A zero deadline intentionally expires before the application reconciler
    # can visit the queue. The executor must leave the queued future runnable
    # so its normal callback owns source cleanup and pending-counter release.
    assert service.shutdown(wait=True, timeout=0) is False
    queued_future = service._scheduled_futures[second["job_id"]]
    assert queued_future.cancelled() is False
    assert second["job_id"] in service._job_paths

    release.set()
    assert service.shutdown(wait=True, timeout=2) is True
    assert first["job_id"] in service._jobs
    assert service._async_pending == 0
    assert service._scheduled_futures == {}
    assert service._job_paths == {}
    assert all(not thread.is_alive() for thread in service._executor._threads)
    assert list((tmp_path / "staging").iterdir()) == []


def test_all_synchronous_mutations_fail_closed_after_shutdown(tmp_path: Path) -> None:
    service = IngestionApplicationService(object(), staging_root=tmp_path / "staging")
    assert service.shutdown(wait=True) is True

    operations = (
        lambda: service.upload(
            io.BytesIO(b"after-stop"),
            filename="after.txt",
            collection_id="collection-a",
            workspace_id="workspace-a",
            tenant_id="tenant-a",
        ),
        lambda: service.reindex(
            "document-a",
            collection_id="collection-a",
            workspace_id="workspace-a",
            tenant_id="tenant-a",
        ),
        lambda: service.retry(
            "job-a",
            source=io.BytesIO(b"after-stop"),
            filename="after.txt",
            workspace_id="workspace-a",
            allowed_collection_ids=["collection-a"],
            tenant_id="tenant-a",
        ),
        lambda: service.delete_document(
            "document-a",
            workspace_id="workspace-a",
            allowed_collection_ids=["collection-a"],
            tenant_id="tenant-a",
        ),
    )

    for operation in operations:
        with pytest.raises(IngestionApplicationError) as stopped:
            operation()
        assert stopped.value.code == "storage_unavailable"


def test_shutdown_closes_admission_without_waiting_on_a_blocking_sync_mutation(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor

    started = threading.Event()
    release = threading.Event()

    class BlockingIngestion:
        def ingest(self, _path, **kwargs):
            started.set()
            release.wait(2)
            return {
                "job_id": kwargs.get("job_id", "sync-blocked"),
                "document_id": "doc-sync-blocked",
                "status": "published",
                "stage": "published",
                "progress": 1.0,
                "attempt": 1,
                "error_code": None,
                "tenant_id": kwargs["tenant_id"],
                "workspace_id": kwargs["workspace_id"],
                "collection_id": kwargs["collection_id"],
            }

    service = IngestionApplicationService(
        BlockingIngestion(),
        staging_root=tmp_path / "staging",
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            service.upload,
            io.BytesIO(b"blocking sync mutation"),
            filename="blocking.txt",
            collection_id="collection-a",
            workspace_id="workspace-a",
            tenant_id="tenant-a",
        )
        assert started.wait(1)
        began = time.monotonic()
        assert service.shutdown(wait=True, timeout=0.05) is False
        assert time.monotonic() - began < 0.5
        assert service._accepting_work is False
        release.set()
        assert future.result(timeout=2)["status"] == "published"
    assert service.shutdown(wait=True, timeout=1) is True


def test_refresh_callback_runs_after_application_lock_is_released(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor

    refreshed = threading.Event()

    class ImmediateIngestion:
        def __init__(self) -> None:
            self._operation_lock = threading.RLock()

        def operation_guard(self):
            return self._operation_lock

        def ingest(self, _path, **kwargs):
            return {
                "job_id": kwargs.get("job_id", "job-refresh"),
                "document_id": "doc-refresh",
                "status": "published",
                "stage": "published",
                "progress": 1.0,
                "attempt": 1,
                "error_code": None,
                "tenant_id": kwargs["tenant_id"],
                "workspace_id": kwargs["workspace_id"],
                "collection_id": kwargs["collection_id"],
            }

    service: IngestionApplicationService

    def refresh() -> None:
        def probe_lock() -> bool:
            acquired = service._lock.acquire(timeout=0.2)
            if acquired:
                service._lock.release()
            return acquired

        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(probe_lock).result(timeout=0.5)
            def probe_canonical_lock() -> bool:
                acquired = service.ingestion._operation_lock.acquire(timeout=0.2)
                if acquired:
                    service.ingestion._operation_lock.release()
                return acquired

            acquired_canonical = pool.submit(probe_canonical_lock).result(timeout=0.5)
            assert acquired_canonical
        refreshed.set()

    canonical = ImmediateIngestion()
    service = IngestionApplicationService(
        canonical,
        staging_root=tmp_path / "staging",
        refresh_callback=refresh,
    )
    result = service.upload(
        io.BytesIO(b"refresh callback"),
        filename="refresh.txt",
        collection_id="collection-a",
        workspace_id="workspace-a",
        tenant_id="tenant-a",
    )

    assert result["status"] == "published"
    assert refreshed.is_set()


def test_cancellation_cannot_overwrite_a_publication_that_won_the_gate(tmp_path: Path) -> None:
    publication_entered = threading.Event()
    release_publication = threading.Event()
    release_return = threading.Event()

    class PublicationRaceIngestion:
        def __init__(self) -> None:
            self.job: dict[str, object] | None = None

        def ingest(self, _path, **kwargs):
            published = {
                "job_id": kwargs["job_id"],
                "document_id": "doc-race",
                "status": "published",
                "stage": "published",
                "progress": 1.0,
                "attempt": 1,
                "error_code": None,
                "tenant_id": kwargs["tenant_id"],
                "workspace_id": kwargs["workspace_id"],
                "collection_id": kwargs["collection_id"],
            }
            with kwargs["publication_guard"]():
                self.job = published
                publication_entered.set()
                assert release_publication.wait(2)
            assert release_return.wait(2)
            return published

        def cancel(self, _job_id: str) -> bool:
            return False

        def get_status(self, _job_id: str):
            return self.job

    canonical = PublicationRaceIngestion()
    service = IngestionApplicationService(canonical, staging_root=tmp_path / "staging")
    submitted = service.submit_upload(
        io.BytesIO(b"publication race"),
        filename="race.txt",
        collection_id="collection-a",
        workspace_id="workspace-a",
        tenant_id="tenant-a",
    )
    assert publication_entered.wait(2)

    release_publication.set()
    cancelled = service.cancel(
        submitted["job_id"],
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        allowed_collection_ids=["collection-a"],
    )

    assert cancelled is not None
    assert cancelled["status"] == "published"
    assert cancelled["cancelled"] is False

    release_return.set()
    assert service.shutdown(wait=True, timeout=2) is True
    assert service.get_status(
        submitted["job_id"],
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        allowed_collection_ids=["collection-a"],
    )["status"] == "published"


def test_noncooperative_worker_has_bounded_shutdown_without_store_close(tmp_path: Path) -> None:
    started = threading.Event()
    release = threading.Event()

    class NonCooperativeIngestion:
        def ingest(self, _path, **kwargs):
            started.set()
            release.wait(2)
            return {
                "job_id": kwargs["job_id"],
                "document_id": "doc-blocked",
                "status": "published",
                "stage": "published",
                "progress": 1.0,
                "attempt": 1,
                "error_code": None,
                "tenant_id": kwargs["tenant_id"],
                "workspace_id": kwargs["workspace_id"],
                "collection_id": kwargs["collection_id"],
            }

    service = IngestionApplicationService(
        NonCooperativeIngestion(),
        staging_root=tmp_path / "staging",
    )
    service.submit_upload(
        io.BytesIO(b"blocked"),
        filename="blocked.txt",
        collection_id="collection-a",
        workspace_id="workspace-a",
        tenant_id="tenant-a",
    )
    assert started.wait(1)

    began = time.monotonic()
    assert service.shutdown(wait=True, timeout=0.05) is False
    assert time.monotonic() - began < 0.5
    assert service._executor._shutdown is True
    assert any(thread.is_alive() for thread in service._executor._threads)
    assert (tmp_path / "staging").exists()

    release.set()
    assert service.shutdown(wait=True, timeout=1) is True
    assert all(not thread.is_alive() for thread in service._executor._threads)


def test_private_staging_cleanup_respects_close_deadline(monkeypatch) -> None:
    entered = threading.Event()
    release = threading.Event()

    from services import ingestion_service as ingestion_module

    original_rmtree = ingestion_module.shutil.rmtree

    def blocked_rmtree(root) -> None:
        entered.set()
        assert release.wait(2)
        original_rmtree(root)

    monkeypatch.setattr(ingestion_module.shutil, "rmtree", blocked_rmtree)
    service = IngestionApplicationService(object())

    began = time.monotonic()
    assert service.close(timeout=0.05) is False
    assert time.monotonic() - began < 0.5
    assert entered.wait(1)

    release.set()
    assert service.close(timeout=1) is True
    assert not service.staging_root.exists()


def test_reentrant_shutdown_releases_enqueue_gate(tmp_path: Path) -> None:
    class ImmediateIngestion:
        def ingest(self, _path, **kwargs):
            return {
                "job_id": kwargs["job_id"],
                "document_id": "doc-reentrant",
                "status": "published",
                "stage": "published",
                "progress": 1.0,
                "attempt": 1,
                "error_code": None,
                "tenant_id": kwargs["tenant_id"],
                "workspace_id": kwargs["workspace_id"],
                "collection_id": kwargs["collection_id"],
            }

    service = None
    observed: list[str] = []

    def sink(event):
        observed.append(event["event"])
        if event["event"] == "worker.ingestion.enqueued":
            service.shutdown(wait=True)

    service = IngestionApplicationService(
        ImmediateIngestion(),
        staging_root=tmp_path / "staging",
        event_sink=sink,
    )
    result = service.submit_upload(
        io.BytesIO(b"reentrant shutdown"),
        filename="reentrant.txt",
        collection_id="collection-a",
        workspace_id="workspace-a",
        tenant_id="tenant-a",
    )
    service.shutdown(wait=True)

    assert result["status"] == "queued"
    assert "worker.ingestion.enqueued" in observed
    assert all(not thread.is_alive() for thread in service._executor._threads)
