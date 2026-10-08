from __future__ import annotations

from types import SimpleNamespace

import pytest

from rick_identity import (
    IdentityError,
    IdentityProviderImpl,
    InMemorySessionStore,
    Pbkdf2Verifier,
    PostgresIdentityError,
    PostgresRecoveryStore,
    PostgresSessionStore,
    PostgresUserStore,
    hash_password,
)
from rick_identity.postgres import _row_dict
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

    duplicate_connection = Connection([
        ("token_hash", [session_row(authorization_snapshot='{"permissions":["chat.query"],"permissions":["chat.query"]}')], 1),
    ])
    assert PostgresSessionStore(factory_for(duplicate_connection), ttl_seconds=600).get("bearer") is None

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


def test_user_store_persists_membership_status_independently_of_global_user_status():
    connection = Connection([
        ("INSERT INTO rick_users", [], 1),
        ("INSERT INTO rick_memberships", [], 1),
    ])

    PostgresUserStore(factory_for(connection)).save(user_row(status="active", membership_status="disabled"))

    assert connection.cursor_instance.queries[1][1][4] == "disabled"
    assert connection.commits == 1


def test_user_lookup_carries_tenant_scope_and_redacts_nothing_into_query() -> None:
    connection = Connection([("WHERE u.user_id", [user_row()], 1)])
    store = PostgresUserStore(factory_for(connection))

    result = store.get_by_id_for_tenant("user-a", "tenant-a")

    assert result["user_id"] == "user-a"
    query, params = connection.cursor_instance.queries[0]
    assert "m.tenant_id = %s" in query
    assert params == ("user-a", "tenant-a")
    assert connection.closed


def test_tenant_email_lookup_requires_exactly_one_active_membership() -> None:
    active = user_row(
        workspace_id="workspace-a",
        role="VETERINARIAN",
        permission_overrides={"add": [], "remove": []},
        authorized_collection_ids=["workspace-a-collection"],
    )
    connection = Connection([("lower(u.email)", [active], 1)])

    result = PostgresUserStore(factory_for(connection)).get_by_email_for_tenant(
        "user-a@example.test", "tenant-a",
    )

    assert result is not None
    assert result["workspace_id"] == "workspace-a"
    query, params = connection.cursor_instance.queries[0]
    assert "m.tenant_id = %s" in query
    assert "u.status = 'active'" in query
    assert "m.status = 'active'" in query
    assert "LIMIT 2" in query
    assert "ORDER BY" not in query
    assert params == ("user-a@example.test", "tenant-a")


def test_login_rejects_multiple_active_memberships_without_creating_a_session() -> None:
    memberships = [
        user_row(
            workspace_id="workspace-a",
            role="PLATFORM_ADMIN",
            permission_overrides={"add": [], "remove": []},
            authorized_collection_ids=["workspace-a-collection"],
        ),
        user_row(
            workspace_id="workspace-b",
            role="VETERINARIAN",
            permission_overrides={"add": [], "remove": ["cases.read"]},
            authorized_collection_ids=["workspace-b-collection"],
        ),
    ]
    connection = Connection([("lower(u.email)", memberships, 2)])
    users = PostgresUserStore(factory_for(connection))
    sessions = InMemorySessionStore()
    provider = IdentityProviderImpl(users=users, sessions=sessions, verifier=Pbkdf2Verifier())

    with pytest.raises(IdentityError) as error:
        provider.login(
            email="user-a@example.test", password="secret-password", tenant_id="tenant-a",
            ip=None, user_agent=None,
        )

    assert error.value.code == "unauthorized"
    assert "workspace" not in str(error.value).casefold()
    query, params = connection.cursor_instance.queries[0]
    assert "m.tenant_id = %s" in query
    assert "u.status = 'active'" in query
    assert "m.status = 'active'" in query
    assert "LIMIT 2" in query
    assert params == ("user-a@example.test", "tenant-a")
    assert sessions.records() == []


