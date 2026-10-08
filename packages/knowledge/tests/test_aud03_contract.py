import pytest

from rick_knowledge import Chunk, Document, InMemoryKnowledgeStore, SQLiteKnowledgeStore, content_checksum, document_id_for_content


def test_identity_encoding_is_unambiguous():
    checksum = content_checksum("same bytes")
    scopes = [("default", "tenant:t:w"), ("t", "w"), ("default", "x:c:y"), ("default", "x")]
    ids = [document_id_for_content(tenant_id=t, workspace_id=w, collection_id="c", checksum=checksum) for t, w in scopes]
    assert len(set(ids)) == len(ids)
    assert ids[0] == document_id_for_content(tenant_id="default", workspace_id="tenant:t:w", collection_id="c", checksum=checksum)


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_tombstone_rejects_upsert_and_chunk_replacement(tmp_path, kind):
    k = InMemoryKnowledgeStore() if kind == "memory" else SQLiteKnowledgeStore(tmp_path / "tombstone.sqlite")
    doc = Document(document_id="d", tenant_id="t", workspace_id="w", collection_id="c", status="published")
    k.upsert_document(doc)
    k.delete_document("d")
    with pytest.raises(ValueError):
        k.upsert_document(Document(document_id="d", tenant_id="t", workspace_id="w", collection_id="c", status="published"))
    with pytest.raises(ValueError):
        k.replace_document_chunks("d", [Chunk(chunk_id="ch", document_id="d", tenant_id="t")])
    assert k.get_document("d").status == "deleted"
    assert k.get_chunks("d") == []
    assert k.list_documents("w", tenant_id="t") == []
    if kind == "sqlite":
        k.close()


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_delete_compensation_is_explicit_and_checks_lineage(tmp_path, kind):
    from copy import deepcopy
    k = InMemoryKnowledgeStore() if kind == "memory" else SQLiteKnowledgeStore(tmp_path / "restore.sqlite")
    doc = Document(document_id="d", tenant_id="t", workspace_id="w", collection_id="c", content_checksum="checksum", document_version="v1", status="published", metadata={"_ingestion_attempt": "A"})
    chunk = Chunk(chunk_id="ch", document_id="d", tenant_id="t", text="evidence")
    k.upsert_document(deepcopy(doc))
    k.replace_document_chunks("d", [chunk])
    k.delete_document("d")
    invalid = deepcopy(doc)
    invalid.metadata["_ingestion_attempt"] = "B"
    with pytest.raises(ValueError):
        k.restore_deleted_document(invalid, [chunk])
    assert k.get_document("d").status == "deleted" and k.get_chunks("d") == []
    with pytest.raises(ValueError):
        k.restore_deleted_document(deepcopy(doc), [Chunk(chunk_id="foreign", document_id="d", tenant_id="foreign")])
    assert k.get_document("d").status == "deleted" and k.get_chunks("d") == []
    k.restore_deleted_document(deepcopy(doc), [chunk])
    assert k.get_document("d").status == "published" and k.get_chunks("d") == [chunk]
    if kind == "sqlite":
        k.close()


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_ensure_collection_cannot_overwrite_concurrent_review(tmp_path, kind):
    from rick_knowledge import Collection
    from threading import Barrier
    from concurrent.futures import ThreadPoolExecutor
    k = InMemoryKnowledgeStore() if kind == "memory" else SQLiteKnowledgeStore(tmp_path / "creation.sqlite")
    other = k if kind == "memory" else SQLiteKnowledgeStore(tmp_path / "creation.sqlite")
    barrier = Barrier(2)
    def create():
        barrier.wait(timeout=3)
        other.ensure_collection(Collection(tenant_id="t", workspace_id="w", collection_id="c", title="Default"))
    def review():
        barrier.wait(timeout=3)
        k.upsert_collection(Collection(tenant_id="t", workspace_id="w", collection_id="c", title="Reviewed", status="archived", version=9, metadata={"retention": "hold"}))
    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks = [pool.submit(create), pool.submit(review)]
        for task in tasks:
            task.result(timeout=5)
    catalog = k.get_collection("w", "c", tenant_id="t")
    assert catalog.title == "Reviewed" and catalog.version == 9 and catalog.status == "archived"
    assert catalog.metadata == {"retention": "hold"}
    if kind == "sqlite":
        other.close()
        k.close()
