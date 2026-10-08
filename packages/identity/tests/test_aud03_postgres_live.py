"""Opt-in disposable PostgreSQL adapter checks, run centrally by the Lead.

Set RICK_AUD03_IDENTITY_POSTGRES_DSN to an authorized disposable lab DSN.
Every test creates/removes its own random schema; no existing schema is used.
"""

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import re
from threading import Barrier
import uuid
import time

import pytest

from rick_identity import (
    IdentityProviderImpl, OIDCIdentityProvider, OIDCSettings, OIDCVerifier,
    Pbkdf2Verifier, PostgresSessionStore, PostgresUserStore, hash_password,
)


@pytest.fixture
def lab():
    dsn = os.environ.get("RICK_AUD03_IDENTITY_POSTGRES_DSN")
    if not dsn:
        pytest.skip("NOT_RUN: Lead must supply the private disposable PostgreSQL lab DSN")
    import psycopg
    from psycopg import sql

    schema = "aud03_identity_" + uuid.uuid4().hex
    with psycopg.connect(dsn) as db:
        db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))

    def connect():
        return psycopg.connect(dsn, options=f"-c search_path={schema} -c statement_timeout=10000")

    try:
        # Use the actual canonical table definitions and contract additions.
        root = Path(__file__).resolve().parents[3]
        source = (root / "infrastructure/migrations/0002_product_schema.sql").read_text()
        with connect() as db:
            for table in ("rick_tenants", "rick_users", "rick_memberships", "rick_sessions"):
                ddl = re.search(rf"CREATE TABLE IF NOT EXISTS {table} \(.*?\n\);", source, re.S)
                assert ddl is not None
                db.execute(ddl.group())
            db.execute("ALTER TABLE rick_users ADD COLUMN password_hash TEXT")
            db.execute("ALTER TABLE rick_memberships ADD COLUMN authorized_collection_ids JSONB NOT NULL DEFAULT '[]'::jsonb")
            db.execute("INSERT INTO rick_tenants (tenant_id, display_name) VALUES ('t', 'Synthetic AUD03 tenant')")
        yield connect
    finally:
        with psycopg.connect(dsn) as db:
            db.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def runtime(connect, role="PLATFORM_ADMIN", grants=None):
    users = PostgresUserStore(connect)
    users.save({"user_id": "u", "external_subject": "subject", "email": "u@example.test", "tenant_id": "t",
                "workspace_id": "w", "status": "active", "membership_status": "active", "role": role,
                "password_hash": hash_password("synthetic-password"), "authorized_collection_ids":
                ["*"] if grants is None else grants})
    return IdentityProviderImpl(users=users, sessions=PostgresSessionStore(connect), verifier=Pbkdf2Verifier())


def login(provider):
    return provider.login(email="u@example.test", password="synthetic-password", tenant_id="t",
                          ip=None, user_agent=None)["session_token"]


@pytest.mark.parametrize("role", ["KNOWLEDGE_MANAGER", "VETERINARIAN"])
def test_live_last_grant_removal_persists_across_provider_recreation(lab, role):
    provider = runtime(lab, role, ["allowed"])
    token = login(provider)
    assert provider.validate_session(token)["allowed_collection_ids"] == ["allowed"]
    user = provider.users.get_by_id_for_tenant_workspace("u", "t", "w")
    user["authorized_collection_ids"] = []
    user["role_version"] += 1
    provider.users.save(user)
    recreated = IdentityProviderImpl(users=PostgresUserStore(lab), sessions=PostgresSessionStore(lab), verifier=Pbkdf2Verifier())
    assert not recreated.validate_session(token)["authenticated"]
    snapshot = recreated.validate_session(login(recreated))
    assert snapshot["authenticated"]
    assert snapshot["allowed_collection_ids"] == []