def test_global_active_email_lookup_rejects_ambiguous_recovery_memberships() -> None:
    connection = Connection([
        ("lower(u.email)", [
            user_row(tenant_id="tenant-a", workspace_id="workspace-a"),
            user_row(tenant_id="tenant-b", workspace_id="workspace-b"),
        ], 2),
    ])

    result = PostgresUserStore(factory_for(connection)).get_unique_active_by_email(
        "user-a@example.test",
    )

    assert result is None
    query, params = connection.cursor_instance.queries[0]
    assert "u.status = 'active'" in query
    assert "m.status = 'active'" in query
    assert "LIMIT 2" in query
    assert "ORDER BY" not in query
    assert params == ("user-a@example.test",)


def test_identity_stores_join_caller_transaction_without_committing_or_closing_it() -> None:
    connection = Connection([
        ("WHERE u.user_id", [user_row()], 1),
        ("INSERT INTO rick_users", [], 1),
        ("INSERT INTO rick_memberships", [], 1),
        ("UPDATE rick_sessions", [], 2),
    ])

    def unused_factory():
        raise AssertionError("caller-owned transaction must be reused")

    users = PostgresUserStore(unused_factory)
    sessions = PostgresSessionStore(unused_factory, ttl_seconds=600)
    assert users.get_by_id_for_tenant("user-a", "tenant-a", connection=connection)["user_id"] == "user-a"
    users.save(user_row(), connection=connection)
    assert sessions.revoke_user(
        "user-a", tenant_id="tenant-a", reason="password_reset", connection=connection
    ) == 2

    assert connection.commits == 0
    assert connection.rollbacks == 0
    assert connection.closed is False
    assert len(connection.cursor_instance.queries) == 4


def test_identity_row_decoder_accepts_psycopg_column_descriptors() -> None:
    class Column:
        def __init__(self, name):
            self.name = name

    cursor = type("CursorDescription", (), {"description": [Column("user_id"), Column("tenant_id")]})()

    assert _row_dict(cursor, ("user-a", "tenant-a")) == {
        "user_id": "user-a",
        "tenant_id": "tenant-a",
    }


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
    consume = Connection([("UPDATE rick_password_reset_tokens", [{
        "user_id": "user-a", "tenant_id": "tenant-a", "workspace_id": "workspace-a",
    }], 1)])
    replay = Connection([("UPDATE rick_password_reset_tokens", [], 0)])
    store = PostgresRecoveryStore(factory_for(issue, consume, replay))

    token = store.issue(user_id="user-a", tenant_id="tenant-a", workspace_id="workspace-a")
    assert len(token) > 20
    issue_params = issue.cursor_instance.queries[0][1]
    assert token not in str(issue_params)
    assert store.consume(token) == {
        "user_id": "user-a", "tenant_id": "tenant-a", "workspace_id": "workspace-a",
    }
    assert store.consume(token) is None


def test_user_store_locks_only_the_exact_workspace_membership_for_update() -> None:
    connection = Connection([("FOR UPDATE OF m", [user_row()], 1)])
    store = PostgresUserStore(factory_for(connection))

    resolved = store.get_by_id_for_tenant_workspace_for_update(
        "user-a", "tenant-a", "workspace-a", connection=connection,
    )

    assert resolved is not None
    query, params = connection.cursor_instance.queries[0]
    assert "m.tenant_id = %s" in query
    assert "m.workspace_id = %s" in query
    assert "FOR UPDATE OF m" in query
    assert params == ("user-a", "tenant-a", "workspace-a")


def test_user_store_lookup_and_password_update_keep_workspace_and_membership_scope() -> None:
    lookup = Connection([("m.workspace_id = %s", [user_row()], 1)])
    update = Connection([("UPDATE rick_users", [], 1)])
    store = PostgresUserStore(factory_for(lookup, update))

    resolved = store.get_by_id_for_tenant_workspace("user-a", "tenant-a", "workspace-a")
    assert resolved is not None
    assert (resolved["user_id"], resolved["tenant_id"], resolved["workspace_id"]) == (
        "user-a", "tenant-a", "workspace-a",
    )
    assert resolved["membership_status"] == "active"
    assert lookup.cursor_instance.queries[0][1] == ("user-a", "tenant-a", "workspace-a")

    assert store.update_password_credentials(user_id="user-a", password_hash="new-hash") is True
    update_sql = update.cursor_instance.queries[0][0].lower()
    assert "update rick_users" in update_sql
    assert "password_version = coalesce(password_version, 1) + 1" in update_sql
    assert "rick_memberships" not in update_sql
    assert update.cursor_instance.queries[0][1] == ("new-hash", "user-a")


