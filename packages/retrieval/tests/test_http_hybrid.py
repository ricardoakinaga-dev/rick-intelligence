"""Canonical HTTP hybrid contracts; all transports in this file are mocks."""

from copy import deepcopy
import json
import math
import uuid

import httpx
import pytest

from rick_retrieval import (
    HTTP_HYBRID_INDEX_VERSION, InMemoryBackend, QdrantBackend,
    QdrantBoundsError, QdrantHttpVectorStore, QdrantHybridUnavailableError,
    QdrantLimits, QdrantSchemaMismatchError, QdrantStatusError,
    QdrantValidationError, RetrievalEngine, RetrievalOptions, sparse_vector,
    versioned_index_collection,
)

SCOPE = {"tenant_id": "tenant-a", "workspace_id": "workspace-a", "allowed_collection_ids": ["allowed"]}


def point(key="allowed", text="needle", **scope):
    return {
        "point_id": str(uuid.uuid5(uuid.NAMESPACE_URL, key)), "vector": [1.0, 0.0],
        "payload": {
            "tenant_id": "tenant-a", "workspace_id": "workspace-a", "collection_id": "allowed",
            "chunk_id": key, "document_id": "doc-" + key, "text": text,
            "source": "allowed.txt", **scope,
        },
    }


def hit(key="allowed", score=0.5, **scope):
    item = point(key, **scope)
    return {"id": item["point_id"], "payload": item["payload"], "score": score}


class Wire:
    """A narrow wire fixture, deliberately separate from real-Qdrant tests."""

    def __init__(self, *, hybrid=True, dimensions=2):
        self.params = {
            "vectors": {"dense": {"size": dimensions, "distance": "Cosine"}},
            "sparse_vectors": {"sparse": {}} if hybrid else None,
        }
        self.requests = []
        self.failures = {}
        self.hits = {"dense": [hit()], "sparse": [hit(score=1.0)]}

    def handle(self, request):
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, request.url.path, body, len(request.content)))
        if request.method == "GET":
            return httpx.Response(200, json={"result": {"status": "green", "config": {"params": self.params}}})
        if request.method == "PUT":
            return httpx.Response(200, json={"result": True})
        assert request.url.path.endswith("/points/query"), request.url.path
        modality = body["using"]
        failure = self.failures.get(modality)
        if failure == "timeout":
            raise httpx.ReadTimeout("private endpoint/credential detail")
        if isinstance(failure, int):
            return httpx.Response(failure, text="private response body")
        return httpx.Response(200, json={"result": {"points": self.hits[modality]}})

    def store(self, **kwargs):
        return QdrantHttpVectorStore(
            "http://qdrant.test", "documents", transport=httpx.MockTransport(self.handle),
            max_attempts=1, **kwargs,
        )


def test_schema_and_upsert_preserve_both_representations_on_the_wire():
    wire = Wire()
    with wire.store() as store:
        store.create_collection(vector_dimensions=2)
        store.prepare_index(vector_dimensions=2)
        batches = store.plan_upsert_batches([point(text="needle needle exato")])
        assert store.upsert_points(batches[0]) == 1
    assert wire.requests[0][2] == {
        "vectors": {"dense": {"size": 2, "distance": "Cosine"}},
        "sparse_vectors": {"sparse": {"index": {"on_disk": False}}},
    }
    stored = wire.requests[-1][2]["points"][0]
    assert stored["vector"]["dense"] == [1.0, 0.0]
    expected = sparse_vector("needle needle exato")
    assert stored["vector"]["sparse"] == {
        "indices": sorted(expected), "values": [expected[index] for index in sorted(expected)],
    }
    assert stored["payload"]["index_version"] == HTTP_HYBRID_INDEX_VERSION
    assert {key: stored["payload"][key] for key in ("tenant_id", "workspace_id", "collection_id")} == {
        "tenant_id": "tenant-a", "workspace_id": "workspace-a", "collection_id": "allowed",
    }


def test_sparse_snapshot_float32_rounding_is_restorable_but_changed_weight_is_rejected():
    wire = Wire()
    item = point(text="needle needle exato")
    canonical = sparse_vector(item["payload"]["text"])
    indices = sorted(canonical)
    # Qdrant's JSON response renders stored float32 weights with about seven
    # significant digits, e.g. log(2) as 0.6931472.
    rounded = [float(f"{canonical[index]:.8g}") for index in indices]
    item["sparse_vector"] = {"indices": indices, "values": rounded}

    with wire.store() as store:
        store.prepare_index(vector_dimensions=2)
        assert store.upsert_points([item]) == 1
        assert wire.requests[-1][2]["points"][0]["vector"]["sparse"]["values"] == rounded

        changed = deepcopy(item)
        changed["sparse_vector"]["values"][0] += 0.001
        requests_before = len(wire.requests)
        with pytest.raises(QdrantSchemaMismatchError):
            store.upsert_points([changed])
        assert len(wire.requests) == requests_before


