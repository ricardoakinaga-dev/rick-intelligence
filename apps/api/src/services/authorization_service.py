"""Authorization facade — orchestration only, calls packages/authorization.

No role tables, no alias maps, no fallbacks live here. Authenticated modern
snapshots are ALWAYS checked with authoritative semantics: an explicit removal
or an empty list can never be re-granted via role defaults.
"""

from __future__ import annotations

from rick_authorization import (
    AuthorizationError,
    build_retrieval_context as _build_context,
    can_access_workspace,
    canonical_role,
    filter_collection_items as _filter_items,
    permission_granted,
)
from core.otel import record_safe_exception, stage_span


def has_permission(session, permission: str) -> bool:
    """Authoritative check against the session snapshot. No role fallback."""
    with stage_span("auth.authorization", attributes={"auth.operation": "permission_check"}) as span:
        try:
            if not getattr(session, "authenticated", False):
                return False
            return permission_granted(
                role=None,
                permissions=list(getattr(session, "permissions", None) or []),
                required=permission,
                authoritative=True,
            )
        except Exception as exc:
            record_safe_exception(span, exc)
            raise


def build_retrieval_context(session, *, workspace_id: str, collection_id: str | None = None) -> dict:
    """Server-side scope; request input narrows only. Raises ApiError(forbidden)."""
    from core.errors import ApiError

    tenant_id = getattr(session, "tenant_id", None)
    fields = getattr(session, "model_fields_set", None) or getattr(session, "__fields_set__", None)
    if (
        not isinstance(tenant_id, str)
        or not tenant_id.strip()
        or not isinstance(fields, set)
        or "tenant_id" not in fields
    ):
        raise ApiError("forbidden")
    try:
        return _build_context(
            user_id=getattr(session, "user_id", None),
            session_workspace=getattr(session, "workspace_id", None),
            requested_workspace=workspace_id,
            allowed_collection_ids=list(getattr(session, "allowed_collection_ids", None) or []),
            permissions=list(getattr(session, "permissions", None) or []),
            role=getattr(session, "canonical_role", None) or getattr(session, "role", None),
            requested_collection_id=collection_id,
            tenant_id=tenant_id,
        )
    except AuthorizationError as exc:
        raise ApiError(exc.code or "forbidden")


def filter_collection_items(items: list[dict], context: dict) -> list[dict]:
    return _filter_items(items, context.get("allowed_collection_ids", []))


__all__ = ["has_permission", "build_retrieval_context", "filter_collection_items", "can_access_workspace", "canonical_role"]
