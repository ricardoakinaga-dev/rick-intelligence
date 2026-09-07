"""Canonical identity runtime tests: lifecycle, authority, migration, mode gating."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "authorization" / "src"))

import pytest

from rick_authorization import permission_granted
from rick_identity import (
    IdentityError,
    IdentityProviderImpl,
    InMemorySessionStore,
    InMemoryUserStore,
    Pbkdf2Verifier,
    PlainTestVerifier,
    hash_password,
    verify_password_hash,
)


def make_provider(**user_overrides):
    users = InMemoryUserStore()
    record = {"user_id": "u1", "email": "u1@example.com", "role": "VETERINARIAN",
              "tenant_id": "default", "workspace_id": "default", "status": "active",
              "permission_overrides": {"add": [], "remove": []},
              "authorized_collection_ids": ["rag_phase0"],
              "password_plain": "secret-pw", "password_version": 1, "role_version": 1}
    record.update(user_overrides)
    users.seed(record)
    return IdentityProviderImpl(users=users, sessions=InMemorySessionStore(), verifier=PlainTestVerifier()), users


def test_login_snapshot_is_authoritative():
    provider, _ = make_provider()
    issued = provider.login(email="u1@example.com", password="secret-pw", tenant_id="default", ip=None, user_agent=None)
    snap = provider.validate_session(issued["session_token"])
    assert snap["authenticated"] and snap["authorization_state"] == "AUTHORITATIVE"
    assert snap["permissions"] == ["chat.query", "collections.read", "history.read", "sources.read"]
    assert not permission_granted(role=None, permissions=snap["permissions"],
                                  required="documents.read", authoritative=True)


def test_wrong_password_and_disabled():
    provider, users = make_provider()
    with pytest.raises(IdentityError):
        provider.login(email="u1@example.com", password="nope", tenant_id="default", ip=None, user_agent=None)
    user = users.get_by_id("u1")
    user["status"] = "disabled"
    users.save(user)
    with pytest.raises(IdentityError):
        provider.login(email="u1@example.com", password="secret-pw", tenant_id="default", ip=None, user_agent=None)


def test_logout_expiry_revoke():
    provider, _ = make_provider()
    token = provider.login(email="u1@example.com", password="secret-pw", tenant_id="default", ip=None, user_agent=None)["session_token"]
    assert provider.validate_session(token)["authenticated"]
    provider.logout(token)
    assert not provider.validate_session(token)["authenticated"]

    provider2, _ = make_provider()
    provider2.sessions.ttl_seconds = -1
    token2 = provider2.login(email="u1@example.com", password="secret-pw", tenant_id="default", ip=None, user_agent=None)["session_token"]
    assert not provider2.validate_session(token2)["authenticated"]

    provider3, _ = make_provider()
    token3 = provider3.login(email="u1@example.com", password="secret-pw", tenant_id="default", ip=None, user_agent=None)["session_token"]
    assert provider3.revoke_session(token3) == 1
    assert provider3.revoke_session(token3) == 0


def test_session_touch_slides_expiry_with_the_configured_idle_ttl() -> None:
    sessions = InMemorySessionStore(ttl_seconds=120)
    token = sessions.create({"user_id": "u1", "tenant_id": "tenant-1"})
    record = sessions.get(token)
    assert record is not None
    original_expiry = record["expires_at"]

    time.sleep(0.001)
    sessions.touch(token)

    refreshed = sessions.get(token)
    assert refreshed is not None
    assert refreshed["last_seen_at"] >= record["created_at"]
    assert refreshed["expires_at"] > original_expiry


def test_password_and_role_change_invalidate():
    provider, users = make_provider()
    token = provider.login(email="u1@example.com", password="secret-pw", tenant_id="default", ip=None, user_agent=None)["session_token"]
    user = users.get_by_id("u1")
    user["password_version"] = 2
    users.save(user)
    assert not provider.validate_session(token)["authenticated"]

    provider2, users2 = make_provider()
    token2 = provider2.login(email="u1@example.com", password="secret-pw", tenant_id="default", ip=None, user_agent=None)["session_token"]
    user2 = users2.get_by_id("u1")
    user2["role_version"] = 2
    users2.save(user2)
    assert not provider2.validate_session(token2)["authenticated"]


def test_removed_permission_never_restored_on_refresh():
    users = InMemoryUserStore()
    users.seed({"user_id": "k", "email": "k@example.com", "role": "KNOWLEDGE_MANAGER",
                "tenant_id": "default", "workspace_id": "default", "status": "active",
                "permission_overrides": {"add": [], "remove": ["documents.read"]},
                "authorized_collection_ids": [], "password_plain": "pw",
                "password_version": 1, "role_version": 1})
    provider = IdentityProviderImpl(users=users, sessions=InMemorySessionStore(), verifier=PlainTestVerifier())
    token = provider.login(email="k@example.com", password="pw", tenant_id="default", ip=None, user_agent=None)["session_token"]
    for _ in range(3):  # refresh must not restore the removal
        snap = provider.validate_session(token)
        assert "documents.read" not in snap["permissions"]
        assert not permission_granted(role=None, permissions=snap["permissions"],
                                      required="documents.read", authoritative=True)


def test_legacy_migration_is_one_time():
    provider, users = make_provider()
    token = provider.login(email="u1@example.com", password="secret-pw", tenant_id="default", ip=None, user_agent=None)["session_token"]
    record = provider.sessions.get(token)
    # Simulate a pre-migration record: strip snapshot fields.
    for key in ("permissions", "authorization_state", "canonical_role"):
        record.pop(key, None)
    record["authorization_state"] = "LEGACY_UNMIGRATED"
    snap = provider.validate_session(token)
    assert snap["authorization_state"] == "MIGRATED"
    assert snap["permissions"] == ["chat.query", "collections.read", "history.read", "sources.read"]
    snap2 = provider.validate_session(token)
    assert snap2["authorization_state"] == "MIGRATED"  # stable, not re-derived widening


def test_pbkdf2_roundtrip_and_user_redaction():
    hashed = hash_password("correct horse")
    assert verify_password_hash(hashed, "correct horse")
    assert not verify_password_hash(hashed, "wrong")
    provider, _ = make_provider()
    assert "password_plain" not in provider.get_user("u1")


def test_tenant_binding_is_explicit_and_fail_closed():
    provider, _ = make_provider(tenant_id="tenant-a")
    with pytest.raises(IdentityError):
        provider.login(
            email="u1@example.com", password="secret-pw", tenant_id="default", ip=None, user_agent=None
        )
    with pytest.raises(IdentityError):
        provider.login(
            email="u1@example.com", password="secret-pw", tenant_id=None, ip=None, user_agent=None
        )

    provider_without_tenant, _ = make_provider(tenant_id=None)
    with pytest.raises(IdentityError):
        provider_without_tenant.login(
            email="u1@example.com", password="secret-pw", tenant_id="default", ip=None, user_agent=None
        )


def test_session_tenant_binding_is_revalidated_on_every_refresh():
    provider, users = make_provider(tenant_id="tenant-a")
    token = provider.login(
        email="u1@example.com", password="secret-pw", tenant_id="tenant-a", ip=None, user_agent=None
    )["session_token"]
    user = users.get_by_id("u1")
    user["tenant_id"] = "tenant-b"
    users.save(user)

    assert not provider.validate_session(token)["authenticated"]
