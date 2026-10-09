from types import SimpleNamespace

import pytest

from apps.api.tests.support import login_as


def test_persisted_history_json_decoder_rejects_oversized_and_nonfinite_values():
    from services.chat_history import _decode_json

    oversized = '{"answer":"' + ("a" * (256 * 1024)) + '"}'
    assert _decode_json(oversized, {}) == {}
    assert _decode_json('{"metadata":{"stream_ttft_ms":NaN}}', {}) == {}


def test_chat_history_and_sources_are_scoped_and_bounded(client):
    from services.chat_history import InMemoryChatHistoryStore

    client.app.state.providers.chat_history = InMemoryChatHistoryStore()
    login_as(client, "km@example.com")

    response = client.post("/api/v1/chat", json={"message": "Quais fontes estão disponíveis?"})
    assert response.status_code == 200, response.text

    history = client.get("/api/v1/history", params={"limit": 10})
    assert history.status_code == 200, history.text
    assert history.json()["total"] == 1
    item = history.json()["items"][0]
    assert item["question"] == "Quais fontes estão disponíveis?"
    assert "tenant_id" not in item and "user_id" not in item

    sources = client.get("/api/v1/sources", params={"limit": 10})
    assert sources.status_code == 200, sources.text
    # The stub no longer fabricates a source when no retrieval evidence exists.
    assert sources.json()["total"] == 0


def test_history_store_does_not_cross_user_scope(client):
    from services.chat_history import InMemoryChatHistoryStore

    client.app.state.providers.chat_history = InMemoryChatHistoryStore()
    login_as(client, "km@example.com")
    assert client.post("/api/v1/chat", json={"message": "pergunta privada"}).status_code == 200
    client.post("/api/v1/auth/logout")

    login_as(client, "vet@example.com")
    history = client.get("/api/v1/history")
    assert history.status_code == 200, history.text
    assert history.json()["total"] == 0


def test_chat_read_models_use_cursor_pagination_and_real_totals(client):
    from services.chat_history import InMemoryChatHistoryStore

    client.app.state.providers.chat_history = InMemoryChatHistoryStore()
    login_as(client, "km@example.com")
    for conversation_id in ("conv-page-a", "conv-page-b", "conv-page-c"):
        response = client.post(
            "/api/v1/chat",
            json={"message": f"pergunta {conversation_id}", "conversation_id": conversation_id},
        )
        assert response.status_code == 200, response.text

    first = client.get("/api/v1/conversations", params={"limit": 1})
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["total"] == 3
    assert len(first_body["items"]) == 1
    assert first_body["next_cursor"]

    second = client.get(
        "/api/v1/conversations",
        params={"limit": 1, "cursor": first_body["next_cursor"]},
    )
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert second_body["total"] == 3
    assert second_body["items"][0]["conversation_id"] != first_body["items"][0]["conversation_id"]

    history = client.get("/api/v1/history", params={"limit": 1})
    assert history.status_code == 200, history.text
    assert history.json()["total"] == 3
    assert history.json()["next_cursor"]


def test_sqlite_stream_terminal_outcome_survives_restart_and_stays_out_of_context(tmp_path):
    from types import SimpleNamespace

    from services.chat_history import SQLiteChatHistoryStore

    session = SimpleNamespace(tenant_id="tenant-a", workspace_id="workspace-a", user_id="user-a")
    path = tmp_path / "chat-history.sqlite3"
    store = SQLiteChatHistoryStore(path)
    store.record_stream_outcome(
        session=session, message="pergunta interrompida", conversation_id="conv-1",
        message_id="msg-1", status="partial", answer="resposta parcial",
        error_code="provider_timeout", metadata={"mode": "grounded", "stream_mode": "live"},
    )
    history = store.list_history(session=session)
    assert history[0]["metadata"]["stream_status"] == "partial"
    assert history[0]["metadata"]["error_code"] == "provider_timeout"
    assert store.get_context(session=session, conversation_id="conv-1") == []
    store.close()

    restarted = SQLiteChatHistoryStore(path)
    assert restarted.list_history(session=session)[0]["answer"] == "resposta parcial"
    assert restarted.list_history(session=session)[0]["metadata"]["stream_status"] == "partial"
    restarted.close()