def test_postgres_refresh_uses_exact_workspace_membership_and_current_grants() -> None:
    requested = user_row(
        workspace_id="workspace-b",
        role="VETERINARIAN",
        authorized_collection_ids=["workspace-b-collection"],
    )
    connection = Connection([("m.workspace_id = %s", [requested], 1)])
    provider = PostgresIdentityProvider(factory_for(connection))
    context = {
        "user_id": "user-a",
        "tenant_id": "tenant-a",
        "workspace_id": "workspace-b",
        "allowed_collection_ids": ["workspace-a-collection", "workspace-b-collection"],
        "permissions": ["chat.query", "cases.manage", "documents.read"],
    }

    refreshed = provider.refresh_authorization_context(context=context)

    assert refreshed is not None
    assert refreshed["allowed_collection_ids"] == ["workspace-b-collection"]
    assert "documents.read" not in refreshed["permissions"]
    query, params = connection.cursor_instance.queries[0]
    assert "m.tenant_id = %s" in query
    assert "m.workspace_id = %s" in query
    assert params == ("user-a", "tenant-a", "workspace-b")


def test_postgres_refresh_fails_closed_without_workspace_or_exact_resolver() -> None:
    def unexpected_connection():
        raise AssertionError("invalid or unscoped refresh must not query membership")

    provider = PostgresIdentityProvider(unexpected_connection)
    context = {"user_id": "user-a", "tenant_id": "tenant-a", "workspace_id": "workspace-a"}

    assert provider.refresh_authorization_context(context={"user_id": "user-a", "tenant_id": "tenant-a"}) is None

    provider._users.get_by_id_for_tenant_workspace = None
    assert provider.refresh_authorization_context(context=context) is None

    mis_scoped_provider = PostgresIdentityProvider(unexpected_connection)
    mis_scoped_provider._users.get_by_id_for_tenant_workspace = (
        lambda *_args: user_row(
            workspace_id="workspace-a",
            role="PLATFORM_ADMIN",
            authorized_collection_ids=["workspace-a-collection"],
        )
    )
    assert mis_scoped_provider.refresh_authorization_context(context=context) is None


@pytest.mark.parametrize(
    ("tenant_id", "membership_tenants"),
    [("tenant-a", ("tenant-a", "tenant-a")), (None, ("tenant-a", "tenant-b"))],
)
def test_password_reset_ambiguity_returns_no_token(tenant_id, membership_tenants) -> None:
    connection = Connection([
        ("lower(u.email)", [
            user_row(
                tenant_id=membership_tenants[0], workspace_id="workspace-a",
                role="PLATFORM_ADMIN", authorized_collection_ids=["workspace-a-collection"],
            ),
            user_row(
                tenant_id=membership_tenants[1], workspace_id="workspace-b",
                role="VETERINARIAN", authorized_collection_ids=["workspace-b-collection"],
            ),
        ], 2),
    ])
    provider = PostgresIdentityProvider(factory_for(connection))

    token = provider.issue_password_reset(email="user-a@example.test", tenant_id=tenant_id)

    assert token is None
    assert len(connection.cursor_instance.queries) == 1
    assert connection.commits == 0


def test_password_reset_without_tenant_succeeds_for_one_active_membership() -> None:
    lookup = Connection([("lower(u.email)", [user_row()], 1)])
    issue = Connection([("INSERT INTO rick_password_reset_tokens", [], 1)])
    provider = PostgresIdentityProvider(factory_for(lookup, issue))

    token = provider.issue_password_reset(email="user-a@example.test", tenant_id=None)

    assert isinstance(token, str) and token
    assert lookup.cursor_instance.queries[0][1] == ("user-a@example.test",)
    issue_query, issue_params = issue.cursor_instance.queries[0]
    assert "workspace_id" in issue_query
    assert token not in str(issue_params)
    assert issue_params[1:4] == ("tenant-a", "user-a", "workspace-a")


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
