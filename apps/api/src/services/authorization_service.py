"""Authorization service — routes never compare role strings; they call this."""

from __future__ import annotations

from models import SessionSnapshot
from services.identity_service import CANONICAL_PERMISSIONS, canonical_role


def has_permission(session: SessionSnapshot, permission: str) -> bool:
    if not session.authenticated:
        return False
    perms = set(session.permissions or [])
    if "*" in perms:
        return True
    if permission in perms:
        return True
    # Fall back to canonical role grant (covers snapshots without explicit perms).
    role_grant = set(CANONICAL_PERMISSIONS.get(canonical_role(session.canonical_role or session.role), []))
    return "*" in role_grant or permission in role_grant


def build_retrieval_context(session: SessionSnapshot, *, workspace_id: str, collection_id: str | None = None) -> dict:
    """Server-side scope; request input can only narrow, never widen.

    Raises ApiError(forbidden) when the requested collection is outside the grant.
    """
    from core.errors import ApiError

    if session.workspace_id and workspace_id != session.workspace_id:
        # PLATFORM_ADMIN may operate cross-workspace; others are confined.
        if canonical_role(session.canonical_role or session.role) != "PLATFORM_ADMIN":
            raise ApiError("forbidden")
    allowed = list(session.allowed_collection_ids or [])
    role = canonical_role(session.canonical_role or session.role)
    if not allowed and role in ("PLATFORM_ADMIN", "KNOWLEDGE_MANAGER"):
        allowed = ["*"]
    if not allowed:
        allowed = ["rag_phase0"]
    if collection_id:
        if "*" not in allowed and collection_id not in allowed:
            raise ApiError("forbidden")
        allowed = [collection_id]
    return {
        "user_id": session.user_id,
        "workspace_id": workspace_id,
        "allowed_collection_ids": allowed,
        "permissions": list(session.permissions or []),
    }


def filter_collection_items(items: list[dict], context: dict) -> list[dict]:
    allowed = set(context.get("allowed_collection_ids", []))
    if "*" in allowed:
        return items
    return [i for i in items if (i.get("collection_id") or i.get("qdrant_collection")) in allowed]
