"""Shared typed models for the API boundary (no legacy imports here)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SessionSnapshot(BaseModel):
    authenticated: bool = False
    session_state: str = "anonymous"
    user_id: str | None = None
    email: str | None = None
    role: str | None = None
    canonical_role: str | None = None
    permissions: list[str] = Field(default_factory=list)
    tenant_id: str | None = None
    workspace_id: str | None = None
    session_id: str | None = None
    allowed_collection_ids: list[str] = Field(default_factory=list)


class AuditEvent(BaseModel):
    action: str
    actor_user_id: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    workspace_id: str | None = None
    request_id: str | None = None
    metadata: dict = Field(default_factory=dict)
