from __future__ import annotations

from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from core.errors import ApiError
from services.postgres_identity import PostgresIdentityProvider


class _Connection:
    def __init__(self, *, role="VETERINARIAN", fail_outbox=False, active_admins=1,
                 active_admins_by_workspace=None, other_tenants=()):
        self.user = None if role is None else {
            "user_id": "user-a",
            "external_subject": None,
            "email": "user-a@example.test",
            "status": "active",
            "password_hash": "stored-hash",
            "password_version": 1,
            "role_version": 1,
            "tenant_id": "tenant-a",
            "workspace_id": "workspace-a",
            "role": role,
            "membership_status": "active",
            "permission_overrides": {"add": [], "remove": []},
            "authorized_collection_ids": [],
        }
        self.fail_outbox = fail_outbox
        self.active_admins = active_admins
        self.active_admins_by_workspace = dict(active_admins_by_workspace or {})
        self.other_tenants = tuple(other_tenants)
        self.outbox: list[tuple[str, dict]] = []
        self.session_revocations = 0
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.trace: list[str] = []
        self.query_params: list[tuple[object, ...]] = []
        self._snapshot = (deepcopy(self.user), [], 0)

    def cursor(self):
        return _Cursor(self)

    def commit(self):
        self.commits += 1
        self._snapshot = (deepcopy(self.user), list(self.outbox), self.session_revocations)

    def rollback(self):
        self.rollbacks += 1
        if self._snapshot is not None:
            self.user, self.outbox, self.session_revocations = deepcopy(self._snapshot)

    def close(self):
        self.closed = True


class _Cursor:
    def __init__(self, connection):
        self.connection = connection
        self.rows = []
        self.rowcount = 0

    def execute(self, query, params=()):
        compact = " ".join(query.lower().split())
        self.connection.trace.append(compact)
        self.connection.query_params.append(tuple(params))
        self.rows = []
        self.rowcount = 0
        if compact.startswith("select pg_advisory_xact_lock"):
            return
        if compact.startswith("select count(*) as count from rick_outbox"):
            self.rows = [{"count": 0}]
            return
        if compact.startswith("select user_id from rick_users where user_id = %s for update"):
            (user_id,) = params
            if self.connection.user and self.connection.user["user_id"] == user_id:
                self.rows = [{"user_id": user_id}]
            return
        if compact.startswith("select exists (") and "from rick_memberships" in compact:
            user_id, tenant_id = params
            has_other = (
                self.connection.user is not None
                and self.connection.user["user_id"] == user_id
                and bool(self.connection.other_tenants)
            )
            self.rows = [{"has_other_tenant_memberships": has_other}]
            return
        if "from rick_users" in compact and "lower(u.email) = %s" in compact:
            return
        if "from rick_users" in compact and "u.user_id = %s and m.tenant_id = %s" in compact:
            user_id, tenant_id, *workspace_filter = params
            if self.connection.user and self.connection.user["user_id"] == user_id and self.connection.user["tenant_id"] == tenant_id:
                if not workspace_filter or self.connection.user["workspace_id"] == workspace_filter[0]:
                    self.rows = [deepcopy(self.connection.user)]
            return
        if compact.startswith("select count(*) as count") and "from rick_users" in compact:
            count = self.connection.active_admins
            if len(params) > 1:
                count = self.connection.active_admins_by_workspace.get(params[1], count)
            self.rows = [{"count": count}]
            return
        if compact.startswith("insert into rick_users"):
            user_id, external_subject, email, status, password_hash, password_version, role_version = params
            self.connection.user = {
                "user_id": user_id,
                "external_subject": external_subject,
                "email": email,
                "status": status,
                "password_hash": password_hash,
                "password_version": password_version,
                "role_version": role_version,
                "tenant_id": None,
                "workspace_id": None,
                "role": None,
                "membership_status": None,
                "permission_overrides": {"add": [], "remove": []},
                "authorized_collection_ids": [],
            }
            self.rowcount = 1
            return
        if compact.startswith("insert into rick_memberships"):
            tenant_id, user_id, workspace_id, role, status, overrides, grants = params
            assert self.connection.user is not None and self.connection.user["user_id"] == user_id
            self.connection.user.update({
                "tenant_id": tenant_id,
                "workspace_id": workspace_id,
                "role": role,
                "membership_status": status,
                "permission_overrides": json.loads(overrides),
                "authorized_collection_ids": json.loads(grants),
            })
            self.rowcount = 1
            return
        if compact.startswith("update rick_sessions"):
            self.connection.session_revocations += 2
            self.rowcount = 2
            return
        if compact.startswith("update rick_memberships set status = %s"):
            status, user_id, tenant_id, workspace_id = params
            user = self.connection.user
            if (
                user is not None
                and user["user_id"] == user_id
                and user["tenant_id"] == tenant_id
                and user["workspace_id"] == workspace_id
            ):
                user["membership_status"] = status
                self.rowcount = 1
            return
        if compact.startswith("insert into rick_outbox"):
            if self.connection.fail_outbox:
                raise RuntimeError("simulated outbox write error")
            event_id, tenant_id, _aggregate_id, payload = params
            self.connection.outbox.append((event_id, json.loads(payload)))
            self.rowcount = 1
            return
        raise AssertionError(f"unexpected SQL: {compact}")

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        rows, self.rows = self.rows, []
        return rows

    def close(self):
        return None


