import copy
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from rick_authorization import AuthorizationError, build_retrieval_context, can_access_collection
from rick_identity import IdentityProviderImpl, InMemorySessionStore, InMemoryUserStore, PlainTestVerifier, PostgresSessionStore
from services.authorization_service import refresh_context_from_user


class SQLiteSessions:
    """Detached, durable protocol fixture; SQLite is not a production adapter."""

    def __init__(self, path):
        self.path = path
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, record TEXT)")
        self.migrations = 0

    def create(self, record):
        token = "synthetic"
        record = {**record, "session_id": "s", "expires_at": time.time() + 600}
        self.save(token, record)
        return token

    def get(self, token):
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT record FROM sessions WHERE token = ?", (token,)).fetchone()
        return json.loads(row[0]) if row else None

    def save(self, token, record):
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT OR REPLACE INTO sessions VALUES (?, ?)", (token, json.dumps(record)))

    def touch(self, token):
        pass

    def update_authorization_snapshot(self, token, *, expected, snapshot):
        with sqlite3.connect(self.path) as db:
            result = db.execute("UPDATE sessions SET record = ? WHERE token = ? AND record = ?",
                                (json.dumps({**expected, **snapshot}), token, json.dumps(expected)))
        self.migrations += result.rowcount
        return result.rowcount == 1


class SQLiteUsers:
    """Durable user/grant protocol fixture with detached reads."""

    def __init__(self, path):
        self.path = path
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS users (user_id TEXT PRIMARY KEY, record TEXT)")

    def save(self, record):
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT OR REPLACE INTO users VALUES (?, ?)", (record["user_id"], json.dumps(record)))

    seed = save

    def get_by_id(self, user_id):
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT record FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def get_by_email_for_tenant(self, email, tenant_id):
        with sqlite3.connect(self.path) as db:
            records = [json.loads(row[0]) for row in db.execute("SELECT record FROM users")]
        return next((r for r in records if r["email"] == email and r["tenant_id"] == tenant_id), None)

    def get_by_id_for_tenant_workspace(self, user_id, tenant_id, workspace_id):
        record = self.get_by_id(user_id)
        return record if record and record["tenant_id"] == tenant_id and record["workspace_id"] == workspace_id else None


def provider_for(sessions, role="KNOWLEDGE_MANAGER", grants=None):
    users = SQLiteUsers(sessions.path.with_name("users.db")) if isinstance(sessions, SQLiteSessions) else InMemoryUserStore()
    users.seed({"user_id": "u", "email": "u@example.test", "password_plain": "pw", "tenant_id": "t",
                "workspace_id": "w", "role": role, "status": "active", "authorized_collection_ids":
                ["allowed"] if grants is None else grants})
    return IdentityProviderImpl(users=users, sessions=sessions, verifier=PlainTestVerifier())


def login(provider):
    return provider.login(email="u@example.test", password="pw", tenant_id="t", ip=None, user_agent=None)["session_token"]


@pytest.fixture(params=["memory", "sqlite"])
def sessions(request, tmp_path):
    return InMemorySessionStore() if request.param == "memory" else SQLiteSessions(tmp_path / "sessions.db")


@pytest.mark.parametrize("role", ["KNOWLEDGE_MANAGER", "VETERINARIAN"])
def test_last_grant_revocation_survives_login_and_refresh(sessions, role):
    provider = provider_for(sessions, role)
    token = login(provider)
    before = provider.validate_session(token)
    assert before["allowed_collection_ids"] == ["allowed"]
    user = provider.users.get_by_id("u")
    user["authorized_collection_ids"] = []
    provider.users.save(user)
    if isinstance(provider.users, SQLiteUsers):
        provider.users = SQLiteUsers(provider.users.path)
        user = provider.users.get_by_id("u")
        assert user["authorized_collection_ids"] == []
    refreshed = refresh_context_from_user(before, user)
    assert refreshed["allowed_collection_ids"] == []
    after = provider.validate_session(login(provider))
    assert after["authenticated"]
    assert after["allowed_collection_ids"] == []
    for snapshot in (refreshed, after):
        assert not can_access_collection(allowed=snapshot["allowed_collection_ids"], collection_id="rag_phase0")
        with pytest.raises(AuthorizationError):
            build_retrieval_context(user_id="u", tenant_id="t", session_workspace="w", requested_workspace="w",
                                    allowed_collection_ids=snapshot["allowed_collection_ids"], permissions=snapshot["permissions"],
                                    role=role, requested_collection_id="allowed")


@pytest.mark.parametrize("grants", [["allowed"], ["*"]])
def test_login_and_refresh_keep_explicit_valid_grants(sessions, grants):
    provider = provider_for(sessions, grants=grants)
    snapshot = provider.validate_session(login(provider))
    assert snapshot["allowed_collection_ids"] == grants
    assert refresh_context_from_user(snapshot, provider.users.get_by_id("u"))["allowed_collection_ids"] == grants


def mutate(sessions, token, record):
    if isinstance(sessions, InMemorySessionStore):
        sessions.get(token).clear()
        sessions.get(token).update(record)
    else:
        sessions.save(token, record)


BAD_MODERN = [("permissions", "MISSING"), ("permissions", None), ("permissions", "*"),
    ("permissions", [None]), ("permissions", [" "]), ("permissions", ["chat.query\n"]),
    ("authorization_snapshot_version", "MISSING"), ("authorization_snapshot_version", True),
    ("authorization_snapshot_version", 2), ("authorization_state", "MISSING"),
    ("authorization_state", "unknown"), ("canonical_role", "unknown"),
    ("allowed_collection_ids", "MISSING"), ("allowed_collection_ids", "*"),
    ("allowed_collection_ids", [None])]


