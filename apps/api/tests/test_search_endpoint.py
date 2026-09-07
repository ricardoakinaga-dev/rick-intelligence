"""API contract and ACL coverage for the canonical root search endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import create_app
from conftest import login_as, make_settings


@pytest.fixture()
def search_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("RICK_API_ROOT_RETRIEVAL", "1")
    return TestClient(create_app(make_settings()), raise_server_exceptions=False)


def test_search_requires_authentication(search_client: TestClient) -> None:
    response = search_client.post("/api/v1/search", json={"query": "higiene"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_search_returns_acl_scoped_public_evidence(search_client: TestClient) -> None:
    login_as(search_client, "vet@example.com")

    response = search_client.post(
        "/api/v1/search",
        json={"query": "higiene ordenha", "collection_id": "rag_phase0", "top_k": 1},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"query", "items", "total", "metadata"}
    assert body["query"] == "higiene ordenha"
    assert body["total"] == len(body["items"]) == 1
    assert "tenant_id" not in body
    assert "tenant_id" not in body["metadata"]

    item = body["items"][0]
    assert set(item) == {
        "document_id",
        "chunk_id",
        "title",
        "source",
        "text",
        "score",
        "rank",
        "page_start",
        "page_end",
        "section",
        "checksum",
        "collection_id",
        "workspace_id",
    }
    assert item["collection_id"] == "rag_phase0"
    assert item["workspace_id"] == "default"
    assert item["text"]
    assert item["rank"] == 0


def test_search_rejects_cross_workspace_and_missing_permission(search_client: TestClient) -> None:
    login_as(search_client, "vet@example.com")
    cross_workspace = search_client.post(
        "/api/v1/search",
        json={"query": "higiene", "workspace_id": "other-workspace"},
    )
    assert cross_workspace.status_code == 403
    assert cross_workspace.json()["error"]["code"] == "forbidden"

    identity = search_client.app.state.providers.identity
    identity._users.seed({
        "user_id": "search-denied",
        "email": "search-denied@example.com",
        "role": "VETERINARIAN",
        "tenant_id": "default",
        "workspace_id": "default",
        "permission_overrides": {"add": [], "remove": ["sources.read"]},
        "authorized_collection_ids": ["rag_phase0"],
        "password_plain": "password123",
        "password_version": 1,
        "role_version": 1,
        "status": "active",
    })
    login_as(search_client, "search-denied@example.com")
    forbidden = search_client.post("/api/v1/search", json={"query": "higiene"})
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "forbidden"


@pytest.mark.parametrize(
    "body",
    [
        {"query": "   "},
        {"query": "higiene", "top_k": 0},
        {"query": "higiene", "top_k": 21},
        {"query": "x" * 2_001},
    ],
)
def test_search_rejects_unbounded_or_invalid_input(search_client: TestClient, body: dict) -> None:
    login_as(search_client, "vet@example.com")

    response = search_client.post("/api/v1/search", json=body)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


def test_search_rejects_query_over_configured_limit() -> None:
    client = TestClient(
        create_app(make_settings(max_query_chars=8)),
        raise_server_exceptions=False,
    )
    login_as(client, "vet@example.com")

    response = client.post("/api/v1/search", json={"query": "higiene longa"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"


def test_search_without_retrieval_returns_safe_root_error(client: TestClient) -> None:
    login_as(client, "vet@example.com")

    response = client.post("/api/v1/search", json={"query": "higiene"})

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "retrieval_failed"
    assert "tenant" not in response.text.lower()


@pytest.mark.parametrize("scope", [{"tenant_id": "tenant-b"}, {"tenant_id": None}, {"workspace_id": "other"}, {"collection_id": "secret"}])
def test_search_rejects_injected_evidence_outside_final_scope(search_client: TestClient, scope: dict) -> None:
    login_as(search_client, "vet@example.com")

    class InjectedRetrieval:
        def retrieve(self, *, query: str, context: dict, top_k: int):
            evidence = {
                "evidence_id": "ev-foreign",
                "document_id": "doc-foreign",
                "chunk_id": "chunk-foreign",
                "tenant_id": "default",
                "workspace_id": "default",
                "collection_id": "rag_phase0",
                "text": "TENANT-B-SECRET",
            }
            evidence.update(scope)
            return {"query": query, "evidence": [evidence]}

    search_client.app.state.providers.retrieval = InjectedRetrieval()
    response = search_client.post("/api/v1/search", json={"query": "higiene"})

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "retrieval_failed"
    assert "TENANT-B-SECRET" not in response.text
