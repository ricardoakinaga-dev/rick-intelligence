"""Shared API-boundary models.

SessionSnapshot is OWNED by packages/contracts — this module only re-exports it
so route/dependency import paths stay stable. No policy lives here.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from rick_contracts.security import SessionSnapshot  # noqa: F401 (canonical re-export)


class AuditEvent(BaseModel):
    action: str
    actor_user_id: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    workspace_id: str | None = None
    request_id: str | None = None
    metadata: dict = Field(default_factory=dict)
