"""Request IDs, security headers, CORS, request limits, rate limiting."""

from conftest import login_as


def test_request_id_headers(client):
    resp = client.get("/health/live")
    assert "X-Request-ID" in resp.headers
    resp2 = client.get("/health/live", headers={"X-Request-ID": "abc", "X-Correlation-ID": "corr-1"})
    assert resp2.headers["X-Request-ID"] == "abc"
    assert resp2.headers["X-Correlation-ID"] == "corr-1"


def test_request_id_rejects_control_characters(client):
    response = client.get("/health/live", headers={"X-Request-ID": "bad\nforged"})
    request_id = response.headers["X-Request-ID"]
    assert request_id != "bad\nforged"
    assert all(ord(char) >= 0x20 for char in request_id)
    assert len(request_id) <= 128


def test_oversize_correlation_id_regenerated(client):
    resp = client.get("/health/live", headers={"X-Correlation-ID": "x" * 500})
    assert resp.headers["X-Correlation-ID"] != "x" * 500
    assert len(resp.headers["X-Correlation-ID"]) <= 128


def test_error_carries_request_id(client):
    resp = client.get("/api/v1/admin/users")
    assert resp.status_code == 401
    assert resp.json()["error"]["request_id"] == resp.headers["X-Request-ID"]


def test_security_headers(client):
    resp = client.get("/health/live")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("Referrer-Policy") == "no-referrer"


def test_cors_allowlist_no_wildcard_with_credentials(client):
    resp = client.options("/api/v1/auth/login", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert resp.headers.get("Access-Control-Allow-Origin") != "*"


def test_request_size_limit(app, providers):
    from fastapi.testclient import TestClient

    from app import create_app
    from conftest import make_settings
    from dependencies.services import Providers as P
    from services.audit import InMemoryAuditSink
    from services.chat_service import StubChatBackend
    from services.identity_service import InMemoryIdentityProvider

    settings = make_settings(max_json_bytes=100)
    p = P(settings=settings, identity=InMemoryIdentityProvider(), chat_backend=StubChatBackend(),
          health_checks={}, audit_sink=InMemoryAuditSink())
    c = TestClient(create_app(settings, p), raise_server_exceptions=False)
    resp = c.post("/api/v1/auth/login", content="x" * 500, headers={"Content-Type": "application/json"})
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "request_too_large"


def test_login_rate_limited(client):
    for _ in range(12):
        client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "x", "tenant_id": "default"})
    resp = client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "x", "tenant_id": "default"})
    assert resp.status_code in (401, 429)


def test_ingestion_openapi_declares_both_upload_and_reindex_bodies(app):
    schema = app.openapi()
    upload = schema["paths"]["/api/v1/documents/upload"]["post"]["requestBody"]
    multipart = upload["content"]["multipart/form-data"]["schema"]
    assert multipart["required"] == ["file", "collection_id"]
    assert multipart["properties"]["file"] == {"type": "string", "format": "binary"}
    assert "application/json" in upload["content"]

    reindex = schema["paths"]["/api/v1/ingestion/reindex"]["post"]["requestBody"]
    assert reindex["content"]["application/json"]["schema"]["required"] == ["document_id"]
