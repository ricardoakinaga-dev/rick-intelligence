"""Behavioral tests for the local durable audit adapter."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import stat

from services.sqlite_audit import SCHEMA_VERSION, SQLiteAuditSink


def test_append_list_limit_and_order(tmp_path: Path):
    sink = SQLiteAuditSink(tmp_path / "audit" / "events.sqlite3", max_events=10)
    assert sink.append({"sequence": 1}) is True
    assert sink.append({"sequence": 2}) is True
    assert sink.append({"sequence": 3}) is True

    assert [item["sequence"] for item in sink.list(limit=2, order="asc")] == [1, 2]
    assert [item["sequence"] for item in sink.list(limit=2, order="desc")] == [3, 2]
    assert [item["sequence"] for item in sink.events] == [1, 2, 3]
    assert sink.list(limit=0) == []
    sink.close()


def test_file_permissions_schema_and_wal(tmp_path: Path):
    parent = tmp_path / "private-audit"
    parent.mkdir(mode=0o755)
    database = parent / "events.sqlite3"
    sink = SQLiteAuditSink(database)
    sink.append({"action": "permission-check"})

    assert stat.S_IMODE(parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(database.stat().st_mode) == 0o600
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    sink.close()


def test_events_survive_close_and_reopen(tmp_path: Path):
    database = tmp_path / "audit" / "events.sqlite3"
    first = SQLiteAuditSink(database, retention=10)
    first.append({"action": "restart", "request_id": "req-1"})
    first.close()

    second = SQLiteAuditSink(database, retention=10)
    assert second.list(order="asc") == [{"action": "restart", "request_id": "req-1"}]
    second.close()


def test_retention_keeps_only_newest_events_and_is_reapplied_on_reopen(tmp_path: Path):
    database = tmp_path / "audit" / "events.sqlite3"
    first = SQLiteAuditSink(database, max_events=3)
    for sequence in range(5):
        assert first.append({"sequence": sequence}) is True
    assert [item["sequence"] for item in first.events] == [2, 3, 4]
    first.close()

    second = SQLiteAuditSink(database, max_events=2)
    assert [item["sequence"] for item in second.events] == [3, 4]
    second.close()


def test_basic_concurrency_serializes_writers_and_preserves_retention(tmp_path: Path):
    database = tmp_path / "audit" / "events.sqlite3"
    sinks = [SQLiteAuditSink(database, max_events=200) for _ in range(4)]

    def write(index: int) -> bool:
        return sinks[index % len(sinks)].append({"writer": index % len(sinks), "sequence": index})

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(write, range(120)))

    assert all(results)
    assert len(sinks[0].list(order="asc")) == 120
    assert {item["sequence"] for item in sinks[1].events} == set(range(120))
    for sink in sinks:
        sink.close()


def test_malformed_events_are_safe_and_secrets_are_redacted(tmp_path: Path):
    sink = SQLiteAuditSink(tmp_path / "audit" / "events.sqlite3")
    cycle: dict[str, object] = {}
    cycle["cycle"] = cycle
    malformed = [None, [], {"bad": object()}, {"bad": {"set-value"}}, cycle, {"bad": float("nan")}]

    for event in malformed:
        assert sink.append(event) is False
        sink.emit(event)
    assert sink.events == []

    original = {
        "action": "auth.login",
        "password": "do-not-store",
        "nested": {"authorization": "Bearer do-not-store"},
        "safe": ["value", 1],
    }
    assert sink.append(original) is True
    stored = sink.list(order="asc")[0]
    assert stored == {"action": "auth.login"}
    assert "do-not-store" not in json.dumps(stored)
    assert original["password"] == "do-not-store"

    opaque = {
        "action": "chat.query",
        "opaque": "synthetic secret and private document content",
        "target_id": "https://example.test/audit?token=secret",
        "nested": {"document_content": "private document"},
    }
    assert sink.append(opaque) is True
    stored_opaque = sink.list(order="desc")[0]
    assert stored_opaque["target_id"] == "https://example.test/audit"
    assert "opaque" not in stored_opaque
    assert "nested" not in stored_opaque
    assert "synthetic secret" not in json.dumps(stored_opaque)

    userinfo = {
        "action": "url.audit",
        "target_id": "https://alice:p%40ss123@example.test/a?token=secret#fragment",
    }
    assert sink.append(userinfo) is True
    stored_userinfo = sink.list(order="desc")[0]
    assert stored_userinfo["target_id"] == "https://example.test/a"
    assert "alice" not in json.dumps(stored_userinfo)
    assert "p%40ss123" not in json.dumps(stored_userinfo)

    non_http_userinfo = {
        "action": "url.audit.non_http",
        "target_id": "postgres://alice:secret@example.test/a?password=secret#fragment",
    }
    assert sink.append(non_http_userinfo) is True
    stored_non_http = sink.list(order="desc")[0]
    assert stored_non_http["target_id"] == "postgres://example.test/a"
    assert "alice" not in json.dumps(stored_non_http)
    assert "secret" not in json.dumps(stored_non_http)

    # No-action adapter records still pass through an explicit narrow
    # diagnostic allowlist; arbitrary opaque fields are rejected.
    assert sink.append({"opaque": "safe-looking but not an audit field"}) is False

    bounded = {"payload": list(range(200))}
    assert sink.append(bounded) is True
    assert len(sink.list(order="desc")[0]["payload"]) == 64

    oversized = {"payload": ["x" * 512 for _ in range(64)], "second": ["y" * 512 for _ in range(64)]}
    assert sink.append(oversized) is False
    sink.close()


def test_persisted_event_json_is_bounded_and_finite(tmp_path: Path):
    database = tmp_path / "audit" / "events.sqlite3"
    sink = SQLiteAuditSink(database)
    assert sink.append({"action": "persisted.boundary", "status": "ok"}) is True
    sink.close()

    with sqlite3.connect(database) as connection:
        oversized = '{"action":"persisted.boundary"}' + (" " * (64 * 1024))
        connection.execute("UPDATE audit_events SET event_json=?", (oversized,))
        connection.commit()

    reopened = SQLiteAuditSink(database)
    assert reopened.events == []
    reopened.close()

    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE audit_events SET event_json=?",
            ('{"action":"persisted.boundary","status":NaN}',),
        )
        connection.commit()

    reopened = SQLiteAuditSink(database)
    assert reopened.events == []
    reopened.close()
