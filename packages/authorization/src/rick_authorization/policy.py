"""Canonical authorization policy engine — the SINGLE source of truth.

Owns: canonical roles, permission registry, role defaults, legacy aliases,
override normalization, effective-permission resolution, wildcard semantics,
authoritative snapshot enforcement, workspace/collection scope, RetrievalContext.

Stdlib only. MUST NOT import legacy apps or apps/api (enforced by tests).

Security invariants:
- effective = role_defaults + add − remove; removal always wins.
- Modern authoritative snapshots NEVER fall back to role defaults.
  `permissions=[]` means no permissions.
- Legacy migration is explicit (`authorization_state == "LEGACY_UNMIGRATED"`)
  and one-time: derive once, persist, mark migrated.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

CANONICAL_COLLECTION_ID = "rag_phase0"
AUTHORIZATION_SNAPSHOT_VERSION = 1

CANONICAL_ROLES = ("PLATFORM_ADMIN", "KNOWLEDGE_MANAGER", "VETERINARIAN")

LEGACY_ROLE_ALIASES = {
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


# ---------------------------------------------------------------- roles ---

def canonical_role(role: str | None) -> str:
    candidate = str(role or "viewer").strip().lower()
    return LEGACY_ROLE_ALIASES.get(candidate, "VETERINARIAN")


def legacy_role_label(role: str | None) -> str:
    return {
        "PLATFORM_ADMIN": "super_admin",
        "KNOWLEDGE_MANAGER": "admin_rag",
        "VETERINARIAN": "viewer",
    }[canonical_role(role)]


# ---------------------------------------------------------- permissions ---

def permission_alias(permission: str) -> str:
    candidate = str(permission or "").strip().lower()
    return LEGACY_PERMISSION_ALIASES.get(candidate, candidate)


def normalize_permissions(permissions: Iterable[str] | None) -> list[str]:
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
    if hasattr(overrides, "model_dump"):
        payload = overrides.model_dump(exclude_none=True)  # type: ignore[union-attr]
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
        # Unknown identifiers are preserved verbatim (legacy parity) but remain
        # inert: every enforcement point checks membership of a canonical
        # required id, so an unknown string can never satisfy a real check.
        return normalize_permissions([p for p in raw if isinstance(p, str)])

    additions = set(values("add"))
    removals = set(values("remove"))
    additions.difference_update(removals)  # removal wins conflicts
    return {"add": sorted(additions), "remove": sorted(removals)}


def permissions_for_role(role: str | None, overrides: dict | None = None) -> list[str]:
    base = set(normalize_permissions(ROLE_PERMISSIONS[canonical_role(role)]))
    normalized = normalize_permission_overrides(overrides)
    additions = set(normalized["add"])
    removals = set(normalized["remove"])

    if "*" in removals:
        resolved = (base | additions) - {"*"}
        resolved.difference_update(removals - {"*"})
        return sorted(resolved)

    if "*" in base or "*" in additions:
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
    """Decide a permission check.

    authoritative=True (all modern session paths): the snapshot is final —
    NO role fallback, ever. An explicit empty/reduced list stays denied.
    authoritative=False: legacy helper contract — an OMITTED snapshot (empty
    list + role given) may use role defaults exactly once at migration time.
    """
    required_canonical = permission_alias(required)
    resolved = set(normalize_permissions(permissions))
    if "*" in resolved:
        return True
    if required_canonical in resolved:
        return True
    if authoritative:
        return False
    if role is not None and not resolved:
        fallback = set(permissions_for_role(role))
        return "*" in fallback or required_canonical in fallback
    return False


# ------------------------------------------------------------ collections ---

def _normalize_collection_id(value: str) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        raise ValueError("empty collection id")
    lowered = candidate.lower()
    if lowered in {"cvg_master_rag", "rickvet_documents", "rag_phase0"}:
        return CANONICAL_COLLECTION_ID
    return candidate


def allowed_collection_ids_for_user(user: Mapping | object) -> list[str]:
    if isinstance(user, Mapping):
        role = user.get("role")
        raw = user.get("authorized_collection_ids", [])
    else:
        role = getattr(user, "role", None)
        raw = getattr(user, "authorized_collection_ids", [])
    grants = []
    for item in raw or []:
        if not isinstance(item, str) or not item.strip():
            continue
        grants.append("*" if item.strip() == "*" else _normalize_collection_id(item))
    if grants:
        return grants
    if canonical_role(role) in {"PLATFORM_ADMIN", "KNOWLEDGE_MANAGER"}:
        return ["*"]
    return [CANONICAL_COLLECTION_ID]


def can_access_collection(*, allowed: Iterable[str], collection_id: str | None) -> bool:
    try:
        resolved = _normalize_collection_id(collection_id or "")
    except ValueError:
        return False
    granted = set(allowed or [])
    return "*" in granted or resolved in granted


def can_access_workspace(*, session_workspace: str | None, requested_workspace: str, role: str | None) -> bool:
    """PLATFORM_ADMIN may cross workspaces; others are confined to their session workspace."""
    if requested_workspace == (session_workspace or requested_workspace):
        return True
    return canonical_role(role) == "PLATFORM_ADMIN"


# ------------------------------------------------------ retrieval context ---

class AuthorizationError(Exception):
    def __init__(self, code: str = "forbidden"):
        super().__init__(code)
        self.code = code


def build_retrieval_context(
    *,
    user_id: str | None,
    session_workspace: str | None,
    requested_workspace: str,
    allowed_collection_ids: Iterable[str],
    permissions: Iterable[str],
    role: str | None,
    requested_collection_id: str | None = None,
) -> dict:
    """Trusted factory: request input narrows scope, never widens it."""
    if not can_access_workspace(
        session_workspace=session_workspace, requested_workspace=requested_workspace, role=role
    ):
        raise AuthorizationError("forbidden")
    allowed = list(allowed_collection_ids or [])
    if requested_collection_id:
        try:
            narrowed = _normalize_collection_id(requested_collection_id)
        except ValueError:
            raise AuthorizationError("forbidden")
        if "*" not in set(allowed) and narrowed not in set(allowed):
            raise AuthorizationError("forbidden")
        allowed = [narrowed]
    return {
        "user_id": user_id,
        "workspace_id": requested_workspace,
        "allowed_collection_ids": allowed,
        "permissions": list(permissions or []),
    }


def filter_collection_items(items: list[dict], allowed: Iterable[str]) -> list[dict]:
    granted = set(allowed or [])
    if "*" in granted:
        return list(items)
    return [i for i in items if (i.get("collection_id") or i.get("qdrant_collection")) in granted]
