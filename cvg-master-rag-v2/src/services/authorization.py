"""Canonical role, permission, and collection-scope policy.

The persisted API still accepts legacy role names during migration. Business
logic should call these helpers instead of comparing role strings directly.
"""

from __future__ import annotations

from collections.abc import Iterable

from services.rag_contract import CANONICAL_COLLECTION_ID, normalize_collection_id


CANONICAL_ROLES = ("PLATFORM_ADMIN", "KNOWLEDGE_MANAGER", "VETERINARIAN")
LEGACY_TO_CANONICAL = {
    "platform_admin": "PLATFORM_ADMIN",
    "super_admin": "PLATFORM_ADMIN",
    "admin": "PLATFORM_ADMIN",
    "knowledge_manager": "KNOWLEDGE_MANAGER",
    "admin_rag": "KNOWLEDGE_MANAGER",
    "operator": "KNOWLEDGE_MANAGER",
    "veterinarian": "VETERINARIAN",
    "viewer": "VETERINARIAN",
    "auditor": "VETERINARIAN",
}

# Canonical permission identifiers. Legacy route identifiers are accepted by
# permission_granted() through LEGACY_PERMISSION_ALIASES.
ROLE_PERMISSIONS: dict[str, tuple[str, ...]] = {
    "PLATFORM_ADMIN": ("*",),
    "KNOWLEDGE_MANAGER": (
        "chat.query",
        "documents.read",
        "documents.upload",
        "documents.manage",
        "sources.read",
        "collections.read",
        "collections.manage",
        "ingestion.run",
        "reindex.run",
        "observability.read",
        "audit.read",
        "corpus.audit",
        "corpus.repair",
    ),
    "VETERINARIAN": (
        "chat.query",
        "documents.read",
        "sources.read",
        "collections.read",
    ),
}

LEGACY_PERMISSION_ALIASES = {
    "search.execute": "chat.query",
    "query.execute": "chat.query",
    "documents.search": "chat.query",
    "documents.query": "chat.query",
    "sources.read": "sources.read",
    "documents.read": "documents.read",
    "documents.upload": "documents.upload",
}


def canonical_role(role: str | None) -> str:
    candidate = str(role or "viewer").strip().lower()
    return LEGACY_TO_CANONICAL.get(candidate, "VETERINARIAN")


def legacy_role_for_canonical(role: str | None) -> str:
    canonical = canonical_role(role)
    return {
        "PLATFORM_ADMIN": "super_admin",
        "KNOWLEDGE_MANAGER": "admin_rag",
        "VETERINARIAN": "viewer",
    }[canonical]


def permission_alias(permission: str) -> str:
    return LEGACY_PERMISSION_ALIASES.get(str(permission).strip(), str(permission).strip())


def permissions_for_role(role: str | None, overrides: dict | None = None) -> list[str]:
    base = list(ROLE_PERMISSIONS[canonical_role(role)])
    if "*" in base:
        return ["*"]
    resolved = set(base)
    payload = overrides if isinstance(overrides, dict) else {}
    for permission in payload.get("add", []) if isinstance(payload.get("add"), list) else []:
        if isinstance(permission, str) and permission.strip():
            resolved.add(permission_alias(permission))
    for permission in payload.get("remove", []) if isinstance(payload.get("remove"), list) else []:
        if isinstance(permission, str) and permission.strip():
            resolved.discard(permission_alias(permission))
    return sorted(resolved)


def permission_granted(
    *,
    role: str | None = None,
    permissions: Iterable[str] = (),
    required: str,
) -> bool:
    required_canonical = permission_alias(required)
    resolved = {permission_alias(item) for item in permissions if isinstance(item, str)}
    if "*" in resolved:
        return True
    if required_canonical in resolved:
        return True
    # A session assembled from an older persisted record may omit permissions;
    # derive them from its role without weakening explicit removals.
    if role is not None:
        return required_canonical in set(permissions_for_role(role))
    return False


def allowed_collection_ids_for_user(user: dict | object) -> list[str]:
    """Resolve a user/role grant into a retrieval scope.

    Platform administrators and knowledge managers with no explicit grant are
    scoped to all collections in their active workspace. Veterinarians default
    to the canonical collection only; explicit grants are normalized and kept.
    """
    if isinstance(user, dict):
        role = user.get("role")
        raw = user.get("authorized_collection_ids", [])
    else:
        role = getattr(user, "role", None)
        raw = getattr(user, "authorized_collection_ids", [])
    grants = [
        "*" if item.strip() == "*" else normalize_collection_id(item)
        for item in raw
        if isinstance(item, str) and item.strip()
    ]
    if grants:
        return grants
    if canonical_role(role) in {"PLATFORM_ADMIN", "KNOWLEDGE_MANAGER"}:
        return ["*"]
    return [CANONICAL_COLLECTION_ID]