@pytest.mark.parametrize("distance", ["Dot", "Euclid", "Manhattan"])
def test_collection_creation_rejects_distances_unsupported_by_retrieval(distance):
    wire = Wire()
    with wire.store() as store:
        with pytest.raises(QdrantValidationError):
            store.create_collection(vector_dimensions=2, distance=distance)
    assert wire.requests == []


def test_sparse_bytes_participate_in_batch_planning_without_dropping_sparse():
    wire = Wire()
    points = [point(str(index), " ".join(f"term{i:03d}" for i in range(30))) for index in range(3)]
    with wire.store(limits=QdrantLimits(max_request_bytes=1800)) as store:
        store.prepare_index(vector_dimensions=2)
        planned = store.plan_upsert_batches(points)
        assert [len(batch) for batch in planned] == [1, 1, 1]
        assert all("sparse_vector" in batch[0] for batch in planned)
        assert sum(store.upsert_points(batch) for batch in planned) == 3
    assert all(size <= 1800 for method, _, _, size in wire.requests if method == "PUT")


@pytest.mark.parametrize("mutation", ["dimensions", "nan", "indices", "weights", "version"])
def test_complete_plan_rejects_bad_later_point_before_any_write(mutation):
    wire = Wire()
    points = [point("first"), point("second")]
    if mutation == "dimensions":
        points[1]["vector"] = [1.0]
    elif mutation == "nan":
        points[1]["vector"] = [math.nan, 0.0]
    elif mutation == "indices":
        points[1]["sparse_vector"] = {"indices": [1, 1], "values": [1.0, 1.0]}
    elif mutation == "weights":
        points[1]["sparse_vector"] = {"indices": [1], "values": [math.inf]}
    else:
        points[1]["payload"]["index_version"] = "incompatible-v2"
    with wire.store(max_points=1) as store:
        store.prepare_index(vector_dimensions=2)
        with pytest.raises((QdrantValidationError, QdrantSchemaMismatchError)):
            store.plan_upsert_batches(points)
    assert [method for method, *_ in wire.requests] == ["GET"]


def test_both_queries_have_identical_scope_and_foreign_rows_never_reach_fusion(monkeypatch):
    import rick_retrieval.pipeline as pipeline

    wire = Wire()
    foreign = [
        hit("allowed", score=99, tenant_id="tenant-b"),
        hit("foreign-workspace", score=99, workspace_id="workspace-b"),
        hit("foreign-collection", score=99, collection_id="secret"),
    ]
    wire.hits = {
        "dense": [*foreign, hit("shared"), hit("dense-only")],
        "sparse": [*foreign, hit("shared"), hit("sparse-only")],
    }
    observed = []
    original_fusion = pipeline.rrf_fusion

    def fusion(dense, sparse):
        observed.append((dense, sparse))
        assert {item["chunk_id"] for item in dense + sparse} == {"shared", "dense-only", "sparse-only"}
        return original_fusion(dense, sparse)

    class Reranker:
        def rerank(self, query, candidates):
            assert len(candidates) == 3
            assert all(item["tenant_id"] == "tenant-a" for item in candidates)
            return candidates

    monkeypatch.setattr(pipeline, "rrf_fusion", fusion)
    with wire.store() as store:
        result = RetrievalEngine(backend=QdrantBackend(store), embed=lambda _: [[1.0, 0.0]],
                                 reranker=Reranker()).retrieve(
            query="needle", context=SCOPE, options=RetrievalOptions(rerank=True),
        )
    assert len(observed) == 1
    assert result.backend == "qdrant-http-hybrid" and not result.fallback_used
    assert result.metadata["dense_status"] == result.metadata["sparse_status"] == "ok"
    assert result.selected_count == 3
    queries = [body for method, _, body, _ in wire.requests if method == "POST"]
    assert [body["using"] for body in queries] == ["dense", "sparse"]
    expected_filter = {"must": [
        {"key": "tenant_id", "match": {"value": "tenant-a"}},
        {"key": "workspace_id", "match": {"value": "workspace-a"}},
        {"key": "collection_id", "match": {"any": ["allowed"]}},
    ]}
    assert all(body["filter"] == expected_filter for body in queries)
    assert queries[1]["query"]["indices"] == sorted(sparse_vector("needle"))


