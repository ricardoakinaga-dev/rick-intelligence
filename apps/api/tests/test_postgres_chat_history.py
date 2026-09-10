from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.postgres_chat_history import PostgresChatHistoryError, PostgresChatHistoryStore, _json


SESSION = SimpleNamespace(tenant_id="tenant-a", workspace_id="workspace-a", user_id="user-a")


def test_database_json_decoder_rejects_oversized_and_nonfinite_history_values() -> None:
    oversized = '{"answer":"' + ("a" * (256 * 1024)) + '"}'

    assert _json(oversized, {}) == {}
    assert _json('{"metadata":{"stream_ttft_ms":NaN}}', {}) == {}


class Cursor:
    def __init__(self, steps):
        self.steps = list(steps)
        self.queries = []
        self._rows = []
        self.rowcount = 0
        self.description = None

    def execute(self, query, params=()):
        self.queries.append((query, params))
        if not self.steps:
            raise AssertionError(f"unexpected query: {query}")
        expected, rows, rowcount = self.steps.pop(0)
        if expected not in query:
            raise AssertionError(f"expected {expected!r}, got {query!r}")
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
        return remaining.pop(0)

    return factory


def conversation_row():
    return {
        "conversation_id": "conv-1",
        "title": "Consulta",
        "workspace_id": "workspace-a",
        "collection_id": "guides",
        "status": "active",
        "created_at": 100.0,
        "updated_at": 101.0,
        "message_count": 2,
    }


def test_create_conversation_is_scoped_and_restart_safe_at_the_adapter_boundary():
    connection = Connection([
        ("SELECT status FROM rick_conversations", [], 0),
        ("INSERT INTO rick_conversations", [], 1),
        ("GROUP BY c.conversation_id", [conversation_row()], 1),
    ])
    store = PostgresChatHistoryStore(factory_for(connection))

    result = store.create_conversation(
        session=SESSION, conversation_id="conv-1", title="Consulta", collection_id="guides",
    )

    assert result["conversation_id"] == "conv-1"
    assert result["workspace_id"] == "workspace-a"
    assert connection.commits == 1
    assert "tenant_id=%s" in connection.cursor_instance.queries[0][0]
    assert "workspace_id=%s" in connection.cursor_instance.queries[0][0]
    assert connection.closed


def test_append_writes_user_and_assistant_in_one_transaction_and_replays_idempotency():
    response = {
        "conversation_id": "conv-1", "message_id": "msg-1", "answer": "Resposta",
        "citations": [{"document_id": "doc-1", "chunk_id": "chunk-1", "title": "Guia"}],
        "metadata": {"evidence_status": "APPROVED_EVIDENCE"},
    }
    write = Connection([
        ("SELECT metadata FROM rick_messages", [], 0),
        ("SELECT status FROM rick_conversations", [], 0),
        ("INSERT INTO rick_conversations", [], 1),
        ("INSERT INTO rick_messages", [], 1),
        ("INSERT INTO rick_messages", [], 1),
        ("UPDATE rick_conversations", [], 1),
    ])
    replay = Connection([
        ("SELECT metadata FROM rick_messages", [{"metadata": {"response": response}}], 1),
    ])
    store = PostgresChatHistoryStore(factory_for(write, replay))

    stored = store.append(session=SESSION, message="Pergunta", response=response, idempotency_key="retry-1")
    repeated = store.get_idempotent(session=SESSION, idempotency_key="retry-1")

    assert stored == response
    assert repeated == response
    assert write.commits == 1
    assert len([query for query, _ in write.cursor_instance.queries if "INSERT INTO rick_messages" in query]) == 2


def test_archived_conversation_and_invalid_message_id_fail_closed():
    archived = Connection([
        ("SELECT status FROM rick_conversations", [{"status": "archived"}], 1),
    ])
    store = PostgresChatHistoryStore(factory_for(archived))

    with pytest.raises(PostgresChatHistoryError) as error:
        store.append(
            session=SESSION,
            message="Pergunta",
            response={"conversation_id": "conv-1", "message_id": "msg-1", "answer": "ok"},
        )
    assert error.value.code == "conflict"
    assert archived.rollbacks == 1

    with pytest.raises(PostgresChatHistoryError) as invalid:
        store.append(
            session=SESSION,
            message="Pergunta",
            response={"conversation_id": "conv-1", "message_id": "bad\nmessage", "answer": "ok"},
        )
    assert invalid.value.code == "invalid_input"