@pytest.mark.parametrize("key,value", BAD_MODERN)
@pytest.mark.parametrize("state", ["AUTHORITATIVE", "MIGRATED"])
def test_modern_snapshot_corruption_never_derives_role_defaults(sessions, state, key, value):
    provider = provider_for(sessions, role="PLATFORM_ADMIN", grants=["*"])
    token = login(provider)
    record = copy.deepcopy(sessions.get(token))
    record["authorization_state"] = state
    if value == "MISSING":
        record.pop(key, None)
    else:
        record[key] = value
    mutate(sessions, token, record)
    assert not provider.validate_session(token)["authenticated"]
    persisted = sessions.get(token)
    assert persisted.get("authorization_state") == record.get("authorization_state")
    assert persisted.get("permissions") == record.get("permissions")


def test_explicit_empty_modern_permissions_remain_authoritative(sessions):
    provider = provider_for(sessions, role="PLATFORM_ADMIN", grants=[])
    token = login(provider)
    record = copy.deepcopy(sessions.get(token))
    record["permissions"] = []
    mutate(sessions, token, record)
    for _ in range(2):
        snapshot = provider.validate_session(token)
        assert snapshot["authenticated"]
        assert snapshot["permissions"] == []
        assert snapshot["allowed_collection_ids"] == []
        assert snapshot["authorization_state"] == "AUTHORITATIVE"


@pytest.mark.parametrize("explicit_marker", [True, False])
def test_genuine_legacy_migration_persists_once_and_survives_reopen(sessions, explicit_marker):
    provider = provider_for(sessions, grants=[])
    token = login(provider)
    record = copy.deepcopy(sessions.get(token))
    for key in ("permissions", "canonical_role", "authorization_snapshot_version", "authorization_state"):
        record.pop(key, None)
    if explicit_marker:
        record["authorization_state"] = "LEGACY_UNMIGRATED"
    mutate(sessions, token, record)
    first = provider.validate_session(token)
    assert first["authenticated"]
    assert first["authorization_state"] == "MIGRATED"
    assert first["allowed_collection_ids"] == []
    assert sessions.get(token)["permissions"] == first["permissions"]
    user = provider.users.get_by_id("u")
    user["permission_overrides"] = {"add": ["users.manage"]}
    provider.users.save(user)
    if isinstance(sessions, SQLiteSessions):
        assert sessions.migrations == 1
        reopened = SQLiteSessions(sessions.path)
        provider.sessions = reopened
    second = provider.validate_session(token)
    assert second["permissions"] == first["permissions"]
    assert second["authorization_state"] == "MIGRATED"


@pytest.mark.parametrize("key,value", BAD_MODERN)
def test_postgres_decoding_rejects_corrupt_modern_snapshot(key, value):
    snapshot = {"role": "super_admin", "canonical_role": "PLATFORM_ADMIN", "permissions": ["*"],
                "authorization_state": "AUTHORITATIVE", "authorization_snapshot_version": 1,
                "allowed_collection_ids": ["*"]}
    if value == "MISSING":
        snapshot.pop(key, None)
    else:
        snapshot[key] = value
    assert PostgresSessionStore._record({"authorization_snapshot": snapshot}) is None


def test_detached_legacy_without_persistence_port_is_denied():
    sessions = InMemorySessionStore()
    provider = provider_for(sessions)
    token = login(provider)
    record = copy.deepcopy(sessions.get(token))
    for key in ("permissions", "canonical_role", "authorization_snapshot_version", "authorization_state"):
        record.pop(key, None)

    class Detached:
        def get(self, token):
            return copy.deepcopy(record)
        def touch(self, token):
            raise AssertionError("denied session must not slide expiry")

    provider.sessions = Detached()
    assert not provider.validate_session(token)["authenticated"]


def test_memory_concurrent_migration_writes_only_one_current_snapshot():
    sessions = InMemorySessionStore()
    provider = provider_for(sessions)
    token = login(provider)
    record = sessions.get(token)
    for key in ("permissions", "canonical_role", "authorization_snapshot_version", "authorization_state"):
        record.pop(key, None)
    expected = copy.deepcopy(record)
    migrated = provider._migrate_legacy_record(record, provider.users.get_by_id("u"))
    barrier = Barrier(2)

    def persist():
        barrier.wait(timeout=5)
        return sessions.update_authorization_snapshot(token, expected=copy.deepcopy(expected), snapshot=migrated)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: persist(), range(2)))
    assert sorted(results) == [False, True]
    assert sessions.get(token)["authorization_state"] == "MIGRATED"


@pytest.mark.parametrize("terminal", ["expired", "revoked", "deleted", "changed"])
def test_memory_legacy_migration_rejects_changed_or_terminal_source(terminal):
    sessions = InMemorySessionStore()
    provider = provider_for(sessions)
    token = login(provider)
    record = sessions.get(token)
    for key in ("permissions", "canonical_role", "authorization_snapshot_version", "authorization_state"):
        record.pop(key, None)
    expected = copy.deepcopy(record)
    migrated = provider._migrate_legacy_record(record, provider.users.get_by_id("u"))
    if terminal == "expired":
        record["expires_at"] = 0
    elif terminal == "revoked":
        record["revoked_at"] = time.time()
    elif terminal == "deleted":
        sessions.delete(token)
    else:
        record["role_version"] = 2
    assert sessions.update_authorization_snapshot(token, expected=expected, snapshot=migrated) is False
