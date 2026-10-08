from __future__ import annotations

import json

import pytest

from admin_audit_outbox import PostgresAdminAuditReconciler, _row_dict


EVENT_ID = "admin-audit-completion-1"
EVENT = {
    "action": "admin.user_updated",
    "actor_user_id": "admin-1",
    "target_id": "user-1",
    "tenant_id": "tenant-1",
    "workspace_id": "workspace-1",
    "request_id": "request-1",
    "status": "completed",
}


def outbox_row(*, event_id=EVENT_ID, payload=None, tenant_id="tenant-1", attempts=0):
    return {
        "event_id": event_id,
        "tenant_id": tenant_id,
        "payload": dict(EVENT) if payload is None else dict(payload) if isinstance(payload, dict) else payload,
        "attempts": attempts,
    }


class ScriptedCursor:
    def __init__(self, steps):
        self.steps = list(steps)
        self.queries = []
        self.rowcount = 0
        self.description = None
        self._rows = []
        self.closed = False

    def execute(self, query, params=()):
        self.queries.append((query, params))
        if not self.steps:
            raise AssertionError("unexpected SQL statement")
        expected, rows, rowcount = self.steps.pop(0)
        assert expected in query
        if isinstance(rows, Exception):
            raise rows
        self._rows = list(rows)
        self.rowcount = rowcount

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchall(self):
        rows, self._rows = self._rows, []
        return rows

    def close(self):
        self.closed = True


class ScriptedConnection:
    def __init__(self, steps, *, commit_error=None):
        self.cursor_instance = ScriptedCursor(steps)
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.commit_error = commit_error

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commits += 1
        if self.commit_error is not None:
            raise self.commit_error

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def factory_for(*connections):
    remaining = list(connections)

    def factory():
        if not remaining:
            raise AssertionError("connection factory was called too many times")
        return remaining.pop(0)

    return factory


def retry_connection(*, attempts=0):
    return ScriptedConnection(
        [
            ("SELECT attempts", [{"attempts": attempts}], 1),
            ("UPDATE rick_outbox", [{"attempts": attempts + 1}], 1),
        ]
    )


def test_projects_only_due_admin_completion_and_commits_projection_together():
    payload = {**EVENT, "password": "private-password-must-not-persist"}
    connection = ScriptedConnection(
        [
            ("FROM rick_outbox", [outbox_row(payload=payload)], 1),
            ("INSERT INTO rick_audit_events", [{"event_id": EVENT_ID}], 1),
            ("UPDATE rick_outbox", [{"event_id": EVENT_ID}], 1),
        ]
    )
    reconciler = PostgresAdminAuditReconciler(factory_for(connection))

    assert reconciler.process_once() == 1

    select_sql, select_params = connection.cursor_instance.queries[0]
    assert select_params == ("admin.audit.completion", 100)
    assert "event_type=%s" in select_sql
    assert "published_at IS NULL" in select_sql
    assert "dead_lettered_at IS NULL" in select_sql
    assert "available_at <= NOW()" in select_sql
    assert "FOR UPDATE SKIP LOCKED" in select_sql

    insert_sql, insert_params = connection.cursor_instance.queries[1]
    assert "ON CONFLICT (event_id) DO NOTHING" in insert_sql
    assert insert_params[0] == EVENT_ID
    assert insert_params[1] == "tenant-1"
    assert json.loads(insert_params[8]) == {"status": "completed"}
    assert "private-password" not in repr(insert_params)

    update_sql, update_params = connection.cursor_instance.queries[2]
    assert "published_at=NOW()" in update_sql
    assert update_params == (EVENT_ID, "admin.audit.completion")
    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert connection.cursor_instance.closed is True
    assert connection.closed is True


def test_empty_batch_commits_and_returns_zero():
    connection = ScriptedConnection([("FROM rick_outbox", [], 0)])
    reconciler = PostgresAdminAuditReconciler(factory_for(connection), batch_size=7)

    assert reconciler.process_once() == 0
    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert connection.closed is True


def test_outbox_row_decoder_accepts_psycopg_column_descriptors():
    class Column:
        def __init__(self, name):
            self.name = name

    cursor = type("CursorDescription", (), {"description": [Column("event_id"), Column("tenant_id")]})()

    assert _row_dict(cursor, (EVENT_ID, "tenant-1")) == {
        "event_id": EVENT_ID,
        "tenant_id": "tenant-1",
    }


def test_projection_error_rolls_back_then_records_retry_in_a_fresh_transaction():
    invalid = {**EVENT, "tenant_id": "different-tenant"}
    work = ScriptedConnection([("FROM rick_outbox", [outbox_row(payload=invalid)], 1)])
    retry = retry_connection(attempts=0)
    reconciler = PostgresAdminAuditReconciler(factory_for(work, retry))

    assert reconciler.process_once() == 0

    assert work.rollbacks == 1
    assert work.commits == 0
    assert work.closed and work.cursor_instance.closed
    assert retry.commits == 1
    assert retry.rollbacks == 0
    retry_sql, retry_params = retry.cursor_instance.queries[1]
    assert "audit_projection_failed" in retry_sql
    assert retry_params == (1, False, 1.0, False, EVENT_ID, "admin.audit.completion")