@pytest.mark.parametrize("store_kind", ["memory", "sqlite"])
def test_context_limit_is_applied_after_incomplete_and_acl_filtering(tmp_path, store_kind):
    from services.chat_history import InMemoryChatHistoryStore, SQLiteChatHistoryStore

    session = SimpleNamespace(tenant_id="tenant-a", workspace_id="workspace-a", user_id="user-a")
    store = InMemoryChatHistoryStore() if store_kind == "memory" else SQLiteChatHistoryStore(tmp_path / "context.sqlite3")
    store.append(
        session=session, message="visível", response={
            "conversation_id": "conv-context", "message_id": "msg-visible", "answer": "resposta visível",
            "citations": [{"document_id": "doc-visible", "collection_id": "visible"}],
            "metadata": {"stream_status": "complete"},
        },
    )
    for index in range(8):
        store.record_stream_outcome(
            session=session, message=f"interrompida-{index}", conversation_id="conv-context",
            message_id=f"msg-partial-{index}", status="partial", answer="não usar",
        )
    assert store.get_context(
        session=session, conversation_id="conv-context", limit=1,
        allowed_collection_ids=["visible"],
    ) == [
        {"role": "user", "content": "visível"},
        {"role": "assistant", "content": "resposta visível"},
    ]
    page = store.list_sources_page(
        session=session, limit=10, allowed_collection_ids=["visible"],
    )
    assert page["total"] == 1
    assert page["items"][0]["document_id"] == "doc-visible"
    if hasattr(store, "close"):
        store.close()


@pytest.mark.parametrize("store_kind", ["memory", "sqlite"])
def test_incomplete_idempotent_outcome_is_replaced_by_retry(tmp_path, store_kind):
    from services.chat_history import InMemoryChatHistoryStore, SQLiteChatHistoryStore

    session = SimpleNamespace(tenant_id="tenant-a", workspace_id="workspace-a", user_id="user-a")
    store = InMemoryChatHistoryStore() if store_kind == "memory" else SQLiteChatHistoryStore(tmp_path / "retry.sqlite3")
    store.record_stream_outcome(
        session=session, message="pergunta", conversation_id="conv-retry", message_id="msg-partial",
        status="partial", answer="parcial", idempotency_key="retry-key",
    )
    assert store.get_idempotent(session=session, idempotency_key="retry-key") is None
    response = store.append(
        session=session, message="pergunta", idempotency_key="retry-key", response={
            "conversation_id": "conv-retry", "message_id": "msg-complete", "answer": "completa",
            "citations": [], "metadata": {"stream_status": "complete"},
        },
    )
    assert response["message_id"] == "msg-complete"
    assert store.get_idempotent(session=session, idempotency_key="retry-key") == response
    assert len(store.list_history(session=session)) == 1
    assert store.get_context(session=session, conversation_id="conv-retry", limit=1) == [
        {"role": "user", "content": "pergunta"},
        {"role": "assistant", "content": "completa"},
    ]
    if hasattr(store, "close"):
        store.close()


