"""Knowledge unit tests: identity stability, lifecycle, payload contract."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from rick_knowledge import (
    REQUIRED_PAYLOAD_FIELDS,
    Chunk,
    Collection,
    Document,
    InMemoryKnowledgeStore,
    build_point_payload,
    chunk_id_for_document,
    content_checksum,
    document_id_for_content,
    document_version,
    normalize_collection_id,
    point_id_for_chunk,
    validate_payload,
)


def test_identity_stability():
    checksum = content_checksum("same content")
    a = document_id_for_content(workspace_id="w", collection_id="rag_phase0", checksum=checksum)
    b = document_id_for_content(workspace_id="w", collection_id="cvg_master_rag", checksum=checksum)
    assert a == b  # alias converges
    assert document_id_for_content(workspace_id="other", collection_id="rag_phase0", checksum=checksum) != a
    assert document_id_for_content(workspace_id="w", collection_id="rag_phase0", checksum=content_checksum("changed")) != a
    assert document_version(checksum) == f"sha256:{checksum[:16]}"
    assert point_id_for_chunk("chunk_x") == point_id_for_chunk("chunk_x")
    assert chunk_id_for_document("doc1", 3) == "chunk_doc1_0003"


def test_collection_validation():
    assert normalize_collection_id(None) == "rag_phase0"
    with pytest.raises(ValueError):
        normalize_collection_id("has space!")


def test_lifecycle_and_delete_cascade():
    store = InMemoryKnowledgeStore()
    store.upsert_collection(Collection(workspace_id="w", collection_id="c", title="C"))
    doc = Document(document_id="d1", workspace_id="w", collection_id="c", status="processing")
    store.upsert_document(doc)
    store.replace_document_chunks("d1", [Chunk(chunk_id="chunk_d1_0000", document_id="d1", text="hi")])
    store.set_document_status("d1", "published")
    assert store.get_document("d1").status == "published"
    store.set_document_status("d1", "unpublished")
    assert store.delete_document("d1") == 1
    assert store.get_chunks("d1") == []  # no orphaned chunks
    with pytest.raises(ValueError):
        store.set_document_status("d1", "published")  # deleted stays deleted
    with pytest.raises(ValueError):
        store.set_document_status("d1", "bogus")


def test_payload_contract_and_drift():
    doc = Document(document_id="d", workspace_id="w", collection_id="c", document_version="sha256:abc",
                   content_checksum="abc", display_filename="f.pdf", title="T",
                   embedding_model="text-embedding-3-small")
    chunk = Chunk(chunk_id="chunk_d_0000", document_id="d", text="hello", page_start=2)
    payload = build_point_payload(chunk=chunk, document=doc)
    assert validate_payload(payload) == []
    assert payload["page_start"] == 2 and payload["schema_version"] == "rag-contract-v1"
    assert set(REQUIRED_PAYLOAD_FIELDS) >= set(payload) - {"document_filename", "qdrant_collection"}
    broken = {k: v for k, v in payload.items() if k != "checksum"}
    assert validate_payload(broken) == ["checksum"]