def _actor():
    return SimpleNamespace(
        user_id="admin-a",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        role="PLATFORM_ADMIN",
        canonical_role="PLATFORM_ADMIN",
        permissions=["users.manage", "audit.read"],
    )


def test_admin_create_commits_identity_and_sanitized_audit_outbox_together():
    connection = _Connection(role=None)
    provider = PostgresIdentityProvider(lambda: connection)

    user, event_id = provider.admin_create_user(
        actor=_actor(), email="new@example.test", role="VETERINARIAN",
        tenant_id="tenant-a", password="private-password", request_id="req-123",
    )

    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert connection.closed is True
    assert user["email"] == "new@example.test"
    assert user["workspace_id"] == "workspace-a"
    assert len(connection.outbox) == 1
    assert connection.outbox[0][0] == event_id
    assert connection.outbox[0][1] == {
        "action": "admin.user_created",
        "actor_user_id": "admin-a",
        "target_type": "user",
        "target_id": user["user_id"],
        "tenant_id": "tenant-a",
        "workspace_id": "workspace-a",
        "request_id": "req-123",
        "status": "completed",
    }
    assert "private-password" not in json.dumps(connection.outbox)
    assert next(index for index, query in enumerate(connection.trace) if query.startswith("insert into rick_memberships")) < next(
        index for index, query in enumerate(connection.trace) if query.startswith("insert into rick_outbox")
    )


def test_legacy_postgres_create_entrypoint_fails_closed_without_actor_and_uses_atomic_outbox_with_actor():
    unscoped_connection = _Connection(role=None)
    unscoped_provider = PostgresIdentityProvider(lambda: unscoped_connection)

    with pytest.raises(ApiError) as missing_actor:
        unscoped_provider.create_user(
            email="unscoped@example.test", role="VETERINARIAN",
            tenant_id="tenant-a", password="private-password",
        )

    assert missing_actor.value.code == "provider_unavailable"
    assert unscoped_connection.user is None
    assert unscoped_connection.commits == 0
    assert unscoped_connection.trace == []

    connection = _Connection(role=None)
    provider = PostgresIdentityProvider(lambda: connection)
    user = provider.create_user(
        actor=_actor(), email="scoped@example.test", role="VETERINARIAN",
        tenant_id="tenant-a", password="private-password", request_id="req-direct-create",
    )

    assert user["email"] == "scoped@example.test"
    assert connection.commits == 1
    assert len(connection.outbox) == 1
    assert connection.outbox[0][1]["action"] == "admin.user_created"
    assert connection.outbox[0][1]["target_id"] == user["user_id"]


