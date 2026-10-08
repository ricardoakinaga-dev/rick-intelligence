from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import create_app
from conftest import login_as, make_settings
from core.errors import ApiError


def _seed_user(identity, *, user_id: str, email: str, role: str, workspace_id: str) -> dict:
    record = {
        "user_id": user_id,
        "email": email,
        "role": role,
        "tenant_id": "default",
        "workspace_id": workspace_id,
        "status": "active",
        "membership_status": "active",
        "permission_overrides": {"add": [], "remove": []},
        "authorized_collection_ids": [],
        "password_plain": "password123",
        "password_version": 1,
        "role_version": 1,
    }
    identity._users.seed(record)
    return record


@pytest.mark.parametrize("operation", ["update", "deactivate", "reset"])
def test_volatile_admin_mutations_reject_same_tenant_other_workspace(operation):
    client = TestClient(create_app(make_settings()), raise_server_exceptions=False)
    login_as(client, "admin@example.com")
    identity = client.app.state.providers.identity
    before = deepcopy(_seed_user(
        identity,
        user_id="workspace-b-user",
        email="workspace-b@example.test",
        role="VETERINARIAN",
        workspace_id="workspace-b",
    ))

    if operation == "update":
        response = client.patch(
            "/api/v1/admin/users/workspace-b-user",
            json={"email": "changed@example.test"},
        )
    elif operation == "deactivate":
        response = client.post("/api/v1/admin/users/workspace-b-user/deactivate")
    else:
        response = client.post(
            "/api/v1/admin/users/workspace-b-user/reset-password",
            json={"password": "new-private-password"},
        )

    assert response.status_code == 403, response.text
    assert identity._users.get_by_id("workspace-b-user") == before


@pytest.mark.parametrize("operation", ["update", "deactivate", "reset"])
def test_admin_route_rejects_foreign_target_before_provider_mutation(operation, monkeypatch):
    client = TestClient(create_app(make_settings()), raise_server_exceptions=False)
    login_as(client, "admin@example.com")
    providers = client.app.state.providers
    identity = providers.identity
    _seed_user(
        identity,
        user_id="foreign-target",
        email="foreign-target@example.test",
        role="VETERINARIAN",
        workspace_id="workspace-b",
    )

    def unsafe_mutation(**_kwargs):
        raise AssertionError("foreign target reached provider mutation")

    method = {"update": "update_user", "deactivate": "deactivate_user", "reset": "reset_password"}[operation]
    monkeypatch.setattr(identity, method, unsafe_mutation)
    events_before = len(providers.audit_sink.events)
    if operation == "update":
        response = client.patch("/api/v1/admin/users/foreign-target", json={"email": "changed@example.test"})
    elif operation == "deactivate":
        response = client.post("/api/v1/admin/users/foreign-target/deactivate")
    else:
        response = client.post(
            "/api/v1/admin/users/foreign-target/reset-password",
            json={"password": "new-private-password"},
        )

    assert response.status_code == 403, response.text
    assert len(providers.audit_sink.events) == events_before


@pytest.mark.parametrize("workspace_id", ["default", "workspace-a"])
def test_volatile_admin_create_uses_actor_workspace(workspace_id):
    client = TestClient(create_app(make_settings()), raise_server_exceptions=False)
    email = "admin@example.com"
    if workspace_id != "default":
        _seed_user(
            client.app.state.providers.identity,
            user_id="workspace-a-admin",
            email="workspace-a-admin@example.test",
            role="PLATFORM_ADMIN",
            workspace_id=workspace_id,
        )
        email = "workspace-a-admin@example.test"
    login_as(client, email)

    response = client.post("/api/v1/admin/users", json={
        "email": "workspace-created@example.test",
        "role": "VETERINARIAN",
        "tenant_id": "default",
        "password": "private-password",
    })

    assert response.status_code == 201, response.text
    created_id = response.json()["user"]["user_id"]
    created = client.app.state.providers.identity._users.get_by_id(created_id)
    assert created is not None
    assert created["tenant_id"] == "default"
    assert created["workspace_id"] == workspace_id


