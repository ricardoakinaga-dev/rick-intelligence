"""Legacy auth compatibility facade (adapter boundary).

Preserved `cvg-master-rag-v2/src/services/authorization.py` files are kept
byte-identical (migration preservation rule). This facade exposes the same
helper SHAPES backed by the canonical root engine, so legacy callers can be
switched route-by-route after differential equivalence is proven:

legacy route -> this facade -> packages/authorization (+ packages/identity)

Deprecation state: DUAL. Migration owner: PH131-LEGACY-FACADE (Phase 1.4+).
"""

from __future__ import annotations

from rick_authorization import (
    allowed_collection_ids_for_user,
    canonical_role,
    legacy_role_label,
    normalize_permission_overrides,
    normalize_permissions,
    permission_alias,
    permission_granted,
    permissions_for_role,
)

# Legacy-compatible names (drop-in for cvg `services.authorization` imports).
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


def legacy_permission_check(*, role=None, permissions=(), required, authoritative=True) -> bool:
    """Canonical-backed check with legacy call shape.

    Unlike the legacy default (`authoritative=False`), this facade defaults to
    authoritative so migrated callers cannot inherit role fallback silently.
    """
    return permission_granted(role=role, permissions=permissions, required=required, authoritative=authoritative)


__all__ = [
    "LEGACY_TO_CANONICAL",
    "allowed_collection_ids_for_user",
    "canonical_role",
    "legacy_permission_check",
    "legacy_role_label",
    "normalize_permission_overrides",
    "normalize_permissions",
    "permission_alias",
    "permission_granted",
    "permissions_for_role",
]