def test_retry_backoff_is_exponential_and_capped():
    failed = {**EVENT, "action": "bad action"}
    work = ScriptedConnection([("FROM rick_outbox", [outbox_row(payload=failed)], 1)])
    retry = retry_connection(attempts=6)
    reconciler = PostgresAdminAuditReconciler(factory_for(work, retry), max_attempts=8)

    assert reconciler.process_once() == 0
    params = retry.cursor_instance.queries[1][1]
    assert params == (7, False, 64.0, False, EVENT_ID, "admin.audit.completion")


def test_exhausted_attempts_are_dead_lettered_without_storing_exception_text():
    invalid = {**EVENT, "action": "bad action"}
    work = ScriptedConnection([("FROM rick_outbox", [outbox_row(payload=invalid)], 1)])
    retry = retry_connection(attempts=7)
    reconciler = PostgresAdminAuditReconciler(factory_for(work, retry), max_attempts=8)

    assert reconciler.process_once() == 0

    sql, params = retry.cursor_instance.queries[1]
    assert "dead_lettered_at=CASE WHEN %s THEN NOW()" in sql
    assert params == (8, True, 128.0, True, EVENT_ID, "admin.audit.completion")
    assert "bad action" not in repr(params)


def test_retry_backoff_has_a_finite_upper_bound():
    invalid = {**EVENT, "action": "bad action"}
    work = ScriptedConnection([("FROM rick_outbox", [outbox_row(payload=invalid)], 1)])
    retry = retry_connection(attempts=10)
    reconciler = PostgresAdminAuditReconciler(factory_for(work, retry), max_attempts=12)

    assert reconciler.process_once() == 0
    assert retry.cursor_instance.queries[1][1] == (
        11, False, 300.0, False, EVENT_ID, "admin.audit.completion"
    )


def test_conflicting_stable_event_id_is_not_silently_acknowledged():
    existing = {
        "event_id": EVENT_ID,
        "tenant_id": "tenant-1",
        "actor_user_id": "different-actor",
        "action": "admin.user_updated",
        "target_type": None,
        "target_id": "user-1",
        "workspace_id": "workspace-1",
        "request_id": "request-1",
        "metadata": {"status": "completed"},
    }
    work = ScriptedConnection(
        [
            ("FROM rick_outbox", [outbox_row()], 1),
            ("INSERT INTO rick_audit_events", [], 0),
            ("SELECT event_id, tenant_id", [existing], 1),
        ]
    )
    retry = retry_connection(attempts=0)
    reconciler = PostgresAdminAuditReconciler(factory_for(work, retry))

    assert reconciler.process_once() == 0
    assert work.rollbacks == 1
    assert not any("UPDATE rick_outbox" in query for query, _ in work.cursor_instance.queries)
    assert retry.commits == 1


def test_replay_with_same_stable_event_id_and_content_is_idempotent():
    existing = {
        "event_id": EVENT_ID,
        "tenant_id": "tenant-1",
        "actor_user_id": "admin-1",
        "action": "admin.user_updated",
        "target_type": None,
        "target_id": "user-1",
        "workspace_id": "workspace-1",
        "request_id": "request-1",
        "metadata": {"status": "completed"},
    }
    connection = ScriptedConnection(
        [
            ("FROM rick_outbox", [outbox_row()], 1),
            ("INSERT INTO rick_audit_events", [], 0),
            ("SELECT event_id, tenant_id", [existing], 1),
            ("UPDATE rick_outbox", [{"event_id": EVENT_ID}], 1),
        ]
    )
    reconciler = PostgresAdminAuditReconciler(factory_for(connection))

    assert reconciler.process_once() == 1
    assert connection.commits == 1
    assert connection.rollbacks == 0


@pytest.mark.parametrize(
    "payload",
    [
        '{"action":"admin.user_updated","tenant_id":"tenant-1","tenant_id":"tenant-2"}',
        '{"action":"admin.user_updated","tenant_id":NaN}',
        "x" * (64 * 1024 + 1),
    ],
)
def test_malformed_bounded_json_is_retried_without_projection(payload):
    work = ScriptedConnection([("FROM rick_outbox", [outbox_row(payload=payload)], 1)])
    retry = retry_connection()
    reconciler = PostgresAdminAuditReconciler(factory_for(work, retry))

    assert reconciler.process_once() == 0
    assert work.rollbacks == 1
    assert not any("INSERT INTO rick_audit_events" in query for query, _ in work.cursor_instance.queries)
    assert retry.commits == 1