def test_admin_deactivation_rolls_back_user_and_sessions_if_outbox_write_fails():
    connection = _Connection(fail_outbox=True)
    provider = PostgresIdentityProvider(lambda: connection)

    with pytest.raises(ApiError) as error:
        provider.admin_deactivate_user(actor=_actor(), user_id="user-a", request_id="req-456")

    assert error.value.code == "provider_unavailable"
    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert connection.user["status"] == "active"
    assert connection.session_revocations == 0
    assert connection.outbox == []
    assert connection.closed is True
    assert any(query.startswith("update rick_sessions") for query in connection.trace)


def test_admin_deactivation_disables_only_the_tenant_membership():
    connection = _Connection()
    provider = PostgresIdentityProvider(lambda: connection)

    revoked, event_id = provider.admin_deactivate_user(actor=_actor(), user_id="user-a", request_id="req-457")

    assert revoked == 2
    assert connection.user["status"] == "active"
    assert connection.user["membership_status"] == "disabled"
    assert connection.user["password_hash"] == "stored-hash"
    assert connection.user["password_version"] == 1
    assert connection.user["role_version"] == 1
    assert connection.commits == 1
    assert connection.outbox[0][0] == event_id
    assert any(query.startswith("update rick_memberships set status = %s") for query in connection.trace)
    assert not any(query.startswith("insert into rick_users") or "update rick_users" in query for query in connection.trace)
    scoped_sessions = next(
        (params for query, params in zip(connection.trace, connection.query_params)
         if query.startswith("update rick_sessions")),
        None,
    )
    assert scoped_sessions == ("user_disabled", "user-a", "tenant-a", "workspace-a")
    assert ("user-a", "tenant-a", "workspace-a") in connection.query_params


def test_admin_deactivation_repairs_active_membership_for_globally_disabled_user():
    connection = _Connection()
    connection.user["status"] = "disabled"
    provider = PostgresIdentityProvider(lambda: connection)

    revoked, event_id = provider.admin_deactivate_user(
        actor=_actor(), user_id="user-a", request_id="req-global-disabled",
    )

    assert revoked == 2
    assert connection.user["status"] == "disabled"
    assert connection.user["membership_status"] == "disabled"
    assert connection.commits == 1
    assert connection.outbox[0][0] == event_id
    assert any(query.startswith("update rick_memberships set status = %s") for query in connection.trace)


def test_inactive_platform_admin_can_be_demoted_or_deactivated_again():
    demotion = _Connection(role="PLATFORM_ADMIN", active_admins=1)
    demotion.user["membership_status"] = "disabled"
    demoted_user, _event_id = PostgresIdentityProvider(lambda: demotion).admin_update_user(
        actor=_actor(), user_id="user-a", role="VETERINARIAN", request_id="req-458"
    )
    assert demoted_user["role"] == "VETERINARIAN"
    assert demotion.user["membership_status"] == "disabled"
    assert demotion.commits == 1

    deactivation = _Connection(role="PLATFORM_ADMIN", active_admins=1)
    deactivation.user["membership_status"] = "disabled"
    revoked, _event_id = PostgresIdentityProvider(lambda: deactivation).admin_deactivate_user(
        actor=_actor(), user_id="user-a", request_id="req-459"
    )
    assert revoked == 2
    assert deactivation.user["status"] == "active"
    assert deactivation.user["membership_status"] == "disabled"
    assert deactivation.commits == 1


def test_admin_demotion_protects_last_platform_admin_in_actor_workspace():
    connection = _Connection(
        role="PLATFORM_ADMIN", active_admins=2,
        active_admins_by_workspace={"workspace-a": 1},
    )
    provider = PostgresIdentityProvider(lambda: connection)

    with pytest.raises(ApiError) as error:
        provider.admin_update_user(
            actor=_actor(), user_id="user-a", role="VETERINARIAN", request_id="req-last-workspace-admin",
        )

    assert error.value.code == "conflict"
    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert connection.user["role"] == "PLATFORM_ADMIN"
    assert connection.outbox == []
    assert ("tenant-a", "workspace-a") in connection.query_params
    assert any(
        "and m.workspace_id = %s" in query
        for query in connection.trace
        if query.startswith("select count(*) as count")
    )