@pytest.mark.parametrize("operation", ["demote", "deactivate"])
def test_volatile_admin_protects_last_active_admin_per_workspace(operation):
    client = TestClient(create_app(make_settings()), raise_server_exceptions=False)
    login_as(client, "admin@example.com")
    identity = client.app.state.providers.identity
    original = deepcopy(identity._users.get_by_id("admin"))
    _seed_user(
        identity,
        user_id="sibling-workspace-admin",
        email="sibling-admin@example.test",
        role="PLATFORM_ADMIN",
        workspace_id="workspace-b",
    )

    blocked = (
        client.patch("/api/v1/admin/users/admin", json={"role": "VETERINARIAN"})
        if operation == "demote"
        else client.post("/api/v1/admin/users/admin/deactivate")
    )

    assert blocked.status_code == 409, blocked.text
    assert identity._users.get_by_id("admin") == original

    _seed_user(
        identity,
        user_id="second-default-admin",
        email="second-admin@example.test",
        role="PLATFORM_ADMIN",
        workspace_id="default",
    )
    allowed = (
        client.patch("/api/v1/admin/users/admin", json={"role": "VETERINARIAN"})
        if operation == "demote"
        else client.post("/api/v1/admin/users/admin/deactivate")
    )

    assert allowed.status_code == 200, allowed.text
    if operation == "demote":
        assert identity._users.get_by_id("admin")["role"] == "VETERINARIAN"
    else:
        assert identity._users.get_by_id("admin")["membership_status"] == "disabled"


def test_volatile_concurrent_admin_demotions_cannot_remove_both_last_admins():
    client = TestClient(create_app(make_settings()), raise_server_exceptions=False)
    identity = client.app.state.providers.identity
    _seed_user(
        identity,
        user_id="concurrent-admin-a",
        email="concurrent-admin-a@example.test",
        role="PLATFORM_ADMIN",
        workspace_id="workspace-race",
    )
    _seed_user(
        identity,
        user_id="concurrent-admin-b",
        email="concurrent-admin-b@example.test",
        role="PLATFORM_ADMIN",
        workspace_id="workspace-race",
    )
    actor = SimpleNamespace(tenant_id="default", workspace_id="workspace-race")
    start = Barrier(3)

    def demote(user_id):
        start.wait(timeout=5)
        try:
            identity.update_user(actor=actor, user_id=user_id, role="VETERINARIAN")
            return "updated"
        except ApiError as exc:
            if exc.code == "conflict":
                return "conflict"
            raise

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(demote, "concurrent-admin-a"),
            pool.submit(demote, "concurrent-admin-b"),
        ]
        start.wait(timeout=5)
        outcomes = [future.result(timeout=5) for future in futures]

    assert sorted(outcomes) == ["conflict", "updated"]
    assert sum(
        identity._users.get_by_id(user_id)["role"] == "PLATFORM_ADMIN"
        for user_id in ("concurrent-admin-a", "concurrent-admin-b")
    ) == 1


def test_volatile_deactivation_disables_membership_and_revokes_only_its_workspace():
    client = TestClient(create_app(make_settings()), raise_server_exceptions=False)
    identity = client.app.state.providers.identity
    target = _seed_user(
        identity,
        user_id="workspace-a-user",
        email="workspace-a@example.test",
        role="VETERINARIAN",
        workspace_id="default",
    )
    login = identity.login(
        email=target["email"],
        password="password123",
        tenant_id="default",
        ip=None,
        user_agent=None,
    )
    own_token = login["session_token"]
    foreign_scope_token = identity._sessions.create({
        "user_id": target["user_id"],
        "email": target["email"],
        "role": "VETERINARIAN",
        "canonical_role": "VETERINARIAN",
        "permissions": [],
        "authorization_snapshot_version": 1,
        "authorization_state": "AUTHORITATIVE",
        "allowed_collection_ids": [],
        "tenant_id": "default",
        "workspace_id": "sibling-workspace",
        "password_version": 1,
        "role_version": 1,
    })
    login_as(client, "admin@example.com")
    actor = SimpleNamespace(tenant_id="default", workspace_id="default")

    revoked = identity.deactivate_user(actor=actor, user_id=target["user_id"])

    assert revoked == 1
    updated = identity._users.get_by_id(target["user_id"])
    assert updated["status"] == "active"
    assert updated["membership_status"] == "disabled"
    assert identity._sessions.get(own_token) is None
    assert identity._sessions.get(foreign_scope_token)["revoked_at"] is None
    assert identity.validate_token(foreign_scope_token).authenticated is False
    listed = client.get("/api/v1/admin/users")
    assert listed.status_code == 200, listed.text
    target_view = next(item for item in listed.json()["items"] if item["user_id"] == target["user_id"])
    assert target_view["status"] == "active"
    assert target_view["membership_status"] == "disabled"


def test_volatile_admin_cannot_move_a_user_to_another_workspace():
    client = TestClient(create_app(make_settings()), raise_server_exceptions=False)
    login_as(client, "admin@example.com")
    identity = client.app.state.providers.identity
    before = deepcopy(identity._users.get_by_id("vet"))

    response = client.patch(
        "/api/v1/admin/users/vet",
        json={"workspace_id": "workspace-b"},
    )

    assert response.status_code == 403, response.text
    assert identity._users.get_by_id("vet") == before
