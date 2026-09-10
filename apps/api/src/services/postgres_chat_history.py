"""PostgreSQL conversation read/write adapter.

The API service keeps this adapter behind the same small methods used by the
local chat-history stores. A connection factory is injected; every query is
scoped by tenant, workspace, and user. User and assistant messages are
written in one transaction, with the client idempotency key attached only to
the user message so a retry cannot create a second turn.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
import json
import time
import uuid
from datetime import datetime
from typing import Protocol

from services.chat_history import (
    InMemoryChatHistoryStore,
    STREAM_CONTEXT_EXCLUDED_STATUSES,
    STREAM_TERMINAL_STATUSES,
    _decode_json,
    _bounded_page,
    _filter_citations,
    _turn_allowed,
    _scope,
)


class DbConnection(Protocol):
    def cursor(self) -> object: ...
    def commit(self) -> object: ...
    def rollback(self) -> object: ...
    def close(self) -> object: ...


class PostgresChatHistoryError(RuntimeError):
    def __init__(self, code: str = "conversation_unavailable") -> None:
        self.code = code if code in {"conversation_unavailable", "invalid_input", "not_found", "conflict"} else "conversation_unavailable"
        super().__init__(self.code)


def _row_dict(cursor: object, row: object) -> dict[str, object]:
    if isinstance(row, Mapping):
        return {str(key): value for key, value in row.items()}
    description = getattr(cursor, "description", None) or ()
    names = [item[0] for item in description if isinstance(item, (tuple, list)) and item]
    return dict(zip(names, row if isinstance(row, (tuple, list)) else ()))


def _json(value: object, default: object) -> object:
    return _decode_json(value, default)


def _timestamp(value: object) -> float | object:
    if isinstance(value, datetime):
        return value.timestamp()
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def _conversation_id(value: object) -> str:
    if not isinstance(value, str):
        raise PostgresChatHistoryError("invalid_input")
    candidate = value.strip()
    if not candidate or len(candidate) > 128 or any(ord(char) < 0x20 or ord(char) == 0x7F for char in candidate):
        raise PostgresChatHistoryError("invalid_input")
    return candidate


def _bounded_key(value: object, *, maximum: int = 128) -> str:
    if not isinstance(value, str):
        raise PostgresChatHistoryError("invalid_input")
    candidate = value.strip()
    if not candidate or len(candidate) > maximum or any(ord(char) < 0x20 or ord(char) == 0x7F for char in candidate):
        raise PostgresChatHistoryError("invalid_input")
    return candidate


def _stored_stream_status(metadata: object) -> object:
    if not isinstance(metadata, Mapping):
        return None
    status = metadata.get("stream_status")
    if status is not None:
        return status
    response = metadata.get("response")
    if isinstance(response, Mapping):
        response_metadata = response.get("metadata")
        if isinstance(response_metadata, Mapping):
            return response_metadata.get("stream_status")
    return None


class PostgresChatHistoryStore:
    """Transactional implementation of the API chat-history port."""

    max_answer_chars = 8_000

    def __init__(self, connection_factory: Callable[[], DbConnection], *, close_connections: bool = True) -> None:
        if not callable(connection_factory):
            raise PostgresChatHistoryError("invalid_input")
        self._connection_factory = connection_factory
        self._close_connections = close_connections

    @contextmanager
    def _session(self, *, write: bool = False) -> Iterator[tuple[DbConnection, object]]:
        connection: DbConnection | None = None
        cursor: object | None = None
        try:
            connection = self._connection_factory()
            if connection is None:
                raise PostgresChatHistoryError()
            cursor = connection.cursor()
            yield connection, cursor
            if write:
                connection.commit()
        except PostgresChatHistoryError:
            if write and connection is not None:
                try:
                    connection.rollback()
                except Exception:
                    pass
            raise
        except Exception:
            if write and connection is not None:
                try:
                    connection.rollback()
                except Exception:
                    pass
            raise PostgresChatHistoryError() from None
        finally:
            if cursor is not None:
                close = getattr(cursor, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        pass
            if self._close_connections and connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

    @staticmethod
    def _execute(cursor: object, query: str, params: tuple[object, ...] = ()) -> None:
        execute = getattr(cursor, "execute", None)
        if not callable(execute):
            raise PostgresChatHistoryError()
        execute(query, params)

    @staticmethod
    def _one(cursor: object) -> dict[str, object] | None:
        row = getattr(cursor, "fetchone", lambda: None)()
        return None if row is None else _row_dict(cursor, row)

    @staticmethod
    def _many(cursor: object) -> list[dict[str, object]]:
        return [_row_dict(cursor, row) for row in getattr(cursor, "fetchall", lambda: [])()]

    @staticmethod
    def _public(row: Mapping[str, object]) -> dict[str, object]:
        return {
            "conversation_id": row.get("conversation_id"),
            "title": row.get("title") or "Nova conversa",
            "workspace_id": row.get("workspace_id"),
            "collection_id": row.get("collection_id"),
            "status": row.get("status") or "active",
            "created_at": _timestamp(row.get("created_at")),
            "updated_at": _timestamp(row.get("updated_at")),
            "message_count": max(0, int(row.get("message_count") or 0)),
        }

    def _conversation(self, cursor: object, scope: tuple[str, str, str], conversation_id: str) -> dict[str, object] | None:
        self._execute(cursor, """
            SELECT c.conversation_id, c.title, c.workspace_id, c.collection_id,
                   c.status, c.created_at, c.updated_at,
                   COUNT(m.message_id)::integer AS message_count
            FROM rick_conversations c
            LEFT JOIN rick_messages m ON m.conversation_id = c.conversation_id
            WHERE c.tenant_id = %s AND c.workspace_id = %s AND c.user_id = %s
              AND c.conversation_id = %s
            GROUP BY c.conversation_id, c.title, c.workspace_id, c.collection_id,
                     c.status, c.created_at, c.updated_at
        """, (*scope, conversation_id))
        return self._one(cursor)

    def create_conversation(self, *, session: object, conversation_id: str | None = None,
                            title: str | None = None, collection_id: str | None = None) -> dict[str, object]:
        scope = _scope(session)
        conversation_id = _conversation_id(conversation_id or f"conv-{uuid.uuid4().hex[:16]}")
        title = (title or "Nova conversa").strip()[:160] or "Nova conversa"
        collection = (collection_id or "").strip()[:128] or None
        with self._session(write=True) as (_connection, cursor):
            self._execute(cursor, "SELECT status FROM rick_conversations WHERE tenant_id=%s AND workspace_id=%s AND user_id=%s AND conversation_id=%s FOR UPDATE", (*scope, conversation_id))
            existing = self._one(cursor)
            if existing and existing.get("status") == "archived":
                raise PostgresChatHistoryError("conflict")
            self._execute(cursor, """
                INSERT INTO rick_conversations
                    (conversation_id, tenant_id, workspace_id, user_id, collection_id, title, status)
                VALUES (%s, %s, %s, %s, %s, %s, 'active')
                ON CONFLICT (conversation_id) DO NOTHING
            """, (conversation_id, *scope, collection, title))
            row = self._conversation(cursor, scope, conversation_id)
        if row is None:
            raise PostgresChatHistoryError()
        return self._public(row)

    def ensure_conversation(self, **kwargs):
        return self.create_conversation(**kwargs)

    def get_conversation(self, *, session: object, conversation_id: str) -> dict[str, object] | None:
        scope = _scope(session)
        conversation_id = _conversation_id(conversation_id)
        with self._session() as (_connection, cursor):
            row = self._conversation(cursor, scope, conversation_id)
        return self._public(row) if row else None

    def list_conversations_page(
        self, *, session: object, limit: int = 50, offset: int = 0,
    ) -> dict[str, object]:
        bounded, bounded_offset = _bounded_page(limit, offset)
        scope = _scope(session)
        with self._session() as (_connection, cursor):
            self._execute(cursor, "SELECT COUNT(*) AS total FROM rick_conversations WHERE tenant_id=%s AND workspace_id=%s AND user_id=%s", scope)
            total_row = self._one(cursor) or {}
            total = int(total_row.get("total") or 0)
            self._execute(cursor, """
                SELECT c.conversation_id, c.title, c.workspace_id, c.collection_id,
                       c.status, c.created_at, c.updated_at, COUNT(m.message_id)::integer AS message_count
                FROM rick_conversations c
                LEFT JOIN rick_messages m ON m.conversation_id = c.conversation_id
                WHERE c.tenant_id=%s AND c.workspace_id=%s AND c.user_id=%s
                GROUP BY c.conversation_id, c.title, c.workspace_id, c.collection_id,
                         c.status, c.created_at, c.updated_at
                ORDER BY c.updated_at DESC, c.conversation_id LIMIT %s OFFSET %s
            """, (*scope, bounded, bounded_offset))
            rows = self._many(cursor)
        items = [self._public(row) for row in rows]
        next_offset = bounded_offset + bounded if bounded_offset + bounded < total else None
        return {"items": items, "total": total, "next_offset": next_offset}

    def list_conversations(self, *, session: object, limit: int = 50) -> list[dict[str, object]]:
        return self.list_conversations_page(session=session, limit=limit)["items"]  # type: ignore[return-value]

    def archive_conversation(self, *, session: object, conversation_id: str) -> bool:
        scope = _scope(session)
        conversation_id = _conversation_id(conversation_id)
        with self._session(write=True) as (_connection, cursor):
            self._execute(cursor, "UPDATE rick_conversations SET status='archived', updated_at=NOW() WHERE tenant_id=%s AND workspace_id=%s AND user_id=%s AND conversation_id=%s", (*scope, conversation_id))
            return int(getattr(cursor, "rowcount", 0) or 0) == 1

    def get_context(
        self, *, session: object, conversation_id: str, limit: int = 12,
        allowed_collection_ids: object = None,
    ) -> list[dict[str, str]]:
        bounded = min(50, max(0, int(limit)))
        scope = _scope(session)
        conversation_id = _conversation_id(conversation_id)
        with self._session() as (_connection, cursor):
            self._execute(cursor, """
                SELECT role, content, citations, metadata FROM rick_messages
                WHERE tenant_id=%s AND workspace_id=%s AND user_id=%s AND conversation_id=%s
                ORDER BY created_at DESC, message_id DESC
            """, (*scope, conversation_id))
            rows = self._many(cursor)
        messages: list[dict[str, str]] = []
        for row in reversed(rows):
            role = row.get("role")
            if role not in {"user", "assistant"}:
                continue
            metadata = _json(row.get("metadata"), {})
            if role == "assistant":
                if not _turn_allowed(_json(row.get("citations"), []), allowed_collection_ids):
                    if messages and messages[-1].get("role") == "user":
                        messages.pop()
                    continue
                if isinstance(metadata, Mapping) and metadata.get("stream_status") in STREAM_CONTEXT_EXCLUDED_STATUSES:
                    if messages and messages[-1].get("role") == "user":
                        messages.pop()
                    continue
            messages.append({"role": str(role), "content": str(row.get("content") or "")})
        return messages[-bounded * 2:] if bounded else []

    def get_idempotent(self, *, session: object, idempotency_key: str) -> dict[str, object] | None:
        scope = _scope(session)
        key = _bounded_key(idempotency_key)
        with self._session() as (_connection, cursor):
            self._execute(cursor, """
                SELECT metadata FROM rick_messages
                WHERE tenant_id=%s AND workspace_id=%s AND user_id=%s
                  AND role='user' AND idempotency_key=%s LIMIT 1
            """, (*scope, key))
            row = self._one(cursor)
        metadata = _json(row.get("metadata"), {}) if row else {}
        response = metadata.get("response") if isinstance(metadata, Mapping) else None
        if _stored_stream_status(metadata) in STREAM_CONTEXT_EXCLUDED_STATUSES:
            return None
        return dict(response) if isinstance(response, Mapping) else None

    def append(self, *, session: object, message: str, response: Mapping[str, object],
               idempotency_key: str | None = None) -> dict[str, object]:
        scope = _scope(session)
        conversation_id = _conversation_id(response.get("conversation_id"))
        message_id = _bounded_key(response.get("message_id"))
        key = _bounded_key(idempotency_key) if idempotency_key is not None else None
        answer = str(response.get("answer") or "")[: self.max_answer_chars]
        citations = InMemoryChatHistoryStore._safe_citations(response.get("citations"))
        safe_response = {
            "conversation_id": conversation_id,
            "message_id": message_id,
            "answer": answer,
            "citations": citations,
            "metadata": dict(response.get("metadata") or {}) if isinstance(response.get("metadata"), Mapping) else {},
        }
        user_message_id = f"user-{uuid.uuid5(uuid.NAMESPACE_URL, f'{scope}:{conversation_id}:{message_id}').hex[:24]}"
        with self._session(write=True) as (_connection, cursor):
            if key:
                self._execute(cursor, "SELECT metadata FROM rick_messages WHERE tenant_id=%s AND workspace_id=%s AND user_id=%s AND role='user' AND idempotency_key=%s FOR UPDATE", (*scope, key))
                existing = self._one(cursor)
                if existing:
                    stored = _json(existing.get("metadata"), {})
                    replay = stored.get("response") if isinstance(stored, Mapping) else None
                    stream_status = _stored_stream_status(stored)
                    if stream_status not in STREAM_CONTEXT_EXCLUDED_STATUSES:
                        return dict(replay) if isinstance(replay, Mapping) else dict(response)
                    old_user_message_id = existing.get("message_id")
                    if not isinstance(old_user_message_id, str) or not old_user_message_id:
                        self._execute(cursor, "SELECT message_id, conversation_id FROM rick_messages WHERE tenant_id=%s AND workspace_id=%s AND user_id=%s AND role='user' AND idempotency_key=%s FOR UPDATE", (*scope, key))
                        existing_ids = self._one(cursor) or {}
                        old_user_message_id = existing_ids.get("message_id")
                    old_assistant_message_id = replay.get("message_id") if isinstance(replay, Mapping) else None
                    if not isinstance(old_user_message_id, str) or not old_user_message_id:
                        old_user_message_id = user_message_id
                    if not isinstance(old_assistant_message_id, str) or not old_assistant_message_id:
                        old_assistant_message_id = message_id
                    self._execute(cursor, """
                        UPDATE rick_messages SET conversation_id=%s, content=%s,
                            metadata=CAST(%s AS jsonb)
                        WHERE tenant_id=%s AND workspace_id=%s AND user_id=%s
                          AND message_id=%s AND role='user'
                    """, (conversation_id, str(message or "")[:20_000],
                           json.dumps({"response": safe_response}, ensure_ascii=False, separators=(",", ":")),
                           *scope, old_user_message_id))
                    assistant_metadata = {
                        "turn_user_message_id": old_user_message_id,
                        **safe_response["metadata"],
                    }
                    self._execute(cursor, """
                        UPDATE rick_messages SET conversation_id=%s, content=%s,
                            citations=CAST(%s AS jsonb), metadata=CAST(%s AS jsonb)
                        WHERE tenant_id=%s AND workspace_id=%s AND user_id=%s
                          AND message_id=%s AND role='assistant'
                    """, (conversation_id, answer,
                           json.dumps(citations, ensure_ascii=False, separators=(",", ":")),
                           json.dumps(assistant_metadata, ensure_ascii=False, separators=(",", ":")),
                           *scope, old_assistant_message_id))
                    self._execute(cursor, "UPDATE rick_conversations SET updated_at=NOW() WHERE tenant_id=%s AND workspace_id=%s AND user_id=%s AND conversation_id=%s", (*scope, conversation_id))
                    return safe_response
            self._execute(cursor, "SELECT status FROM rick_conversations WHERE tenant_id=%s AND workspace_id=%s AND user_id=%s AND conversation_id=%s FOR UPDATE", (*scope, conversation_id))
            conversation = self._one(cursor)
            if conversation is None:
                self._execute(cursor, "INSERT INTO rick_conversations (conversation_id, tenant_id, workspace_id, user_id, title, status) VALUES (%s,%s,%s,%s,%s,'active')", (conversation_id, *scope, str(message or "Nova conversa")[:160] or "Nova conversa"))
            elif conversation.get("status") == "archived":
                raise PostgresChatHistoryError("conflict")
            self._execute(cursor, """
                INSERT INTO rick_messages
                    (message_id, conversation_id, tenant_id, workspace_id, user_id, role, content, citations, metadata, idempotency_key)
                VALUES (%s,%s,%s,%s,%s,'user',%s,'[]'::jsonb,CAST(%s AS jsonb),%s)
            """, (user_message_id, conversation_id, *scope, str(message or "")[:20_000],
                   json.dumps({"response": safe_response}, ensure_ascii=False, separators=(",", ":")), key))
            assistant_metadata = {
                "turn_user_message_id": user_message_id,
                **safe_response["metadata"],
            }
            self._execute(cursor, """
                INSERT INTO rick_messages
                    (message_id, conversation_id, tenant_id, workspace_id, user_id, role, content, citations, metadata)
                VALUES (%s,%s,%s,%s,%s,'assistant',%s,CAST(%s AS jsonb),CAST(%s AS jsonb))
            """, (message_id, conversation_id, *scope, answer,
                   json.dumps(citations, ensure_ascii=False, separators=(",", ":")),
                   json.dumps(assistant_metadata, ensure_ascii=False, separators=(",", ":"))))
            self._execute(cursor, "UPDATE rick_conversations SET updated_at=NOW() WHERE tenant_id=%s AND workspace_id=%s AND user_id=%s AND conversation_id=%s", (*scope, conversation_id))
        return safe_response

    def record_stream_outcome(
        self, *, session: object, message: str, conversation_id: str, message_id: str,
        status: str, answer: str = "", error_code: str | None = None,
        metadata: Mapping[str, object] | None = None, idempotency_key: str | None = None,
    ) -> dict[str, object]:
        if status not in STREAM_TERMINAL_STATUSES:
            raise PostgresChatHistoryError("invalid_input")
        stream_metadata = dict(metadata or {})
        stream_metadata["stream_status"] = status
        if error_code:
            stream_metadata["error_code"] = error_code
        return self.append(
            session=session,
            message=message,
            response={
                "conversation_id": conversation_id,
                "message_id": message_id,
                "answer": str(answer or "")[: self.max_answer_chars],
                "citations": [],
                "metadata": stream_metadata,
            },
            idempotency_key=idempotency_key,
        )

    def _history_entries(
        self, *, session: object, conversation_id: str | None = None,
        allowed_collection_ids: object = None,
    ) -> list[dict[str, object]]:
        scope = _scope(session)
        with self._session() as (_connection, cursor):
            self._execute(cursor, """
                SELECT u.conversation_id, u.created_at, u.content AS question,
                       a.message_id, a.content AS answer, a.citations, a.metadata
                FROM rick_messages u
                LEFT JOIN rick_messages a ON a.conversation_id=u.conversation_id
                    AND a.tenant_id=u.tenant_id AND a.workspace_id=u.workspace_id
                    AND a.user_id=u.user_id AND a.role='assistant'
                    AND a.metadata->>'turn_user_message_id' = u.message_id
                WHERE u.tenant_id=%s AND u.workspace_id=%s AND u.user_id=%s
                  AND u.role='user'
                  AND (%s IS NULL OR u.conversation_id=%s)
                ORDER BY u.created_at DESC, u.message_id DESC
            """, (*scope, conversation_id, conversation_id))
            rows = self._many(cursor)
        result: list[dict[str, object]] = []
        for row in rows:
            metadata = _json(row.get("metadata"), {})
            response = metadata.get("response") if isinstance(metadata, Mapping) else None
            if isinstance(response, Mapping):
                value = dict(response)
            else:
                value = {
                    "conversation_id": row.get("conversation_id"),
                    "message_id": row.get("message_id"),
                    "answer": row.get("answer") or "",
                    "citations": _json(row.get("citations"), []),
                    "metadata": {
                        key: value for key, value in metadata.items()
                        if key != "turn_user_message_id"
                    } if isinstance(metadata, Mapping) else {},
                }
            if not _turn_allowed(value.get("citations"), allowed_collection_ids):
                continue
            value["citations"] = _filter_citations(value.get("citations"), allowed_collection_ids)
            value["question"] = row.get("question") or ""
            value["created_at"] = _timestamp(row.get("created_at"))
            result.append(value)
        return result

    def list_history_page(
        self, *, session: object, limit: int = 50, offset: int = 0,
        conversation_id: str | None = None, allowed_collection_ids: object = None,
    ) -> dict[str, object]:
        bounded, bounded_offset = _bounded_page(limit, offset)
        entries = self._history_entries(
            session=session, conversation_id=conversation_id,
            allowed_collection_ids=allowed_collection_ids,
        )
        page = entries[bounded_offset:bounded_offset + bounded]
        next_offset = bounded_offset + bounded if bounded_offset + bounded < len(entries) else None
        return {"items": page, "total": len(entries), "next_offset": next_offset}

    def list_history(self, *, session: object, limit: int = 50) -> list[dict[str, object]]:
        return self.list_history_page(session=session, limit=limit)["items"]  # type: ignore[return-value]

    def list_sources_page(
        self, *, session: object, limit: int = 50, offset: int = 0,
        allowed_collection_ids: object = None,
    ) -> dict[str, object]:
        bounded, bounded_offset = _bounded_page(limit, offset)
        result: list[dict[str, object]] = []
        seen: set[tuple[str, str | None]] = set()
        for entry in self._history_entries(
            session=session, allowed_collection_ids=allowed_collection_ids,
        ):
            for citation in entry.get("citations") or []:
                if not isinstance(citation, Mapping):
                    continue
                identity = (str(citation.get("document_id")), citation.get("chunk_id"))
                if identity in seen:
                    continue
                seen.add(identity)
                result.append({**dict(citation), "conversation_id": entry.get("conversation_id"), "message_id": entry.get("message_id"), "created_at": entry.get("created_at")})
        total = len(result)
        page = result[bounded_offset:bounded_offset + bounded]
        next_offset = bounded_offset + bounded if bounded_offset + bounded < total else None
        return {"items": page, "total": total, "next_offset": next_offset}

    def list_sources(self, *, session: object, limit: int = 50) -> list[dict[str, object]]:
        return self.list_sources_page(session=session, limit=limit)["items"]  # type: ignore[return-value]

    def health_check(self) -> bool:
        try:
            with self._session() as (_connection, cursor):
                self._execute(cursor, "SELECT 1")
                return self._one(cursor) is not None
        except PostgresChatHistoryError:
            return False

    def close(self) -> None:
        """Connections are short-lived; pooled ownership stays with the caller."""


__all__ = ["DbConnection", "PostgresChatHistoryError", "PostgresChatHistoryStore"]
