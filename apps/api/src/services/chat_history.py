"""Bounded chat history/source read model for the canonical local runtime.

The store is intentionally an application read model, not a durable message
bus. It keeps a bounded, ACL-scoped view so the API can expose the history and
sources contracts without leaking another user's workspace or unbounded prompt
content. A durable implementation can replace this object through Providers.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from contextlib import contextmanager
import json
import math
from pathlib import Path
import sqlite3
from threading import RLock
import time
from typing import Any
import uuid


def _value(item: object, name: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _scope(session: object) -> tuple[str, str, str]:
    tenant_id = _value(session, "tenant_id")
    workspace_id = _value(session, "workspace_id")
    user_id = _value(session, "user_id")
    if any(not isinstance(value, str) or not value.strip() for value in (tenant_id, workspace_id, user_id)):
        raise ValueError("session scope is required")
    return tenant_id.strip(), workspace_id.strip(), user_id.strip()


STREAM_TERMINAL_STATUSES = frozenset({"partial", "error", "cancelled", "complete"})
STREAM_CONTEXT_EXCLUDED_STATUSES = frozenset({"partial", "error", "cancelled"})


def _bounded_page(limit: object, offset: object = 0) -> tuple[int, int]:
    try:
        bounded_limit = min(100, max(1, int(limit)))
        bounded_offset = min(100_000, max(0, int(offset)))
    except (TypeError, ValueError, OverflowError):
        bounded_limit, bounded_offset = 50, 0
    return bounded_limit, bounded_offset


def _normalise_allowed_collection_ids(value: object) -> set[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return {value.strip()} if value.strip() else set()
    if isinstance(value, (list, tuple, set, frozenset)):
        return {str(item).strip() for item in value if str(item).strip()}
    return set()


def _safe_citations(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[dict[str, Any]] = []
    for raw in value[:32]:
        if not isinstance(raw, Mapping):
            continue
        item: dict[str, Any] = {}
        for name in (
            "document_id", "chunk_id", "title", "collection_id",
            "page_start", "page_end", "checksum",
        ):
            candidate = raw.get(name)
            if candidate is not None and isinstance(candidate, (str, int, float)):
                item[name] = candidate
        if item.get("document_id"):
            result.append(item)
    return result


def _filter_citations(value: object, allowed_collection_ids: object = None) -> list[dict[str, Any]]:
    citations = _safe_citations(value)
    allowed = _normalise_allowed_collection_ids(allowed_collection_ids)
    if allowed is None or "*" in allowed:
        return citations
    return [citation for citation in citations if citation.get("collection_id") in allowed]


def _turn_allowed(value: object, allowed_collection_ids: object = None) -> bool:
    allowed = _normalise_allowed_collection_ids(allowed_collection_ids)
    if allowed is None or "*" in allowed:
        return True
    citations = _safe_citations(value)
    return not citations or all(citation.get("collection_id") in allowed for citation in citations)


def _safe_stream_metadata(value: object) -> dict[str, Any]:
    """Keep only bounded, non-sensitive stream metadata in the read model."""

    if not isinstance(value, Mapping):
        return {}
    result: dict[str, Any] = {}
    for name in (
        "backend", "mode", "workspace_id", "stream_status", "stream_mode", "error_code",
    ):
        candidate = value.get(name)
        if isinstance(candidate, str) and len(candidate) <= 128:
            result[name] = candidate
    for name in ("stream_ttft_ms", "stream_duration_ms"):
        candidate = value.get(name)
        try:
            number = float(candidate)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number) and number >= 0:
            result[name] = round(number, 3)
    return result


class InMemoryChatHistoryStore:
    """Thread-safe bounded history used by the hermetic root runtime."""

    def __init__(self, *, max_entries: int = 2000, max_answer_chars: int = 8000) -> None:
        if max_entries <= 0 or max_entries > 100_000:
            raise ValueError("max_entries is out of range")
        if max_answer_chars <= 0 or max_answer_chars > 100_000:
            raise ValueError("max_answer_chars is out of range")
        self.max_entries = max_entries
        self.max_answer_chars = max_answer_chars
        self._entries: deque[dict[str, Any]] = deque(maxlen=max_entries)
        self._conversations: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        self._idempotent: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        self._lock = RLock()

    @staticmethod
    def _conversation_key(scope: tuple[str, str, str], conversation_id: str) -> tuple[str, str, str, str]:
        return (*scope, conversation_id)

    @staticmethod
    def _conversation_public(item: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "conversation_id": item["conversation_id"],
            "title": item.get("title") or "Nova conversa",
            "workspace_id": item["workspace_id"],
            "collection_id": item.get("collection_id"),
            "status": item.get("status", "active"),
            "created_at": item["created_at"],
            "updated_at": item["updated_at"],
            "message_count": int(item.get("message_count", 0)),
        }

    def create_conversation(
        self, *, session: object, conversation_id: str | None = None,
        title: str | None = None, collection_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a scoped conversation or return an existing requested id.

        Conversation ids are opaque and only become visible after the server
        binds them to the caller's tenant, workspace, and user.
        """
        scope = _scope(session)
        conversation_id = (conversation_id or f"conv-{uuid.uuid4().hex[:16]}").strip()
        if not conversation_id or len(conversation_id) > 128:
            raise ValueError("conversation_id is invalid")
        now = time.time()
        key = self._conversation_key(scope, conversation_id)
        with self._lock:
            item = self._conversations.get(key)
            if item is None:
                item = {
                    "conversation_id": conversation_id,
                    "tenant_id": scope[0], "workspace_id": scope[1], "user_id": scope[2],
                    "title": (title or "Nova conversa").strip()[:160] or "Nova conversa",
                    "collection_id": (collection_id or "").strip()[:128] or None,
                    "status": "active", "created_at": now, "updated_at": now,
                    "message_count": 0,
                }
                self._conversations[key] = item
            elif item.get("status") == "archived":
                raise ValueError("conversation is archived")
            return self._conversation_public(item)

    def ensure_conversation(
        self, *, session: object, conversation_id: str, title: str | None = None,
        collection_id: str | None = None,
    ) -> dict[str, Any]:
        return self.create_conversation(
            session=session, conversation_id=conversation_id,
            title=title, collection_id=collection_id,
        )

    def get_conversation(self, *, session: object, conversation_id: str) -> dict[str, Any] | None:
        scope = _scope(session)
        with self._lock:
            item = self._conversations.get(self._conversation_key(scope, conversation_id))
            return self._conversation_public(item) if item else None

    def list_conversations_page(
        self, *, session: object, limit: int = 50, offset: int = 0,
    ) -> dict[str, Any]:
        bounded, bounded_offset = _bounded_page(limit, offset)
        scope = _scope(session)
        with self._lock:
            items = [
                self._conversation_public(item)
                for key, item in self._conversations.items()
                if key[:3] == scope
            ]
        ordered = sorted(items, key=lambda item: (-float(item["updated_at"]), item["conversation_id"]))
        page = ordered[bounded_offset:bounded_offset + bounded]
        next_offset = bounded_offset + bounded if bounded_offset + bounded < len(ordered) else None
        return {"items": page, "total": len(ordered), "next_offset": next_offset}

    def list_conversations(self, *, session: object, limit: int = 50) -> list[dict[str, Any]]:
        return self.list_conversations_page(session=session, limit=limit)["items"]

    def archive_conversation(self, *, session: object, conversation_id: str) -> bool:
        scope = _scope(session)
        with self._lock:
            item = self._conversations.get(self._conversation_key(scope, conversation_id))
            if item is None:
                return False
            item["status"] = "archived"
            item["updated_at"] = time.time()
            return True

    def get_context(
        self, *, session: object, conversation_id: str, limit: int = 12,
        allowed_collection_ids: object = None,
    ) -> list[dict[str, str]]:
        bounded = min(50, max(0, int(limit)))
        scope = _scope(session)
        with self._lock:
            entries = [
                entry for entry in self._entries
                if (entry.get("tenant_id"), entry.get("workspace_id"), entry.get("user_id")) == scope
                and entry.get("conversation_id") == conversation_id
            ]
        messages: list[dict[str, str]] = []
        for entry in entries:
            if not _turn_allowed(entry.get("citations"), allowed_collection_ids):
                continue
            metadata = entry.get("metadata")
            if isinstance(metadata, Mapping) and metadata.get("stream_status") in STREAM_CONTEXT_EXCLUDED_STATUSES:
                continue
            messages.extend((
                {"role": "user", "content": str(entry.get("question") or "")},
                {"role": "assistant", "content": str(entry.get("answer") or "")},
            ))
        return messages[-bounded * 2:] if bounded else []

    def get_idempotent(self, *, session: object, idempotency_key: str) -> dict[str, Any] | None:
        scope = _scope(session)
        key = self._conversation_key(scope, idempotency_key)
        with self._lock:
            response = self._idempotent.get(key)
            if response is None:
                return None
            metadata = response.get("metadata") if isinstance(response, Mapping) else None
            if isinstance(metadata, Mapping) and metadata.get("stream_status") in STREAM_CONTEXT_EXCLUDED_STATUSES:
                return None
            return dict(response)

    @staticmethod
    def _safe_citations(value: object) -> list[dict[str, Any]]:
        return _safe_citations(value)

    def append(
        self, *, session: object, message: str, response: Mapping[str, Any],
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        tenant_id, workspace_id, user_id = _scope(session)
        if not user_id:
            return dict(response)
        question = str(message or "")[:20000]
        answer = str(response.get("answer") or "")[: self.max_answer_chars]
        conversation_id = str(response.get("conversation_id") or "")[:128]
        if not conversation_id:
            raise ValueError("conversation_id is required")
        scoped_key = self._conversation_key((tenant_id, workspace_id, user_id), conversation_id)
        idempotency_key = (idempotency_key or "").strip()[:128] or None
        entry = {
            "conversation_id": conversation_id,
            "message_id": str(response.get("message_id") or "")[:128],
            "question": question,
            "answer": answer,
            "citations": self._safe_citations(response.get("citations")),
            "metadata": _safe_stream_metadata(response.get("metadata")),
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "user_id": user_id,
            "idempotency_key": idempotency_key,
            "created_at": time.time(),
        }
        with self._lock:
            conversation = self._conversations.get(scoped_key)
            if conversation is None:
                conversation = {
                    "conversation_id": conversation_id,
                    "tenant_id": tenant_id, "workspace_id": workspace_id, "user_id": user_id,
                    "title": question[:160] or "Nova conversa", "collection_id": None,
                    "status": "active", "created_at": entry["created_at"],
                    "updated_at": entry["created_at"], "message_count": 0,
                }
                self._conversations[scoped_key] = conversation
            if conversation.get("status") == "archived":
                raise ValueError("conversation is archived")
            if idempotency_key:
                idempotency_scope = self._conversation_key((tenant_id, workspace_id, user_id), idempotency_key)
                existing = self._idempotent.get(idempotency_scope)
                if existing is not None:
                    status = (existing.get("metadata") or {}).get("stream_status") if isinstance(existing, Mapping) else None
                    if status not in STREAM_CONTEXT_EXCLUDED_STATUSES:
                        return dict(existing)
                    for candidate in reversed(self._entries):
                        if (
                            candidate.get("tenant_id"), candidate.get("workspace_id"), candidate.get("user_id"),
                            candidate.get("idempotency_key"),
                        ) == (tenant_id, workspace_id, user_id, idempotency_key):
                            entry["created_at"] = candidate.get("created_at", entry["created_at"])
                            candidate.update(entry)
                            self._idempotent[idempotency_scope] = dict(response)
                            conversation["updated_at"] = time.time()
                            return dict(response)
                self._idempotent[idempotency_scope] = dict(response)
            self._entries.append(entry)
            conversation["updated_at"] = entry["created_at"]
            conversation["message_count"] = int(conversation.get("message_count", 0)) + 2
        return dict(response)

    def record_stream_outcome(
        self, *, session: object, message: str, conversation_id: str, message_id: str,
        status: str, answer: str = "", error_code: str | None = None,
        metadata: Mapping[str, Any] | None = None, idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Persist a terminal stream outcome without making it prompt context."""

        if status not in STREAM_TERMINAL_STATUSES:
            raise ValueError("invalid stream status")
        stream_metadata = dict(metadata or {})
        stream_metadata["stream_status"] = status
        if error_code:
            stream_metadata["error_code"] = error_code
        response = {
            "conversation_id": conversation_id,
            "message_id": message_id,
            "answer": str(answer or "")[: self.max_answer_chars],
            "citations": [],
            "metadata": stream_metadata,
        }
        return self.append(
            session=session, message=message, response=response,
            idempotency_key=idempotency_key,
        )

    def list_history_page(
        self, *, session: object, limit: int = 50, offset: int = 0,
        conversation_id: str | None = None, allowed_collection_ids: object = None,
    ) -> dict[str, Any]:
        bounded, bounded_offset = _bounded_page(limit, offset)
        scope = _scope(session)
        with self._lock:
            entries = [
                dict(entry)
                for entry in reversed(self._entries)
                if (entry.get("tenant_id"), entry.get("workspace_id"), entry.get("user_id")) == scope
                and (conversation_id is None or entry.get("conversation_id") == conversation_id)
                and _turn_allowed(entry.get("citations"), allowed_collection_ids)
            ]
        total = len(entries)
        page = entries[bounded_offset:bounded_offset + bounded]
        for entry in page:
            entry["citations"] = _filter_citations(entry.get("citations"), allowed_collection_ids)
            entry.pop("tenant_id", None)
            entry.pop("workspace_id", None)
            entry.pop("user_id", None)
            entry.pop("idempotency_key", None)
        next_offset = bounded_offset + bounded if bounded_offset + bounded < total else None
        return {"items": page, "total": total, "next_offset": next_offset}

    def list_history(self, *, session: object, limit: int = 50) -> list[dict[str, Any]]:
        return self.list_history_page(session=session, limit=limit)["items"]

    def list_sources_page(
        self, *, session: object, limit: int = 50, offset: int = 0,
        allowed_collection_ids: object = None,
    ) -> dict[str, Any]:
        bounded, bounded_offset = _bounded_page(limit, offset)
        scope = _scope(session)
        seen: set[tuple[str, str | None]] = set()
        sources: list[dict[str, Any]] = []
        with self._lock:
            entries = list(reversed(self._entries))
        for entry in entries:
            if (entry.get("tenant_id"), entry.get("workspace_id"), entry.get("user_id")) != scope:
                continue
            for citation in _filter_citations(entry.get("citations", []), allowed_collection_ids):
                key = (str(citation.get("document_id")), citation.get("chunk_id"))
                if key in seen:
                    continue
                seen.add(key)
                sources.append({
                    **citation,
                    "conversation_id": entry.get("conversation_id"),
                    "message_id": entry.get("message_id"),
                    "created_at": entry.get("created_at"),
                })
        total = len(sources)
        page = sources[bounded_offset:bounded_offset + bounded]
        next_offset = bounded_offset + bounded if bounded_offset + bounded < total else None
        return {"items": page, "total": total, "next_offset": next_offset}

    def list_sources(self, *, session: object, limit: int = 50) -> list[dict[str, Any]]:
        return self.list_sources_page(session=session, limit=limit)["items"]

    def close(self) -> None:
        """Match the durable adapter lifecycle; there is no local handle."""
        return None


class SQLiteChatHistoryStore:
    """Transactional conversation store for local restart and integration tests.

    This adapter deliberately keeps the same narrow API as the in-memory
    implementation. Production composition can replace it with a Postgres
    adapter without changing the HTTP or Professor contracts.
    """

    SCHEMA_VERSION = 1

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self.max_answer_chars = 8_000
        if self.path != ":memory:":
            location = Path(self.path)
            location.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if location.exists() and location.is_dir():
                raise ValueError("chat history path must be a file")
        self._lock = RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        if self.path != ":memory:":
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.execute("PRAGMA synchronous = NORMAL")
        self._initialize()

    @contextmanager
    def _transaction(self):
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield
            except Exception:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()

    @contextmanager
    def _read(self):
        with self._lock:
            yield self._connection

    def _initialize(self) -> None:
        with self._transaction():
            current = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
            if current not in (0, self.SCHEMA_VERSION):
                raise RuntimeError(f"unsupported chat history schema version: {current}")
            if current == 0:
                self._connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS conversations (
                        conversation_id TEXT NOT NULL,
                        tenant_id TEXT NOT NULL,
                        workspace_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        collection_id TEXT,
                        status TEXT NOT NULL CHECK (status IN ('active','archived')),
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL,
                        PRIMARY KEY (tenant_id, workspace_id, user_id, conversation_id)
                    );
                    CREATE TABLE IF NOT EXISTS chat_turns (
                        message_id TEXT NOT NULL,
                        conversation_id TEXT NOT NULL,
                        tenant_id TEXT NOT NULL,
                        workspace_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        question TEXT NOT NULL,
                        answer TEXT NOT NULL,
                        citations_json TEXT NOT NULL,
                        metadata_json TEXT NOT NULL,
                        response_json TEXT NOT NULL,
                        idempotency_key TEXT,
                        created_at REAL NOT NULL,
                        PRIMARY KEY (tenant_id, workspace_id, user_id, message_id),
                        UNIQUE (tenant_id, workspace_id, user_id, idempotency_key)
                    );
                    CREATE INDEX IF NOT EXISTS chat_turns_scope_idx
                      ON chat_turns (tenant_id, workspace_id, user_id, created_at DESC);
                    PRAGMA user_version = 1;
                    """
                )

    @staticmethod
    def _public(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "conversation_id": row["conversation_id"], "title": row["title"],
            "workspace_id": row["workspace_id"], "collection_id": row["collection_id"],
            "status": row["status"], "created_at": row["created_at"],
            "updated_at": row["updated_at"], "message_count": int(row["message_count"]),
        }

    def _row_conversation(self, scope: tuple[str, str, str], conversation_id: str):
        tenant_id, workspace_id, user_id = scope
        with self._read() as connection:
            row = connection.execute(
                """SELECT c.*, (SELECT COUNT(*) * 2 FROM chat_turns t
                   WHERE t.tenant_id=c.tenant_id AND t.workspace_id=c.workspace_id
                   AND t.user_id=c.user_id AND t.conversation_id=c.conversation_id) AS message_count
                   FROM conversations c WHERE c.tenant_id=? AND c.workspace_id=?
                   AND c.user_id=? AND c.conversation_id=?""",
                (tenant_id, workspace_id, user_id, conversation_id),
            ).fetchone()
        return row

    def create_conversation(self, *, session: object, conversation_id: str | None = None,
                            title: str | None = None, collection_id: str | None = None) -> dict[str, Any]:
        scope = _scope(session)
        conversation_id = (conversation_id or f"conv-{uuid.uuid4().hex[:16]}").strip()
        if not conversation_id or len(conversation_id) > 128:
            raise ValueError("conversation_id is invalid")
        now = time.time()
        with self._transaction():
            existing = self._connection.execute(
                "SELECT status FROM conversations WHERE tenant_id=? AND workspace_id=? AND user_id=? AND conversation_id=?",
                (*scope, conversation_id),
            ).fetchone()
            if existing and existing["status"] == "archived":
                raise ValueError("conversation is archived")
            self._connection.execute(
                """INSERT INTO conversations
                   (conversation_id, tenant_id, workspace_id, user_id, title, collection_id, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
                   ON CONFLICT(tenant_id, workspace_id, user_id, conversation_id) DO NOTHING""",
                (conversation_id, *scope, (title or "Nova conversa").strip()[:160] or "Nova conversa",
                 (collection_id or "").strip()[:128] or None, now, now),
            )
        row = self._row_conversation(scope, conversation_id)
        if row is None:
            raise RuntimeError("conversation creation failed")
        return self._public(row)

    def ensure_conversation(self, **kwargs):
        return self.create_conversation(**kwargs)

    def get_conversation(self, *, session: object, conversation_id: str) -> dict[str, Any] | None:
        row = self._row_conversation(_scope(session), conversation_id)
        return self._public(row) if row else None

    def list_conversations_page(
        self, *, session: object, limit: int = 50, offset: int = 0,
    ) -> dict[str, Any]:
        bounded, bounded_offset = _bounded_page(limit, offset)
        scope = _scope(session)
        with self._read() as connection:
            total = int(connection.execute(
                "SELECT COUNT(*) FROM conversations WHERE tenant_id=? AND workspace_id=? AND user_id=?",
                scope,
            ).fetchone()[0])
            rows = connection.execute(
                """SELECT c.*, (SELECT COUNT(*) * 2 FROM chat_turns t
                   WHERE t.tenant_id=c.tenant_id AND t.workspace_id=c.workspace_id
                   AND t.user_id=c.user_id AND t.conversation_id=c.conversation_id) AS message_count
                   FROM conversations c WHERE c.tenant_id=? AND c.workspace_id=? AND c.user_id=?
                   ORDER BY c.updated_at DESC, c.conversation_id LIMIT ? OFFSET ?""",
                (*scope, bounded, bounded_offset),
            ).fetchall()
        items = [self._public(row) for row in rows]
        next_offset = bounded_offset + bounded if bounded_offset + bounded < total else None
        return {"items": items, "total": total, "next_offset": next_offset}

    def list_conversations(self, *, session: object, limit: int = 50) -> list[dict[str, Any]]:
        return self.list_conversations_page(session=session, limit=limit)["items"]

    def archive_conversation(self, *, session: object, conversation_id: str) -> bool:
        scope = _scope(session)
        with self._transaction():
            result = self._connection.execute(
                "UPDATE conversations SET status='archived', updated_at=? WHERE tenant_id=? AND workspace_id=? AND user_id=? AND conversation_id=?",
                (time.time(), *scope, conversation_id),
            )
        return result.rowcount == 1

    def get_context(
        self, *, session: object, conversation_id: str, limit: int = 12,
        allowed_collection_ids: object = None,
    ) -> list[dict[str, str]]:
        bounded = min(50, max(0, int(limit)))
        scope = _scope(session)
        with self._read() as connection:
            rows = connection.execute(
                """SELECT question, answer, citations_json, metadata_json FROM chat_turns WHERE tenant_id=? AND workspace_id=?
                   AND user_id=? AND conversation_id=? ORDER BY created_at DESC, message_id DESC""",
                (*scope, conversation_id),
            ).fetchall()
        messages: list[dict[str, str]] = []
        for row in reversed(rows):
            metadata = json.loads(row["metadata_json"] or "{}")
            citations = json.loads(row["citations_json"] or "[]")
            if not _turn_allowed(citations, allowed_collection_ids):
                continue
            if isinstance(metadata, Mapping) and metadata.get("stream_status") in STREAM_CONTEXT_EXCLUDED_STATUSES:
                continue
            messages.extend(({"role": "user", "content": row["question"]},
                             {"role": "assistant", "content": row["answer"]}))
        return messages[-bounded * 2:] if bounded else []

    def get_idempotent(self, *, session: object, idempotency_key: str) -> dict[str, Any] | None:
        scope = _scope(session)
        with self._read() as connection:
            row = connection.execute(
                "SELECT response_json FROM chat_turns WHERE tenant_id=? AND workspace_id=? AND user_id=? AND idempotency_key=?",
                (*scope, idempotency_key.strip()[:128]),
            ).fetchone()
        if row is None:
            return None
        value = json.loads(row["response_json"])
        if not isinstance(value, dict):
            return None
        metadata = value.get("metadata")
        if isinstance(metadata, Mapping) and metadata.get("stream_status") in STREAM_CONTEXT_EXCLUDED_STATUSES:
            return None
        return value

    def append(self, *, session: object, message: str, response: Mapping[str, Any],
               idempotency_key: str | None = None) -> dict[str, Any]:
        scope = _scope(session)
        conversation_id = str(response.get("conversation_id") or "")[:128]
        message_id = str(response.get("message_id") or "")[:128]
        if not conversation_id or not message_id:
            raise ValueError("conversation and message ids are required")
        key = (idempotency_key or "").strip()[:128] or None
        response_json = json.dumps(dict(response), ensure_ascii=False, separators=(",", ":"))
        citations_json = json.dumps(response.get("citations") or [], ensure_ascii=False, separators=(",", ":"))
        metadata_json = json.dumps(response.get("metadata") or {}, ensure_ascii=False, separators=(",", ":"))
        now = time.time()
        with self._transaction():
            if key:
                existing = self._connection.execute(
                    "SELECT message_id, response_json FROM chat_turns WHERE tenant_id=? AND workspace_id=? AND user_id=? AND idempotency_key=?",
                    (*scope, key),
                ).fetchone()
                if existing is not None:
                    value = json.loads(existing["response_json"])
                    metadata = value.get("metadata") if isinstance(value, dict) else None
                    if not (isinstance(metadata, Mapping) and metadata.get("stream_status") in STREAM_CONTEXT_EXCLUDED_STATUSES):
                        return value if isinstance(value, dict) else dict(response)
                    self._connection.execute(
                        """UPDATE chat_turns SET message_id=?, conversation_id=?, question=?, answer=?,
                           citations_json=?, metadata_json=?, response_json=?, created_at=?
                           WHERE tenant_id=? AND workspace_id=? AND user_id=? AND idempotency_key=?""",
                        (message_id, conversation_id, str(message or "")[:20_000],
                         str(response.get("answer") or "")[: self.max_answer_chars], citations_json,
                         metadata_json, response_json, now, *scope, key),
                    )
                    self._connection.execute(
                        "UPDATE conversations SET updated_at=? WHERE tenant_id=? AND workspace_id=? AND user_id=? AND conversation_id=?",
                        (now, *scope, conversation_id),
                    )
                    return dict(response)
            conversation = self._connection.execute(
                "SELECT status FROM conversations WHERE tenant_id=? AND workspace_id=? AND user_id=? AND conversation_id=?",
                (*scope, conversation_id),
            ).fetchone()
            if conversation is None:
                self._connection.execute(
                    """INSERT INTO conversations
                       (conversation_id, tenant_id, workspace_id, user_id, title, collection_id, status, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, NULL, 'active', ?, ?)""",
                    (conversation_id, *scope, str(message or "Nova conversa")[:160] or "Nova conversa", now, now),
                )
            elif conversation["status"] == "archived":
                raise ValueError("conversation is archived")
            self._connection.execute(
                """INSERT INTO chat_turns
                   (message_id, conversation_id, tenant_id, workspace_id, user_id, question, answer,
                    citations_json, metadata_json, response_json, idempotency_key, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (message_id, conversation_id, *scope, str(message or "")[:20000],
                 str(response.get("answer") or "")[: self.max_answer_chars], citations_json,
                 metadata_json, response_json, key, now),
            )
            self._connection.execute(
                "UPDATE conversations SET updated_at=? WHERE tenant_id=? AND workspace_id=? AND user_id=? AND conversation_id=?",
                (now, *scope, conversation_id),
            )
        return dict(response)

    def record_stream_outcome(
        self, *, session: object, message: str, conversation_id: str, message_id: str,
        status: str, answer: str = "", error_code: str | None = None,
        metadata: Mapping[str, Any] | None = None, idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if status not in STREAM_TERMINAL_STATUSES:
            raise ValueError("invalid stream status")
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
    ) -> list[dict[str, Any]]:
        scope = _scope(session)
        with self._read() as connection:
            rows = connection.execute(
                """SELECT response_json, question, created_at FROM chat_turns
                   WHERE tenant_id=? AND workspace_id=? AND user_id=?
                     AND (? IS NULL OR conversation_id=?)
                   ORDER BY created_at DESC, message_id DESC""",
                (*scope, conversation_id, conversation_id),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            value = json.loads(row["response_json"])
            if isinstance(value, dict):
                if not _turn_allowed(value.get("citations"), allowed_collection_ids):
                    continue
                value["citations"] = _filter_citations(value.get("citations"), allowed_collection_ids)
                value["question"] = row["question"]
                value["created_at"] = row["created_at"]
                result.append(value)
        return result

    def list_history_page(
        self, *, session: object, limit: int = 50, offset: int = 0,
        conversation_id: str | None = None, allowed_collection_ids: object = None,
    ) -> dict[str, Any]:
        bounded, bounded_offset = _bounded_page(limit, offset)
        entries = self._history_entries(
            session=session, conversation_id=conversation_id,
            allowed_collection_ids=allowed_collection_ids,
        )
        page = entries[bounded_offset:bounded_offset + bounded]
        next_offset = bounded_offset + bounded if bounded_offset + bounded < len(entries) else None
        return {"items": page, "total": len(entries), "next_offset": next_offset}

    def list_history(self, *, session: object, limit: int = 50) -> list[dict[str, Any]]:
        return self.list_history_page(session=session, limit=limit)["items"]

    def list_sources_page(
        self, *, session: object, limit: int = 50, offset: int = 0,
        allowed_collection_ids: object = None,
    ) -> dict[str, Any]:
        bounded, bounded_offset = _bounded_page(limit, offset)
        items: list[dict[str, Any]] = []
        seen: set[tuple[str, str | None]] = set()
        for entry in self._history_entries(
            session=session, allowed_collection_ids=allowed_collection_ids,
        ):
            for citation in entry.get("citations") or []:
                if not isinstance(citation, Mapping):
                    continue
                key = (str(citation.get("document_id")), citation.get("chunk_id"))
                if key in seen:
                    continue
                seen.add(key)
                items.append({**dict(citation), "conversation_id": entry.get("conversation_id"),
                              "message_id": entry.get("message_id"), "created_at": entry.get("created_at")})
        total = len(items)
        page = items[bounded_offset:bounded_offset + bounded]
        next_offset = bounded_offset + bounded if bounded_offset + bounded < total else None
        return {"items": page, "total": total, "next_offset": next_offset}

    def list_sources(self, *, session: object, limit: int = 50) -> list[dict[str, Any]]:
        return self.list_sources_page(session=session, limit=limit)["items"]

    def close(self) -> None:
        with self._lock:
            self._connection.close()


__all__ = ["InMemoryChatHistoryStore", "SQLiteChatHistoryStore"]
