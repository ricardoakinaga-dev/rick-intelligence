"""An explicitly empty ACL must stop before any data or provider access."""

import pytest

from rick_retrieval import RetrievalEngine


@pytest.mark.parametrize("grants", [[], None])
def test_empty_scope_does_not_touch_index_embedding_primary_or_fallback(grants):
    calls = []

    class Backend:
        name = "counted"

        def search(self, **kwargs):
            calls.append("search")
            return [], []

    class Engine(RetrievalEngine):
        def _chunks(self):
            calls.append("chunks")
            return []

    def embed(texts):
        calls.append("embed")
        return [[1.0]]

    engine = Engine(backend=Backend(), fallback=Backend(), embed=embed)
    result = engine.retrieve(query="private question", context={
        "tenant_id": "t", "workspace_id": "w", "allowed_collection_ids": grants,
    })
    assert calls == []
    assert result.evidence == []
    assert result.candidate_count == result.selected_count == 0
    assert result.fallback_used is False


@pytest.mark.parametrize("grants", [["allowed"], ["*"]])
def test_nonempty_scope_still_calls_embedding_and_search(grants):
    calls = []

    class Backend:
        name = "counted"

        def search(self, **kwargs):
            calls.append(("search", kwargs["allowed_collection_ids"]))
            return [], []

    def embed(texts):
        calls.append(("embed", texts))
        return [[1.0]]

    result = RetrievalEngine(backend=Backend(), embed=embed).retrieve(
        query="valid question", context={
            "tenant_id": "t", "workspace_id": "w", "allowed_collection_ids": grants,
        },
    )
    assert calls == [("embed", ["valid question"]), ("search", grants)]
    assert result.evidence == []
