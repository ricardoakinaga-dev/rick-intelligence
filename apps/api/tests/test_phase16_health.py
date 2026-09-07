"""Focused Phase 1.6 readiness checks and redaction tests."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest
from fastapi.testclient import TestClient

from app import create_app
from conftest import login_as, make_settings
from core.lifecycle import DependencyState, evaluate_checks
from core import lifecycle
from dependencies.services import Providers
from services.audit import InMemoryAuditSink
from services.chat_service import StubChatBackend
from services.identity_service import InMemoryIdentityProvider


def test_forwarded_client_ip_requires_a_configured_trusted_proxy() -> None:
    from core.security import get_client_ip

    assert get_client_ip(True, "10.0.0.2", "198.51.100.10") == "10.0.0.2"
    assert get_client_ip(
        True, "10.0.0.2", "198.51.100.10, 10.0.0.2", ("10.0.0.0/24",)
    ) == "198.51.100.10"
    assert get_client_ip(
        True, "10.0.0.2", "not-an-ip, 10.0.0.2", ("10.0.0.0/24",)
    ) == "10.0.0.2"
    assert get_client_ip(True, "10.0.0.2", "198.51.100.10", None) == "10.0.0.2"


def _client(*, health_checks: dict | None = None, **components) -> TestClient:
    providers = Providers(
        settings=make_settings(),
        identity=InMemoryIdentityProvider(),
        chat_backend=StubChatBackend(),
        health_checks=health_checks or {},
        audit_sink=InMemoryAuditSink(),
    )
    for name, value in components.items():
        setattr(providers, name, value)
    return TestClient(create_app(providers.settings, providers), raise_server_exceptions=False)


def test_readiness_reports_selected_runtime_components_without_changing_liveness() -> None:
    class Healthy:
        def health_check(self):
            return True

    client = _client(provider=Healthy(), lease=Healthy(), retrieval=Healthy(), ingestion=Healthy())
    assert client.get("/health/live").json() == {"status": "live"}
    response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert {check["name"] for check in body["checks"]} == {
        "kernel", "provider", "lease", "retrieval", "ingestion"
    }
    assert all(set(check) == {"name", "ok", "required"} for check in body["checks"])


def test_readiness_preserves_custom_checks_and_distinguishes_degraded_and_not_ready() -> None:
    optional = lambda: DependencyState(name="optional-store", ok=False, required=False, detail="offline")
    degraded = _client(health_checks={"optional-store": optional})
    response = degraded.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"

    required = lambda: DependencyState(name="required-store", ok=False, required=True, detail="offline")
    not_ready = _client(health_checks={"required-store": required})
    response = not_ready.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_selected_runtime_component_cannot_downgrade_itself_to_optional() -> None:
    class Misreported:
        def health_check(self):
            return DependencyState(name="storage", ok=False, required=False, detail="offline")

    client = _client(storage=Misreported())
    response = client.get("/health/ready")

    assert response.status_code == 503
    check = next(item for item in response.json()["checks"] if item["name"] == "storage")
    assert check == {"name": "storage", "ok": False, "required": True}


def test_async_checks_and_admin_details_are_safe() -> None:
    async def bad_check():
        raise RuntimeError("https://provider.example/v1?api_key=secret")

    client = _client(health_checks={"provider": bad_check})
    public = client.get("/health/ready")
    assert public.status_code == 503
    assert "provider.example" not in public.text
    assert "secret" not in public.text

    login_as(client, "admin@example.com")
    admin = client.get("/api/v1/admin/health")
    assert admin.status_code == 200
    assert admin.json()["status"] == "not_ready"
    assert "provider.example" not in admin.text
    assert "secret" not in admin.text
    assert admin.json()["checks"] == [
        {"name": "provider", "ok": False, "required": True, "detail": "check_failed"}
    ]


def test_evaluate_checks_never_serializes_raw_provider_values() -> None:
    async def raw_value():
        return {
            "name": "provider",
            "ok": False,
            "required": False,
            "detail": "https://provider.example/secret?token=abc",
        }

    import asyncio

    states = asyncio.run(evaluate_checks({"provider": raw_value}))
    assert states[0].detail == "unavailable"
    assert "provider.example" not in str(states[0])


async def _eventually(predicate) -> None:
    async def poll():
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(poll(), timeout=1)


def test_sync_blocking_preserves_loop_progress_and_total_budget() -> None:
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    calls = []

    def blocked():
        started.set()
        try:
            release.wait()
            return True
        finally:
            finished.set()

    async def run():
        loop = asyncio.get_running_loop()
        before = loop.time()
        request = asyncio.create_task(evaluate_checks(
            {"blocked": blocked, **{f"later{i}": lambda: calls.append(1) for i in range(50)}},
            timeout_seconds=0.04,
        ))
        try:
            await _eventually(started.is_set)
            assert not release.is_set()  # Loop progressed while worker is blocked.
            states = await asyncio.wait_for(request, 0.5)
            assert loop.time() - before < 0.5
            assert [s.name for s in states] == ["blocked", *[f"later{i}" for i in range(50)]]
            assert all(s.detail == "check_timeout" for s in states)
            assert lifecycle.evaluate_readiness(states) == ("not_ready", 503)
            assert calls == []
        finally:
            release.set()
            await _eventually(finished.is_set)
            await request

    asyncio.run(run())


def test_hung_sync_checks_have_no_queue_and_recover_capacity() -> None:
    release = threading.Event()
    workers = []

    def blocked():
        workers.append(threading.current_thread())
        release.wait()
        raise RuntimeError("secret https://provider.example?token=abc")

    async def run():
        try:
            for _ in range(lifecycle.MAX_READINESS_THREADS):
                state = (await evaluate_checks({"db": blocked}, timeout_seconds=0.02))[0]
                assert state.detail == "check_timeout"
            for _ in range(20):
                state = (await evaluate_checks({"db": blocked}, timeout_seconds=0.02))[0]
                assert state.detail == "check_capacity"
                assert "secret" not in str(state)
            assert len(workers) == lifecycle.MAX_READINESS_THREADS
            assert all(worker.daemon for worker in workers)
        finally:
            release.set()
            await _eventually(lambda: all(not worker.is_alive() for worker in workers))
        assert (await evaluate_checks({"db": lambda: True}))[0].ok

    asyncio.run(run())


def test_async_resistant_checks_keep_bounded_slots_on_caller_loop() -> None:
    async def run():
        loop = asyncio.get_running_loop()
        release = asyncio.Event()
        cancelled = asyncio.Event()
        tasks = []

        async def resistant():
            assert asyncio.get_running_loop() is loop
            tasks.append(asyncio.current_task())
            while not release.is_set():
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    cancelled.set()
            raise RuntimeError("secret https://provider.example?token=abc")

        try:
            for _ in range(lifecycle.MAX_READINESS_TASKS):
                state = (await evaluate_checks({"db": resistant}, timeout_seconds=0.02))[0]
                assert state.detail == "check_timeout"
            await asyncio.wait_for(cancelled.wait(), 0.5)
            for _ in range(20):
                states = await evaluate_checks({"db": resistant}, timeout_seconds=0.02)
                assert states[0].detail == "check_capacity"
                assert lifecycle.evaluate_readiness(states) == ("not_ready", 503)
            assert len(tasks) == lifecycle.MAX_READINESS_TASKS
            assert len(lifecycle._active_tasks) == lifecycle.MAX_READINESS_TASKS
        finally:
            release.set()
            await asyncio.gather(*tasks)
            await _eventually(lambda: not lifecycle._active_tasks)
        assert (await evaluate_checks({"db": lambda: True}))[0].ok

    asyncio.run(run())


def test_caller_cancellation_returns_without_joining_resistant_check() -> None:
    async def run():
        started = asyncio.Event()
        cancelled = asyncio.Event()
        release = asyncio.Event()
        tasks = []

        async def resistant():
            tasks.append(asyncio.current_task())
            started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.set()
                await release.wait()
            return True

        request = asyncio.create_task(evaluate_checks({"db": resistant}))
        try:
            await asyncio.wait_for(started.wait(), 0.5)
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(request, 0.5)
            await asyncio.wait_for(cancelled.wait(), 0.5)
            assert not tasks[0].done()
        finally:
            release.set()
            await asyncio.gather(*tasks)
            await _eventually(lambda: not lifecycle._active_tasks)

    asyncio.run(run())


def test_async_cooperative_cancellation_and_optional_timeout() -> None:
    async def run():
        cancelled = asyncio.Event()

        async def hanging():
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        states = await evaluate_checks({"optional": hanging}, default_required=False, timeout_seconds=0.02)
        await asyncio.wait_for(cancelled.wait(), 0.5)
        assert lifecycle.evaluate_readiness(states) == ("degraded", 200)
        assert states[0].detail == "check_timeout"

    asyncio.run(run())


def test_mixed_results_order_loop_affinity_and_required_async_wrappers() -> None:
    from types import SimpleNamespace

    async def run():
        loop = asyncio.get_running_loop()
        order = []

        def sync_check():
            order.append("sync")
            return True

        async def optional():
            assert asyncio.get_running_loop() is loop
            order.append("async")
            return DependencyState("optional", False, False, "offline")

        states = await evaluate_checks({"sync": sync_check, "optional": optional, "raw": {"ok": True}})
        assert order == ["sync", "async"]
        assert [s.name for s in states] == ["sync", "optional", "raw"]
        assert lifecycle.evaluate_readiness(states) == ("degraded", 200)
        for custom in ({}, {"storage": optional}):
            providers = SimpleNamespace(storage=SimpleNamespace(health_check=optional), health_checks=custom)
            states = await lifecycle.collect_readiness_states(providers)
            assert states[0].required is True
            assert lifecycle.evaluate_readiness(states) == ("not_ready", 503)

    asyncio.run(run())


@pytest.mark.parametrize("budget", [0, -1, float("inf"), float("nan")])
def test_readiness_rejects_unbounded_or_invalid_budget(budget) -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        asyncio.run(evaluate_checks({}, timeout_seconds=budget))


def test_hung_sync_worker_does_not_delay_process_shutdown() -> None:
    script = """
