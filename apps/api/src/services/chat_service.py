"""Chat application service — the single orchestration point for platform chat.

Routes validate HTTP and call this service. The service enforces ACL narrowing,
calls the injected ChatBackend, and never exposes chain-of-thought.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Mapping
import inspect
from typing import AsyncIterator, Protocol

from core.errors import ApiError
from models import SessionSnapshot
from services.authorization_service import build_retrieval_context
from services.chat_history import IdempotencyConflict, idempotency_fingerprint


MAX_IDEMPOTENCY_KEY_CHARS = 128


def _canonical_idempotency_key(value: object) -> str | None:
    """Validate and normalize a retry key before it reaches IDs or history."""

    if value is None:
        return None
    if not isinstance(value, str) or len(value) > MAX_IDEMPOTENCY_KEY_CHARS:
        raise ApiError("validation_error")
    key = value.strip()
    if not key or any(ord(char) < 0x20 or ord(char) == 0x7F for char in key):
        raise ApiError("validation_error")
    return key


def _turn_identifier(prefix: str, session: object, idempotency_key: str | None) -> str:
    """Keep retry identifiers stable before a concurrent stream is persisted."""

    if not isinstance(idempotency_key, str) or not idempotency_key:
        return f"{prefix}-{uuid.uuid4().hex[:12]}"
    identity = json.dumps(
        [getattr(session, field, None) for field in ("tenant_id", "workspace_id", "user_id")]
        + [idempotency_key],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"{prefix}-{uuid.uuid5(uuid.NAMESPACE_URL, identity).hex[:12]}"


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
                 telemetry=None, authorization_revalidator=None):
        self.backend = backend
        self.history = history
        self.context_turns = max(0, min(50, int(context_turns)))
        self.telemetry = telemetry
        self.authorization_revalidator = authorization_revalidator

    async def _refresh_context(self, context: Mapping[str, object]) -> dict[str, object]:
        """Recheck live grants and make every refreshed scope narrowing-only."""
        original = dict(context)
        target = self.authorization_revalidator
        if not callable(target):
            return original
        try:
            if inspect.iscoroutinefunction(target) or inspect.iscoroutinefunction(getattr(target, "__call__", None)):
                current = target(context=dict(original))
            else:
                current = await asyncio.to_thread(target, context=dict(original))
            if inspect.isawaitable(current):
                current = await current
        except Exception:
            raise ApiError("forbidden") from None
        if not isinstance(current, Mapping) or any(
            current.get(key) != original.get(key)
            for key in ("tenant_id", "workspace_id", "user_id")
        ):
            raise ApiError("forbidden")
        old_collections, new_collections = original.get("allowed_collection_ids"), current.get("allowed_collection_ids")
        old_permissions, new_permissions = original.get("permissions"), current.get("permissions")
        if (
            not isinstance(old_collections, list) or not isinstance(new_collections, list)
            or not all(isinstance(item, str) for item in [*old_collections, *new_collections])
            or not isinstance(old_permissions, list) or not isinstance(new_permissions, list)
            or not all(isinstance(item, str) for item in [*old_permissions, *new_permissions])
        ):
            raise ApiError("forbidden")

        def narrow(previous: list[str], refreshed: list[str]) -> list[str]:
            if "*" in previous:
                return sorted(set(refreshed))
            if "*" in refreshed:
                return sorted(set(previous))
            return sorted(set(previous).intersection(refreshed))

        allowed = narrow(old_collections, new_collections)
        permissions = narrow(old_permissions, new_permissions)
        if (old_collections and not allowed) or not ({"chat.query", "*"} & set(permissions)):
            raise ApiError("forbidden")
        return {**original, "allowed_collection_ids": allowed, "permissions": permissions}

    async def _cached_response(self, value: Mapping[str, object], context: Mapping[str, object]) -> dict:
        from rick_contracts.chat import ChatResponse
        from services.chat_history import _safe_chat_response

        try:
            response = _safe_chat_response(value)
            response = ChatResponse.model_validate(response).model_dump(mode="json")
        except Exception:
            raise ApiError("forbidden") from None
        allowed = context.get("allowed_collection_ids")
        if not isinstance(allowed, list) or not all(isinstance(item, str) for item in allowed):
            raise ApiError("forbidden")
        if response["metadata"].get("evidence_status") == "APPROVED_EVIDENCE" and not response["citations"]:
            raise ApiError("forbidden")
        if "*" not in allowed and any(
            not isinstance(item.get("collection_id"), str)
            or item["collection_id"] not in allowed
            for item in response["citations"]
        ):
            raise ApiError("forbidden")
        await self._validate_current_sources(response, context)
        return response

    async def _validate_current_sources(
        self, response: Mapping[str, object], context: Mapping[str, object],
    ) -> None:
        validator = getattr(self.backend, "validate_cached_response", None)
        if not callable(validator):
            return
        try:
            valid = validator(context=dict(context), response=response)
            if inspect.isawaitable(valid):
                valid = await valid
        except Exception:
            valid = False
        if valid is not True:
            raise ApiError("forbidden")

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

    @staticmethod
    def _turn_fingerprint(*, session: SessionSnapshot, message: str,
                          collection_id: str | None) -> str:
        """Fingerprint a retry key's turn so it cannot be replayed elsewhere."""

        return idempotency_fingerprint(
            session=session, message=message, collection_id=collection_id,
        )

    def _replayable_turn(self, *, session: SessionSnapshot, idempotency_key: str,
                         conversation_id: str, fingerprint: str) -> dict | None:
        """Return the stored turn only when it belongs to this exact turn.

        A key reused for another conversation, message or collection is a
        conflict, never a replay: the caller must see 409 instead of another
        conversation's answer.
        """
        reader = getattr(self.history, "get_idempotent", None) if self.history is not None else None
        if not callable(reader):
            return None
        try:
            existing = reader(
                session=session, idempotency_key=idempotency_key,
                conversation_id=conversation_id, fingerprint=fingerprint,
            )
        except IdempotencyConflict:
            raise ApiError("conflict") from None
        if existing is None:
            return None
        if existing.get("conversation_id") != conversation_id:
            raise ApiError("conflict")
        return existing

    def _persisted_turn(self, *, session: SessionSnapshot, message: str,
                        response: Mapping[str, object], idempotency_key: str | None,
                        fingerprint: str | None) -> Mapping | None:
        """Append a durable turn, surfacing an idempotency clash as 409."""
        append = getattr(self.history, "append", None) if self.history is not None else None
        if not callable(append):
            return None
        try:
            persisted = append(
                session=session, message=message, response=response,
                idempotency_key=idempotency_key, fingerprint=fingerprint,
            )
        except IdempotencyConflict:
            raise ApiError("conflict") from None
        return persisted if isinstance(persisted, Mapping) else None

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
        idempotency_key = _canonical_idempotency_key(idempotency_key)
        workspace = workspace_id or session.workspace_id or "default"
        context = build_retrieval_context(session, workspace_id=workspace, collection_id=collection_id)
        context = await self._refresh_context(context)
        conv_id = conversation_id or _turn_identifier("conv", session, idempotency_key)
        fingerprint = (
            self._turn_fingerprint(session=session, message=message, collection_id=collection_id)
            if idempotency_key else None
        )
        if idempotency_key and fingerprint is not None:
            existing = self._replayable_turn(
                session=session, idempotency_key=idempotency_key,
                conversation_id=conv_id, fingerprint=fingerprint,
            )
            if existing is not None:
                return await self._cached_response(existing, context)
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
            "message_id": _turn_identifier("msg", session, idempotency_key),
            "answer": result.get("answer", ""),
            "citations": result.get("citations", []),
            "metadata": {
                **(result.get("metadata", {})), "mode": mode, "workspace_id": workspace,
                **dict(response_metadata or {}),
            },
        }
        from rick_contracts.chat import ChatResponse
        from services.chat_history import _safe_chat_response

        serialized = ChatResponse.model_validate(_safe_chat_response(response)).model_dump(mode="json")
        await self._validate_current_sources(serialized, context)
        if self.history is not None:
            try:
                persisted = self._persisted_turn(
                    session=session, message=message, response=serialized,
                    idempotency_key=idempotency_key, fingerprint=fingerprint,
                )
                if persisted is not None:
                    return await self._cached_response(persisted, context)
            except ApiError:
                raise
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
                               idempotency_key: str | None = None,
                               fingerprint: str | None = None) -> None:
        recorder = getattr(self.history, "record_stream_outcome", None) if self.history is not None else None
        if not callable(recorder):
            return
        # Preserve compatibility with a legacy recorder that has not yet
        # adopted the idempotency/fingerprint arguments, while keeping write
        # failures visible to the caller.
        signature_error: TypeError | None = None
        for extra in (
            {"idempotency_key": idempotency_key, "fingerprint": fingerprint},
            {"idempotency_key": idempotency_key},
            {},
        ):
            try:
                recorder(
                    session=session, message=message, conversation_id=conversation_id,
                    message_id=message_id, status=status, answer=answer,
                    error_code=error_code, metadata=metadata, **extra,
                )
                return
            except TypeError as exc:
                if not any(name in str(exc) for name in ("idempotency_key", "fingerprint")):
                    raise RuntimeError("stream outcome persistence failed") from exc
                signature_error = exc
            except Exception as exc:
                raise RuntimeError("stream outcome persistence failed") from exc
        raise RuntimeError("stream outcome persistence failed") from signature_error

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
        start_sent = False
        key_error: ApiError | None = None
        try:
            idempotency_key = _canonical_idempotency_key(idempotency_key)
        except ApiError as exc:
            key_error = exc
            idempotency_key = None
        conv_id = conversation_id or _turn_identifier("conv", session, idempotency_key)
        msg_id = _turn_identifier("msg", session, idempotency_key)
        workspace = workspace_id or session.workspace_id or "default"
        fingerprint = (
            self._turn_fingerprint(session=session, message=message, collection_id=collection_id)
            if idempotency_key else None
        )

        try:
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
                    if key_error is not None:
                        raise key_error
                    context = build_retrieval_context(
                        session, workspace_id=workspace, collection_id=collection_id,
                    )
                    context = await self._refresh_context(context)
                    if idempotency_key and fingerprint is not None:
                        existing = self._replayable_turn(
                            session=session, idempotency_key=idempotency_key,
                            conversation_id=conv_id, fingerprint=fingerprint,
                        )
                        if existing is not None:
                            existing = await self._cached_response(existing, context)
                            conv_id = existing["conversation_id"]
                            msg_id = existing["message_id"]
                            replay = True
                            yield {
                                "type": "start", "conversation_id": conv_id,
                                "message_id": msg_id, "provisional": True,
                            }
                            start_sent = True
                            answer = existing["answer"]
                            for index in range(0, len(answer), 120):
                                delta = answer[index:index + 120]
                                if first_delta_at is None:
                                    first_delta_at = time.monotonic()
                                yield {"type": "delta", "conversation_id": conv_id,
                                       "message_id": msg_id, "delta": delta, "provisional": True}
                            for citation in existing["citations"]:
                                yield {"type": "citation", "conversation_id": conv_id,
                                       "message_id": msg_id, "citation": citation}
                            terminal_status = "complete"
                            yield {"type": "completion", "conversation_id": conv_id, "message_id": msg_id,
                                   "answer": answer, "citations": existing["citations"],
                                   "metadata": existing["metadata"], "provisional": False}
                            return
                    self._prepare_conversation(
                        session=session, conversation_id=conv_id, collection_id=collection_id,
                    )
                    scope_ready = True
                    yield {
                        "type": "start", "conversation_id": conv_id,
                        "message_id": msg_id, "provisional": True,
                    }
                    start_sent = True
                    history = self._read_context(
                        session=session, conversation_id=conv_id, context=context,
                    )
                    stream = stream_backend(
                        message=message, context=context, conversation_id=conv_id, history=history,
                    )
                    if inspect.isawaitable(stream):
                        stream = await stream
                    final: dict | None = None
                    async for event in stream:
                        if not isinstance(event, Mapping):
                            continue
                        # Provider deltas remain private until the final
                        # publication/grant checks accept the complete answer.
                        if event.get("type") == "final" and isinstance(event.get("result"), Mapping):
                            final = dict(event["result"])
                    if final is None:
                        raise ApiError("generation_failed")
                    metadata = dict(final.get("metadata") or {}) if isinstance(final.get("metadata"), Mapping) else {}
                    metadata.update({
                        "mode": mode, "workspace_id": workspace,
                        "stream_status": "complete", "stream_mode": "live",
                        "stream_duration_ms": round((time.monotonic() - started) * 1000, 3),
                    })
                    answer = final.get("answer", "")
                    if isinstance(answer, str) and answer:
                        metadata["stream_ttft_ms"] = round((time.monotonic() - started) * 1000, 3)
                    response = {
                        "conversation_id": conv_id, "message_id": msg_id,
                        "answer": answer, "citations": final.get("citations", []),
                        "metadata": metadata,
                    }
                    from rick_contracts.chat import ChatResponse
                    from services.chat_history import _safe_chat_response

                    serialized = ChatResponse.model_validate(_safe_chat_response(response)).model_dump(mode="json")
                    await self._validate_current_sources(serialized, context)
                    if self.history is not None:
                        persisted = self._persisted_turn(
                            session=session, message=message, response=serialized,
                            idempotency_key=idempotency_key, fingerprint=fingerprint,
                        )
                        if persisted is not None:
                            serialized = await self._cached_response(persisted, context)
                            if (
                                serialized["conversation_id"] != conv_id
                                or serialized["message_id"] != msg_id
                            ):
                                raise ApiError("conflict")
                    conv_id = serialized["conversation_id"]
                    msg_id = serialized["message_id"]
                    answer = serialized["answer"]
                    answer_so_far = answer[:8000]
                    for index in range(0, len(answer), 120):
                        delta = answer[index:index + 120]
                        if first_delta_at is None:
                            first_delta_at = time.monotonic()
                        yield {"type": "delta", "conversation_id": conv_id,
                               "message_id": msg_id, "delta": delta, "provisional": True}
                    terminal_status = "complete"
                    for citation in serialized["citations"]:
                        yield {"type": "citation", "conversation_id": conv_id,
                               "message_id": msg_id, "citation": citation}
                    yield {"type": "completion", "conversation_id": conv_id, "message_id": msg_id,
                           "answer": serialized["answer"], "citations": serialized["citations"],
                           "metadata": serialized["metadata"], "provisional": False}
                    return
                except ApiError as exc:
                    terminal_status = "partial" if answer_so_far else "error"
                    terminal_error = exc.code
                    if not start_sent:
                        yield {"type": "start", "conversation_id": conv_id,
                               "message_id": msg_id, "provisional": True}
                        start_sent = True
                    yield {"type": "error", "code": exc.code, "message": exc.message,
                           "provisional": False}
                    return
                except Exception as exc:
                    terminal_status = "partial" if answer_so_far else "error"
                    terminal_error = self._stream_error_code(exc)
                    if not start_sent:
                        yield {"type": "start", "conversation_id": conv_id,
                               "message_id": msg_id, "provisional": True}
                        start_sent = True
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
                if key_error is not None:
                    raise key_error
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
                from rick_contracts.chat import ChatResponse

                result = ChatResponse.model_validate(result).model_dump(mode="json")
                conv_id = result["conversation_id"]
                msg_id = result["message_id"]
                scope_ready = True
            except ApiError as exc:
                terminal_status = "error"
                terminal_error = exc.code
                if not start_sent:
                    yield {"type": "start", "conversation_id": conv_id,
                           "message_id": msg_id, "provisional": True}
                    start_sent = True
                yield {"type": "error", "code": exc.code, "message": exc.message,
                       "provisional": False}
                return
            except Exception:
                terminal_status = "error"
                terminal_error = "generation_failed"
                if not start_sent:
                    yield {"type": "start", "conversation_id": conv_id,
                           "message_id": msg_id, "provisional": True}
                    start_sent = True
                yield {"type": "error", "code": "generation_failed", "message": "Generation failed.",
                       "provisional": False}
                return
            answer = str(result.get("answer") or "")
            answer_so_far = answer[:8000]
            yield {"type": "start", "conversation_id": conv_id,
                   "message_id": msg_id, "provisional": True}
            start_sent = True
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
                   "answer": answer, "citations": result["citations"],
                   "metadata": result["metadata"], "provisional": False}
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
                        fingerprint=fingerprint,
                    )
            finally:
                self._record_stream_metrics(
                    outcome=terminal_status, started=started, first_delta_at=first_delta_at,
                )
