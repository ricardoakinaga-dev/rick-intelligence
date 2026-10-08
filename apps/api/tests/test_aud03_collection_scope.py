"""Collection mutations must narrow the live authenticated HTTP scope."""

import pytest

from rick_knowledge import Collection


@pytest.mark.parametrize("method,suffix,body", [
    ("PATCH", "", {"title": "changed"}),
    ("POST", "/archive", None),
])
@pytest.mark.parametrize("grants,expected", [(["allowed"], 403), (["secret"], 200), (["*"], 200)])
def test_collection_mutation_requires_grant(client, providers, method, suffix, body, grants, expected):
    providers.identity._users.seed({
        "user_id": "limited-manager", "email": "limited-manager@example.test",
        "tenant_id": "default", "workspace_id": "default", "role": "KNOWLEDGE_MANAGER",
        "status": "active", "password_plain": "password123", "authorized_collection_ids": grants,
    })
    providers.knowledge.upsert_collection(Collection(
        tenant_id="default", workspace_id="default", collection_id="secret", title="Original",
    ))
    login = client.post("/api/v1/auth/login", json={
        "email": "limited-manager@example.test", "password": "password123", "tenant_id": "default",
    })
    assert login.status_code == 200, login.text
    response = client.request(method, "/api/v1/collections/secret" + suffix,
                              **({"json": body} if body is not None else {}))
    assert response.status_code == expected, response.text
    stored = providers.knowledge.get_collection("default", "secret", tenant_id="default")
    if expected == 403:
        assert stored.title == "Original" and stored.status == "active"
    elif method == "PATCH":
        assert stored.title == "changed" and stored.status == "active"
    else:
        assert stored.status == "archived"
