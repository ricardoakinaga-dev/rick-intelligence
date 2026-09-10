"""Platform-native chat endpoint (canonical contract; no chain-of-thought)."""

from __future__ import annotations

import json
import hashlib
import base64
import binascii

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from core.errors import ApiError, envelope
from core.rate_limit import InMemoryRateLimiter, check_rate_limit_async, ensure_rate_limiter
from core.streaming import ClosingStreamingRoute, closing_stream
from dependencies.identity import require_authenticated
from dependencies.services import get_providers
from rick_contracts.chat import (
    ChatRequest,
    ChatResponse,
    ChatStreamEvent,
    ConversationDetailResponse,
    ConversationListResponse,
    HistoryListResponse,
    SourceListResponse,
    ConversationSummary,
)
from services.audit import emit_required
from services.chat_service import ChatApplicationService

router = APIRouter(tags=["Clinical"], route_class=ClosingStreamingRoute)


InMemoryChatRateLimiter = InMemoryRateLimiter


def _chat_rate_limiter(providers):
    return ensure_rate_limiter(providers)


def _chat_rate_key(session) -> str:
    identity = ":".join(
        str(value or "")
        for value in (getattr(session, "tenant_id", None), getattr(session, "user_id", None))
    )
    if not identity.strip(":"):
        identity = str(getattr(session, "session_id", None) or "authenticated")
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


async def _rate_allowed(providers, key: str, *, request_id: str | None = None) -> bool:
    limiter = _chat_rate_limiter(providers)
    try:
        return await check_rate_limit_async(
            limiter,
            key,
            limit_per_min=providers.settings.chat_rate_limit_per_min,
            request_id=request_id,
        )
    except TypeError as exc:
        raise ApiError("internal_error") from exc


async def _chat_rate_allowed(providers, session, *, request_id: str | None = None) -> bool:
    return await _rate_allowed(providers, _chat_rate_key(session), request_id=request_id)


async def _compat_rate_allowed(providers, api_key: str, *, request_id: str | None = None) -> bool:
    """Apply the same bounded limiter to API-key compatibility traffic."""
    key = hashlib.sha256(f"compat:{api_key}".encode("utf-8")).hexdigest()
    return await _rate_allowed(providers, key, request_id=request_id)


def _service(request: Request) -> ChatApplicationService:
    providers = get_providers(request)
    return ChatApplicationService(
        providers.chat_backend, providers.chat_history,
        telemetry=getattr(request.app.state, "telemetry", None),
    )  # type: ignore[arg-type]


def _encode_cursor(offset: int | None) -> str | None:
    if offset is None:
        return None
    raw = str(max(0, int(offset))).encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str | None) -> int:
    if cursor is None or not cursor.strip():
        return 0
    candidate = cursor.strip()
    if len(candidate) > 256:
        raise ApiError("validation_error", "Invalid pagination cursor.")
    try:
        padded = candidate + "=" * (-len(candidate) % 4)
        value = base64.urlsafe_b64decode(padded.encode("ascii")).decode("ascii")
        offset = int(value)
    except (ValueError, UnicodeError, binascii.Error):
        raise ApiError("validation_error", "Invalid pagination cursor.") from None
    if offset < 0 or offset > 100_000:
        raise ApiError("validation_error", "Invalid pagination cursor.")
    return offset


def _page(store, page_method: str, legacy_method: str, *, session, limit: int,
          offset: int, **kwargs):
    method = getattr(store, page_method, None)
    if callable(method):
        return method(session=session, limit=limit, offset=offset, **kwargs)
    legacy = getattr(store, legacy_method, None)
    if not callable(legacy):
        return {"items": [], "total": 0, "next_offset": None}
    try:
        items = list(legacy(session=session, limit=limit) or [])
    except TypeError:
        items = list(legacy(session=session, limit=limit) or [])
    page = items[offset:offset + limit]
    next_offset = offset + limit if offset + limit < len(items) else None
    return {"items": page, "total": len(items), "next_offset": next_offset}


