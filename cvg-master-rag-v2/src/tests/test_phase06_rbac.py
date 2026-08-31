import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.main import app, _filter_document_response_items
from models.schemas import EnterpriseSession, EnterpriseTenant, EnterpriseUser
from services.admin_service import create_user, reset_admin_state, update_user
from services.api_security import build_retrieval_context, require_permission, session_has_permission
from services.authorization import (
    CANONICAL_PERMISSION_IDS,
    permissions_for_role,
    permission_granted,
)
from services.enterprise_service import SESSION_COOKIE_NAME


@pytest.fixture(autouse=True)
def reset_enterprise_state():
    reset_admin_state()
    yield
    reset_admin_state()


def _session(*, role: str = "viewer", permissions: list[str] | None = None, grants: list[str] | None = None):
    tenant = EnterpriseTenant(
        tenant_id="default",
        name="Workspace Principal",
        workspace_id="default",
        plan="enterprise",
        status="active",
    )
    user = EnterpriseUser(
        user_id="user-phase06",
        name="Phase 0.6 User",
        email="phase06@example.com",
        role=role,
        permissions=permissions if permissions is not None else permissions_for_role(role),
        authorized_collection_ids=grants if grants is not None else [],
    )
    return EnterpriseSession(
        authenticated=True,
        session_state="active",
        session_token="phase06-session",
        user=user,
        active_tenant=tenant,
        available_tenants=[tenant],
    )


def _session_record(token: str, *, permissions: list[str], role: str = "viewer") -> dict:
    return {
        "session_token": token,
        "user_id": "legacy-user",
        "tenant_id": "default",
        "role_snapshot": role,
        "permissions_snapshot": permissions,
        "created_at": "2026-08-30T00:00:00Z",
        "last_seen_at": "2026-08-30T00:01:00Z",
        "expires_at": "2099-01-01T00:00:00Z",
        "revoked_at": None,
        "revoked_reason": None,
    }


def _patch_session_store(monkeypatch, token: str, record: dict, user: dict):
    import services.enterprise_service as enterprise

    tenant = {
        "tenant_id": "default",
        "name": "Workspace Principal",
        "workspace_id": "default",
        "plan": "enterprise",
        "status": "active",
        "document_count": 0,
    }
    monkeypatch.setattr(enterprise, "get_user", lambda user_id: user if user_id == user["user_id"] else None)
    monkeypatch.setattr(enterprise, "can_access_tenant", lambda *_args: True)
    monkeypatch.setattr(enterprise, "get_accessible_tenants", lambda _user: [tenant])
    monkeypatch.setattr(
        enterprise,
        "update_session_state",
        lambda mutator: mutator({"sessions": {token: dict(record)}}),
    )


def test_permission_overrides_add_remove_and_user_api_contract_are_deterministic():
    created = create_user(
        {
            "user_id": "phase06-overrides",
            "name": "Overrides User",
            "email": "phase06-overrides@example.com",
            "password": "Phase06Secure!123",
            "role": "viewer",
            "tenant_id": "default",
            "status": "active",
            "permission_overrides": {
                "add": ["documents.read"],
                "remove": ["query.execute"],
            },
        }
    )

    assert "documents.read" in created["permissions"]
    assert "chat.query" not in created["permissions"]
    assert created["permission_overrides"] == {
        "add": ["documents.read"],
        "remove": ["chat.query"],
    }

    updated = update_user(
        "phase06-overrides",
        {
            "permission_overrides": {
                "add": ["documents.manage"],
                "remove": ["documents.read"],
            }
        },
    )
    assert "documents.manage" in updated["permissions"]
    assert "documents.read" not in updated["permissions"]
    assert "documents.read" not in permissions_for_role(
        updated["role"], updated["permission_overrides"]
    )


def test_remove_inherited_permission_is_not_regranted_by_role_fallback():
    effective = permissions_for_role("operator", {"remove": ["documents.upload"]})

    assert "documents.upload" not in effective
    assert not permission_granted(
        role="operator",
        permissions=effective,
        required="documents.upload",
        authoritative=True,
    )


