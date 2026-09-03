"""OpenAI-compatible adapter — delegates to the canonical ChatApplicationService.

Not a second Professor implementation: OpenWebUI -> this adapter -> ChatApplicationService.
Deviations documented in docs/architecture/api-compatibility.md (usage is null, not fabricated).
"""

from __future__ import annotations

import json
import time
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core.errors import ApiError
from core.security import constant_time_compare
from dependencies.services import get_providers
from models import SessionSnapshot
from services.authorization_service import build_retrieval_context
from services.chat_service import ChatApplicationService

router = APIRouter(tags=["Compatibility"])


class CompatMessage(BaseModel):
    role: str = "user"
    content: str | list | None = None


class CompatRequest(BaseModel):
    model: str | None = None
    messages: list[CompatMessage] = Field(min_length=1)
    stream: bool = False
    user: str | None = Field(default=None, max_length=128)
    conversation_id: str | None = Field(default=None, max_length=128)


def _extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and "text" in item:
                parts.append(str(item.get("text") or ""))
        return "\n".join(p for p in parts if p)
    return ""


def _check_api_key(request: Request) -> None:
    providers = get_providers()
    expected = providers.settings.compat_api_key
    if not expected:
        raise ApiError("provider_unavailable", "Compatibility API key is not configured.")
    auth = request.headers.get("authorization") or ""
    presented = auth[len("Bearer "):].strip() if auth.startswith("Bearer ") else ""
    if not presented:
        presented = (request.headers.get("x-api-key") or "").strip()
    if not constant_time_compare(presented, expected):
        raise ApiError("unauthorized")


def _compat_session() -> SessionSnapshot:
    """Compat domain uses a server-bound service identity; collection scope comes from server config."""
    return SessionSnapshot(
        authenticated=True, session_state="active", user_id="compat-service",
        role="KNOWLEDGE_MANAGER", canonical_role="KNOWLEDGE_MANAGER",
        permissions=["chat.query", "sources.read"], workspace_id="default",
        tenant_id="default", allowed_collection_ids=["*"],
    )


@router.get("/v1/models")
def list_models(request: Request):
    _check_api_key(request)
    providers = get_providers()
    return {"object": "list", "data": [{"id": "rick-professor", "object": "model",
            "created": int(time.time()), "owned_by": "rick-professor"}]}


@router.post("/v1/chat/completions")
async def chat_completions(payload: CompatRequest, request: Request):
    _check_api_key(request)
    providers = get_providers()
    texts = [_extract_text(m.content) for m in payload.messages if m.role != "system"]
    prompt = "\n\n".join(t for t in texts if t.strip())
    if not prompt:
        raise ApiError("validation_error", "No user message provided.")
    if len(prompt) > providers.settings.max_chat_message_chars:
        raise ApiError("validation_error", "Message is too long.")
    session = _compat_session()
    conversation_id = payload.conversation_id or payload.user or f"openwebui-{uuid.uuid4().hex[:8]}"
    service = ChatApplicationService(providers.chat_backend)  # type: ignore[arg-type]
    created = int(time.time())
    completion_id = f"chatcmpl-{created}-{uuid.uuid4().hex[:6]}"
    model = payload.model or "rick-professor"

    if payload.stream:
        async def event_gen():
            yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model, 'choices': [{'index': 0, 'delta': {'role': 'assistant'}, 'finish_reason': None}]})}\n\n"
            async for event in service.stream_events(session=session, message=prompt,
                                                     conversation_id=conversation_id,
                                                     collection_id=None, workspace_id="default", mode="grounded"):
                if await request.is_disconnected():
                    break
                if event["type"] == "delta":
                    yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model, 'choices': [{'index': 0, 'delta': {'content': event.get('delta', '')}, 'finish_reason': None}]})}\n\n"
                elif event["type"] == "error":
                    yield f"data: {json.dumps({'error': {'message': event.get('message'), 'type': 'server_error'}})}\n\n"
                    break
                elif event["type"] == "completion":
                    yield f"data: {json.dumps({'id': completion_id, 'object': 'chat.completion.chunk', 'created': created, 'model': model, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(event_gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache, no-transform"})

    result = await service.chat(session=session, message=prompt, conversation_id=conversation_id,
                                collection_id=None, workspace_id="default", mode="grounded")
    return {
        "id": completion_id, "object": "chat.completion", "created": created, "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": result["answer"]}, "finish_reason": "stop"}],
        "usage": None,  # documented: never fabricated
        "metadata": result.get("metadata", {}),
    }
