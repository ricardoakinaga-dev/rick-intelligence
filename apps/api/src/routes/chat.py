"""Platform-native chat endpoint (canonical contract; no chain-of-thought)."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core.errors import ApiError
from dependencies.identity import require_authenticated
from dependencies.services import get_providers
from services.chat_service import ChatApplicationService

router = APIRouter(tags=["Clinical"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    conversation_id: str | None = Field(default=None, max_length=128)
    collection_id: str | None = Field(default=None, max_length=128)
    workspace_id: str | None = Field(default=None, max_length=128)
    mode: str = Field(default="grounded", max_length=32)
    stream: bool = False


def _service() -> ChatApplicationService:
    providers = get_providers()
    return ChatApplicationService(providers.chat_backend)  # type: ignore[arg-type]


@router.post("/api/v1/chat")
async def chat(payload: ChatRequest, request: Request, session=Depends(require_authenticated)):
    providers = get_providers()
    if len(payload.message) > providers.settings.max_chat_message_chars:
        raise ApiError("validation_error", "Message is too long.")
    service = _service()
    if payload.stream:
        async def event_gen():
            async for event in service.stream_events(
                session=session, message=payload.message, conversation_id=payload.conversation_id,
                collection_id=payload.collection_id, workspace_id=payload.workspace_id, mode=payload.mode,
            ):
                # Client disconnect propagates cancellation: stop generating.
                if await request.is_disconnected():
                    break
                yield f"data: {json.dumps(event)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(event_gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    return await service.chat(session=session, message=payload.message, conversation_id=payload.conversation_id,
                              collection_id=payload.collection_id, workspace_id=payload.workspace_id, mode=payload.mode)


@router.get("/api/v1/history")
def history(session=Depends(require_authenticated)):
    return {"items": [], "total": 0}


@router.get("/api/v1/sources")
def sources(session=Depends(require_authenticated)):
    from core.errors import ApiError
    from services.authorization_service import has_permission

    if not has_permission(session, "sources.read"):
        raise ApiError("forbidden")
    return {"items": [], "total": 0}
