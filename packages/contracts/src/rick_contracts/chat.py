"""Platform chat contract — frozen in Phase 1.3 so Professor extraction (1.4) keeps the public API stable."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from rick_contracts.base import StrictContractModel

MAX_CHAT_MESSAGE_CHARS = 20000


class ChatRequest(StrictContractModel):
    message: str = Field(min_length=1, max_length=MAX_CHAT_MESSAGE_CHARS)
    conversation_id: str | None = Field(default=None, max_length=128)
    idempotency_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Client retry key; scoped to the authenticated user and conversation turn",
    )
    collection_id: str | None = Field(default=None, max_length=128, description="Scope hint only; server ACL decides")
    workspace_id: str | None = Field(default=None, max_length=128)
    mode: str = Field(default="grounded", max_length=32)
    stream: bool = False


class Citation(StrictContractModel):
    document_id: str
    chunk_id: str | None = None
    title: str | None = None
    collection_id: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    checksum: str | None = None


class ChatResponse(StrictContractModel):
    conversation_id: str
    message_id: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConversationSummary(StrictContractModel):
    conversation_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=160)
    workspace_id: str = Field(min_length=1, max_length=128)
    collection_id: str | None = Field(default=None, max_length=128)
    status: Literal["active", "archived"]
    created_at: float
    updated_at: float
    message_count: int = Field(ge=0, le=100_000)


class ConversationListResponse(StrictContractModel):
    items: list[ConversationSummary] = Field(default_factory=list, max_length=100)
    total: int = Field(ge=0, le=100_000)
    next_cursor: str | None = Field(default=None, max_length=256)


class ConversationMessage(StrictContractModel):
    conversation_id: str = Field(min_length=1, max_length=128)
    message_id: str = Field(min_length=1, max_length=128)
    question: str = Field(max_length=20_000)
    answer: str = Field(max_length=8_000)
    citations: list[Citation] = Field(default_factory=list, max_length=32)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: float


class ConversationDetailResponse(StrictContractModel):
    conversation: ConversationSummary
    items: list[ConversationMessage] = Field(default_factory=list, max_length=100)
    total: int = Field(ge=0, le=100_000)
    next_cursor: str | None = Field(default=None, max_length=256)


class HistoryListResponse(StrictContractModel):
    items: list[ConversationMessage] = Field(default_factory=list, max_length=100)
    total: int = Field(ge=0, le=100_000)
    next_cursor: str | None = Field(default=None, max_length=256)


class SourceItem(Citation):
    conversation_id: str = Field(min_length=1, max_length=128)
    message_id: str = Field(min_length=1, max_length=128)
    created_at: float


class SourceListResponse(StrictContractModel):
    items: list[SourceItem] = Field(default_factory=list, max_length=100)
    total: int = Field(ge=0, le=100_000)
    next_cursor: str | None = Field(default=None, max_length=256)


class ChatStreamEvent(StrictContractModel):
    type: Literal["start", "delta", "citation", "completion", "error"]
    conversation_id: str | None = None
    message_id: str | None = None
    delta: str | None = None
    citation: Citation | None = None
    answer: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    code: str | None = None
    message: str | None = None
    provisional: bool | None = None
