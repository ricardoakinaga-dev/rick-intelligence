"""Chat application service — the single orchestration point for platform chat.

Routes validate HTTP and call this service. The service enforces ACL narrowing,
calls the injected ChatBackend, and never exposes chain-of-thought.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from typing import AsyncIterator, Protocol

from core.errors import ApiError
from models import SessionSnapshot
from services.authorization_service import build_retrieval_context


class ChatBackend(Protocol):
    async def generate(self, *, message: str, context: dict, conversation_id: str) -> dict: ...


class StubChatBackend:
    """Deterministic hermetic backend for tests/dev (no provider calls).

    When the application injects the local retrieval facade, this backend still
    remains provider-free but returns only real ACL-scoped citations. It never
    manufactures a source or presents an ungrounded answer as grounded.
    """

    def __init__(self, retrieval=None):
        self.retrieval = retrieval

    async def generate(self, *, message: str, context: dict, conversation_id: str) -> dict:
        if self.retrieval is not None:
            try:
                result = self.retrieval.retrieve(query=message, context=context, top_k=3)
            except Exception:
                return {
                    "answer": "Não foi possível consultar as fontes locais.",
                    "citations": [],
                    "metadata": {
                        "backend": "stub",
                        "conversation_id": conversation_id,
                        "evidence_status": "RETRIEVAL_FAILED",
                    },
                }
            citations = []
            for evidence in getattr(result, "evidence", []) or []:
                if isinstance(evidence, Mapping):
                    get = evidence.get
                else:
                    get = lambda key, default=None: getattr(evidence, key, default)
                citations.append(
                    {
                        "document_id": get("document_id"),
                        "chunk_id": get("chunk_id"),
                        "title": get("title") or get("source"),
                        "collection_id": get("collection_id"),
                        "page_start": get("page_start"),
                        "page_end": get("page_end"),
                        "checksum": get("checksum"),
                    }
                )
            if not citations:
                return {
                    "answer": "Não há evidência aprovada para responder a esta consulta.",
                    "citations": [],
                    "metadata": {
                        "backend": "stub",
                        "conversation_id": conversation_id,
                        "evidence_status": "NO_EVIDENCE",
                    },
                }
            return {
                "answer": f"Resposta fundamentada (stub) para: {message[:500]}",
                "citations": citations,
                "metadata": {
                    "backend": "stub",
                    "conversation_id": conversation_id,
                    "evidence_status": "APPROVED_EVIDENCE" if citations else "NO_EVIDENCE",
                },
            }
        return {
            "answer": "Não há evidência aprovada para responder a esta consulta (stub).",
            "citations": [],
            "metadata": {
                "backend": "stub",
                "conversation_id": conversation_id,
                "evidence_status": "NO_EVIDENCE",
            },
        }


class ChatApplicationService:
    def __init__(self, backend: ChatBackend, history=None):
        self.backend = backend
        self.history = history

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
        try:
            result = await self.backend.generate(message=message, context=context, conversation_id=conv_id)
        except Exception as exc:
            from services.professor_backend import ProfessorBackendError

            if isinstance(exc, ProfessorBackendError):
                code = {
                    "lease_unavailable": "lock_unavailable",
                    "lease_lost": "lock_unavailable",
                    "retrieval_failed": "retrieval_failed",
                    "provider_failed": "provider_unavailable",
                    "citation_invalid": "generation_failed",
                }.get(exc.stage, "generation_failed")
                raise ApiError(code) from None
            # Typed root provider/lease errors are safe to classify here while
            # the public envelope remains free of causes and response bodies.
            try:
                from rick_providers import ProviderError
                from rick_locking import LeaseError

                if isinstance(exc, ProviderError):
                    code = {"timeout": "provider_timeout", "rate_limit": "provider_rate_limit"}.get(
                        exc.code, "provider_unavailable"
                    )
                    raise ApiError(code) from None
                if isinstance(exc, LeaseError):
                    raise ApiError("lock_unavailable") from None
            except ImportError:
                pass
            raise
        response = {
            "conversation_id": conv_id,
            "message_id": f"msg-{uuid.uuid4().hex[:12]}",
            "answer": result.get("answer", ""),
            "citations": result.get("citations", []),
            "metadata": {**(result.get("metadata", {})), "mode": mode, "workspace_id": workspace},
        }
        from rick_contracts.chat import ChatResponse

        serialized = ChatResponse.model_validate(response).model_dump(mode="json")
        if self.history is not None:
            try:
                self.history.append(session=session, message=message, response=serialized)
            except Exception:
                # A read-model failure must never turn a successful grounded
                # response into a failed chat request.
                pass
        return serialized

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
