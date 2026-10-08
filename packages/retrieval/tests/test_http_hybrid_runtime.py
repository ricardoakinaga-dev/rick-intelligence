"""Opt-in real Qdrant tests; no server, provider, or database is auto-discovered.

Run only against a disposable loopback Qdrant via RICK_Q24_QDRANT_URL. All
collections/aliases are unique and removed by this fixture. Embeddings and
knowledge/object stores are deterministic test doubles, explicitly not an
end-to-end production/provider or semantic-quality acceptance campaign.
"""

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
import uuid

import httpx
import pytest

from rick_retrieval import (
    BM25FReranker, HttpResponse, QdrantBackend, QdrantHttpVectorStore,
    QdrantLimits, QdrantSchemaMismatchError, QdrantValidationError,
    RetrievalEngine, RetrievalOptions,
)

SCOPE = {"tenant_id": "tenant-a", "workspace_id": "workspace-a", "allowed_collection_ids": ["allowed"]}


class RecordingTransport:
    def __init__(self):
        self.client = httpx.Client(trust_env=False)
        self.calls = []
        self.fail_leg = None
        self.fail_upsert = None
        self.fail_delete_document_id = None
        self.upserts = 0

    def request(self, method, url, *, headers, content, timeout):
        body = json.loads(content) if content else None
        self.calls.append((method, urlsplit(url).path, body, len(content)))
        if method == "PUT" and body and "points" in body:
            self.upserts += 1
        # Forward first, then fault the acknowledgement. This exercises an
        # ambiguous partial write rather than a mock that never stored data.
        response = self.client.request(method, url, headers=headers, content=content, timeout=timeout)
        if body and body.get("using") == self.fail_leg and self.fail_leg is not None:
            return HttpResponse(503, b'{"status":"injected_unavailable"}')
        if method == "PUT" and body and "points" in body and self.upserts == self.fail_upsert:
            return HttpResponse(503, b'{"status":"injected_lost_ack"}')
        if method == "POST" and urlsplit(url).path.endswith("/points/delete") and body:
            deleted_document_ids = {
                condition.get("match", {}).get("value")
                for condition in body.get("filter", {}).get("must", [])
                if condition.get("key") == "document_id"
                and isinstance(condition.get("match"), dict)
            }
            if self.fail_delete_document_id in deleted_document_ids:
                self.fail_delete_document_id = None
                return HttpResponse(503, b'{"status":"injected_lost_delete_ack"}')
        return HttpResponse(response.status_code, response.content, dict(response.headers))

    def close(self):
        self.client.close()


@pytest.fixture
def lab():
    endpoint = os.environ.get("RICK_Q24_QDRANT_URL")
    if not endpoint:
        pytest.skip("explicit disposable Qdrant endpoint is required")
    parsed = urlsplit(endpoint)
    assert parsed.scheme == "http" and parsed.hostname == "127.0.0.1" and parsed.port
    assert os.environ.get("RICK_Q24_QDRANT_DISPOSABLE") == "1"
    made, stores = [], []

    def make(*, dimensions=2, hybrid=True, collection=None, create=True, **kwargs):
        name = collection or "q24_" + uuid.uuid4().hex[:16]
        transport = RecordingTransport()
        store = QdrantHttpVectorStore(endpoint, name, transport=transport, max_attempts=1, **kwargs)
        stores.append(store)
        if create:
            made.append(name)
            assert store.create_collection(vector_dimensions=dimensions, hybrid=hybrid)
        return store, transport

    yield endpoint, make
    with httpx.Client(base_url=endpoint, trust_env=False) as client:
        aliases = client.get("/aliases").json()["result"]["aliases"]
        actions = [{"delete_alias": {"alias_name": entry["alias_name"]}}
                   for entry in aliases if entry["collection_name"] in made]
        if actions:
            assert client.post("/collections/aliases", json={"actions": actions}).is_success
        for name in made:
            assert client.delete("/collections/" + name).is_success
    for store in stores:
        store.close()