@pytest.mark.parametrize("state", ["AUTHORITATIVE", "MIGRATED"])
def test_live_modern_missing_permissions_is_denied_without_rewriting_snapshot(lab, state):
    provider = runtime(lab)
    token = login(provider)
    with lab() as db:
        db.execute("UPDATE rick_sessions SET authorization_snapshot = (authorization_snapshot - 'permissions') || jsonb_build_object('authorization_state', %s::text)", (state,))
    assert not provider.validate_session(token)["authenticated"]
    with lab() as db:
        snapshot = db.execute("SELECT authorization_snapshot FROM rick_sessions").fetchone()[0]
    assert "permissions" not in snapshot
    assert snapshot["authorization_state"] == state


def test_live_concurrent_legacy_migrations_commit_one_snapshot(lab):
    provider = runtime(lab, grants=[])
    token = login(provider)
    with lab() as db:
        db.execute("UPDATE rick_sessions SET authorization_snapshot = '{\"role\":\"super_admin\",\"authorization_state\":\"LEGACY_UNMIGRATED\"}'::jsonb")
    barrier = Barrier(2)

    class SynchronizedSessions(PostgresSessionStore):
        def get(self, token):
            record = super().get(token)
            if record and record.get("authorization_state") == "LEGACY_UNMIGRATED":
                barrier.wait(timeout=10)
            return record

    def validate():
        candidate = IdentityProviderImpl(users=PostgresUserStore(lab), sessions=SynchronizedSessions(lab), verifier=Pbkdf2Verifier())
        return candidate.validate_session(token)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: validate(), range(2)))
    assert sorted(result["authenticated"] for result in results) == [False, True]
    winner = next(result for result in results if result["authenticated"])
    assert winner["allowed_collection_ids"] == []
    assert winner["authorization_state"] == "MIGRATED"
    user = provider.users.get_by_id_for_tenant_workspace("u", "t", "w")
    user["permission_overrides"] = {"remove": ["*"]}
    provider.users.save(user)
    assert provider.validate_session(token)["permissions"] == []
    assert provider.sessions.get(token)["permissions"] == winner["permissions"]


@pytest.mark.parametrize("terminal", ["revoked", "expired"])
def test_live_legacy_migration_fence_rejects_terminal_source(lab, terminal):
    provider = runtime(lab)
    token = login(provider)
    with lab() as db:
        db.execute("UPDATE rick_sessions SET authorization_snapshot = '{\"role\":\"super_admin\",\"authorization_state\":\"LEGACY_UNMIGRATED\"}'::jsonb")
    expected = provider.sessions.get(token)
    migrated = provider._migrate_legacy_record(expected, provider.users.get_by_id_for_tenant_workspace("u", "t", "w"))
    with lab() as db:
        db.execute("UPDATE rick_sessions SET revoked_at = NOW()" if terminal == "revoked"
                   else "UPDATE rick_sessions SET expires_at = NOW() - INTERVAL '1 second'")
    assert provider.sessions.update_authorization_snapshot(token, expected=expected, snapshot=migrated) is False
    assert not provider.validate_session(token)["authenticated"]


def test_live_oidc_resolver_uses_active_postgres_authority_with_explicit_empty_grants(lab):
    import jwt

    password_provider = runtime(lab, role="VETERINARIAN", grants=[])
    secret = "synthetic-aud03-live-oidc-secret-32-bytes"
    token = jwt.encode({"sub": "subject", "iss": "https://issuer.example", "aud": "test",
                        "exp": time.time() + 600, "tenant_id": "t", "role": "PLATFORM_ADMIN",
                        "workspace_id": "foreign"}, secret, algorithm="HS256", headers={"kid": "test"})
    verifier = OIDCVerifier(OIDCSettings(issuer="https://issuer.example", audience="test", algorithms=("HS256",)),
                            key_resolver=lambda kid: secret)

    def resolve(subject, claims, tenant):
        record = password_provider.users.get_by_id_for_tenant_workspace("u", tenant, "w")
        if record is None or record["external_subject"] != subject:
            return None
        return {**record, "subject": record["external_subject"]}

    provider = OIDCIdentityProvider(verifier, membership_resolver=resolve)
    snapshot = provider.validate_token(token)
    assert snapshot.authenticated
    assert snapshot.canonical_role == "VETERINARIAN"
    assert snapshot.workspace_id == "w"
    assert snapshot.allowed_collection_ids == []
    with lab() as db:
        db.execute("UPDATE rick_memberships SET status = 'disabled'")
    assert not provider.validate_token(token).authenticated


