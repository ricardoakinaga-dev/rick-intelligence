"""Canonical negative matrix (§35): authority, escalation, widening, refresh."""

from conftest import login_as


def test_vet_cannot_gain_documents_by_fallback(client):
    login_as(client, "vet@example.com")
    assert client.get("/api/v1/documents").status_code == 403
    me = client.get("/api/v1/auth/me").json()
    assert "documents.read" not in me.get("permissions", me and [])


def test_km_cannot_escalate_to_platform(client):
    login_as(client, "km@example.com")
    assert client.get("/api/v1/admin/users").status_code == 403
    assert client.post("/api/v1/admin/sessions/revoke", json={}).status_code == 403
    assert client.get("/api/v1/admin/system").status_code == 403


def test_explicitly_removed_stays_denied_across_refresh(client, providers):
    # Seed a KM user with an explicit removal as DATA, then refresh repeatedly.
    providers.identity._users.seed({
        "user_id": "kmx", "email": "kmx@example.com", "role": "KNOWLEDGE_MANAGER",
        "tenant_id": "default", "workspace_id": "default", "status": "active",
        "permission_overrides": {"add": [], "remove": ["documents.read", "documents.upload"]},
        "authorized_collection_ids": [], "password_plain": "password123",
        "password_version": 1, "role_version": 1,
    })
    resp = client.post("/api/v1/auth/login", json={"email": "kmx@example.com", "password": "password123", "tenant_id": "default"})
    assert resp.status_code == 200
    for _ in range(3):
        assert client.get("/api/v1/documents").status_code == 403
        assert client.post("/api/v1/documents/upload",
                           json={"filename": "x.pdf", "collection_id": "rag_phase0"}).status_code == 403
        # Untouched grants still work: removal is surgical, fallback is dead.
        assert client.get("/api/v1/sources").status_code == 200


def test_collection_and_workspace_widening_denied(client):
    login_as(client, "vet@example.com")
    assert client.post("/api/v1/chat", json={"message": "hi", "collection_id": "nope-evil"}).status_code == 403
    assert client.post("/api/v1/chat", json={"message": "hi", "workspace_id": "foreign"}).status_code == 403


def test_production_mode_refuses_test_verifier():
    from rick_identity import PlainTestVerifier
    from services.identity_service import InMemoryIdentityProvider

    import pytest

    with pytest.raises(RuntimeError):
        InMemoryIdentityProvider(mode="production", verifier=PlainTestVerifier())
    # Production with the real verifier starts (seeded users get hashed creds).
    InMemoryIdentityProvider(mode="production")


def test_public_serialization_has_no_secrets(client):
    login_as(client, "admin@example.com")
    body = client.get("/api/v1/auth/me").json()
    blob = str(body).lower()
    assert "password" not in blob and "bearer" not in blob and "reset_token" not in blob
    users = client.get("/api/v1/admin/users").json()
    assert "password" not in str(users).lower()
