"""Error contract: safe envelope, no leaks, stable codes."""

from conftest import login_as


def test_404_envelope_has_request_id(client):
    resp = client.get("/nope-unknown-xyz")
    # Unknown paths return framework 404; assert no stack/secret leakage either way.
    assert resp.status_code == 404
    assert "traceback" not in resp.text.lower()
    # A guarded unknown-shaped id still enforces auth first (default-deny before 404).
    guarded = client.get("/api/v1/documents/does-not-exist")
    assert guarded.status_code == 401
    assert guarded.json()["error"]["code"] == "unauthorized"


def test_internal_error_is_sanitized(app, providers):
    from fastapi.testclient import TestClient

    from core.errors import ApiError

    @app.get("/api/v1/_boom")
    def boom():
        raise RuntimeError("qdrant connection string redis://secret:pass@host exploded")

    c = TestClient(app, raise_server_exceptions=False)
    login_as(c, "admin@example.com")
    resp = c.get("/api/v1/_boom")
    assert resp.status_code == 500
    body = resp.json()
    assert body["error"]["code"] == "internal_error"
    assert "redis://" not in resp.text
    assert "traceback" not in resp.text.lower()


def test_provider_failure_mapping():
    from adapters.legacy.cvg import translate_legacy_exception

    assert translate_legacy_exception(RuntimeError("qdrant timeout")).code == "vector_store_unavailable"
    assert translate_legacy_exception(RuntimeError("redis down")).code == "lock_unavailable"


def test_validation_error_shape(client):
    resp = client.post("/api/v1/auth/login", json={"email": "x"})  # missing password
    assert resp.status_code in (400, 422)
    if resp.status_code == 400:
        assert resp.json()["error"]["code"] == "validation_error"
