"""API test helpers, independent of pytest's mutable conftest module name."""

from fastapi.testclient import TestClient

from core.config import ApiSettings


def make_settings(**overrides):
    base = dict(cors_allowed_origins=("http://localhost:3000",), session_cookie_secure=False)
    base.update(overrides)
    return ApiSettings(**base)


def login_as(client: TestClient, email: str, password: str = "password123"):
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password, "tenant_id": "default"})
    assert resp.status_code == 200, resp.text
    return resp