def test_wildcard_role_removal_expands_effective_set_and_stays_denied():
    effective = permissions_for_role(
        "PLATFORM_ADMIN",
        {"remove": ["documents.read", "query.execute"]},
    )

    assert set(effective) == set(CANONICAL_PERMISSION_IDS) - {"documents.read", "chat.query"}
    assert not permission_granted(
        role="super_admin",
        permissions=effective,
        required="documents.read",
    )
    assert permission_granted(
        role="super_admin",
        permissions=effective,
        required="users.manage",
        authoritative=True,
    )


def test_wildcard_removal_does_not_expand_to_all_permissions():
    effective = permissions_for_role("PLATFORM_ADMIN", {"remove": ["*"]})

    assert effective == []
    assert not permission_granted(
        role="PLATFORM_ADMIN",
        permissions=effective,
        required="users.manage",
        authoritative=True,
    )


def test_explicit_empty_session_snapshot_does_not_fall_back_to_role(monkeypatch):
    import services.enterprise_service as enterprise

    token = "explicit-empty-session"
    user = {
        "user_id": "legacy-user",
        "name": "Legacy User",
        "email": "legacy@example.com",
        "role": "admin_rag",
        "permission_overrides": {},
        "status": "active",
        "tenant_id": "default",
    }
    record = _session_record(token, role="admin_rag", permissions=[])
    _patch_session_store(monkeypatch, token, record, user)

    payload = enterprise.get_session(token)
    session = EnterpriseSession(**payload)

    assert payload["user"]["permissions"] == []
    assert not session_has_permission(session, "documents.upload")
    assert not session_has_permission(session, "users.manage")


def test_legacy_permission_snapshot_survives_current_user_change_until_invalidation(monkeypatch):
    import services.enterprise_service as enterprise

    token = "stable-snapshot-session"
    user = {
        "user_id": "legacy-user",
        "name": "Legacy User",
        "email": "legacy@example.com",
        "role": "viewer",
        "permission_overrides": {},
        "status": "active",
        "tenant_id": "default",
    }
    record = _session_record(token, role="viewer", permissions=["query.execute"])
    _patch_session_store(monkeypatch, token, record, user)

    first = enterprise.get_session(token)
    user["permission_overrides"] = {"add": ["documents.read"]}
    second = enterprise.get_session(token)

    assert first["user"]["permissions"] == ["chat.query"]
    assert second["user"]["permissions"] == ["chat.query"]
    assert not session_has_permission(EnterpriseSession(**second), "documents.read")

    user["role_changed_at"] = "2099-01-01T00:00:00Z"
    invalidated = enterprise.get_session(token)
    assert invalidated["authenticated"] is False
    assert invalidated["session_state"] == "expired"


def test_legacy_session_without_snapshot_is_migrated_once_and_then_stable(monkeypatch):
    import services.enterprise_service as enterprise

    token = "migrated-legacy-session"
    user = {
        "user_id": "legacy-user",
        "name": "Legacy User",
        "email": "legacy@example.com",
        "role": "viewer",
        "permission_overrides": {},
        "status": "active",
        "tenant_id": "default",
        "authorized_collection_ids": ["rag_phase0"],
    }
    record = {
        "session_token": token,
        "user_id": "legacy-user",
        "tenant_id": "default",
        "role_snapshot": "viewer",
        "created_at": "2026-08-30T00:00:00Z",
        "last_seen_at": "2026-08-30T00:01:00Z",
        "expires_at": "2099-01-01T00:00:00Z",
        "revoked_at": None,
        "revoked_reason": None,
    }
    captured: list[dict] = []
    stored = {"sessions": {token: dict(record)}}
    _patch_session_store(monkeypatch, token, record, user)
    monkeypatch.setattr(
        enterprise,
        "update_session_state",
        lambda mutator: (captured.append(mutator(stored)), stored)[1],
    )

    first = enterprise.get_session(token)
    expected_permissions = permissions_for_role("viewer")
    assert first["user"]["permissions"] == expected_permissions
    migrated = captured[-1]["sessions"][token]
    assert migrated["permissions_snapshot"] == expected_permissions
    assert migrated["authorized_collection_ids_snapshot"] == ["rag_phase0"]

    user["permission_overrides"] = {"add": ["documents.read"]}
    user["authorized_collection_ids"] = ["other-collection"]
    second = enterprise.get_session(token)
    assert second["user"]["permissions"] == expected_permissions
    assert second["user"]["authorized_collection_ids"] == ["rag_phase0"]