def point(key, text, vector=(1.0, 0.0), **scope):
    return {
        "point_id": str(uuid.uuid5(uuid.NAMESPACE_URL, key)), "vector": list(vector),
        "payload": {"chunk_id": key, "document_id": "doc-" + key,
                    "tenant_id": "tenant-a", "workspace_id": "workspace-a", "collection_id": "allowed",
                    "text": text, "source": key + ".txt", **scope},
    }


def report(case, **values):
    record = {"case": case, **values}
    print(json.dumps(record, sort_keys=True))
    folder = os.environ.get("RICK_Q24_EVIDENCE_DIR")
    if folder:
        Path(folder, case + ".json").write_text(json.dumps(record, indent=2, sort_keys=True))


class Embeddings:
    model = "synthetic-dense-v1"
    dimensions = 1536

    def __init__(self):
        self.calls = []

    def embed(self, texts):
        self.calls.append(len(texts))
        return [[(index + 1) / 1537 for index in range(self.dimensions)] for _ in texts]


class Lines:
    def chunk(self, *, text, pages, document_id):
        from rick_ingestion.chunking import ChunkPlan

        return [ChunkPlan(text=line, chunk_index=index, page_start=1,
                          checksum=hashlib.sha256(line.encode()).hexdigest())
                for index, line in enumerate(text.splitlines()) if line.strip()]


def test_real_external_worker_batches_sparse_points_and_restart(lab, tmp_path):
    from external_ingestion import ExternalIngestionHandler
    from rick_ingestion import IngestionService
    from rick_knowledge import InMemoryKnowledgeStore

    endpoint, make = lab
    store, wire = make(dimensions=1536)
    for field in ("tenant_id", "workspace_id", "collection_id"):
        store.create_payload_index(field_name=field)
    knowledge, embeddings = InMemoryKnowledgeStore(), Embeddings()
    service = IngestionService(knowledge=knowledge, vectors=store, embeddings=embeddings, chunker=Lines())
    content = "\n".join(f"needle{i:04d} synthetic source line" for i in range(257)).encode()

    class ObjectStore:
        def get(self, scope, key, *, max_bytes):
            assert scope.tenant_id == "tenant-a" and scope.workspace_id == "workspace-a"
            return content

    record = SimpleNamespace(job_id="runtime-batches", tenant_id="tenant-a", workspace_id="workspace-a",
                             collection_id="allowed", payload={
        "object_key": "source.txt", "display_filename": "source.txt", "operation": "ingest",
        "checksum": "sha256:" + hashlib.sha256(content).hexdigest(),
    })
    handler = ExternalIngestionHandler(service, ObjectStore(), temp_root=tmp_path)
    job = handler(record)
    assert job.status == "published" and embeddings.calls == [256, 1]
    assert knowledge.get_document(job.document_id).status == "published"
    writes = [(body, size) for method, _, body, size in wire.calls if method == "PUT" and "points" in body]
    assert len(writes) > 1
    assert sum(len(body["points"]) for body, _ in writes) == 257
    assert all(len(body["points"]) <= 256 and size <= 4 * 1024 * 1024 for body, size in writes)
    assert all(set(item["vector"]) == {"dense", "sparse"} for body, _ in writes for item in body["points"])
    assert list(tmp_path.iterdir()) == []
    assert store.count_for_document(job.document_id, "allowed", tenant_id="tenant-a", workspace_id="workspace-a") == 257
    restarted, _ = make(collection=store.collection, create=False)
    result = restarted.search_hybrid(query="needle0256", query_vector=embeddings.embed(["query"])[0], **SCOPE)
    assert result.mode == "hybrid" and result.sparse[0].payload["text"].startswith("needle0256")
    with pytest.raises(QdrantSchemaMismatchError):
        restarted.prepare_index(vector_dimensions=768)
    sample = httpx.post(endpoint + "/collections/" + store.collection + "/points/scroll",
                        json={"limit": 1, "with_vector": True, "with_payload": True}).json()["result"]["points"][0]
    assert set(sample["vector"]) == {"dense", "sparse"}
    report("real-worker-batches", points=257, dimensions=1536, batch_sizes=[len(body["points"]) for body, _ in writes],
           request_bytes=[size for _, size in writes], restart_observation=result.metadata,
           real_services=["Qdrant HTTP"], doubles=["embeddings", "knowledge", "object storage", "line chunker"])


