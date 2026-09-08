"""Canonical authorization engine tests (stdlib-only package)."""

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rick_authorization import (
    CANONICAL_PERMISSION_IDS,
    CANONICAL_ROLES,
    LEGACY_ROLE_ALIASES,
    ROLE_PERMISSIONS,
    AuthorizationError,
    allowed_collection_ids_for_user,
    build_retrieval_context,
    can_access_collection,
    can_access_workspace,
    canonical_role,
    normalize_permission_overrides,
    permission_granted,
    permissions_for_role,
)


def test_canonical_roles_frozen():
    assert CANONICAL_ROLES == ("PLATFORM_ADMIN", "KNOWLEDGE_MANAGER", "VETERINARIAN")


def test_role_aliases():
    for alias in ("admin", "super_admin", "platform_admin", "admin_rag", "operator",
                  "knowledge_manager", "viewer", "veterinarian", "auditor"):
        assert canonical_role(alias) in CANONICAL_ROLES
    assert canonical_role("admin") == "PLATFORM_ADMIN"
    assert canonical_role("operator") == "KNOWLEDGE_MANAGER"
    assert canonical_role("viewer") == "VETERINARIAN"
    assert canonical_role(None) == "VETERINARIAN"
    assert canonical_role("nonsense") == "VETERINARIAN"


def test_base_permissions():
    assert permissions_for_role("VETERINARIAN") == [
        "cases.feedback", "cases.manage", "cases.read",
        "chat.query", "collections.read", "history.read", "sources.read",
    ]
    km = permissions_for_role("KNOWLEDGE_MANAGER")
    assert "documents.read" in km and "cases.review" in km and "users.manage" not in km and "runtime.manage" not in km
    assert permissions_for_role("PLATFORM_ADMIN") == ["*"]


def test_removal_wins_and_empty_means_none():
    assert "documents.read" not in permissions_for_role("KNOWLEDGE_MANAGER", {"remove": ["documents.read"]})
    assert permissions_for_role("VETERINARIAN", {"add": ["documents.read"], "remove": ["documents.read"]}) == \
        ["cases.feedback", "cases.manage", "cases.read", "chat.query", "collections.read", "history.read", "sources.read"]
    assert not permission_granted(role=None, permissions=[], required="chat.query", authoritative=True)


def test_authoritative_never_falls_back():
    # THE hard invariant: explicit reduced snapshot cannot regain via role.
    assert not permission_granted(role="KNOWLEDGE_MANAGER", permissions=["chat.query"],
                                  required="documents.read", authoritative=True)
    assert not permission_granted(role="PLATFORM_ADMIN", permissions=[],
                                  required="chat.query", authoritative=True)


def test_wildcard_materialization():
    assert permissions_for_role("PLATFORM_ADMIN", {"remove": ["users.manage"]}) != ["*"]
    resolved = permissions_for_role("PLATFORM_ADMIN", {"remove": ["users.manage"]})
    assert "users.manage" not in resolved and "chat.query" in resolved
    # removing "*" itself denies inheritance; explicit adds survive
    resolved = permissions_for_role("PLATFORM_ADMIN", {"remove": ["*"], "add": ["chat.query"]})
    assert resolved == ["chat.query"]


def test_override_normalization_dedupes_and_aliases():
    out = normalize_permission_overrides({"add": ["search.execute", "search.execute"], "remove": []})
    assert out == {"add": ["chat.query"], "remove": []}
    assert normalize_permission_overrides("garbage") == {"add": [], "remove": []}


def test_collections_narrow_only():
    assert can_access_collection(allowed=["rag_phase0"], collection_id="rag_phase0")
    assert not can_access_collection(allowed=["rag_phase0"], collection_id="secret")
    assert can_access_collection(allowed=["*"], collection_id="anything")
    assert not can_access_collection(allowed=["rag_phase0"], collection_id="not a collection!!!"[:0] or "")
    ctx = build_retrieval_context(user_id="u", session_workspace="w", requested_workspace="w",
                                  allowed_collection_ids=["a", "b"], permissions=["chat.query"],
                                  role="VETERINARIAN", requested_collection_id="a",
                                  tenant_id="default")
    assert ctx["allowed_collection_ids"] == ["a"]
    try:
        build_retrieval_context(user_id="u", session_workspace="w", requested_workspace="w",
                                allowed_collection_ids=["a"], permissions=[], role="VETERINARIAN",
                                requested_collection_id="b", tenant_id="default")
        raise AssertionError("widening must fail")
    except AuthorizationError:
        pass


def test_workspace_policy():
    assert can_access_workspace(session_workspace="w", requested_workspace="other", role="PLATFORM_ADMIN")
    assert not can_access_workspace(session_workspace="w", requested_workspace="other", role="VETERINARIAN")
    assert not can_access_workspace(session_workspace="w", requested_workspace="other", role="KNOWLEDGE_MANAGER")


def test_property_algebra_invariants():
    """Deterministic property sweep (fixed seed): removal-wins + authority hold everywhere."""
    rng = random.Random(13131)
    registry = list(CANONICAL_PERMISSION_IDS)
    for _ in range(500):
        role = rng.choice(list(CANONICAL_ROLES))
        adds = rng.sample(registry, rng.randint(0, 3))
        removes = rng.sample(registry, rng.randint(0, 3))
        resolved = permissions_for_role(role, {"add": adds, "remove": removes})
        for r in removes:
            if r != "*":
                assert r not in resolved, (role, adds, removes, resolved)
        for perm in registry:
            decided = permission_granted(role=None, permissions=resolved, required=perm, authoritative=True)
            assert decided == (perm in resolved or "*" in resolved)
        # Unknown required ids are granted only by wildcard or explicit presence.
        unknown = permission_granted(role=None, permissions=resolved, required="no.such.perm", authoritative=True)
        assert unknown == ("*" in resolved or "no.such.perm" in resolved)
