from __future__ import annotations

import pytest

from services.audit_operations_store import AuditOperationError, PostgresAuditOperationStore


class Cursor:
    def __init__(self, steps):
        self.steps = list(steps)
        self.queries = []
        self.rowcount = 0
        self._rows = []
        self.description = None

    def execute(self, query, params=()):
        self.queries.append((query, params))
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


def test_begin_is_idempotent_and_marks_requested():
    connection = Connection([("INSERT INTO rick_audit_operations", [], 1)])
    store = PostgresAuditOperationStore(lambda: connection)
    store.begin(
        operation_id="op-1", action="auth.logout", request_id="req-1",
        tenant_id="tenant-1", actor_user_id="user-1", workspace_id="workspace-1",
        payload={"request_id": "req-1"},
    )
    query, params = connection.cursor_instance.queries[0]
    assert "ON CONFLICT (action, request_id) DO NOTHING" in query
    assert params[0] == "op-1" and params[1] == "auth.logout"
    assert connection.commits == 1


def test_mark_effect_is_idempotent_when_row_is_already_effect_applied():
    connection = Connection([
        ("UPDATE rick_audit_operations", [], 0),
        ("SELECT state FROM rick_audit_operations", [{"state": "effect_applied"}], 0),
    ])
    store = PostgresAuditOperationStore(lambda: connection)
    assert store.mark_effect("op-1", connection=connection) is True


def test_acknowledge_and_failure_are_terminal():
    acknowledged = Connection([("UPDATE rick_audit_operations", [], 1)])
    failed = Connection([("UPDATE rick_audit_operations", [], 1)])
    store = PostgresAuditOperationStore(lambda: acknowledged)
    assert store.acknowledge("op-1") is True
    store = PostgresAuditOperationStore(lambda: failed)
    assert store.fail("op-2", "projection_failed") is True
    assert "attempts = attempts + 1" in failed.cursor_instance.queries[0][0]


def test_pending_is_bounded_and_ordered():
    connection = Connection([("SELECT * FROM rick_audit_operations", [{"operation_id": "op-1"}], 0)])
    store = PostgresAuditOperationStore(lambda: connection)
    rows = store.pending(limit=10, older_than_seconds=30)
    assert rows == [{"operation_id": "op-1"}]
    query, params = connection.cursor_instance.queries[0]
    assert "ORDER BY updated_at ASC" in query
    assert params == (30, 10)


def test_invalid_tokens_are_rejected_without_database_access():
    store = PostgresAuditOperationStore(lambda: pytest.fail("must not open a connection"))
    with pytest.raises(AuditOperationError):
        store.begin(operation_id="bad id", action="auth.logout", request_id="req-1")
    with pytest.raises(AuditOperationError):
        store.begin(operation_id="op-1", action="auth.logout", request_id="bad id")


def test_indeterminate_keeps_an_effect_without_acknowledgement_visible():
    connection = Connection([("UPDATE rick_audit_operations", [], 1)])
    store = PostgresAuditOperationStore(lambda: connection)
    assert store.indeterminate("op-1", "effect_unknown") is True
    assert "state = 'indeterminate'" in connection.cursor_instance.queries[0][0]
