"""Canonical authorization package — single source of truth (stdlib only)."""

from rick_authorization.policy import (
    AUTHORIZATION_SNAPSHOT_VERSION,
    CANONICAL_COLLECTION_ID,
    CANONICAL_PERMISSION_IDS,
    CANONICAL_ROLES,
    LEGACY_PERMISSION_ALIASES,
    LEGACY_ROLE_ALIASES,
    ROLE_PERMISSIONS,
    AuthorizationError,
    allowed_collection_ids_for_user,
    build_retrieval_context,
    can_access_collection,
    can_access_workspace,
    canonical_role,
    filter_collection_items,
    legacy_role_label,
    normalize_permission_overrides,
    normalize_permissions,
    permission_alias,
    permission_granted,
    permissions_for_role,
)

__all__ = [
    "AUTHORIZATION_SNAPSHOT_VERSION", "CANONICAL_COLLECTION_ID",
    "CANONICAL_PERMISSION_IDS", "CANONICAL_ROLES",
    "LEGACY_PERMISSION_ALIASES", "LEGACY_ROLE_ALIASES", "ROLE_PERMISSIONS",
    "AuthorizationError", "allowed_collection_ids_for_user",
    "build_retrieval_context", "can_access_collection", "can_access_workspace",
    "canonical_role", "filter_collection_items", "legacy_role_label",
    "normalize_permission_overrides", "normalize_permissions",
    "permission_alias", "permission_granted", "permissions_for_role",
]
