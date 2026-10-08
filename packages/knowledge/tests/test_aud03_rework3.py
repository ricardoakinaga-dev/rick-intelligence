"""Public catalog values and delete-compensation lineage are detached/exact."""
from copy import deepcopy

import pytest

from rick_knowledge import Collection, Document, Chunk, InMemoryKnowledgeStore, SQLiteKnowledgeStore


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    value = InMemoryKnowledgeStore() if request.param == "memory" else SQLiteKnowledgeStore(tmp_path / "knowledge.sqlite")
    yield value
    if request.param == "sqlite":
        value.close()


@pytest.mark.parametrize("seam", ["input", "get", "list", "ensure"])
def test_catalog_values_cannot_mutate_stored_archive(store, seam):
    scope = dict(tenant_id="t", workspace_id="w", collection_id="c")
    original = Collection(**scope, title="Reviewed", status="archived", version=9,
                          metadata={"retention": {"mode": "hold"}})
    frozen = deepcopy(original)
    store.upsert_collection(original)
    obtained = {"input": lambda: original,
                "get": lambda: store.get_collection("w", "c", tenant_id="t"),
                "list": lambda: store.list_collections("w", tenant_id="t")[0],
                "ensure": lambda: store.ensure_collection(Collection(**scope))}[seam]()
    obtained.status = "active"
    obtained.title = "Unreviewed"
    obtained.metadata["retention"]["mode"] = "erase"
    assert store.get_collection("w", "c", tenant_id="t") == frozen


def seeded_document(store, scope, identity="d"):
    store.ensure_collection(Collection(**scope))
    doc = Document(**scope, document_id=identity, status="published", document_version="v1", content_checksum="checksum",
        object_ref="objects/v1", ingestion_version="ingest-v1", created_at="2026-01-01T00:00:00Z",
        published_at="2026-01-02T00:00:00Z", parser_version="p1", chunker_version="c1",
        embedding_model="model-v1", embedding_version="e1", metadata={"_ingestion_attempt": "A", "object_key": "objects/v1"})
    store.upsert_document(deepcopy(doc))
    chunk = Chunk(chunk_id=identity + "-chunk", document_id=identity, tenant_id=scope["tenant_id"], text="Evidence")
    store.replace_document_chunks(identity, [chunk])
    return deepcopy(store.get_document(identity)), [chunk]


@pytest.mark.parametrize("field", ["object_ref", "ingestion_version", "published_at", "created_at", "parser_version",
                                  "chunker_version", "embedding_model", "embedding_version", "metadata", "title"])
def test_restore_rejects_changed_retained_document(store, field):
    exercise_restore_lineage(store, dict(tenant_id="t", workspace_id="w", collection_id="c"), field)


def exercise_restore_lineage(store, scope, field):
    original, chunks = seeded_document(store, scope)
    store.delete_document(original.document_id)
    tombstone = deepcopy(store.get_document(original.document_id))
    altered = deepcopy(original)
    setattr(altered, field, {**original.metadata, "object_key": "objects/foreign"} if field == "metadata" else
            "2001-01-01T00:00:00Z" if field in {"created_at", "published_at"} else "foreign-lineage")
    with pytest.raises((ValueError, RuntimeError)):
        store.restore_deleted_document(altered, chunks)
    assert store.get_document(original.document_id) == tombstone and store.get_chunks(original.document_id) == []
    store.restore_deleted_document(deepcopy(original), chunks)
    assert store.get_document(original.document_id) == original and store.get_chunks(original.document_id) == chunks


def test_tombstone_lineage_cannot_change_via_idempotent_deleted_upsert(store):
    original, chunks = seeded_document(store, dict(tenant_id="t", workspace_id="w", collection_id="c"))
    store.delete_document(original.document_id)
    tombstone = deepcopy(store.get_document(original.document_id))
    forged = deepcopy(tombstone)
    forged.object_ref = "objects/foreign"
    with pytest.raises((ValueError, RuntimeError)):
        store.upsert_document(forged)
    store.upsert_document(deepcopy(tombstone))
    assert store.get_document(original.document_id) == tombstone
    store.restore_deleted_document(original, chunks)
    assert store.get_document(original.document_id) == original


def test_memory_tombstone_detaches_live_document_aliases():
    store = InMemoryKnowledgeStore()
    original, chunks = seeded_document(store, dict(tenant_id="t", workspace_id="w", collection_id="c"))
    published_alias = store.get_document(original.document_id)
    store.delete_document(original.document_id)
    tombstone = deepcopy(store.get_document(original.document_id))
    for alias in (published_alias, store.get_document(original.document_id)):
        alias.object_ref = "objects/foreign"
        alias.metadata["_ingestion_attempt"] = "foreign"
        alias.status = "published"
    assert store.get_document(original.document_id) == tombstone
    store.restore_deleted_document(original, chunks)
    assert store.get_document(original.document_id) == original


def test_legacy_restore_omissions_preserve_durable_lineage(store):
    original = Document(document_id="legacy", tenant_id="t", workspace_id="w", collection_id="c", status="published", document_version="v1")
    store.ensure_collection(Collection(tenant_id="t", workspace_id="w", collection_id="c"))
    store.upsert_document(deepcopy(original))
    durable = deepcopy(store.get_document("legacy"))
    store.delete_document("legacy")
    store.restore_deleted_document(original, [])
    assert store.get_document("legacy") == durable
