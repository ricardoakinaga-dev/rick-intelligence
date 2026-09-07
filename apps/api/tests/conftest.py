"""Pytest fixtures for apps/api (hermetic; no Qdrant/Redis/provider)."""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
for _pkg in ("contracts", "authorization", "identity", "observability"):
    _p = Path(__file__).resolve().parents[3] / "packages" / _pkg / "src"
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest
from fastapi.testclient import TestClient

from app import create_app
from core.config import ApiSettings
from dependencies.services import Providers
from services.audit import InMemoryAuditSink
from services.chat_service import StubChatBackend
from services.identity_service import InMemoryIdentityProvider


def make_settings(**overrides):
    base = dict(cors_allowed_origins=("http://localhost:3000",), session_cookie_secure=False)
    base.update(overrides)
    return ApiSettings(**base)


@pytest.fixture()
def providers():
    from services.knowledge_service import seed_demo_corpus

    try:
        from rick_knowledge import InMemoryKnowledgeStore

        knowledge = InMemoryKnowledgeStore()
        seed_demo_corpus(knowledge)
    except ImportError:
        knowledge = None
    return Providers(
        settings=make_settings(),
        identity=InMemoryIdentityProvider(),
        chat_backend=StubChatBackend(),
        health_checks={},
        audit_sink=InMemoryAuditSink(),
        knowledge=knowledge,
    )


@pytest.fixture()
def app(providers):
    return create_app(providers.settings, providers)


@pytest.fixture()
def client(app):
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def login_as(client: TestClient, email: str, password: str = "password123"):
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password, "tenant_id": "default"})
    assert resp.status_code == 200, resp.text
    return resp
