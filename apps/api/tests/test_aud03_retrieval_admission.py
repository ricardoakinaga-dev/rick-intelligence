"""The public service admits scope before rehydrating any private index."""

import pytest

from rick_knowledge import Collection, InMemoryKnowledgeStore
from services.retrieval_service import RetrievalApplicationService


@pytest.mark.parametrize("grants", [[], None])
def test_empty_acl_does_not_rehydrate_or_call_adapters(grants):
    calls = []

    class Vectors:
        def all_points(self, **kwargs):
            calls.append("read")
            return []

    class Embeddings:
        def embed(self, texts):
            calls.append("embed")
            return [[1.0]]

    class Backend:
        name = "admission-probe"

        def search(self, **kwargs):
            calls.append("search")
            return [], []

    knowledge = InMemoryKnowledgeStore()
    knowledge.upsert_collection(Collection(
        tenant_id="admission-tenant", workspace_id="admission-workspace",
        collection_id="allowed", status="active",
    ))
    service = RetrievalApplicationService(knowledge=knowledge, vectors=Vectors(),
                                          embeddings=Embeddings(), backend=Backend(),
                                          fallback=Backend())
    context = {"tenant_id": "admission-tenant", "workspace_id": "admission-workspace",
               "allowed_collection_ids": grants}
    denied = service.retrieve(query="private query", context=context)

    assert calls == []
    assert denied.evidence == []
    assert denied.selected_count == denied.candidate_count == 0
    assert denied.metadata["authorization"] == "empty_scope"
    assert service._indexed is False

    authorized = service.retrieve(query="authorized query", context={
        **context, "allowed_collection_ids": ["allowed"],
    })
    assert calls == ["read", "embed", "search", "search"]
    assert authorized.metadata.get("authorization") != "lifecycle_denied"
    calls.clear()
    service.retrieve(query="private query again", context=context)
    assert calls == []