def test_real_exact_term_ablation_scope_and_partial_failure(lab):
    _, make = lab
    store, wire = make()
    decoys = [point(f"decoy{i:03d}", f"generic semantic concept {i}") for i in range(35)]
    exact = point("exact", "ZXQ731 exact reference", (0.0, 1.0))
    foreign = [
        point("foreign-tenant", "ZXQ731", tenant_id="tenant-b"),
        point("foreign-workspace", "ZXQ731", workspace_id="workspace-b"),
        point("foreign-collection", "ZXQ731", collection_id="secret"),
    ]
    store.upsert_points(decoys + [exact] + foreign)
    dense_store, _ = make(collection=store.collection, create=False, retrieval_mode="dense")
    def engine(selected):
        return RetrievalEngine(backend=QdrantBackend(selected), embed=lambda _: [[1.0, 0.0]],
                               reranker=BM25FReranker())
    opts = RetrievalOptions(top_k=1, candidate_multiplier=1, rerank=True)
    dense = engine(dense_store).retrieve(query="ZXQ731", context=SCOPE, options=opts)
    hybrid = engine(store).retrieve(query="ZXQ731", context=SCOPE, options=opts)
    assert dense.evidence[0]["chunk_id"].startswith("decoy")
    assert hybrid.evidence[0]["chunk_id"] == "exact"
    assert hybrid.evidence[0]["sparse_score"] > 0
    for key, value in [("tenant_id", "no-tenant"), ("workspace_id", "no-workspace"),
                       ("allowed_collection_ids", ["no-collection"])]:
        denied = store.search_hybrid(query="ZXQ731", query_vector=[1.0, 0.0], **(SCOPE | {key: value}))
        assert denied.dense == denied.sparse == []
    wildcard = store.search_hybrid(query="ZXQ731", query_vector=[1.0, 0.0],
                                  **(SCOPE | {"allowed_collection_ids": ["*"]}))
    assert {hit.payload["chunk_id"] for hit in wildcard.sparse} == {"exact", "foreign-collection"}
    partial = {}
    for failed in ("dense", "sparse"):
        wire.fail_leg = failed
        result = engine(store).retrieve(query="ZXQ731", context=SCOPE, options=opts)
        assert result.fallback_used and result.metadata["degraded"]
        assert result.backend != "qdrant-http-hybrid"
        partial[failed] = result.metadata
    wire.fail_leg = None
    full = engine(store).retrieve(query="ZXQ731", context=SCOPE, options=opts)
    assert not full.fallback_used
    report("real-exact-ablation", corpus_points=39, dense_top=dense.evidence[0]["chunk_id"],
           hybrid_top=hybrid.evidence[0]["chunk_id"], dense=dense.metadata, hybrid=hybrid.metadata,
           injected_failures=partial, limits="Synthetic ranking discrimination, not a semantic/provider quality score")


