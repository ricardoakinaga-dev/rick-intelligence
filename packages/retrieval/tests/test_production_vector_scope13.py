"""Hermetic regression for the additive legacy vector scope seam."""

import sys
from copy import deepcopy
from types import ModuleType, SimpleNamespace

import pytest

from rick_ingestion.pipeline import _scoped_call
from rick_retrieval.vectordb import InMemoryVectorStore, QdrantVectorStore


SCOPE = {"tenant_id": "tenant-a", "workspace_id": "workspace-a"}


def points():
    rows = []
    for key, overrides in (
        ("owned", {}),
        ("foreign-tenant", {"tenant_id": "tenant-b"}),
        ("foreign-workspace", {"workspace_id": "workspace-b"}),
        ("foreign-collection", {"collection_id": "collection-b"}),
        ("foreign-document", {"document_id": "document-b"}),
        ("unscoped", {"tenant_id": None, "workspace_id": None}),
    ):
        rows.append({"point_id": key, "vector": [1.0], "payload": {
            **SCOPE, "document_id": "document-a", "collection_id": "collection-a",
            **overrides,
        }})
    return rows


@pytest.mark.parametrize("operation", ["count_for_document", "delete_document"])
def test_existing_public_vector_call_preserves_foreign_sentinels(operation):
    store = InMemoryVectorStore()
    store.upsert_points(points())
    assert _scoped_call(getattr(store, operation), "document-a", "collection-a", **SCOPE) == 1
    expected = points()[1:] if operation == "delete_document" else points()
    assert store.all_points() == expected


INVALID_SCOPES = [
    {"tenant_id": "tenant-a"}, {"workspace_id": "workspace-a"},
    {"tenant_id": None, "workspace_id": None},
] + [
    {**SCOPE, field: value}
    for field in SCOPE
    for value in (None, "", "   ", True, False, 1, [], "bad\nvalue", "x" * 129)
]


@pytest.fixture
def legacy_qdrant(monkeypatch):
    # Finite stand-in for the optional SDK; never construct a network client.
    models = ModuleType("qdrant_client.models")
    models.FieldCondition = lambda **kw: SimpleNamespace(**kw)
    models.Filter = lambda **kw: SimpleNamespace(**kw)
    models.MatchValue = lambda **kw: SimpleNamespace(**kw)
    monkeypatch.setitem(sys.modules, "qdrant_client", ModuleType("qdrant_client"))
    monkeypatch.setitem(sys.modules, "qdrant_client.models", models)
    calls = []

    def invoke(operation, **kwargs):
        calls.append((operation, kwargs))
        return SimpleNamespace(count=7)

    store = object.__new__(QdrantVectorStore)
    store.collection = "physical-index"
    store._client = SimpleNamespace(
        delete=lambda **kw: invoke("delete", **kw),
        count=lambda **kw: invoke("count", **kw),
    )
    return store, calls


@pytest.mark.parametrize("operation", ["count_for_document", "delete_document"])
@pytest.mark.parametrize("scope", INVALID_SCOPES)
def test_invalid_scope_rejected_before_memory_or_client_effect(operation, scope, legacy_qdrant):
    memory = InMemoryVectorStore()
    memory.upsert_points(points())
    before = deepcopy(memory.all_points())
    qdrant, calls = legacy_qdrant
    for store in (memory, qdrant):
        with pytest.raises(ValueError):
            getattr(store, operation)("document-a", "collection-a", **scope)
    assert memory.all_points() == before
    assert calls == []


def test_bare_memory_retains_historical_aggregate_behavior():
    store = InMemoryVectorStore()
    store.upsert_points(points())
    assert store.count_for_document("document-a", "collection-a") == 4
    assert store.delete_document("document-a", "collection-a") == 4
    assert store.all_points() == points()[3:5]


@pytest.mark.parametrize("operation", ["count_for_document", "delete_document"])
@pytest.mark.parametrize("scoped", [False, True])
def test_legacy_qdrant_exact_filter_clauses(operation, scoped, legacy_qdrant):
    store, calls = legacy_qdrant
    result = getattr(store, operation)("document-a", "collection-a", **(SCOPE if scoped else {}))
    assert result == (7 if operation == "count_for_document" else 0)
    assert len(calls) == 1
    _, request = calls[0]
    selector = request["count_filter" if operation == "count_for_document" else "points_selector"]
    clauses = [(condition.key, condition.match.value) for condition in selector.must]
    assert clauses == [
        ("document_id", "document-a"), ("collection_id", "collection-a"),
    ] + (list(SCOPE.items()) if scoped else [])
    assert request["collection_name"] == "physical-index"
    if operation == "count_for_document":
        assert request["exact"] is True


@pytest.mark.parametrize("operation", ["count_for_document", "delete_document"])
def test_scope_is_exact_without_trimming_or_defaulting(operation):
    store = InMemoryVectorStore()
    store.upsert_points(points())
    assert getattr(store, operation)("document-a", "collection-a",
                                     tenant_id=" tenant-a ", workspace_id="workspace-a") == 0
    assert store.all_points() == points()
