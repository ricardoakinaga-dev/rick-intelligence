"""Platform chat contract — frozen in Phase 1.3 so Professor extraction (1.4) keeps the public API stable."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

MAX_CHAT_MESSAGE_CHARS = 20000


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_CHAT_MESSAGE_CHARS)
    conversation_id: str | None = Field(default=None, max_length=128)
    collection_id: str | None = Field(default=None, max_length=128, description="Scope hint only; server ACL decides")
    workspace_id: str | None = Field(default=None, max_length=128)
    mode: str = Field(default="grounded", max_length=32)
    stream: bool = False


class Citation(BaseModel):
    document_id: str
    chunk_id: str | None = None
    title: str | None = None
    collection_id: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    checksum: str | None = None


class ChatResponse(BaseModel):
    conversation_id: str
    message_id: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatStreamEvent(BaseModel):
    type: Literal["start", "delta", "citation", "completion", "error"]
    conversation_id: str | None = None
    message_id: str | None = None
    delta: str | None = None
    citation: Citation | None = None
    answer: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    code: str | None = None
    message: str | None = None
