"""Chat application service — the single orchestration point for platform chat.

Routes validate HTTP and call this service. The service enforces ACL narrowing,
calls the injected ChatBackend, and never exposes chain-of-thought.
"""

from __future__ import annotations

import time
import uuid
from typing import AsyncIterator, Protocol

from core.errors import ApiError
from models import SessionSnapshot
from services.authorization_service import build_retrieval_context


class ChatBackend(Protocol):
    async def generate(self, *, message: str, context: dict, conversation_id: str) -> dict: ...


class StubChatBackend:
    """Deterministic hermetic backend for tests/dev (no provider calls)."""

    async def generate(self, *, message: str, context: dict, conversation_id: str) -> dict:
        allowed = context.get("allowed_collection_ids", ["rag_phase0"])
        collection = allowed[0] if allowed and allowed[0] != "*" else "rag_phase0"
        return {
            "answer": f"Resposta fundamentada (stub) para: {message[:500]}",
            "citations": [{"document_id": "doc-stub-1", "chunk_id": "chunk-stub-1",
                           "title": "Fonte stub", "collection_id": collection}],
            "metadata": {"backend": "stub", "conversation_id": conversation_id},
        }


class ChatApplicationService:
    def __init__(self, backend: ChatBackend):
        self.backend = backend

    async def chat(self, *, session: SessionSnapshot, message: str, conversation_id: str | None,
                   collection_id: str | None, workspace_id: str | None, mode: str) -> dict:
        if not session.authenticated:
            raise ApiError("unauthorized")
        from services.authorization_service import has_permission

        if not has_permission(session, "chat.query"):
            raise ApiError("forbidden")
        if len(message) > 20000 or len(message.strip()) == 0:
            raise ApiError("validation_error")
        workspace = workspace_id or session.workspace_id or "default"
        context = build_retrieval_context(session, workspace_id=workspace, collection_id=collection_id)
        conv_id = conversation_id or f"conv-{uuid.uuid4().hex[:12]}"
        result = await self.backend.generate(message=message, context=context, conversation_id=conv_id)
        return {
            "conversation_id": conv_id,
            "message_id": f"msg-{uuid.uuid4().hex[:12]}",
            "answer": result.get("answer", ""),
            "citations": result.get("citations", []),
            "metadata": {**(result.get("metadata", {})), "mode": mode, "workspace_id": workspace},
        }

    async def stream_events(self, *, session: SessionSnapshot, message: str, conversation_id: str | None,
                            collection_id: str | None, workspace_id: str | None,
                            mode: str) -> AsyncIterator[dict]:
        """Single canonical SSE abstraction: start → delta* → citation* → completion | error."""
        conv_id = conversation_id or f"conv-{uuid.uuid4().hex[:12]}"
        msg_id = f"msg-{uuid.uuid4().hex[:12]}"
        yield {"type": "start", "conversation_id": conv_id, "message_id": msg_id}
        try:
            result = await self.chat(session=session, message=message, conversation_id=conv_id,
                                     collection_id=collection_id, workspace_id=workspace_id, mode=mode)
        except ApiError as exc:
            yield {"type": "error", "code": exc.code, "message": exc.message}
            return
        except Exception:
            yield {"type": "error", "code": "generation_failed", "message": "Generation failed."}
            return
        answer = result["answer"]
        # Delta streaming (chunked; never buffered-and-faked at the protocol level).
        for i in range(0, len(answer), 120):
            yield {"type": "delta", "conversation_id": conv_id, "message_id": msg_id, "delta": answer[i:i + 120]}
        for citation in result["citations"]:
            yield {"type": "citation", "conversation_id": conv_id, "message_id": msg_id, "citation": citation}
        yield {"type": "completion", "conversation_id": conv_id, "message_id": msg_id,
               "answer": answer, "citations": result["citations"]}