@pytest.mark.parametrize("marker", ["password_changed_at", "status_changed_at", "role_changed_at"])
def test_malformed_lifecycle_timestamp_revokes_session(monkeypatch, marker):
    import services.enterprise_service as enterprise

    token = f"malformed-{marker}"
    user = {
        "user_id": "legacy-user",
        "name": "Legacy User",
        "email": "legacy@example.com",
        "role": "viewer",
        "permission_overrides": {},
        "status": "active",
        "tenant_id": "default",
        marker: "not-a-timestamp",
    }
    record = _session_record(token, permissions=["chat.query"])
    _patch_session_store(monkeypatch, token, record, user)

    payload = enterprise.get_session(token)
    assert payload["authenticated"] is False
    assert payload["session_state"] == "expired"


def _login_headers(client: TestClient, email: str) -> dict[str, str]:
    response = client.post(
        "/auth/login",
        json={"email": email, "password": "demo1234", "tenant_id": "default"},
    )
    assert response.status_code == 200, response.text
    token = response.cookies.get(SESSION_COOKIE_NAME)
    assert token
    return {"Authorization": f"Bearer {token}"}


def test_veterinarian_and_knowledge_manager_matrix_and_route_acl_denials():
    veterinarian = set(permissions_for_role("VETERINARIAN"))
    assert veterinarian == {"chat.query", "history.read", "sources.read", "collections.read"}
    assert "library.browse" not in veterinarian
    assert "documents.read" not in veterinarian

    knowledge_manager = set(permissions_for_role("KNOWLEDGE_MANAGER"))
    assert {
        "library.browse",
        "documents.read",
        "documents.manage",
        "documents.upload",
        "ingestion.run",
        "collections.read",
        "collections.manage",
    } <= knowledge_manager

    source_only = _session(permissions=["sources.read"], grants=["rag_phase0"])
    with pytest.raises(HTTPException) as source_error:
        require_permission(source_only, "documents.read")
    assert source_error.value.status_code == 403

    query_without_sources = _session(permissions=["chat.query"], grants=["rag_phase0"])
    with pytest.raises(HTTPException) as sources_error:
        build_retrieval_context(
            query_without_sources,
            workspace_id="default",
            collection_id="rag_phase0",
            require_sources=True,
        )
    assert sources_error.value.status_code == 403

    with pytest.raises(HTTPException) as acl_error:
        build_retrieval_context(
            source_only,
            workspace_id="default",
            collection_id="other-collection",
        )
    assert acl_error.value.status_code == 403

    filtered = _filter_document_response_items(
        {
            "items": [
                {"document_id": "allowed", "collection_id": "rag_phase0"},
                {"document_id": "blocked", "collection_id": "other-collection"},
            ],
            "total": 2,
        },
        # Source visibility never widens the collection ACL.
        type("Context", (), {"allowed_collection_ids": ["rag_phase0"]})(),
        limit=50,
        offset=0,
    )
    assert [item["document_id"] for item in filtered["items"]] == ["allowed"]

    client = TestClient(app)
    viewer_headers = _login_headers(client, "viewer@demo.local")
    documents = client.get("/documents?workspace_id=default", headers=viewer_headers)
    assert documents.status_code == 403, documents.text
    foreign_search = client.post(
        "/search",
        json={"query": "acl", "workspace_id": "default", "collection_id": "other-collection"},
        headers=viewer_headers,
    )
    assert foreign_search.status_code == 403, foreign_search.text
    admin_users = client.get("/admin/users", headers=viewer_headers)
    assert admin_users.status_code == 403, admin_users.text
