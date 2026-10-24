from __future__ import annotations

from audit_reconcile import operation_event, reconcile_pending


class Store:
    def __init__(self, rows):
        self.rows = rows
        self.acknowledged = []
        self.retried = []
        self.failed = []

    def pending(self, *, limit, older_than_seconds):
        return self.rows[:limit]

    def acknowledge(self, operation_id):
        self.acknowledged.append(operation_id)
        return True

    def retry(self, operation_id, error_code):
        self.retried.append((operation_id, error_code))
        return True

    def fail(self, operation_id, error_code):
        self.failed.append((operation_id, error_code))
        return True


class Sink:
    def __init__(self, results):
        self.results = list(results)
        self.events = []

    def emit(self, event):
        self.events.append(event)
        return self.results.pop(0)


def test_reconcile_projects_and_closes_terminal_outcomes():
    store = Store([
        {"operation_id": "op-ok", "action": "auth.logout", "request_id": "r1", "tenant_id": "t", "attempts": 0},
        {"operation_id": "op-retry", "action": "auth.logout", "request_id": "r2", "tenant_id": "t", "attempts": 1},
        {"operation_id": "op-fail", "action": "auth.logout", "request_id": "r3", "tenant_id": "t", "attempts": 4},
    ])
    sink = Sink([True, False, False])
    summary = reconcile_pending(store, sink, max_attempts=5)
    assert summary == {"scanned": 3, "acknowledged": 1, "retried": 1, "failed": 1, "errors": 0}
    assert store.acknowledged == ["op-ok"]
    assert store.retried == [("op-retry", "projection_failed")]
    assert store.failed == [("op-fail", "projection_failed")]
    assert sink.events[0]["status"] == "effect_applied"
    assert sink.events[0]["request_id"] == "r1"


def test_reconcile_counts_one_bad_row_without_aborting_the_batch():
    store = Store([
        {"operation_id": "", "action": "auth.logout", "request_id": "bad", "attempts": 0},
        {"operation_id": "op-ok", "action": "auth.logout", "request_id": "r1", "tenant_id": "t", "attempts": 0},
    ])
    summary = reconcile_pending(store, Sink([True]))
    assert summary["errors"] == 1
    assert summary["acknowledged"] == 1


def test_operation_event_omits_empty_scope():
    event = operation_event({"operation_id": "op", "action": "auth.reset_effect", "request_id": "r", "tenant_id": None})
    assert "tenant_id" not in event
    assert event["action"] == "auth.reset_effect"
