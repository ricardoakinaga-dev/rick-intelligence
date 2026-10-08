from types import SimpleNamespace

import pytest

from rick_authorization import allowed_collection_ids_for_user, can_access_collection, intersect_grants


@pytest.mark.parametrize("role", ["PLATFORM_ADMIN", "KNOWLEDGE_MANAGER", "VETERINARIAN"])
@pytest.mark.parametrize("grants", [[], None, "*", [None, " "]])
def test_explicit_empty_or_invalid_grants_never_inherit(role, grants):
    for user in ({"role": role, "authorized_collection_ids": grants},
                 SimpleNamespace(role=role, authorized_collection_ids=grants)):
        allowed = allowed_collection_ids_for_user(user)
        assert allowed == []
        assert not can_access_collection(allowed=allowed, collection_id="rag_phase0")


@pytest.mark.parametrize("role,expected", [("KNOWLEDGE_MANAGER", ["*"]), ("VETERINARIAN", ["rag_phase0"])])
def test_only_omitted_legacy_grants_receive_defaults(role, expected):
    assert allowed_collection_ids_for_user({"role": role}) == expected
    assert allowed_collection_ids_for_user(SimpleNamespace(role=role)) == expected
    assert allowed_collection_ids_for_user({"role": role, "authorization_state": "AUTHORITATIVE"}) == []
    assert allowed_collection_ids_for_user({"role": role, "authorization_state": "MIGRATED"}) == []


@pytest.mark.parametrize("grants,expected", [(["*"], ["*"]), (["cvg_master_rag", "allowed"], ["rag_phase0", "allowed"])])
def test_explicit_valid_grants_preserve_scope(grants, expected):
    assert allowed_collection_ids_for_user({"role": "VETERINARIAN", "authorized_collection_ids": grants}) == expected


@pytest.mark.parametrize("previous,current,expected", [
    ([], ["*"], []), (["*"], [], []), (["*"], ["limited"], ["limited"]),
    (["limited"], ["*"], ["limited"]), (["*"], ["*"], ["*"]),
    (["a", "b"], ["b", "c"], ["b"]), (["chat.query"], [], []),
    ([], ["chat.query"], []),
])
def test_intersection_preserves_both_ceilings_with_wildcards(previous, current, expected):
    assert intersect_grants(previous, current) == expected