@pytest.mark.parametrize("store_kind", ["memory", "sqlite"])
def test_chat_response_metadata_is_projected_before_persist_and_replay(tmp_path, store_kind):
    import sqlite3
    from services.chat_history import InMemoryChatHistoryStore, SQLiteChatHistoryStore

    session = SimpleNamespace(tenant_id="tenant-a", workspace_id="workspace-a", user_id="user-a")
    path = tmp_path / "safe-history.sqlite3"
    store = InMemoryChatHistoryStore() if store_kind == "memory" else SQLiteChatHistoryStore(path)
    response = store.append(
        session=session,
        message="Pergunta",
        idempotency_key="safe-metadata",
        response={
            "conversation_id": "conv-safe", "message_id": "msg-safe", "answer": "Resposta",
            "citations": [],
            "metadata": {
                "backend": "openai", "mode": "grounded", "decision_action": "ANSWER",
                "provider_secret": "sk-live-secret-value", "prompt": "private prompt text",
                "provider_model": "sk-live-secret-value",
            },
        },
    )
    replay = store.get_idempotent(session=session, idempotency_key="safe-metadata")

    assert response["metadata"] == {"backend": "openai", "mode": "grounded", "decision_action": "ANSWER"}
    assert replay == response
    assert "provider_model" not in response["metadata"]
    if store_kind == "sqlite":
        with sqlite3.connect(path) as connection:
            (stored,) = connection.execute("SELECT response_json FROM chat_turns").fetchone()
        assert "sk-live-secret-value" not in stored
        assert "private prompt text" not in stored
    if hasattr(store, "close"):
        store.close()


def test_sqlite_history_read_sanitizes_metadata_from_legacy_rows(tmp_path):
    import json
    import sqlite3
    from services.chat_history import SQLiteChatHistoryStore

    session = SimpleNamespace(tenant_id="tenant-a", workspace_id="workspace-a", user_id="user-a")
    path = tmp_path / "legacy-metadata.sqlite3"
    store = SQLiteChatHistoryStore(path)
    store.append(
        session=session,
        message="Pergunta",
        response={
            "conversation_id": "conv-legacy", "message_id": "msg-legacy", "answer": "Resposta",
            "citations": [], "metadata": {"backend": "openai"},
        },
    )
    with sqlite3.connect(path) as connection:
        (encoded,) = connection.execute("SELECT response_json FROM chat_turns").fetchone()
        legacy = json.loads(encoded)
        legacy["metadata"] = {
            "backend": "openai", "evidence_status": "WEAK_EVIDENCE",
            "provider_model": "sk-old-secret", "prompt": "old private prompt",
        }
        connection.execute(
            "UPDATE chat_turns SET response_json=?", (json.dumps(legacy),),
        )

    history = store.list_history(session=session)
    assert history[0]["metadata"] == {
        "backend": "openai", "evidence_status": "WEAK_EVIDENCE",
    }
    assert "sk-old-secret" not in repr(history)
    assert "old private prompt" not in repr(history)
    store.close()


@pytest.mark.parametrize("store_kind", ["memory", "sqlite"])
def test_idempotent_replay_is_bound_to_conversation_and_fingerprint(tmp_path, store_kind):
    from services.chat_history import (
        IdempotencyConflict,
        InMemoryChatHistoryStore,
        SQLiteChatHistoryStore,
        idempotency_fingerprint,
    )

    session = SimpleNamespace(tenant_id="tenant-a", workspace_id="workspace-a", user_id="user-a")
    stranger = SimpleNamespace(tenant_id="tenant-a", workspace_id="workspace-a", user_id="user-b")
    path = tmp_path / "fingerprint.sqlite3"
    store = InMemoryChatHistoryStore() if store_kind == "memory" else SQLiteChatHistoryStore(path)
    alpha = idempotency_fingerprint(session=session, message="ALPHA", collection_id=None)
    stored = store.append(
        session=session, message="ALPHA", idempotency_key="fp-key", fingerprint=alpha,
        response={"conversation_id": "conv-A", "message_id": "msg-1", "answer": "A",
                  "citations": [], "metadata": {}},
    )

    assert store.get_idempotent(
        session=session, idempotency_key="fp-key",
        conversation_id="conv-A", fingerprint=alpha,
    ) == stored

    with pytest.raises(IdempotencyConflict):
        store.get_idempotent(
            session=session, idempotency_key="fp-key",
            conversation_id="conv-B", fingerprint=alpha,
        )
    with pytest.raises(IdempotencyConflict):
        store.append(
            session=session, message="BETA", idempotency_key="fp-key",
            fingerprint=idempotency_fingerprint(session=session, message="BETA", collection_id=None),
            response={"conversation_id": "conv-B", "message_id": "msg-2", "answer": "B",
                      "citations": [], "metadata": {}},
        )
    with pytest.raises(IdempotencyConflict):
        store.get_idempotent(
            session=session, idempotency_key="fp-key", conversation_id="conv-A",
            fingerprint=idempotency_fingerprint(session=session, message="ALPHA", collection_id="guides"),
        )

    assert store.get_idempotent(
        session=stranger, idempotency_key="fp-key",
        conversation_id="conv-A", fingerprint=alpha,
    ) is None
    if hasattr(store, "close"):
        store.close()


