"""Canonical role, permission, and collection-scope policy.

The persisted API still accepts legacy role names during migration. Business
logic should call these helpers instead of comparing role strings directly.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

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
# permission_granted() through LEGACY_PERMISSION_ALIASES. A bare wildcard means
# every permission identifier. Once a wildcard role has removals, the effective
# result is materialized from this registry plus explicit additions, then the
# removals are applied so a removal remains visible to request-time checks.
CANONICAL_PERMISSION_IDS = (
    "audit.read",
    "chat.query",
    "collections.manage",
    "collections.read",
    "corpus.audit",
    "corpus.repair",
    "documents.manage",
    "documents.read",
    "documents.upload",
    "history.read",
    "ingestion.run",
    "library.browse",
    "observability.read",
    "reindex.run",
    "runtime.manage",
    "sessions.revoke",
    "sources.read",
    "tenants.read",
    "tenants.manage",
    "users.manage",
)

ROLE_PERMISSIONS: dict[str, tuple[str, ...]] = {
    "PLATFORM_ADMIN": ("*",),
    "KNOWLEDGE_MANAGER": (
        "chat.query",
        "history.read",
        "library.browse",
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
        "history.read",
        "sources.read",
        "collections.read",
    ),
}

LEGACY_PERMISSION_ALIASES = {
    "search.execute": "chat.query",
    "query.execute": "chat.query",
    "documents.search": "chat.query",
    "documents.query": "chat.query",
    "chat.history.read": "history.read",
    "queries.history.read": "history.read",
    "library.read": "library.browse",
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
    candidate = str(permission or "").strip().lower()
    return LEGACY_PERMISSION_ALIASES.get(candidate, candidate)


def normalize_permissions(permissions: Iterable[str] | None) -> list[str]:
    """Return a deterministic, canonical permission list.

    Persisted sessions may contain legacy route names. Normalizing the
    snapshot at the boundary keeps the authorization check independent of the
    spelling used by an older record.
    """
    if permissions is None:
        return []
    if isinstance(permissions, str):
        permissions = (permissions,)
    return sorted(
        {
            normalized
            for item in permissions
            if isinstance(item, str)
            for normalized in (permission_alias(item),)
            if normalized
        }
    )


def normalize_permission_overrides(overrides: object | None) -> dict[str, list[str]]:
    """Normalize add/remove overrides and make removal win on conflicts."""
    if hasattr(overrides, "model_dump"):
        payload = overrides.model_dump(exclude_none=True)
    elif isinstance(overrides, Mapping):
        payload = overrides
    else:
        payload = {}

    def values(key: str) -> list[str]:
        raw = payload.get(key)
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, (list, tuple, set)):
            return []
        return normalize_permissions(raw)

    additions = set(values("add"))
    removals = set(values("remove"))
    additions.difference_update(removals)
    return {"add": sorted(additions), "remove": sorted(removals)}


def permissions_for_role(role: str | None, overrides: dict | None = None) -> list[str]:
    base = set(normalize_permissions(ROLE_PERMISSIONS[canonical_role(role)]))
    normalized_overrides = normalize_permission_overrides(overrides)
    additions = set(normalized_overrides["add"])
    removals = set(normalized_overrides["remove"])

    # Removing the wildcard grant means that no inherited permission remains.
    # Explicit additions can still opt individual permissions back in, while
    # any explicit removal continues to win over those additions.
    if "*" in removals:
        resolved = (base | additions) - {"*"}
        resolved.difference_update(removals - {"*"})
        return sorted(resolved)

    wildcard_source = "*" in base or "*" in additions
    wildcard_granted = wildcard_source
    if wildcard_granted:
        explicit_removals = removals - {"*"}
        if not explicit_removals:
            return ["*"]
        resolved = set(CANONICAL_PERMISSION_IDS)
        resolved.update(additions - {"*"})
        resolved.difference_update(explicit_removals)
        return sorted(resolved)

    resolved = base - {"*"}
    resolved.update(additions - {"*"})
    resolved.difference_update(removals)
    return sorted(resolved)


def permission_granted(
    *,
    role: str | None = None,
    permissions: Iterable[str] = (),
    required: str,
    authoritative: bool = False,
) -> bool:
    required_canonical = permission_alias(required)
    resolved = set(normalize_permissions(permissions))
    if "*" in resolved:
        return True
    if required_canonical in resolved:
        return True
    if authoritative:
        return False
    # Keep the Phase 0.5 direct helper contract for legacy callers that pass
    # an empty permission list as an omitted snapshot. All session/user
    # enforcement paths pass authoritative=True, so an explicit empty or
    # reduced snapshot cannot fall back to its role.
    if role is not None and not resolved:
        fallback = set(permissions_for_role(role))
        return "*" in fallback or required_canonical in fallback
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
