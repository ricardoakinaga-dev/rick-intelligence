"""Chat application service — the single orchestration point for platform chat.

Routes validate HTTP and call this service. The service enforces ACL narrowing,
calls the injected ChatBackend, and never exposes chain-of-thought.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Mapping
import inspect
from typing import AsyncIterator, Protocol

from core.errors import ApiError
from models import SessionSnapshot
from services.authorization_service import build_retrieval_context


class ChatBackend(Protocol):
    async def generate(
        self, *, message: str, context: dict, conversation_id: str,
        history: list[dict[str, str]] | None = None,
    ) -> dict: ...


class StubChatBackend:
    """Deterministic hermetic backend for tests/dev (no provider calls).

    When the application injects the local retrieval facade, this backend still
    remains provider-free but returns only real ACL-scoped citations. It never
    manufactures a source or presents an ungrounded answer as grounded.
    """

    def __init__(self, retrieval=None):
        self.retrieval = retrieval

    async def generate(self, *, message: str, context: dict, conversation_id: str,
                       history: list[dict[str, str]] | None = None) -> dict:
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

    async def generate_stream(self, *, message: str, context: dict, conversation_id: str,
                              history: list[dict[str, str]] | None = None):
        """Expose the same incremental backend port in the hermetic runtime."""
        result = await self.generate(
            message=message, context=context, conversation_id=conversation_id,
            history=history,
        )
        answer = str(result.get("answer") or "")
        for index in range(0, len(answer), 120):
            await asyncio.sleep(0)
            yield {"type": "delta", "delta": answer[index:index + 120]}
        yield {"type": "final", "result": result}


class ChatApplicationService:
    def __init__(self, backend: ChatBackend, history=None, *, context_turns: int = 12,
                 telemetry=None):
        self.backend = backend
        self.history = history
        self.context_turns = max(0, min(50, int(context_turns)))
        self.telemetry = telemetry

    async def _generate(self, *, message: str, context: dict, conversation_id: str,
                        history: list[dict[str, str]]) -> dict:
        target = self.backend.generate
        kwargs = {"message": message, "context": context, "conversation_id": conversation_id}
        try:
            parameters = inspect.signature(target).parameters
        except (TypeError, ValueError):
            parameters = {}
        if "history" in parameters or any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
        ):
            kwargs["history"] = history
        result = target(**kwargs)
        return await result if inspect.isawaitable(result) else result

    def _read_context(self, *, session: SessionSnapshot, conversation_id: str,
                      context: Mapping[str, object]) -> list[dict[str, str]]:
        reader = getattr(self.history, "get_context", None)
        if not callable(reader):
            return []
        kwargs: dict[str, object] = {
            "session": session, "conversation_id": conversation_id, "limit": self.context_turns,
        }
        try:
            parameters = inspect.signature(reader).parameters
        except (TypeError, ValueError):
            parameters = {}
        if "allowed_collection_ids" in parameters or any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
        ):
            kwargs["allowed_collection_ids"] = context.get("allowed_collection_ids")
        try:
            return list(reader(**kwargs) or [])
        except (ValueError, PermissionError, KeyError):
            raise ApiError("forbidden") from None

    def _prepare_conversation(self, *, session: SessionSnapshot, conversation_id: str,
                              collection_id: str | None) -> None:
        ensure = getattr(self.history, "ensure_conversation", None)
        if not callable(ensure):
            return
        try:
            ensure(session=session, conversation_id=conversation_id, collection_id=collection_id)
        except ValueError as exc:
            if "archived" in str(exc).lower():
                raise ApiError("conflict", "This conversation is archived.") from None
            raise ApiError("forbidden") from None
        except (PermissionError, KeyError):
            raise ApiError("forbidden") from None

    async def chat(self, *, session: SessionSnapshot, message: str, conversation_id: str | None,
                   collection_id: str | None, workspace_id: str | None, mode: str,
                   idempotency_key: str | None = None,
                   response_metadata: Mapping[str, object] | None = None) -> dict:
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
        if idempotency_key:
            existing = getattr(self.history, "get_idempotent", lambda **_: None)(
                session=session, idempotency_key=idempotency_key,
            ) if self.history is not None else None
            if existing is not None:
                return existing
        self._prepare_conversation(session=session, conversation_id=conv_id, collection_id=collection_id)
        history = self._read_context(session=session, conversation_id=conv_id, context=context)
        try:
            result = await self._generate(
                message=message, context=context, conversation_id=conv_id,
                history=history,
            )
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
            "metadata": {
                **(result.get("metadata", {})), "mode": mode, "workspace_id": workspace,
                **dict(response_metadata or {}),
            },
        }
        from rick_contracts.chat import ChatResponse

        serialized = ChatResponse.model_validate(response).model_dump(mode="json")
        append = getattr(self.history, "append", None) if self.history is not None else None
        if callable(append):
            try:
                persisted = append(
                    session=session, message=message, response=serialized,
                    idempotency_key=idempotency_key,
                )
                if isinstance(persisted, Mapping):
                    return dict(persisted)
            except Exception:
                # A grounded answer without its durable turn would make
                # idempotency and the conversation read model diverge.
                raise ApiError("provider_unavailable") from None
        return serialized

    @staticmethod
    def _stream_error_code(exc: Exception) -> str:
        try:
            from services.professor_backend import ProfessorBackendError
        except ImportError:
            ProfessorBackendError = ()  # type: ignore[assignment]

        if isinstance(exc, ProfessorBackendError):
            return {
                "lease_unavailable": "lock_unavailable", "lease_lost": "lock_unavailable",
                "retrieval_failed": "retrieval_failed", "provider_failed": "provider_unavailable",
                "citation_invalid": "generation_failed",
            }.get(exc.stage, "generation_failed")
        try:
            from rick_providers import ProviderError
            from rick_locking import LeaseError

            if isinstance(exc, ProviderError):
                return {"timeout": "provider_timeout", "rate_limit": "provider_rate_limit"}.get(
                    exc.code, "provider_unavailable"
                )
            if isinstance(exc, LeaseError):
                return "lock_unavailable"
        except ImportError:
            pass
        return "generation_failed"

    def _record_stream_outcome(self, *, session: SessionSnapshot, message: str,
                               conversation_id: str, message_id: str, status: str,
                               answer: str, error_code: str | None, metadata: Mapping[str, object],
                               idempotency_key: str | None = None) -> None:
        recorder = getattr(self.history, "record_stream_outcome", None) if self.history is not None else None
        if not callable(recorder):
            return
        try:
            recorder(
                session=session, message=message, conversation_id=conversation_id,
                message_id=message_id, status=status, answer=answer,
                error_code=error_code, metadata=metadata,
                idempotency_key=idempotency_key,
            )
        except TypeError as exc:
            # Preserve compatibility with a legacy recorder that has not yet
            # adopted the idempotency argument, while keeping write failures
            # visible to the caller.
            if "idempotency_key" not in str(exc):
                raise RuntimeError("stream outcome persistence failed") from exc
            try:
                recorder(
                    session=session, message=message, conversation_id=conversation_id,
                    message_id=message_id, status=status, answer=answer,
                    error_code=error_code, metadata=metadata,
                )
            except Exception as retry_exc:
                raise RuntimeError("stream outcome persistence failed") from retry_exc
        except Exception as exc:
            raise RuntimeError("stream outcome persistence failed") from exc

    def _record_stream_metrics(self, *, outcome: str, started: float,
                               first_delta_at: float | None) -> None:
        recorder = getattr(self.telemetry, "record_stream", None)
        if not callable(recorder):
            return
        try:
            recorder(
                outcome=outcome,
                ttft_ms=((first_delta_at - started) * 1000) if first_delta_at is not None else None,
                duration_ms=(time.monotonic() - started) * 1000,
            )
        except Exception:
            return

    async def stream_events(self, *, session: SessionSnapshot, message: str, conversation_id: str | None,
                            collection_id: str | None, workspace_id: str | None,
                            mode: str, idempotency_key: str | None = None) -> AsyncIterator[dict]:
        """Single canonical SSE abstraction with durable terminal outcomes."""
        started = time.monotonic()
        first_delta_at: float | None = None
        terminal_status: str | None = None
        terminal_error: str | None = None
        answer_so_far = ""
        scope_ready = False
        replay = False
        conv_id = conversation_id or f"conv-{uuid.uuid4().hex[:12]}"
        msg_id = f"msg-{uuid.uuid4().hex[:12]}"
        workspace = workspace_id or session.workspace_id or "default"

        try:
            yield {
                "type": "start", "conversation_id": conv_id, "message_id": msg_id,
                "provisional": True,
            }

            stream_backend = getattr(self.backend, "generate_stream", None)
            if callable(stream_backend):
                try:
                    if not session.authenticated:
                        raise ApiError("unauthorized")
                    from services.authorization_service import has_permission

                    if not has_permission(session, "chat.query"):
                        raise ApiError("forbidden")
                    if len(message) > 20000 or not message.strip():
                        raise ApiError("validation_error")
                    context = build_retrieval_context(
                        session, workspace_id=workspace, collection_id=collection_id,
                    )
                    if idempotency_key and self.history is not None:
                        existing = getattr(self.history, "get_idempotent", lambda **_: None)(
                            session=session, idempotency_key=idempotency_key,
                        )
                        if existing is not None:
                            conv_id = str(existing.get("conversation_id") or conv_id)
                            msg_id = str(existing.get("message_id") or msg_id)
                            replay = True
                            answer = str(existing.get("answer") or "")
                            for index in range(0, len(answer), 120):
                                delta = answer[index:index + 120]
                                if first_delta_at is None:
                                    first_delta_at = time.monotonic()
                                yield {"type": "delta", "conversation_id": conv_id,
                                       "message_id": msg_id, "delta": delta, "provisional": True}
                            terminal_status = "complete"
                            yield {"type": "completion", "conversation_id": conv_id, "message_id": msg_id,
                                   "answer": answer, "citations": existing.get("citations", []),
                                   "provisional": False}
                            return
                    self._prepare_conversation(
                        session=session, conversation_id=conv_id, collection_id=collection_id,
                    )
                    scope_ready = True
                    history = self._read_context(
                        session=session, conversation_id=conv_id, context=context,
                    )
                    stream = stream_backend(
                        message=message, context=context, conversation_id=conv_id, history=history,
                    )
                    if inspect.isawaitable(stream):
                        stream = await stream
                    final: dict | None = None
                    saw_delta = False
                    async for event in stream:
                        if not isinstance(event, Mapping):
                            continue
                        if event.get("type") == "delta":
                            delta = str(event.get("delta") or "")
                            if delta:
                                saw_delta = True
                                answer_so_far = (answer_so_far + delta)[:8000]
                                if first_delta_at is None:
                                    first_delta_at = time.monotonic()
                                yield {"type": "delta", "conversation_id": conv_id,
                                       "message_id": msg_id, "delta": delta, "provisional": True}
                        elif event.get("type") == "final" and isinstance(event.get("result"), Mapping):
                            final = dict(event["result"])
                            if not saw_delta and final.get("answer"):
                                answer_so_far = str(final.get("answer") or "")[:8000]
                    if final is None:
                        raise ApiError("generation_failed")
                    metadata = dict(final.get("metadata") or {}) if isinstance(final.get("metadata"), Mapping) else {}
                    metadata.update({
                        "mode": mode, "workspace_id": workspace,
                        "stream_status": "complete", "stream_mode": "live",
                        "stream_duration_ms": round((time.monotonic() - started) * 1000, 3),
                    })
                    if first_delta_at is not None:
                        metadata["stream_ttft_ms"] = round((first_delta_at - started) * 1000, 3)
                    response = {
                        "conversation_id": conv_id, "message_id": msg_id,
                        "answer": final.get("answer", ""), "citations": final.get("citations", []),
                        "metadata": metadata,
                    }
                    from rick_contracts.chat import ChatResponse

                    serialized = ChatResponse.model_validate(response).model_dump(mode="json")
                    if not saw_delta and serialized["answer"]:
                        answer_so_far = str(serialized["answer"])[:8000]
                        if first_delta_at is None:
                            first_delta_at = time.monotonic()
                        yield {"type": "delta", "conversation_id": conv_id,
                               "message_id": msg_id, "delta": serialized["answer"], "provisional": True}
                    if self.history is not None:
                        persisted = self.history.append(
                            session=session, message=message, response=serialized,
                            idempotency_key=idempotency_key,
                        )
                        if isinstance(persisted, Mapping):
                            serialized = dict(persisted)
                    terminal_status = "complete"
                    for citation in serialized["citations"]:
                        yield {"type": "citation", "conversation_id": conv_id,
                               "message_id": msg_id, "citation": citation}
                    yield {"type": "completion", "conversation_id": conv_id, "message_id": msg_id,
                           "answer": serialized["answer"], "citations": serialized["citations"],
                           "provisional": False}
                    return
                except ApiError as exc:
                    terminal_status = "partial" if answer_so_far else "error"
                    terminal_error = exc.code
                    yield {"type": "error", "code": exc.code, "message": exc.message,
                           "provisional": False}
                    return
                except Exception as exc:
                    terminal_status = "partial" if answer_so_far else "error"
                    terminal_error = self._stream_error_code(exc)
                    yield {"type": "error", "code": terminal_error, "message": "Generation failed.",
                           "provisional": False}
                    return

            try:
                if not session.authenticated:
                    raise ApiError("unauthorized")
                from services.authorization_service import has_permission

                if not has_permission(session, "chat.query"):
                    raise ApiError("forbidden")
                if len(message) > 20000 or not message.strip():
                    raise ApiError("validation_error")
                self._prepare_conversation(
                    session=session, conversation_id=conv_id, collection_id=collection_id,
                )
                scope_ready = True
                result = await self.chat(
                    session=session, message=message, conversation_id=conv_id,
                    collection_id=collection_id, workspace_id=workspace_id, mode=mode,
                    idempotency_key=idempotency_key,
                    response_metadata={"stream_status": "complete", "stream_mode": "buffered"},
                )
                scope_ready = True
            except ApiError as exc:
                terminal_status = "error"
                terminal_error = exc.code
                yield {"type": "error", "code": exc.code, "message": exc.message,
                       "provisional": False}
                return
            except Exception:
                terminal_status = "error"
                terminal_error = "generation_failed"
                yield {"type": "error", "code": "generation_failed", "message": "Generation failed.",
                       "provisional": False}
                return
            answer = str(result.get("answer") or "")
            answer_so_far = answer[:8000]
            # Compatibility backends are buffered, but the protocol still emits
            # real chunks and records the terminal status in the persisted turn.
            for i in range(0, len(answer), 120):
                if first_delta_at is None:
                    first_delta_at = time.monotonic()
                yield {"type": "delta", "conversation_id": conv_id, "message_id": msg_id,
                       "delta": answer[i:i + 120], "provisional": True}
            terminal_status = "complete"
            for citation in result["citations"]:
                yield {"type": "citation", "conversation_id": conv_id,
                       "message_id": msg_id, "citation": citation}
            yield {"type": "completion", "conversation_id": conv_id, "message_id": msg_id,
                   "answer": answer, "citations": result["citations"], "provisional": False}
        except BaseException:
            if terminal_status is None:
                terminal_status = "cancelled"
            raise
        finally:
            if terminal_status is None:
                terminal_status = "cancelled"
            try:
                if terminal_status != "complete" and scope_ready and not replay:
                    self._record_stream_outcome(
                        session=session, message=message, conversation_id=conv_id, message_id=msg_id,
                        status=terminal_status, answer=answer_so_far, error_code=terminal_error,
                        metadata={"mode": mode, "workspace_id": workspace, "stream_mode": "live"},
                        idempotency_key=idempotency_key,
                    )
            finally:
                self._record_stream_metrics(
                    outcome=terminal_status, started=started, first_delta_at=first_delta_at,
                )