def _allowed_collections(session, workspace: str) -> list[str]:
    from services.authorization_service import build_retrieval_context

    context = build_retrieval_context(session, workspace_id=workspace)
    return list(context.get("allowed_collection_ids", []))


def _validated_stream_event(event: object) -> dict:
    return ChatStreamEvent.model_validate(event).model_dump(mode="json", exclude_none=True)


def _page_response(payload: dict, store: object, page_method: str):
    """Keep legacy injected read models observable while canonical adapters validate."""
    if not callable(getattr(store, page_method, None)):
        return JSONResponse(content=payload)
    return payload


@router.post("/api/v1/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, request: Request, session=Depends(require_authenticated)):
    providers = get_providers(request)
    if not await _chat_rate_allowed(
        providers,
        session,
        request_id=getattr(request.state, "request_id", None),
    ):
        request_id = getattr(request.state, "request_id", "unknown")
        return JSONResponse(
            status_code=429,
            content=envelope("rate_limited", "Too many requests.", request_id, None),
            headers={"Retry-After": "60"},
        )
    if len(payload.message) > providers.settings.max_chat_message_chars:
        raise ApiError("validation_error", "Message is too long.")
    service = _service(request)
    if payload.stream:
        async def event_gen():
            events = service.stream_events(
                session=session, message=payload.message, conversation_id=payload.conversation_id,
                collection_id=payload.collection_id, workspace_id=payload.workspace_id, mode=payload.mode,
                idempotency_key=payload.idempotency_key,
            )
            async with closing_stream(events, request.scope):
                async for event in events:
                    if await request.is_disconnected():
                        break
                    yield f"data: {json.dumps(_validated_stream_event(event))}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(event_gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    return await service.chat(
        session=session, message=payload.message, conversation_id=payload.conversation_id,
        collection_id=payload.collection_id, workspace_id=payload.workspace_id, mode=payload.mode,
        idempotency_key=payload.idempotency_key,
    )


class ConversationCreateRequest(BaseModel):
    conversation_id: str | None = Field(default=None, min_length=1, max_length=128)
    title: str | None = Field(default=None, max_length=160)
    collection_id: str | None = Field(default=None, max_length=128)


def _conversation_store(request: Request):
    store = get_providers(request).chat_history
    if store is None or not callable(getattr(store, "create_conversation", None)):
        raise ApiError("provider_unavailable")
    return store


@router.post("/api/v1/conversations", status_code=201, response_model=ConversationSummary)
def create_conversation(payload: ConversationCreateRequest, request: Request,
                        session=Depends(require_authenticated)):
    from services.authorization_service import build_retrieval_context, has_permission

    if not has_permission(session, "history.read") or not has_permission(session, "chat.query"):
        raise ApiError("forbidden")
    workspace = session.workspace_id or "default"
    build_retrieval_context(session, workspace_id=workspace, collection_id=payload.collection_id)
    try:
        return _conversation_store(request).create_conversation(
            session=session, conversation_id=payload.conversation_id,
            title=payload.title, collection_id=payload.collection_id,
        )
    except ValueError as exc:
        raise ApiError("validation_error", str(exc)) from None


@router.get("/api/v1/conversations", response_model=ConversationListResponse)
def list_conversations(request: Request, session=Depends(require_authenticated),
                       limit: int = Query(default=50, ge=1, le=100),
                       cursor: str | None = Query(default=None, max_length=256)):
    from services.authorization_service import has_permission

    if not has_permission(session, "history.read"):
        raise ApiError("forbidden")
    store = _conversation_store(request)
    page = _page(
        store, "list_conversations_page", "list_conversations", session=session,
        limit=limit, offset=_decode_cursor(cursor),
    )
    payload = {"items": page["items"], "total": page["total"], "next_cursor": _encode_cursor(page.get("next_offset"))}
    return _page_response(payload, store, "list_conversations_page")


