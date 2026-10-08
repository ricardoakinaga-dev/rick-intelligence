"""Authorization facade — orchestration only, calls packages/authorization.

No role tables, no alias maps, no fallbacks live here. Authenticated modern
snapshots are ALWAYS checked with authoritative semantics: an explicit removal
or an empty list can never be re-granted via role defaults.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import inspect

from rick_authorization import (
    AuthorizationError,
    CANONICAL_ROLES,
    LEGACY_ROLE_ALIASES,
    authorization_grants_for_user,
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


def refresh_context_from_user(context: Mapping[str, object], user: Mapping[str, object]) -> dict[str, object] | None:
    """Narrow a request snapshot against one freshly read authoritative user.

    Grants can be revoked while a request is generating. This callback never
    expands the snapshot captured at authentication time; a newly granted
    permission takes effect after a fresh session is issued.
    """
    user_id = context.get("user_id")
    tenant_id = context.get("tenant_id")
    workspace_id = context.get("workspace_id")
    if (
        not isinstance(user_id, str) or not user_id
        or not isinstance(tenant_id, str) or not tenant_id
        or not isinstance(workspace_id, str) or not workspace_id
        or user.get("user_id") != user_id
        or user.get("tenant_id") != tenant_id
        or user.get("status", "active") != "active"
    ):
        return None
    raw_role = user.get("role")
    if (
        not isinstance(raw_role, str)
        or (
            raw_role.strip().upper() not in CANONICAL_ROLES
            and raw_role.strip().casefold() not in LEGACY_ROLE_ALIASES
        )
    ):
        # canonical_role() intentionally maps unknown legacy values to the
        # least-privileged UI role for compatibility. Live revalidation must
        # reject malformed authoritative rows instead of applying that fallback.
        return None
    if not can_access_workspace(
        session_workspace=user.get("workspace_id", "default"),
        requested_workspace=workspace_id,
        role=raw_role,
    ):
        return None
    old_collections = context.get("allowed_collection_ids")
    old_permissions = context.get("permissions")
    if (
        not isinstance(old_collections, list)
        or not all(isinstance(item, str) for item in old_collections)
        or not isinstance(old_permissions, list)
        or not all(isinstance(item, str) for item in old_permissions)
    ):
        return None
    fresh_grants = authorization_grants_for_user(user)
    fresh_collections = fresh_grants["allowed_collection_ids"]
    fresh_permissions = fresh_grants["permissions"]

    def narrow(previous: list[str], current: list[str]) -> list[str]:
        if "*" in previous:
            return sorted(set(current))
        if "*" in current:
            return sorted(set(previous))
        return sorted(set(previous).intersection(current))

    return {
        **dict(context),
        "allowed_collection_ids": narrow(old_collections, fresh_collections),
        "permissions": narrow(old_permissions, fresh_permissions),
    }


def make_authorization_revalidator(
    identity_revalidator,
    *,
    compatibility_workspace_id: str,
    compatibility_collection_ids: list[str] | tuple[str, ...],
):
    """Compose live user checks with the finite, server-issued compat scope."""
    if getattr(identity_revalidator, "compatibility_aware", False) is True:
        return identity_revalidator
    configured_collections = frozenset(
        item for item in compatibility_collection_ids
        if isinstance(item, str) and item and item != "*"
    )

    async def revalidate(*, context: Mapping[str, object]):
        if not isinstance(context, Mapping):
            return None
        if context.get("user_id") == "compat-service":
            collections = context.get("allowed_collection_ids")
            permissions = context.get("permissions")
            if (
                context.get("tenant_id") != "default"
                or context.get("workspace_id") != compatibility_workspace_id
                or not isinstance(collections, list)
                or not collections
                or not all(isinstance(item, str) and item and item != "*" for item in collections)
                or not isinstance(permissions, list)
                or not all(isinstance(item, str) for item in permissions)
                or "chat.query" not in permissions
            ):
                return None
            narrowed = sorted(set(collections).intersection(configured_collections))
            if not narrowed:
                return None
            return {
                **dict(context),
                "allowed_collection_ids": narrowed,
                "permissions": sorted(set(permissions).intersection({"chat.query", "sources.read"})),
            }
        if not callable(identity_revalidator):
            return None
        try:
            is_async = (
                inspect.iscoroutinefunction(identity_revalidator)
                or inspect.iscoroutinefunction(getattr(identity_revalidator, "__call__", None))
            )
            current = (
                identity_revalidator(context=dict(context))
                if is_async
                else await asyncio.to_thread(identity_revalidator, context=dict(context))
            )
            return await current if inspect.isawaitable(current) else current
        except Exception:
            return None

    revalidate.compatibility_aware = True
    return revalidate


__all__ = [
    "has_permission", "build_retrieval_context", "filter_collection_items",
    "refresh_context_from_user", "make_authorization_revalidator",
    "can_access_workspace", "canonical_role",
]
