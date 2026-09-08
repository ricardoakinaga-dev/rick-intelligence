from __future__ import annotations

from datetime import datetime, timezone

from services.postgres_audit import PostgresAuditSink


class Cursor:
    def __init__(self, steps):
        self.steps = list(steps)
        self.queries = []
        self._rows = []
        self.description = None

    def execute(self, query, params=()):
        self.queries.append((query, params))
        expected, rows = self.steps.pop(0)
        assert expected in query
        self._rows = list(rows)

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
    return lambda: remaining.pop(0)


def test_append_sanitizes_and_list_applies_tenant_scope_at_query_time():
    write = Connection([("INSERT INTO rick_audit_events", [])])
    read = Connection([("FROM rick_audit_events", [{
        "action": "document.publish",
        "actor_user_id": "user-a",
        "target_id": "doc-a",
        "target_type": "document",
        "tenant_id": "tenant-a",
        "workspace_id": "workspace-a",
        "request_id": "request-a",
        "metadata": {"status": "published"},
        "occurred_at": datetime(2026, 9, 8, tzinfo=timezone.utc),
    }])])
    store = PostgresAuditSink(factory_for(write, read))

    assert store.append({
        "action": "document.publish", "tenant_id": "tenant-a", "actor_user_id": "user-a",
        "workspace_id": "workspace-a", "target_id": "doc-a", "status": "published",
        "document_content": "private document should not persist",
    })
    events = store.list(tenant_id="tenant-a", workspace_id="workspace-a")

    params = write.cursor_instance.queries[0][1]
    assert "private document" not in repr(params)
    assert events[0]["tenant_id"] == "tenant-a"
    assert events[0]["status"] == "published"
    assert events[0]["occurred_at"].startswith("2026-09-08")
    query, query_params = read.cursor_instance.queries[0]
    assert "tenant_id=%s" in query
    assert query_params[:2] == ("tenant-a", "workspace-a")
    assert write.commits == 1


def test_malformed_or_unscoped_events_are_dropped_without_database_access():
    calls = []

    def factory():
        calls.append(True)
        raise AssertionError("invalid event must not open a connection")

    store = PostgresAuditSink(factory)
    assert not store.append({"action": "document.publish", "target_id": "doc-a"})
    assert not calls
