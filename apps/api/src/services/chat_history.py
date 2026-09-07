"""Bounded chat history/source read model for the canonical local runtime.

The store is intentionally an application read model, not a durable message
bus. It keeps a bounded, ACL-scoped view so the API can expose the history and
sources contracts without leaking another user's workspace or unbounded prompt
content. A durable implementation can replace this object through Providers.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from threading import RLock
import time
from typing import Any


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
        self._lock = RLock()

    @staticmethod
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

    def append(self, *, session: object, message: str, response: Mapping[str, Any]) -> None:
        tenant_id, workspace_id, user_id = _scope(session)
        if not user_id:
            return
        question = str(message or "")[:20000]
        answer = str(response.get("answer") or "")[: self.max_answer_chars]
        entry = {
            "conversation_id": str(response.get("conversation_id") or "")[:128],
            "message_id": str(response.get("message_id") or "")[:128],
            "question": question,
            "answer": answer,
            "citations": self._safe_citations(response.get("citations")),
            "metadata": {
                "backend": str(_value(response.get("metadata"), "backend", ""))[:64]
                if isinstance(response.get("metadata"), Mapping)
                else "",
            },
            "tenant_id": tenant_id,
            "workspace_id": workspace_id,
            "user_id": user_id,
            "created_at": time.time(),
        }
        with self._lock:
            self._entries.append(entry)

    def list_history(self, *, session: object, limit: int = 50) -> list[dict[str, Any]]:
        bounded = min(100, max(1, int(limit)))
        scope = _scope(session)
        with self._lock:
            entries = [
                dict(entry)
                for entry in reversed(self._entries)
                if (entry.get("tenant_id"), entry.get("workspace_id"), entry.get("user_id")) == scope
            ][:bounded]
        for entry in entries:
            entry.pop("tenant_id", None)
            entry.pop("workspace_id", None)
            entry.pop("user_id", None)
        return entries

    def list_sources(self, *, session: object, limit: int = 50) -> list[dict[str, Any]]:
        bounded = min(100, max(1, int(limit)))
        scope = _scope(session)
        seen: set[tuple[str, str | None]] = set()
        sources: list[dict[str, Any]] = []
        with self._lock:
            entries = list(reversed(self._entries))
        for entry in entries:
            if (entry.get("tenant_id"), entry.get("workspace_id"), entry.get("user_id")) != scope:
                continue
            for citation in entry.get("citations", []):
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
                if len(sources) >= bounded:
                    return sources
        return sources


__all__ = ["InMemoryChatHistoryStore"]
