"""Negative security matrix (§51): roles × routes."""

from conftest import login_as


def test_anonymous_admin_is_401(client):
    assert client.get("/api/v1/admin/users").status_code == 401


def test_vet_cannot_admin_users(client):
    login_as(client, "vet@example.com")
    assert client.get("/api/v1/admin/users").status_code == 403


def test_vet_cannot_upload(client):
    login_as(client, "vet@example.com")
    resp = client.post("/api/v1/documents/upload", json={"filename": "x.pdf", "collection_id": "rag_phase0"})
    assert resp.status_code == 403


def test_vet_cannot_browse_library(client):
    login_as(client, "vet@example.com")
    assert client.get("/api/v1/documents").status_code == 403


def test_vet_allowed_sources_and_collections(client):
    login_as(client, "vet@example.com")
    assert client.get("/api/v1/sources").status_code == 200
    resp = client.get("/api/v1/collections")
    assert resp.status_code == 200
    ids = [c["collection_id"] for c in resp.json()["items"]]
    assert "rag_phase0" in ids
    assert "vet-library" not in ids  # outside VET grant


def test_km_cannot_platform_user_admin(client):
    login_as(client, "km@example.com")
    assert client.get("/api/v1/admin/users").status_code == 403


def test_admin_can_manage_users(client):
    login_as(client, "admin@example.com")
    resp = client.get("/api/v1/admin/users")
    assert resp.status_code == 200


def test_chat_cannot_widen_collection(client):
    login_as(client, "vet@example.com")
    resp = client.post("/api/v1/chat", json={"message": "hello", "collection_id": "secret-collection"})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"