@router.get("/api/v1/conversations/{conversation_id}", response_model=ConversationDetailResponse)
def get_conversation(conversation_id: str, request: Request,
                     session=Depends(require_authenticated),
                     limit: int = Query(default=100, ge=1, le=100),
                     cursor: str | None = Query(default=None, max_length=256)):
    from services.authorization_service import build_retrieval_context, has_permission

    if not has_permission(session, "history.read"):
        raise ApiError("forbidden")
    store = _conversation_store(request)
    conversation = store.get_conversation(session=session, conversation_id=conversation_id)
    if conversation is None:
        raise ApiError("not_found")
    allowed = build_retrieval_context(
        session, workspace_id=session.workspace_id or "default",
    ).get("allowed_collection_ids", [])
    page = _page(
        store, "list_history_page", "list_history", session=session,
        limit=limit, offset=_decode_cursor(cursor), conversation_id=conversation_id,
        allowed_collection_ids=allowed,
    )
    payload = {
        "conversation": conversation, "items": page["items"], "total": page["total"],
        "next_cursor": _encode_cursor(page.get("next_offset")),
    }
    return _page_response(payload, store, "list_history_page")


@router.post("/api/v1/conversations/{conversation_id}/archive")
def archive_conversation(conversation_id: str, request: Request,
                         session=Depends(require_authenticated)):
    from services.authorization_service import has_permission

    if not has_permission(session, "history.read"):
        raise ApiError("forbidden")
    store = _conversation_store(request)
    if not store.archive_conversation(session=session, conversation_id=conversation_id):
        raise ApiError("not_found")
    emit_required(get_providers(request).audit_sink, {
        "action": "conversation.archive", "actor_user_id": session.user_id,
        "target_id": conversation_id, "tenant_id": session.tenant_id,
        "workspace_id": session.workspace_id,
        "request_id": getattr(request.state, "request_id", None),
    })
    return {"conversation_id": conversation_id, "status": "archived"}


@router.get("/api/v1/history", response_model=HistoryListResponse)
def history(request: Request, session=Depends(require_authenticated), limit: int = Query(default=50, ge=1, le=100),
            cursor: str | None = Query(default=None, max_length=256)):
    from services.authorization_service import build_retrieval_context, has_permission

    if not has_permission(session, "history.read"):
        raise ApiError("forbidden")
    store = get_providers(request).chat_history
    if store is None:
        return {"items": [], "total": 0, "next_cursor": None}
    allowed = build_retrieval_context(
        session, workspace_id=session.workspace_id or "default",
    ).get("allowed_collection_ids", [])
    page = _page(
        store, "list_history_page", "list_history", session=session,
        limit=limit, offset=_decode_cursor(cursor), allowed_collection_ids=allowed,
    )
    payload = {"items": page["items"], "total": page["total"], "next_cursor": _encode_cursor(page.get("next_offset"))}
    return _page_response(payload, store, "list_history_page")


@router.get("/api/v1/sources", response_model=SourceListResponse)
def sources(request: Request, session=Depends(require_authenticated), limit: int = Query(default=50, ge=1, le=100),
            cursor: str | None = Query(default=None, max_length=256)):
    from services.authorization_service import build_retrieval_context, has_permission

    if not has_permission(session, "sources.read"):
        raise ApiError("forbidden")
    store = get_providers(request).chat_history
    if store is None:
        return {"items": [], "total": 0, "next_cursor": None}
    allowed = build_retrieval_context(
        session, workspace_id=session.workspace_id or "default",
    ).get("allowed_collection_ids", [])
    page = _page(
        store, "list_sources_page", "list_sources", session=session,
        limit=limit, offset=_decode_cursor(cursor), allowed_collection_ids=allowed,
    )
    payload = {"items": page["items"], "total": page["total"], "next_cursor": _encode_cursor(page.get("next_offset"))}
    return _page_response(payload, store, "list_sources_page")