@pytest.mark.parametrize("rerank", [False, True])
def test_sparse_exact_match_wins_a_dense_rrf_tie(rerank):
    class CompetingLegs:
        name = "hybrid-test"

        def search(self, **_kwargs):
            return (
                [{
                    "chunk_id": "dense-decoy", "document_id": "doc-decoy",
                    "tenant_id": "tenant-a", "workspace_id": "workspace-a",
                    "collection_id": "allowed", "text": "stable reference filler",
                    # This makes BM25F prefer the dense-only candidate unless
                    # it retains the sparse leg's precedence inside the RRF tie.
                    "document_filename": " ".join(["stable", "reference"] * 100),
                    "score": 1.0,
                }],
                [{
                    "chunk_id": "sparse-exact", "document_id": "doc-exact",
                    "tenant_id": "tenant-a", "workspace_id": "workspace-a",
                    "collection_id": "allowed", "text": "ZXQ731 stable reference exact identifier",
                    "score": 0.48,
                }],
            )

    from rick_retrieval import BM25FReranker

    result = RetrievalEngine(
        backend=CompetingLegs(), reranker=BM25FReranker(),
        embed=lambda _: [[1.0, 0.0]],
    ).retrieve(
        query="ZXQ731 stable reference", context=SCOPE,
        options=RetrievalOptions(top_k=1, candidate_multiplier=1, rerank=rerank),
    )
    assert result.evidence[0]["chunk_id"] == "sparse-exact"


def test_sparse_leg_discards_zero_score_qdrant_hits():
    candidate = hit("nonmatch", score=0.0)
    assert QdrantBackend._http_candidates(
        [candidate], "workspace-a", {"allowed"}, "tenant-a", sparse=True,
    ) == []
    wire = Wire()
    wire.hits["sparse"] = [candidate]
    encoded = sparse_vector("needle")
    with wire.store() as store:
        assert store.query_sparse(
            {"indices": sorted(encoded), "values": [encoded[index] for index in sorted(encoded)]},
            tenant_id="tenant-a", workspace_id="workspace-a",
            allowed_collection_ids=["allowed"],
        ) == []


def test_engine_scope_check_precedes_fusion_even_for_a_non_qdrant_backend(monkeypatch):
    import rick_retrieval.pipeline as pipeline

    good = point()["payload"] | {"score": 0.5}
    foreign = good | {"tenant_id": "other", "text": "PRIVATE", "score": 999}

    class BrokenBackend:
        name = "untrusted-test"

        def search(self, **kwargs):
            return [foreign, good], [foreign]

    original = pipeline.rrf_fusion

    def fusion(dense, sparse):
        assert dense == [good] and sparse == []
        return original(dense, sparse)

    monkeypatch.setattr(pipeline, "rrf_fusion", fusion)
    result = RetrievalEngine(backend=BrokenBackend()).retrieve(query="needle", context=SCOPE)
    assert result.evidence[0]["text"] == "needle"


@pytest.mark.parametrize("leg", ["dense", "sparse"])
@pytest.mark.parametrize("failure", ["timeout", 503])
def test_one_leg_degrades_explicitly_and_next_request_recovers(leg, failure):
    wire = Wire()
    wire.failures[leg] = failure
    with wire.store() as store:
        engine = RetrievalEngine(backend=QdrantBackend(store), embed=lambda _: [[1.0, 0.0]])
        result = engine.retrieve(query="needle", context=SCOPE)
        expected = "sparse-degraded" if leg == "dense" else "dense-degraded"
        assert result.backend == "qdrant-http-" + expected
        assert result.fallback_used and result.metadata["degraded"]
        assert result.metadata[leg + "_status"] != "ok"
        assert result.selected_count == 1
        assert "private" not in repr(result)
        wire.failures.clear()
        recovered = engine.retrieve(query="needle", context=SCOPE)
        assert recovered.backend == "qdrant-http-hybrid"
        assert not recovered.fallback_used and not recovered.metadata["degraded"]
        assert result.metadata["degraded"]  # Later calls cannot mutate prior observations.


