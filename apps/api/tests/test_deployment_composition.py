from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.config import ApiSettings
import deployment_composition
from services.external_composition import ExternalCompositionError


def test_api_factory_requires_explicit_external_database_before_client_creation():
    settings = ApiSettings(
        environment="dev",
        identity_mode="dev",
        chat_backend_mode="professor",
        cors_allowed_origins=("http://localhost:13000",),
        session_cookie_secure=True,
        external_chat_api_key="dev-key",
        provider_kind="openai_compatible",
        provider_base_url="http://provider:8080/v1",
        locker_base_url="http://locker:8080",
    )

    with pytest.raises(ExternalCompositionError, match="RICK_EXTERNAL_DATABASE_DSN"):
        deployment_composition.build_api_inputs(settings)


def test_worker_factory_returns_a_lifecycle_owner(monkeypatch):
    class Worker:
        def __init__(self):
            self.started = False
            self.stopped = False

        def start(self):
            self.started = True

        def run_forever(self):
            return None

        def health_check(self):
            return True

        def shutdown(self, *, timeout):
            self.stopped = timeout > 0

    worker = Worker()
    providers = SimpleNamespace(worker=worker, health_checks={})
    monkeypatch.setattr(deployment_composition, "_settings", lambda: object())
    monkeypatch.setattr(deployment_composition, "_build_inputs", lambda settings: object())
    monkeypatch.setattr(deployment_composition, "build_external_providers", lambda settings, inputs: providers)

    runtime = deployment_composition.build_worker()

    assert runtime.start() is None
    assert runtime.health_check() is True
    assert runtime.run_forever() is None
    assert runtime.shutdown(timeout=1) is True
    assert worker.started is True
    assert worker.stopped is True


def test_worker_scope_is_never_inferred(monkeypatch):
    monkeypatch.delenv("RICK_WORKER_SCOPE_TENANT", raising=False)
    monkeypatch.delenv("RICK_WORKER_SCOPE_WORKSPACE", raising=False)
    monkeypatch.delenv("RICK_WORKER_SCOPE_COLLECTION", raising=False)

    with pytest.raises(ExternalCompositionError, match="RICK_WORKER_SCOPE_TENANT"):
        deployment_composition._worker_scope()
