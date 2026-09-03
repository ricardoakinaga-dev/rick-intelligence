"""Pytest fixtures for apps/api (hermetic; no Qdrant/Redis/provider)."""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
CONTRACTS_SRC = Path(__file__).resolve().parents[3] / "packages" / "contracts" / "src"
if str(CONTRACTS_SRC) not in sys.path:
    sys.path.insert(0, str(CONTRACTS_SRC))

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
    return Providers(
        settings=make_settings(),
        identity=InMemoryIdentityProvider(),
        chat_backend=StubChatBackend(),
        health_checks={},
        audit_sink=InMemoryAuditSink(),
    )


@pytest.fixture()
def app(providers):
    return create_app(providers.settings, providers)


@pytest.fixture()
def client(app):
    return TestClient(app, raise_server_exceptions=False)


def login_as(client: TestClient, email: str, password: str = "password123"):
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password, "tenant_id": "default"})
    assert resp.status_code == 200, resp.text
    return resp