def test_sqlite_idempotent_conflict_survives_a_restart(tmp_path):
    from services.chat_history import SQLiteChatHistoryStore, idempotency_fingerprint

    session = SimpleNamespace(tenant_id="tenant-a", workspace_id="workspace-a", user_id="user-a")
    path = tmp_path / "restart.sqlite3"
    alpha = idempotency_fingerprint(session=session, message="ALPHA", collection_id=None)
    store = SQLiteChatHistoryStore(path)
    store.append(
        session=session, message="ALPHA", idempotency_key="restart-key", fingerprint=alpha,
        response={"conversation_id": "conv-A", "message_id": "msg-1", "answer": "A",
                  "citations": [], "metadata": {}},
    )
    store.close()

    reopened = SQLiteChatHistoryStore(path)
    assert reopened.get_idempotent(
        session=session, idempotency_key="restart-key",
        conversation_id="conv-A", fingerprint=alpha,
    ) is not None
    reopened.close()


def test_sqlite_idempotent_row_without_a_fingerprint_fails_closed(tmp_path):
    import sqlite3

    from services.chat_history import IdempotencyConflict, SQLiteChatHistoryStore, idempotency_fingerprint

    session = SimpleNamespace(tenant_id="tenant-a", workspace_id="workspace-a", user_id="user-a")
    path = tmp_path / "legacy-fingerprint.sqlite3"
    store = SQLiteChatHistoryStore(path)
    store.append(
        session=session, message="ALPHA", idempotency_key="legacy-key",
        response={"conversation_id": "conv-A", "message_id": "msg-1", "answer": "A",
                  "citations": [], "metadata": {}},
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE chat_turns SET idempotency_fingerprint=NULL WHERE idempotency_key=?",
            ("legacy-key",),
        )
        connection.commit()

    with pytest.raises(IdempotencyConflict):
        store.get_idempotent(
            session=session, idempotency_key="legacy-key", conversation_id="conv-A",
            fingerprint=idempotency_fingerprint(session=session, message="ALPHA", collection_id=None),
        )
    assert store.get_idempotent(session=session, idempotency_key="legacy-key") is not None
    store.close()


def test_sqlite_chat_history_migrates_a_v1_database(tmp_path):
    import sqlite3

    from services.chat_history import SQLiteChatHistoryStore

    path = tmp_path / "v1.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE conversations (
                conversation_id TEXT NOT NULL, tenant_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL, user_id TEXT NOT NULL, title TEXT NOT NULL,
                collection_id TEXT, status TEXT NOT NULL,
                created_at REAL NOT NULL, updated_at REAL NOT NULL,
                PRIMARY KEY (tenant_id, workspace_id, user_id, conversation_id)
            );
            CREATE TABLE chat_turns (
                message_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL, workspace_id TEXT NOT NULL, user_id TEXT NOT NULL,
                question TEXT NOT NULL, answer TEXT NOT NULL, citations_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL, response_json TEXT NOT NULL,
                idempotency_key TEXT, created_at REAL NOT NULL,
                PRIMARY KEY (tenant_id, workspace_id, user_id, message_id),
                UNIQUE (tenant_id, workspace_id, user_id, idempotency_key)
            );
            PRAGMA user_version = 1;
            """
        )
        connection.commit()

    store = SQLiteChatHistoryStore(path)
    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(chat_turns)")}
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    assert "idempotency_fingerprint" in columns
    assert version == SQLiteChatHistoryStore.SCHEMA_VERSION
    store.close()