def test_live_rework_legacy_admin_session_migrates_only_current_veterinarian_authority(lab):
    provider = runtime(lab, role="VETERINARIAN", grants=[])
    token = provider.sessions.create({"user_id": "u", "tenant_id": "t", "workspace_id": "w",
        "role": "super_admin", "authorization_state": "LEGACY_UNMIGRATED", "allowed_collection_ids": [],
        "password_version": 1, "role_version": 1})
    for _ in range(2):
        snapshot = provider.validate_session(token)
        assert snapshot["authenticated"]
        assert snapshot["role"] == "viewer"
        assert snapshot["canonical_role"] == "VETERINARIAN"
        assert "*" not in snapshot["permissions"]
        assert "users.manage" not in snapshot["permissions"]
        assert snapshot["allowed_collection_ids"] == []
    with lab() as db:
        persisted = db.execute("SELECT authorization_snapshot FROM rick_sessions").fetchone()[0]
    assert persisted["canonical_role"] == "VETERINARIAN"
    assert persisted["role"] == "viewer"
    assert persisted["permissions"] == snapshot["permissions"]


@pytest.mark.parametrize("scope", [[], ["limited"]])
def test_live_rework_legacy_explicit_scope_caps_current_wildcard(lab, scope):
    provider = runtime(lab, role="KNOWLEDGE_MANAGER", grants=["*"])
    token = provider.sessions.create({"user_id": "u", "tenant_id": "t", "workspace_id": "w",
        "role": "admin_rag", "authorization_state": "LEGACY_UNMIGRATED", "allowed_collection_ids": scope,
        "password_version": 1, "role_version": 1})
    for _ in range(2):
        assert provider.validate_session(token)["allowed_collection_ids"] == scope
    assert provider.sessions.get(token)["allowed_collection_ids"] == scope


@pytest.mark.parametrize("role", ["KNOWLEDGE_MANAGER", "VETERINARIAN"])
@pytest.mark.parametrize("grants", [["allowed"], ["*"]])
def test_live_rework_same_token_revocation_without_version_bump_keeps_persisted_ceiling(lab, role, grants):
    provider = runtime(lab, role=role, grants=grants)
    token = login(provider)
    before = provider.sessions.get(token)
    user = provider.users.get_by_id_for_tenant_workspace("u", "t", "w")
    user["authorized_collection_ids"] = []
    provider.users.save(user)
    assert provider.users.get_by_id_for_tenant_workspace("u", "t", "w")["role_version"] == before["role_version"]
    for _ in range(2):
        snapshot = provider.validate_session(token)
        assert snapshot["authenticated"]
        assert snapshot["allowed_collection_ids"] == []
    after = PostgresSessionStore(lab).get(token)
    assert after["allowed_collection_ids"] == before["allowed_collection_ids"]
    assert after["permissions"] == before["permissions"]


def test_live_rework_legacy_role_promotion_requires_fresh_login(lab):
    provider = runtime(lab)
    token = provider.sessions.create({"user_id": "u", "tenant_id": "t", "workspace_id": "w",
        "role": "viewer", "authorization_state": "LEGACY_UNMIGRATED", "allowed_collection_ids": ["limited"],
        "password_version": 1, "role_version": 1})
    assert not provider.validate_session(token)["authenticated"]
    assert provider.sessions.get(token)["authorization_state"] == "LEGACY_UNMIGRATED"
    assert provider.validate_session(login(provider))["canonical_role"] == "PLATFORM_ADMIN"
