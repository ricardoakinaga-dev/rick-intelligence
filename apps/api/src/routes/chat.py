"""Platform-native chat endpoint (canonical contract; no chain-of-thought)."""

from __future__ import annotations

import json
import hashlib

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from core.errors import ApiError, envelope
from core.rate_limit import InMemoryRateLimiter, check_rate_limit, ensure_rate_limiter
from core.streaming import ClosingStreamingRoute, closing_stream
from dependencies.identity import require_authenticated
from dependencies.services import get_providers
from rick_contracts.chat import ChatRequest
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


def _rate_allowed(providers, key: str) -> bool:
    limiter = _chat_rate_limiter(providers)
    try:
        return check_rate_limit(limiter, key, limit_per_min=providers.settings.chat_rate_limit_per_min)
    except TypeError as exc:
        raise ApiError("internal_error") from exc


def _chat_rate_allowed(providers, session) -> bool:
    return _rate_allowed(providers, _chat_rate_key(session))


def _compat_rate_allowed(providers, api_key: str) -> bool:
    """Apply the same bounded limiter to API-key compatibility traffic."""
    key = hashlib.sha256(f"compat:{api_key}".encode("utf-8")).hexdigest()
    return _rate_allowed(providers, key)


def _service(request: Request) -> ChatApplicationService:
    providers = get_providers(request)
    return ChatApplicationService(providers.chat_backend, providers.chat_history)  # type: ignore[arg-type]


@router.post("/api/v1/chat")
async def chat(payload: ChatRequest, request: Request, session=Depends(require_authenticated)):
    providers = get_providers(request)
    if not _chat_rate_allowed(providers, session):
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
            )
            async with closing_stream(events, request.scope):
                async for event in events:
                    if await request.is_disconnected():
                        break
                    yield f"data: {json.dumps(event)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(event_gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    return await service.chat(session=session, message=payload.message, conversation_id=payload.conversation_id,
                              collection_id=payload.collection_id, workspace_id=payload.workspace_id, mode=payload.mode)


@router.get("/api/v1/history")
def history(request: Request, session=Depends(require_authenticated), limit: int = Query(default=50, ge=1, le=100)):
    from services.authorization_service import has_permission

    if not has_permission(session, "history.read"):
        raise ApiError("forbidden")
    store = get_providers(request).chat_history
    if store is None or not callable(getattr(store, "list_history", None)):
        return {"items": [], "total": 0}
    items = store.list_history(session=session, limit=limit)
    return {"items": items, "total": len(items)}


@router.get("/api/v1/sources")
def sources(request: Request, session=Depends(require_authenticated), limit: int = Query(default=50, ge=1, le=100)):
    from core.errors import ApiError
    from services.authorization_service import has_permission

    if not has_permission(session, "sources.read"):
        raise ApiError("forbidden")
    store = get_providers(request).chat_history
    if store is None or not callable(getattr(store, "list_sources", None)):
        return {"items": [], "total": 0}
    items = store.list_sources(session=session, limit=limit)
    return {"items": items, "total": len(items)}
