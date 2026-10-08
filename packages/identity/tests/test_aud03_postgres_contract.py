"""DB-API contract fixtures; no live PostgreSQL or production credentials."""

import copy
import json
import time

import pytest

from rick_identity import IdentityProviderImpl, InMemoryUserStore, PlainTestVerifier, PostgresSessionStore
from rick_identity.postgres import PostgresIdentityError


class Database:
    def __init__(self, *, stale=False, fail=False):
        self.stale = stale
        self.fail = fail
        self.migration_writes = 0
        self.commits = 0
        self.rollbacks = 0
        self.row = {"session_id": "s", "user_id": "u", "tenant_id": "t", "workspace_id": "w",
                    "password_version": 1, "role_version": 1, "expires_at": time.time() + 600,
                    "authorization_snapshot": {"role": "super_admin", "authorization_state": "LEGACY_UNMIGRATED"}}

    def connect(self):
        return Connection(self)


class Connection:
    def __init__(self, db):
        self.db = db

    def cursor(self):
        return Cursor(self.db)

    def commit(self):
        self.db.commits += 1

    def rollback(self):
        self.db.rollbacks += 1

    def close(self):
        pass


class Cursor:
    def __init__(self, db):
        self.db = db
        self.rowcount = 0
        self.rows = []

    def execute(self, query, params):
        if query.startswith("SELECT"):
            self.rows = [copy.deepcopy(self.db.row)]
        elif "INSERT INTO rick_sessions" in query:
            session_id, token_hash, tenant, user, workspace, snapshot, password_version, role_version, created, seen, expires = params
            self.db.row = {"session_id": session_id, "token_hash": token_hash, "tenant_id": tenant,
                "user_id": user, "workspace_id": workspace, "authorization_snapshot": json.loads(snapshot),
                "password_version": password_version, "role_version": role_version,
                "created_at": created, "last_seen_at": seen, "expires_at": expires}
        elif "SET authorization_snapshot" in query:
            # Check the adapter's conditional-write contract at its SQL boundary.
            assert "revoked_at IS NULL" in query
            assert "expires_at > NOW()" in query
            assert "authorization_snapshot = CAST(%s AS jsonb)" in query
            assert "AND password_version = %s AND role_version = %s" in query
            if self.db.fail:
                raise RuntimeError("synthetic write failure")
            new_snapshot, token_hash, old_snapshot, password_version, role_version = params
            assert token_hash == self.db.row.get("token_hash", PostgresSessionStore._token_hash("synthetic"))
            if (not self.db.stale and json.loads(old_snapshot) == self.db.row["authorization_snapshot"]
                    and password_version == self.db.row["password_version"]
                    and role_version == self.db.row["role_version"]):
                self.db.row["authorization_snapshot"] = json.loads(new_snapshot)
                self.db.migration_writes += 1
                self.rowcount = 1
        elif "SET last_seen_at" in query:
            self.rowcount = 1
        else:
            raise AssertionError(query)

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def close(self):
        pass


def provider(db):
    users = InMemoryUserStore()
    users.seed({"user_id": "u", "email": "u@example.test", "role": "PLATFORM_ADMIN", "tenant_id": "t",
                "workspace_id": "w", "status": "active", "authorized_collection_ids": [],
                "password_version": 1, "role_version": 1})
    return IdentityProviderImpl(users=users, sessions=PostgresSessionStore(db.connect), verifier=PlainTestVerifier())


def test_postgres_legacy_migration_persists_exactly_once_and_reloads_without_widening():
    db = Database()
    runtime = provider(db)
    snapshot = runtime.validate_session("synthetic")
    assert snapshot["authenticated"]
    assert snapshot["authorization_state"] == "MIGRATED"
    assert snapshot["allowed_collection_ids"] == []
    assert db.migration_writes == 1
    assert db.row["authorization_snapshot"]["permissions"] == ["*"]
    runtime.users.get_by_id("u")["permission_overrides"] = {"remove": ["*"]}
    runtime.sessions = PostgresSessionStore(db.connect)
    assert runtime.validate_session("synthetic")["permissions"] == []
    # Runtime authority narrows, while the one-time migrated ceiling is immutable.
    assert db.row["authorization_snapshot"]["permissions"] == ["*"]
    assert db.migration_writes == 1


def test_postgres_migration_source_changed_denies_without_returning_unpersisted_grants():
    db = Database(stale=True)
    assert not provider(db).validate_session("synthetic")["authenticated"]
    assert db.migration_writes == 0


def test_postgres_migration_write_failure_rolls_back_and_does_not_authenticate():
    db = Database(fail=True)
    with pytest.raises(PostgresIdentityError):
        provider(db).validate_session("synthetic")
    assert db.rollbacks == 1
    assert db.commits == 0
    assert db.row["authorization_snapshot"]["authorization_state"] == "LEGACY_UNMIGRATED"


@pytest.mark.parametrize("state", ["AUTHORITATIVE", "MIGRATED"])
@pytest.mark.parametrize("permissions", [[], ["chat.query"], ["*"]])
def test_postgres_modern_snapshots_keep_exact_permission_and_collection_lists(state, permissions):
    db = Database()
    db.row["authorization_snapshot"] = {"role": "super_admin", "canonical_role": "PLATFORM_ADMIN",
        "authorization_state": state, "authorization_snapshot_version": 1,
        "permissions": permissions, "allowed_collection_ids": []}
    snapshot = provider(db).validate_session("synthetic")
    assert snapshot["authenticated"]
    assert snapshot["permissions"] == permissions
    assert snapshot["allowed_collection_ids"] == []
    assert db.migration_writes == 0


def test_postgres_legacy_marker_cannot_relabel_existing_permissions():
    db = Database()
    db.row["authorization_snapshot"]["permissions"] = []
    assert not provider(db).validate_session("synthetic")["authenticated"]
    assert db.migration_writes == 0