def test_last_active_admin_cannot_be_deactivated():
    connection = _Connection(role="PLATFORM_ADMIN", active_admins=1)
    provider = PostgresIdentityProvider(lambda: connection)

    with pytest.raises(ApiError) as error:
        provider.admin_deactivate_user(actor=_actor(), user_id="user-a")

    assert error.value.code == "conflict"
    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert connection.user["status"] == "active"
    assert connection.outbox == []
    assert not any(query.startswith("update rick_sessions") for query in connection.trace)


def test_admin_reset_rejects_accounts_with_memberships_in_another_tenant():
    connection = _Connection(other_tenants=("tenant-b",))
    original = deepcopy(connection.user)
    provider = PostgresIdentityProvider(lambda: connection)

    with pytest.raises(ApiError) as error:
        provider.admin_reset_password(
            actor=_actor(), user_id="user-a", password="replacement-password", request_id="req-cross-tenant",
        )

    assert error.value.code == "forbidden"
    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert connection.user == original
    assert connection.session_revocations == 0
    assert connection.outbox == []
    lock_index = next(i for i, query in enumerate(connection.trace) if query.startswith("select user_id from rick_users"))
    membership_check_index = next(i for i, query in enumerate(connection.trace) if query.startswith("select exists ("))
    assert lock_index < membership_check_index
    assert not any(query.startswith("update rick_sessions") for query in connection.trace)


def test_admin_reset_rejects_account_only_in_a_sibling_workspace():
    connection = _Connection()
    connection.user["workspace_id"] = "workspace-b"
    connection._snapshot = (deepcopy(connection.user), list(connection.outbox), connection.session_revocations)
    original = deepcopy(connection.user)
    provider = PostgresIdentityProvider(lambda: connection)

    with pytest.raises(ApiError) as error:
        provider.admin_reset_password(
            actor=_actor(), user_id="user-a", password="replacement-password", request_id="req-sibling-workspace",
        )

    assert error.value.code == "forbidden"
    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert connection.user == original
    assert connection.session_revocations == 0
    assert connection.outbox == []
    assert not any(query.startswith("update rick_sessions") for query in connection.trace)
    assert ("user-a", "tenant-a", "workspace-a") in connection.query_params


def test_admin_reset_commits_for_a_single_tenant_account():
    connection = _Connection()
    provider = PostgresIdentityProvider(lambda: connection)

    revoked, event_id = provider.admin_reset_password(
        actor=_actor(), user_id="user-a", password="replacement-password", request_id="req-single-tenant",
    )

    assert revoked == 2
    assert connection.user["password_hash"] != "stored-hash"
    assert connection.user["password_version"] == 2
    assert connection.commits == 1
    assert connection.outbox[0][0] == event_id
    assert connection.outbox[0][1]["tenant_id"] == "tenant-a"
    assert ("user-a", "tenant-a", "workspace-a") in connection.query_params


def test_admin_email_update_rejects_a_global_profile_change_for_another_tenant():
    connection = _Connection(other_tenants=("tenant-b",))
    original = deepcopy(connection.user)
    provider = PostgresIdentityProvider(lambda: connection)

    with pytest.raises(ApiError) as error:
        provider.admin_update_user(
            actor=_actor(), user_id="user-a", email="renamed@example.test", request_id="req-cross-tenant-email",
        )

    assert error.value.code == "forbidden"
    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert connection.user == original
    assert connection.outbox == []


@pytest.mark.parametrize("changes", [
    {"role": "KNOWLEDGE_MANAGER"},
    {"authorized_collection_ids": ["collection-b"]},
    {"permission_overrides": {"add": ["users.manage"], "remove": []}},
])
def test_admin_membership_edit_rejects_shared_account_version_change(changes):
    connection = _Connection(other_tenants=("tenant-b",))
    original = deepcopy(connection.user)
    provider = PostgresIdentityProvider(lambda: connection)

    with pytest.raises(ApiError) as error:
        provider.admin_update_user(actor=_actor(), user_id="user-a", **changes)

    assert error.value.code == "forbidden"
    assert connection.commits == 0
    assert connection.rollbacks == 1
    assert connection.user == original
    assert connection.session_revocations == 0
    assert connection.outbox == []