import asyncio
import threading
from core.lifecycle import evaluate_checks
release = threading.Event()
asyncio.run(evaluate_checks({'db': release.wait}, timeout_seconds=0.02))
"""
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=3,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
             "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0, result.stderr


def test_cancelled_sync_factory_closes_late_coroutine() -> None:
    started = threading.Event()
    release = threading.Event()
    produced = []

    async def result():
        return True

    def factory():
        started.set()
        release.wait()
        produced.append(result())
        return produced[0]

    async def run():
        request = asyncio.create_task(evaluate_checks({"db": factory}))
        try:
            await _eventually(started.is_set)
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(request, 0.5)
        finally:
            release.set()
            await _eventually(lambda: produced and produced[0].cr_frame is None)

    asyncio.run(run())


def test_ready_route_uses_finite_default_and_redacts_timeout() -> None:
    release = threading.Event()
    finished = threading.Event()

    def blocked():
        try:
            release.wait()
            raise RuntimeError("secret https://provider.example?token=abc")
        finally:
            finished.set()

    try:
        with _client(health_checks={"db": blocked}) as client:
            response = client.get("/health/ready")
            assert response.status_code == 503
            assert response.json() == {
                "status": "not_ready",
                "checks": [{"name": "db", "ok": False, "required": True}],
            }
            assert client.get("/health/live").json() == {"status": "live"}
    finally:
        release.set()
        assert finished.wait(1)