def test_real_partial_reindex_keeps_published_copy_cutover_and_rollback(lab, tmp_path):
    from rick_ingestion import IngestionService
    from rick_knowledge import InMemoryKnowledgeStore

    endpoint, make = lab
    old, _ = make(dimensions=1536, hybrid=False)
    new, wire = make(dimensions=1536, limits=QdrantLimits(max_points=2))
    knowledge = InMemoryKnowledgeStore()
    original_embeddings = Embeddings()
    source = tmp_path / "same-content.txt"
    source.write_text("\n".join(f"needle{i} immutable source" for i in range(5)))
    args = {"workspace_id": "workspace-a", "collection_id": "allowed", "tenant_id": "tenant-a"}
    original = IngestionService(knowledge=knowledge, vectors=old, embeddings=original_embeddings, chunker=Lines())
    first = original.ingest(source, **args)
    assert first.status == "published"
    alias = "q24_alias_" + uuid.uuid4().hex[:12]
    assert old.activate_index(alias_name=alias, vector_dimensions=1536, expected_points=5)
    current, _ = make(collection=alias, create=False)
    assert current.search_hybrid(query="needle0", query_vector=original_embeddings.embed(["q"])[0], **SCOPE).mode == "dense-legacy"

    replacement_embeddings = Embeddings()
    replacement_embeddings.model = "synthetic-dense-v2"
    replacement = IngestionService(knowledge=knowledge, vectors=new, embeddings=replacement_embeddings,
                                   embedding_version="emb-v2", chunker=Lines())
    wire.fail_upsert = 2
    failed = replacement.reindex(first.document_id, source, **args)
    assert failed.status == "failed" and wire.upserts == 2
    assert knowledge.get_document(first.document_id).status == "published"
    assert old.count_for_document(first.document_id, "allowed", tenant_id="tenant-a", workspace_id="workspace-a") == 5
    assert new.collection_info().points_count == 0  # Scoped compensation after the lost acknowledgement.
    with pytest.raises(QdrantValidationError):
        new.activate_index(alias_name=alias, vector_dimensions=1536, expected_points=5,
                           old_collection_name=old.collection)
    assert {item.alias_name: item.collection_name for item in old.list_aliases()}[alias] == old.collection

    wire.fail_upsert = None
    retried = replacement.reindex(first.document_id, source, **args)
    assert retried.status == "published" and retried.document_id == failed.document_id
    assert retried.document_id != first.document_id
    assert retried.metadata["index_activation_required"]
    assert knowledge.get_document(first.document_id).status == "published"
    assert knowledge.get_document(retried.document_id).embedding_model == "synthetic-dense-v2"
    replay = replacement.ingest(source, **args)
    assert replay.metadata["deduplicated"] and replay.document_id == retried.document_id
    assert new.activate_index(alias_name=alias, vector_dimensions=1536, expected_points=5,
                              old_collection_name=old.collection)
    assert new.activate_index(alias_name=alias, vector_dimensions=1536, expected_points=5,
                              old_collection_name=old.collection)  # Idempotent activation retry.
    after = current.search_hybrid(query="needle0", query_vector=replacement_embeddings.embed(["q"])[0], **SCOPE)
    assert after.mode == "hybrid" and after.sparse[0].payload["document_id"] == retried.document_id
    assert old.activate_index(alias_name=alias, vector_dimensions=1536, expected_points=5,
                              old_collection_name=new.collection)
    rollback = current.search_hybrid(query="needle0", query_vector=original_embeddings.embed(["q"])[0], **SCOPE)
    assert rollback.mode == "dense-legacy"
    assert all(hit.payload["document_id"] == first.document_id for hit in rollback.dense)
    schemas = {name: httpx.get(endpoint + "/collections/" + name).json()["result"]["config"]["params"]
               for name in (old.collection, new.collection)}
    report("real-transition", lost_ack_job=failed.status, replay_deduplicated=True,
           old_document=first.document_id, new_document=retried.document_id,
           cutover=after.metadata, rollback=rollback.metadata, schemas=schemas,
           retained_counts={"old": 5, "new": 5})


