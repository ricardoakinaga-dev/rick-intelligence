from __future__ import annotations

from threading import Event
from types import SimpleNamespace

from deployment_composition import DeploymentRuntime


class _Worker:
    def __init__(self):
        self.started = False
        self.stopped = False
        self.ran = False

    def start(self):
        self.started = True
        return True

    def health_check(self):
        return self.started

    def run_forever(self):
        self.ran = True

    def request_stop(self):
        self.stopped = True

    def shutdown(self, *, timeout):
        assert timeout > 0
        return True


class _Reconciler:
    def __init__(self, *, healthy=True):
        self.healthy = healthy
        self.processed = Event()

    def health_check(self):
        return self.healthy

    def process_once(self):
        self.processed.set()
        return 0


def test_admin_audit_reconciler_runs_as_worker_sidecar_and_stops_cleanly():
    worker = _Worker()
    reconciler = _Reconciler()
    runtime = DeploymentRuntime(
        SimpleNamespace(worker=worker, health_checks={}),
        admin_audit_reconciler=reconciler,
        admin_audit_poll_interval=0.05,
    )

    assert runtime.start() is True
    assert reconciler.processed.wait(timeout=1)
    assert runtime.readiness_check() is True
    assert runtime.run_forever() is None
    assert runtime.shutdown(timeout=1) is True
    assert worker.started and worker.ran
    assert runtime._admin_audit_thread is None


def test_worker_does_not_start_when_admin_audit_schema_is_unavailable():
    worker = _Worker()
    reconciler = _Reconciler(healthy=False)
    runtime = DeploymentRuntime(
        SimpleNamespace(worker=worker, health_checks={}),
        admin_audit_reconciler=reconciler,
    )

    assert runtime.start() is False
    assert worker.started is False
    assert runtime.shutdown(timeout=1) is True


def test_worker_health_and_transferred_client_close_share_one_owned_loop():
    import asyncio
    loops = []

    class Client:
        closed = 0

        async def aclose(self):
            loops.append(asyncio.get_running_loop())
            self.closed += 1

    async def health():
        loops.append(asyncio.get_running_loop())
        return True

    client = Client()
    runtime = DeploymentRuntime(SimpleNamespace(worker=_Worker(),
        health_checks={"provider": health},
        _composition_inputs=SimpleNamespace(provider_client=client)))
    assert runtime.start() is True
    assert runtime.health_check() is True
    assert runtime.health_check() is True
    assert runtime.shutdown(timeout=1) is True
    assert runtime.shutdown(timeout=1) is True
    assert client.closed == 1
    assert len({id(loop) for loop in loops}) == 1
    assert loops[0].is_closed()
    assert runtime.health_check() is False


def test_failed_cleanup_reports_incomplete_preserves_bridge_and_can_retry():
    import asyncio

    class Provider:
        calls = 0
        loop = None

        async def health_check(self):
            self.loop = asyncio.get_running_loop()
            return True

        async def aclose(self):
            assert asyncio.get_running_loop() is self.loop
            self.calls += 1
            if self.calls <= 2:
                raise RuntimeError("synthetic close failure")

    provider = Provider()
    runtime = DeploymentRuntime(SimpleNamespace(worker=_Worker(), provider=provider,
        health_checks={"provider": provider.health_check}))
    runtime.start()
    assert runtime.health_check() is True
    loop = runtime._async_bridge._loop
    assert runtime.shutdown(timeout=1) is False
    assert not loop.is_closed()
    assert runtime._async_bridge._loop is loop
    assert runtime.shutdown(timeout=1) is False
    assert runtime.shutdown(timeout=1) is True
    assert runtime.shutdown(timeout=1) is True
    assert provider.calls == 3
    assert loop.is_closed()


def test_build_worker_composes_postgres_admin_audit_reconciler(monkeypatch):
    import deployment_composition
    from admin_audit_outbox import PostgresAdminAuditReconciler

    settings = object()
    connection_factory = lambda: None
    inputs = SimpleNamespace(connection_factory=connection_factory)
    providers = SimpleNamespace(worker=_Worker(), health_checks={})
    monkeypatch.setattr(deployment_composition, "_settings", lambda: settings)
    monkeypatch.setattr(deployment_composition, "_build_inputs", lambda _settings: inputs)
    monkeypatch.setattr(
        deployment_composition,
        "build_external_providers",
        lambda _settings, _inputs: providers,
    )
    monkeypatch.setattr(deployment_composition, "configure_process_otel", lambda **_kwargs: None)

    runtime = deployment_composition.build_worker()

    assert isinstance(runtime, DeploymentRuntime)
    assert isinstance(runtime.admin_audit_reconciler, PostgresAdminAuditReconciler)
    assert runtime.admin_audit_reconciler._connection_factory is connection_factory