def test_batch_failure_retries_only_the_row_that_failed():
    malformed = {**EVENT, "action": "bad action"}
    work = ScriptedConnection(
        [
            ("FROM rick_outbox", [outbox_row(event_id="first"), outbox_row(event_id="second", payload=malformed)], 2),
            ("INSERT INTO rick_audit_events", [{"event_id": "first"}], 1),
            ("UPDATE rick_outbox", [{"event_id": "first"}], 1),
        ]
    )
    retry = ScriptedConnection(
        [
            ("SELECT attempts", [{"attempts": 0}], 1),
            ("UPDATE rick_outbox", [{"attempts": 1}], 1),
        ]
    )
    reconciler = PostgresAdminAuditReconciler(factory_for(work, retry))

    assert reconciler.process_once() == 0
    assert work.rollbacks == 1
    assert [params[0] for query, params in retry.cursor_instance.queries] == ["second", 1]
    assert retry.cursor_instance.queries[0][1] == ("second", "admin.audit.completion")


def test_empty_event_id_retries_only_the_poison_row():
    work = ScriptedConnection(
        [
            ("FROM rick_outbox", [outbox_row(event_id=""), outbox_row(event_id="good")], 2),
        ]
    )
    retry = retry_connection()
    reconciler = PostgresAdminAuditReconciler(factory_for(work, retry))

    assert reconciler.process_once() == 0

    assert work.rollbacks == 1
    assert retry.cursor_instance.queries[0][1] == ("", "admin.audit.completion")
    assert all("good" not in params for _, params in retry.cursor_instance.queries)


def test_commit_failure_rolls_back_then_retries_unpublished_batch():
    work = ScriptedConnection(
        [
            ("FROM rick_outbox", [outbox_row()], 1),
            ("INSERT INTO rick_audit_events", [{"event_id": EVENT_ID}], 1),
            ("UPDATE rick_outbox", [{"event_id": EVENT_ID}], 1),
        ],
        commit_error=RuntimeError("private database detail"),
    )
    retry = retry_connection(attempts=2)
    reconciler = PostgresAdminAuditReconciler(factory_for(work, retry))

    assert reconciler.process_once() == 0
    assert work.rollbacks == 1
    assert retry.cursor_instance.queries[0][1] == (EVENT_ID, "admin.audit.completion")
    assert retry.cursor_instance.queries[1][1] == (3, False, 4.0, False, EVENT_ID, "admin.audit.completion")
    assert "private database detail" not in repr(retry.cursor_instance.queries)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"batch_size": 0},
        {"batch_size": 1_001},
        {"batch_size": True},
        {"max_attempts": 0},
        {"max_attempts": 65},
        {"max_attempts": False},
    ],
)
def test_configuration_is_bounded(kwargs):
    with pytest.raises(ValueError):
        PostgresAdminAuditReconciler(lambda: None, **kwargs)


def test_health_check_closes_resources_and_hides_connection_errors():
    healthy = ScriptedConnection([
        ("SELECT available_at", [], 0),
        ("SELECT 1", [(1,)], 1),
    ])
    reconciler = PostgresAdminAuditReconciler(factory_for(healthy))
    assert reconciler.health_check() is True
    assert healthy.commits == 1
    assert healthy.closed and healthy.cursor_instance.closed

    class BrokenFactory:
        def __call__(self):
            raise RuntimeError("private DSN and credentials")

    assert PostgresAdminAuditReconciler(BrokenFactory()).health_check() is False


def test_failed_projection_and_retry_transaction_close_every_resource():
    invalid = {**EVENT, "tenant_id": "wrong-tenant"}
    work = ScriptedConnection([("FROM rick_outbox", [outbox_row(payload=invalid)], 1)])
    retry = ScriptedConnection(
        [
            ("SELECT attempts", [{"attempts": 0}], 1),
            ("UPDATE rick_outbox", [{"attempts": 1}], 1),
        ]
    )
    reconciler = PostgresAdminAuditReconciler(factory_for(work, retry))

    assert reconciler.process_once() == 0
    assert work.closed and work.cursor_instance.closed
    assert retry.closed and retry.cursor_instance.closed


def test_failure_to_persist_retry_state_is_rolled_back_and_kept_private():
    invalid = {**EVENT, "tenant_id": "wrong-tenant"}
    work = ScriptedConnection([("FROM rick_outbox", [outbox_row(payload=invalid)], 1)])
    retry = ScriptedConnection(
        [
            ("SELECT attempts", [{"attempts": 0}], 1),
            ("UPDATE rick_outbox", [{"attempts": 1}], 1),
        ],
        commit_error=RuntimeError("private retry-store failure"),
    )
    reconciler = PostgresAdminAuditReconciler(factory_for(work, retry))

    assert reconciler.process_once() == 0
    assert retry.rollbacks == 1
    assert retry.closed and retry.cursor_instance.closed
    assert "private retry-store failure" not in repr(retry.cursor_instance.queries)