def test_total_failure_requires_an_explicit_backend_fallback():
    wire = Wire()
    wire.failures = {"dense": 503, "sparse": "timeout"}
    with wire.store(circuit_failure_threshold=10) as store:
        engine = RetrievalEngine(backend=QdrantBackend(store), embed=lambda _: [[1.0, 0.0]])
        with pytest.raises(QdrantHybridUnavailableError):
            engine.retrieve(query="needle", context=SCOPE)
        engine.fallback = InMemoryBackend()
        engine.attach_index([point()["payload"] | {"vector": [1.0, 0.0]}])
        result = engine.retrieve(query="needle", context=SCOPE)
        assert result.backend == "memory" and result.fallback_used
        assert result.metadata["fallback_reason"] == "primary_unavailable"


def test_nontransient_error_and_disallowed_partial_fail_closed():
    wire = Wire()
    wire.failures["sparse"] = 400
    with wire.store() as store:
        with pytest.raises(QdrantStatusError):
            store.search_hybrid(query="needle", query_vector=[1.0, 0.0], **SCOPE)
    wire.failures["sparse"] = 503
    with wire.store(allow_partial=False) as store:
        with pytest.raises(QdrantHybridUnavailableError):
            store.search_hybrid(query="needle", query_vector=[1.0, 0.0], **SCOPE)


@pytest.mark.parametrize("hybrid,mode,query,expected,degraded", [
    (False, "auto", "needle", "dense-legacy", True),
    (True, "dense", "needle", "dense", False),
    (True, "auto", "de e", "dense-no-terms", False),
])
def test_dense_compatibility_is_explicit(hybrid, mode, query, expected, degraded):
    wire = Wire(hybrid=hybrid)
    with wire.store(retrieval_mode=mode) as store:
        result = store.search_hybrid(query=query, query_vector=[1.0, 0.0], **SCOPE)
    assert result.mode == expected and result.degraded is degraded
    assert [body["using"] for method, _, body, _ in wire.requests if method == "POST"] == ["dense"]


def test_no_grants_make_no_http_calls_and_wildcard_never_widens_tenant():
    wire = Wire()
    wire.hits["dense"] = wire.hits["sparse"] = [
        hit("other-collection", collection_id="another"),
        hit("other-tenant", tenant_id="other"),
        hit("other-workspace", workspace_id="other"),
    ]
    with wire.store() as store:
        denied = store.search_hybrid(query="needle", query_vector=[1.0, 0.0],
                                     **(SCOPE | {"allowed_collection_ids": []}))
        assert denied.mode == "denied" and wire.requests == []
        result = store.search_hybrid(query="needle", query_vector=[1.0, 0.0],
                                     **(SCOPE | {"allowed_collection_ids": ["*"]}))
    assert [item.payload["chunk_id"] for item in result.dense] == ["other-collection"]
    assert [item.payload["chunk_id"] for item in result.sparse] == ["other-collection"]
    assert all(len(body["filter"]["must"]) == 2 for method, _, body, _ in wire.requests if method == "POST")


@pytest.mark.parametrize("invalid", ["size", "distance", "modifier", "malformed", "missing_sparse"])
def test_restart_and_schema_incompatibility_fail_before_any_write(invalid):
    wire = Wire()
    with wire.store() as first:
        first.prepare_index(vector_dimensions=2)
    if invalid == "size":
        wire.params["vectors"]["dense"]["size"] = 3
    elif invalid == "distance":
        wire.params["vectors"]["dense"]["distance"] = "Dot"
    elif invalid == "modifier":
        wire.params["sparse_vectors"]["sparse"] = {"modifier": "idf"}
    elif invalid == "malformed":
        wire.params["sparse_vectors"] = []
    else:
        wire.params["sparse_vectors"] = None
    with wire.store(retrieval_mode="hybrid") as restarted:
        with pytest.raises(QdrantSchemaMismatchError):
            restarted.prepare_index(vector_dimensions=2)
        with pytest.raises(QdrantSchemaMismatchError):
            restarted.search_hybrid(query="needle", query_vector=[1.0, 0.0], **SCOPE)
    assert all(method == "GET" for method, *_ in wire.requests)


def test_index_identity_changes_with_model_version_or_dimensions():
    args = {"embedding_model": "model-a", "embedding_version": "v1", "dimensions": 1536}
    original = versioned_index_collection("documents", **args)
    assert original == versioned_index_collection("documents", **args)
    assert len({original, *[
        versioned_index_collection("documents", **(args | update)) for update in [
            {"embedding_model": "model-b"}, {"embedding_version": "v2"}, {"dimensions": 768},
        ]
    ]}) == 4