def test_real_same_index_lost_delete_ack_restores_http_snapshot(lab, tmp_path):
    from rick_ingestion import IngestionService
    from rick_knowledge import InMemoryKnowledgeStore

    _, make = lab
    store, wire = make(
        dimensions=1536,
        limits=QdrantLimits(max_points=16, max_request_bytes=32_000),
    )
    knowledge = InMemoryKnowledgeStore()
    original_embeddings = Embeddings()
    source = tmp_path / "same-index-source.txt"
    source.write_text("\n".join(f"snapshot-line-{index} retained source" for index in range(4)))
    args = {"workspace_id": "workspace-a", "collection_id": "allowed", "tenant_id": "tenant-a"}
    original = IngestionService(
        knowledge=knowledge, vectors=store, embeddings=original_embeddings, chunker=Lines(),
    )
    first = original.ingest(source, **args)
    assert first.status == "published"
    snapshot = store.snapshot_document(
        first.document_id, "allowed", tenant_id="tenant-a", workspace_id="workspace-a",
    )
    assert len(snapshot) == 4

    replacement_embeddings = Embeddings()
    replacement_embeddings.model = "synthetic-dense-v2"
    replacement = IngestionService(
        knowledge=knowledge, vectors=store, embeddings=replacement_embeddings,
        embedding_version="emb-v2", chunker=Lines(),
    )
    wire.fail_delete_document_id = first.document_id
    restore_start = len(wire.calls)
    failed = replacement.reindex(first.document_id, source, **args)

    assert failed.status == "failed"
    assert failed.document_id and failed.document_id != first.document_id
    assert wire.fail_delete_document_id is None
    old_status = knowledge.get_document(first.document_id).status
    new_status = knowledge.get_document(failed.document_id).status
    old_count = store.count_for_document(
        first.document_id, "allowed", tenant_id="tenant-a", workspace_id="workspace-a",
    )
    new_count = store.count_for_document(
        failed.document_id, "allowed", tenant_id="tenant-a", workspace_id="workspace-a",
    )
    restored = store.snapshot_document(
        first.document_id, "allowed", tenant_id="tenant-a", workspace_id="workspace-a",
    )
    restored_writes = [
        (body, size) for method, _, body, size in wire.calls[restore_start:]
        if method == "PUT" and "points" in body
        and body["points"][0]["payload"]["document_id"] == first.document_id
    ]
    report("real-same-index-delete-rollback", result=failed.status,
           delete_ack_lost_after_server_mutation=True, previous_status=old_status,
           replacement_status=new_status, previous_count=old_count, replacement_count=new_count,
           restored_points=len(restored), restoration_batch_bytes=[size for _, size in restored_writes],
           requests=[(method, path) for method, path, _, _ in wire.calls])
    assert old_status == "published", {"restored": len(restored), "count": old_count}
    assert new_status == "failed"
    assert old_count == len(snapshot)
    assert new_count == 0
    assert sum(len(body["points"]) for body, _ in restored_writes) == len(snapshot)
    assert all(size <= store.limits.max_request_bytes for _, size in restored_writes)
    assert sorted(snapshot, key=lambda item: item["point_id"]) == sorted(
        restored, key=lambda item: item["point_id"],
    )


def test_real_incomplete_sparse_representation_cannot_activate(lab):
    endpoint, make = lab
    store, _ = make()
    item = point("dense-hole", "needle")
    # Deliberately seed a known-bad artifact through the raw protocol. A green
    # collection and a matching point count alone must not pass promotion.
    response = httpx.put(endpoint + "/collections/" + store.collection + "/points?wait=true", json={"points": [{
        "id": item["point_id"], "vector": {"dense": item["vector"]}, "payload": item["payload"],
    }]})
    assert response.is_success
    assert store.collection_info().points_count == 1
    alias = "q24_incomplete_" + uuid.uuid4().hex[:12]
    with pytest.raises(QdrantValidationError):
        store.activate_index(alias_name=alias, vector_dimensions=2, expected_points=1)
    assert all(entry.alias_name != alias for entry in store.list_aliases())
    report("real-incomplete-schema", incomplete_points=1, activation="rejected", alias_created=False)
