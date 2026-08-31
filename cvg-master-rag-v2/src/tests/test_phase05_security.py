import io

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient

from api.main import app
from models.schemas import EnterpriseSession, EnterpriseTenant, EnterpriseUser, RetrievalContext
from services.authorization import allowed_collection_ids_for_user, canonical_role, permission_granted
from services.enterprise_service import SESSION_COOKIE_NAME, bootstrap_session
from services.upload_security import prepare_upload_filename


@pytest.mark.parametrize(
    "filename",
    ["../escape.txt", "..\\escape.txt", "/tmp/escape.txt", "C:\\tmp\\escape.txt", "a/b.txt", "a\\b.txt", "bad\x00.txt"],
)
def test_upload_filename_rejects_path_injection(filename):
    with pytest.raises(ValueError):
        prepare_upload_filename(filename)


def test_upload_filename_uses_generated_collision_resistant_storage_name():
    display_a, storage_a = prepare_upload_filename("relatório clínico.txt")
    display_b, storage_b = prepare_upload_filename("relatório clínico.txt")
    assert display_a == display_b == "relatório clínico.txt"
    assert storage_a.endswith(".txt")
    assert storage_b.endswith(".txt")
    assert storage_a != storage_b
    assert storage_a.startswith("upload-")


def test_anonymous_bootstrap_does_not_enumerate_tenants():
    payload = bootstrap_session()
    assert payload["authenticated"] is False
    assert payload["available_tenants"] == []


def test_canonical_roles_and_collection_grants_are_explicit():
    assert canonical_role("admin_rag") == "KNOWLEDGE_MANAGER"
    assert canonical_role("viewer") == "VETERINARIAN"
    assert canonical_role("admin") == "PLATFORM_ADMIN"
    assert allowed_collection_ids_for_user({"role": "viewer"}) == ["rag_phase0"]
    assert allowed_collection_ids_for_user({"role": "viewer", "authorized_collection_ids": ["cvg_master_rag"]}) == ["rag_phase0"]
    assert permission_granted(role="admin_rag", permissions=[], required="documents.upload") is True
    assert permission_granted(role="admin_rag", permissions=[], required="users.manage") is False


def _session(*, role="viewer", grants=None, workspace="default"):
    tenant = EnterpriseTenant(
        tenant_id=workspace,
        name=workspace,
        workspace_id=workspace,
        plan="enterprise",
        status="active",
    )
    user = EnterpriseUser(
        user_id="user-1",
        name="User",
        email="user@example.com",
        role=role,
        permissions=["documents.read"],
        authorized_collection_ids=grants or [],
    )
    return EnterpriseSession(
        authenticated=True,
        session_state="active",
        session_token="opaque-session",
        user=user,
        active_tenant=tenant,
        available_tenants=[tenant],
    )


def test_retrieval_context_rejects_cross_workspace_and_collection_access():
    from services.api_security import build_retrieval_context

    session = _session(grants=["collection_a"])
    context = build_retrieval_context(session, workspace_id="default", collection_id="collection_a")
    assert context.allowed_collection_ids == ["collection_a"]
    with pytest.raises(HTTPException) as collection_error:
        build_retrieval_context(session, workspace_id="default", collection_id="collection_b")
    assert collection_error.value.status_code == 403
    with pytest.raises(HTTPException) as workspace_error:
        build_retrieval_context(session, workspace_id="other", collection_id="collection_a")
    assert workspace_error.value.status_code == 403


def test_session_listing_uses_opaque_identifier_without_exposing_bearer(monkeypatch):
    import services.enterprise_service as enterprise

    bearer = "server-only-bearer"
    monkeypatch.setattr(
        enterprise,
        "_load_sessions",
        lambda: {
            bearer: {
                "session_token": bearer,
                "user_id": "user-1",
                "tenant_id": "default",
                "role_snapshot": "viewer",
                "permissions_snapshot": ["query.execute"],
                "created_at": "2026-08-31T00:00:00Z",
                "last_seen_at": "2026-08-31T00:01:00Z",
                "expires_at": "2026-08-31T01:00:00Z",
                "revoked_at": None,
                "revoked_reason": None,
            }
        },
    )

    item = enterprise.list_sessions_for_user("user-1")[0]
    assert item["session_token"] is None
    assert item["session_id"] == enterprise.session_identifier(bearer)
    assert enterprise.session_token_for_identifier(item["session_id"]) == bearer
    assert enterprise.session_token_for_identifier("not-a-session-id") is None


def test_workspace_scoped_observability_requires_an_active_session():
    from services.api_security import resolve_workspace_scope

    with pytest.raises(HTTPException) as error:
        resolve_workspace_scope("default", bootstrap_session(), required_permission="observability.read")
    assert error.value.status_code == 401


def test_http_session_contract_is_cookie_only_and_switch_rotates_cookie():
    client = TestClient(app)
    login = client.post(
        "/auth/login",
        json={"email": "admin@demo.local", "password": "demo1234", "tenant_id": "default"},
    )
    assert login.status_code == 200, login.text
    assert login.json()["session_token"] is None
    bearer = login.cookies.get(SESSION_COOKIE_NAME)
    assert bearer

    for path in ("/session", "/auth/me"):
        response = client.get(path, headers={"Authorization": f"Bearer {bearer}"})
        assert response.status_code == 200, response.text
        assert response.json()["session_token"] is None

    switched = client.post(
        "/auth/switch-tenant",
        json={"tenant_id": "acme-lab"},
        headers={"Authorization": f"Bearer {bearer}"},
    )
    assert switched.status_code == 200, switched.text
    assert switched.json()["session_token"] is None
    assert switched.cookies.get(SESSION_COOKIE_NAME)


def test_knowledge_manager_cannot_target_a_foreign_admin_workspace():
    client = TestClient(app)
    login = client.post(
        "/auth/login",
        json={"email": "operator@demo.local", "password": "demo1234", "tenant_id": "default"},
    )
    assert login.status_code == 200, login.text
    bearer = login.cookies.get(SESSION_COOKIE_NAME)
    assert bearer
    headers = {"Authorization": f"Bearer {bearer}"}

    response = client.get("/admin/audits?workspace_id=acme-lab", headers=headers)
    assert response.status_code == 403, response.text
    response = client.post("/admin/corpus/audit?workspace_id=acme-lab", headers=headers)
    assert response.status_code == 403, response.text
