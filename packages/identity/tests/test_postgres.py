from __future__ import annotations

from types import SimpleNamespace

import pytest

from rick_identity import (
    PostgresIdentityError,
    PostgresRecoveryStore,
    PostgresSessionStore,
    PostgresUserStore,
    hash_password,
)
from services.postgres_identity import PostgresIdentityProvider


class Cursor:
    def __init__(self, steps):
        self.steps = list(steps)
        self.queries = []
        self._rows = []
        self.rowcount = 0

    def execute(self, query, params=()):
        self.queries.append((query, params))
        if not self.steps:
            raise AssertionError(f"unexpected query: {query}")
        expected, rows, rowcount = self.steps.pop(0)
        assert expected in query
        self._rows = list(rows)
        self.rowcount = rowcount

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchall(self):
        rows, self._rows = self._rows, []
        return rows

    def close(self):
        return None


class Connection:
    def __init__(self, steps):
        self.cursor_instance = Cursor(steps)
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def factory_for(*connections):
    remaining = list(connections)

    def factory():
        if not remaining:
            raise AssertionError("connection factory was called more often than scripted")
        return remaining.pop(0)

    return factory


def user_row(**overrides):
    row = {
        "user_id": "user-a",
        "external_subject": None,
        "email": "user-a@example.test",
        "status": "active",
        "password_hash": hash_password("secret-password"),
        "password_version": 1,
        "role_version": 1,
        "tenant_id": "tenant-a",
        "workspace_id": "workspace-a",
        "role": "VETERINARIAN",
        "membership_status": "active",
        "permission_overrides": {"add": [], "remove": []},
        "authorized_collection_ids": ["guides"],
    }
    row.update(overrides)
    return row


def session_row(**overrides):
    row = {
        "session_id": "session-a",
        "user_id": "user-a",
        "tenant_id": "tenant-a",
        "workspace_id": "workspace-a",
        "authorization_snapshot": {
            "email": "user-a@example.test",
            "role": "veterinarian",
            "canonical_role": "VETERINARIAN",
            "permissions": ["chat.query"],
            "authorization_snapshot_version": 1,
            "authorization_state": "AUTHORITATIVE",
            "allowed_collection_ids": ["guides"],
        },
        "password_version": 1,
        "role_version": 1,
        "created_at": 100.0,
        "last_seen_at": 100.0,
        "expires_at": 10_000_000_000.0,
        "revoked_at": None,
        "revoke_reason": None,
    }
    row.update(overrides)
    return row


def test_persisted_identity_json_fails_closed_for_oversized_and_nonfinite_snapshots() -> None:
    oversized = '{"permissions":["chat.query"]}' + (" " * (64 * 1024))
    oversized_connection = Connection([("token_hash", [session_row(authorization_snapshot=oversized)], 1)])
    assert PostgresSessionStore(factory_for(oversized_connection), ttl_seconds=600).get("bearer") is None

    nan_connection = Connection([("token_hash", [session_row(authorization_snapshot='{"permissions":[NaN]}')], 1)])
    assert PostgresSessionStore(factory_for(nan_connection), ttl_seconds=600).get("bearer") is None

    malformed_connection = Connection([("token_hash", [session_row(authorization_snapshot='{"permissions":1}')], 1)])
    assert PostgresSessionStore(factory_for(malformed_connection), ttl_seconds=600).get("bearer") is None


def test_persisted_user_acl_json_fails_closed_instead_of_widening_scope() -> None:
    corrupt = '{"add":[],"remove":[]}' + (" " * (64 * 1024))
    connection = Connection([("WHERE u.user_id", [user_row(authorized_collection_ids=corrupt)], 1)])
    assert PostgresUserStore(factory_for(connection)).get_by_id_for_tenant("user-a", "tenant-a") is None


def test_identity_json_writes_reject_nonfinite_and_oversized_values_before_db() -> None:
    def unexpected_connection():
        raise AssertionError("invalid JSON must be rejected before opening a connection")

    user_store = PostgresUserStore(unexpected_connection)
    with pytest.raises(PostgresIdentityError):
        user_store.save({
            "user_id": "user-a", "email": "user-a@example.test", "tenant_id": "tenant-a",
            "role": "VETERINARIAN", "permission_overrides": {"add": [float("nan")]},
        })
    with pytest.raises(PostgresIdentityError):
        user_store.save({
            "user_id": "user-a", "email": "user-a@example.test", "tenant_id": "tenant-a",
            "role": "VETERINARIAN", "authorized_collection_ids": ["x" * (64 * 1024)],
        })

    session_store = PostgresSessionStore(unexpected_connection, ttl_seconds=600)
    with pytest.raises(PostgresIdentityError):
        session_store.create({
            "user_id": "user-a", "tenant_id": "tenant-a", "workspace_id": "workspace-a",
            "permissions": [float("nan")],
        })


def test_user_lookup_carries_tenant_scope_and_redacts_nothing_into_query() -> None:
    connection = Connection([("WHERE u.user_id", [user_row()], 1)])
    store = PostgresUserStore(factory_for(connection))

    result = store.get_by_id_for_tenant("user-a", "tenant-a")

    assert result["user_id"] == "user-a"
    query, params = connection.cursor_instance.queries[0]
    assert "m.tenant_id = %s" in query
    assert params == ("user-a", "tenant-a")
    assert connection.closed


def test_session_revoke_by_opaque_id_is_tenant_bound() -> None:
    connection = Connection([("UPDATE rick_sessions", [], 1)])
    store = PostgresSessionStore(factory_for(connection), ttl_seconds=600)

    assert store.revoke_session_by_id("session-a", tenant_id="tenant-a") == 1
    query, params = connection.cursor_instance.queries[0]
    assert "session_id = %s AND tenant_id = %s" in query
    assert params[1:] == ("session-a", "tenant-a")
    assert connection.commits == 1


def test_recovery_store_hashes_and_consumes_a_token_once() -> None:
    issue = Connection([("INSERT INTO rick_password_reset_tokens", [], 1)])
    consume = Connection([("UPDATE rick_password_reset_tokens", [{"user_id": "user-a", "tenant_id": "tenant-a"}], 1)])
    store = PostgresRecoveryStore(factory_for(issue, consume))

    token = store.issue(user_id="user-a", tenant_id="tenant-a", workspace_id="workspace-a")
    assert len(token) > 20
    issue_params = issue.cursor_instance.queries[0][1]
    assert token not in str(issue_params)
    assert store.consume(token) == {"user_id": "user-a", "tenant_id": "tenant-a"}


def test_persistent_provider_uses_authoritative_session_snapshot_and_stays_opt_in_for_production() -> None:
    login_user = Connection([("WHERE lower(u.email)", [user_row()], 1)])
    create_session = Connection([("INSERT INTO rick_sessions", [], 1)])
    read_session = Connection([("token_hash", [session_row()], 1)])
    provider = PostgresIdentityProvider(
        factory_for(login_user, create_session, read_session),
        production_safe=False,
    )

    issued = provider.login(
        email="user-a@example.test",
        password="secret-password",
        tenant_id="tenant-a",
        ip=None,
        user_agent=None,
    )

    assert issued["session_id"] == "session-a"
    assert provider.production_safe is False
    assert create_session.commits == 1


def test_session_ttl_is_bounded() -> None:
    with pytest.raises(PostgresIdentityError):
        PostgresSessionStore(lambda: None, ttl_seconds=59)
