"""Discriminating regressions from independent I1 rejection of AUD03-02/05."""

import copy

import pytest

from rick_authorization import AuthorizationError, build_retrieval_context, can_access_collection, permission_granted
from rick_identity import IdentityProviderImpl, InMemorySessionStore, InMemoryUserStore, PlainTestVerifier, PostgresSessionStore
from packages.identity.tests.test_aud03_snapshots import SQLiteSessions, SQLiteUsers, login
from packages.identity.tests.test_aud03_postgres_contract import Database


@pytest.fixture(params=["memory", "sqlite", "postgres"])
def ports(request, tmp_path):
    db = None
    if request.param == "sqlite":
        users, sessions = SQLiteUsers(tmp_path / "users.db"), SQLiteSessions(tmp_path / "sessions.db")
    else:
        users = InMemoryUserStore()
        if request.param == "postgres":
            db = Database()
            sessions = PostgresSessionStore(db.connect)
        else:
            sessions = InMemorySessionStore()
    user = {"user_id": "u", "email": "u@example.test", "password_plain": "pw", "tenant_id": "t",
            "workspace_id": "w", "role": "VETERINARIAN", "status": "active", "membership_status": "active",
            "password_version": 1, "role_version": 1, "authorized_collection_ids": []}
    users.save(user)
    provider = IdentityProviderImpl(users=users, sessions=sessions, verifier=PlainTestVerifier())
    return provider, db


def legacy(provider, role, *, grants=(), omitted=False):
    record = {"user_id": "u", "tenant_id": "t", "workspace_id": "w", "role": role,
              "authorization_state": "LEGACY_UNMIGRATED", "password_version": 1, "role_version": 1}
    if not omitted:
        record["allowed_collection_ids"] = list(grants)
    return provider.sessions.create(record)


def test_legacy_admin_session_never_overrides_current_veterinarian(ports):
    provider, db = ports
    token = legacy(provider, "super_admin")
    for _ in range(2):
        snapshot = provider.validate_session(token)
        assert snapshot["authenticated"]
        assert snapshot["canonical_role"] == "VETERINARIAN"
        assert snapshot["role"] == "viewer"
        assert snapshot["allowed_collection_ids"] == []
        assert not permission_granted(permissions=snapshot["permissions"], required="users.manage", authoritative=True)
    persisted = provider.sessions.get(token)
    assert persisted["canonical_role"] == "VETERINARIAN"
    assert persisted["role"] == "viewer"
    assert "*" not in persisted["permissions"]
    if db:
        assert db.migration_writes == 1


@pytest.mark.parametrize("grants", [[], ["limited"]])
def test_legacy_session_explicit_scope_caps_omitted_user_grant_defaults(ports, grants):
    provider, _ = ports
    user = provider.users.get_by_id("u")
    user["role"] = "KNOWLEDGE_MANAGER"
    user.pop("authorized_collection_ids")
    provider.users.save(user)
    token = legacy(provider, "admin_rag", grants=grants)
    for _ in range(2):
        snapshot = provider.validate_session(token)
        assert snapshot["authenticated"]
        assert snapshot["allowed_collection_ids"] == grants
    assert provider.sessions.get(token)["allowed_collection_ids"] == grants


@pytest.mark.parametrize("role", ["KNOWLEDGE_MANAGER", "VETERINARIAN"])
@pytest.mark.parametrize("grants", [["allowed"], ["*"]])
def test_same_token_loses_collection_privileges_without_version_bump(ports, role, grants):
    provider, _ = ports
    user = provider.users.get_by_id("u")
    user.update(role=role, authorized_collection_ids=grants)
    provider.users.save(user)
    token = login(provider)
    assert provider.validate_session(token)["allowed_collection_ids"] == grants
    original = copy.deepcopy(provider.sessions.get(token))
    user["authorized_collection_ids"] = []
    provider.users.save(user)
    for _ in range(2):
        snapshot = provider.validate_session(token)
        assert snapshot["authenticated"]
        assert snapshot["allowed_collection_ids"] == []
        assert not can_access_collection(allowed=snapshot["allowed_collection_ids"], collection_id="allowed")
        with pytest.raises(AuthorizationError):
            build_retrieval_context(user_id="u", tenant_id="t", session_workspace="w", requested_workspace="w",
                allowed_collection_ids=snapshot["allowed_collection_ids"], permissions=snapshot["permissions"],
                role=role, requested_collection_id="allowed")
    persisted = provider.sessions.get(token)
    assert persisted["allowed_collection_ids"] == original["allowed_collection_ids"]
    assert persisted["authorization_state"] == "AUTHORITATIVE"
    assert persisted["permissions"] == original["permissions"]


def test_live_permission_removal_narrows_without_mutating_or_expanding_snapshot(ports):
    provider, _ = ports
    user = provider.users.get_by_id("u")
    user.update(role="KNOWLEDGE_MANAGER", authorized_collection_ids=["limited"],
                permission_overrides={"remove": ["documents.upload"]})
    provider.users.save(user)
    token = login(provider)
    original = copy.deepcopy(provider.sessions.get(token))
    user["authorized_collection_ids"] = ["*"]
    user["permission_overrides"] = {"add": ["users.manage"], "remove": ["documents.read"]}
    provider.users.save(user)
    snapshot = provider.validate_session(token)
    assert snapshot["authenticated"]
    assert "documents.read" not in snapshot["permissions"]
    assert "documents.upload" not in snapshot["permissions"]
    assert "users.manage" not in snapshot["permissions"]
    assert snapshot["allowed_collection_ids"] == ["limited"]
    persisted = provider.sessions.get(token)
    assert persisted["permissions"] == original["permissions"]
    assert persisted["allowed_collection_ids"] == original["allowed_collection_ids"]


def test_modern_role_change_without_version_bump_cannot_keep_admin_authority(ports):
    provider, _ = ports
    user = provider.users.get_by_id("u")
    user.update(role="PLATFORM_ADMIN", authorized_collection_ids=["*"])
    provider.users.save(user)
    token = login(provider)
    user.update(role="VETERINARIAN", authorized_collection_ids=[])
    provider.users.save(user)
    snapshot = provider.validate_session(token)
    assert not permission_granted(permissions=snapshot["permissions"], required="users.manage", authoritative=True)
    assert snapshot["canonical_role"] != "PLATFORM_ADMIN"


def test_legacy_role_promotion_requires_fresh_login(ports):
    provider, _ = ports
    user = provider.users.get_by_id("u")
    user.update(role="PLATFORM_ADMIN", authorized_collection_ids=["*"])
    provider.users.save(user)
    token = legacy(provider, "viewer", grants=["limited"])
    snapshot = provider.validate_session(token)
    assert not snapshot["authenticated"]
    assert provider.sessions.get(token)["authorization_state"] == "LEGACY_UNMIGRATED"
    assert provider.validate_session(login(provider))["canonical_role"] == "PLATFORM_ADMIN"


def test_legacy_omitted_session_scope_uses_current_authority_once(ports):
    provider, _ = ports
    user = provider.users.get_by_id("u")
    user.update(authorized_collection_ids=["allowed"])
    provider.users.save(user)
    token = legacy(provider, "viewer", omitted=True)
    snapshot = provider.validate_session(token)
    assert snapshot["authenticated"]
    assert snapshot["allowed_collection_ids"] == ["allowed"]
    assert provider.sessions.get(token)["authorization_state"] == "MIGRATED"
