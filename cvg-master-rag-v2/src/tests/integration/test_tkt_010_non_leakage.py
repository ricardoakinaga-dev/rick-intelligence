"""
TKT-010 — Non-leakage suite for tenant/workspace isolation.

This suite exists to satisfy the formal F1 deliverable defined in docs/02_spec/0115
and docs/02_spec/0117. It focuses on easy-to-audit proofs of non-leakage using the
current enterprise contracts.
"""
import sys
from pathlib import Path

from fastapi.testclient import TestClient
import pytest


SRC_DIR = Path(__file__).resolve().parents[2]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from api.main import app
from services.admin_service import reset_admin_state


def enterprise_headers(
    client: TestClient,
    *,
    role: str = "admin",
    tenant_id: str = "default",
) -> dict[str, str]:
    email = {
        "admin": "admin@demo.local",
        "operator": "operator@demo.local",
        "viewer": "viewer@demo.local",
    }[role]
    response = client.post(
        "/auth/login",
        json={
            "email": email,
            "password": "demo1234",
            "tenant_id": tenant_id,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    return {"Authorization": f"Bearer {payload['session_token']}"}


@pytest.fixture(autouse=True)
def reset_state():
    reset_admin_state()
    yield
    reset_admin_state()


class TestTKT010NonLeakage:
    def test_tkt010_operator_cannot_read_foreign_workspace_documents(self):
        client = TestClient(app)
        headers = enterprise_headers(client, role="operator", tenant_id="default")

        response = client.get("/documents?workspace_id=acme-lab", headers=headers)

        assert response.status_code == 403, response.text
        payload = response.json()
        assert payload["detail"]["error"] == "workspace_forbidden"

    def test_tkt010_operator_cannot_search_foreign_workspace(self, monkeypatch):
        calls: list[str] = []

        def fake_search(_request):
            calls.append("search")
            return {
                "query": "should-not-run",
                "workspace_id": "acme-lab",
                "results": [],
                "total_candidates": 0,
                "low_confidence": True,
                "retrieval_time_ms": 1,
                "method": "híbrida",
            }

        monkeypatch.setattr("services.vector_service.search_hybrid", fake_search)

        client = TestClient(app)
        headers = enterprise_headers(client, role="operator", tenant_id="default")

        response = client.post(
            "/search",
            json={"query": "tenant leak", "workspace_id": "acme-lab"},
            headers=headers,
        )

        assert response.status_code == 403, response.text
        assert calls == []

    def test_tkt010_admin_switches_between_three_tenants_without_visual_or_data_leakage(self, monkeypatch):
        def fake_list_document_items(*, workspace_id: str, limit: int, offset: int, source_type=None, status=None, query=None):
            return {
                "workspace_id": workspace_id,
                "items": [
                    {
                        "document_id": f"{workspace_id}-doc",
                        "workspace_id": workspace_id,
                        "catalog_scope": "canonical",
                        "source_type": "md",
                        "filename": f"{workspace_id}.md",
                        "page_count": 1,
                        "char_count": 100,
                        "chunk_count": 1,
                        "status": "parsed",
                        "created_at": "2026-04-19T00:00:00Z",
                        "chunking_strategy": "recursive",
                        "tags": [],
                        "embeddings_model": None,
                        "indexed_at": None,
                        "file_path": None,
                    }
                ],
                "total": 1,
                "limit": limit,
                "offset": offset,
            }

        monkeypatch.setattr("api.main.list_document_items", fake_list_document_items)

        client = TestClient(app)
        headers = enterprise_headers(client, role="admin", tenant_id="default")

        default_docs = client.get("/documents?workspace_id=default", headers=headers)
        assert default_docs.status_code == 200, default_docs.text
        assert default_docs.json()["items"][0]["workspace_id"] == "default"

        switched = client.post("/auth/switch-tenant", json={"tenant_id": "acme-lab"}, headers=headers)
        assert switched.status_code == 200, switched.text
        switched_headers = {"Authorization": f"Bearer {switched.json()['session_token']}"}

        acme_docs = client.get("/documents?workspace_id=acme-lab", headers=switched_headers)
        assert acme_docs.status_code == 200, acme_docs.text
        assert acme_docs.json()["items"][0]["workspace_id"] == "acme-lab"

        switched_again = client.post("/auth/switch-tenant", json={"tenant_id": "northwind"}, headers=switched_headers)
        assert switched_again.status_code == 200, switched_again.text
        northwind_headers = {"Authorization": f"Bearer {switched_again.json()['session_token']}"}

        northwind_docs = client.get("/documents?workspace_id=northwind", headers=northwind_headers)
        assert northwind_docs.status_code == 200, northwind_docs.text
        assert northwind_docs.json()["items"][0]["workspace_id"] == "northwind"

        forbidden_previous = client.get("/documents?workspace_id=acme-lab", headers=northwind_headers)
        assert forbidden_previous.status_code == 403, forbidden_previous.text
