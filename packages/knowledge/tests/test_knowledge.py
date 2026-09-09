"""Knowledge unit tests: identity stability, lifecycle, payload contract."""

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from rick_knowledge import (
    LINEAGE_PAYLOAD_FIELDS,
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
    normalize_tenant_id,
    point_id_for_chunk,
    validate_payload,
)


def test_identity_stability():
    checksum = content_checksum("same content")
    a = document_id_for_content(workspace_id="w", collection_id="rag_phase0", checksum=checksum,
                                tenant_id="default")
    b = document_id_for_content(workspace_id="w", collection_id="cvg_master_rag", checksum=checksum,
                                tenant_id="default")
    assert a == b  # alias converges
    assert document_id_for_content(workspace_id="other", collection_id="rag_phase0", checksum=checksum,
                                   tenant_id="default") != a
    assert document_id_for_content(workspace_id="w", collection_id="rag_phase0",
                                   checksum=content_checksum("changed"), tenant_id="default") != a
    with pytest.raises(TypeError):
        document_id_for_content(workspace_id="w", collection_id="rag_phase0", checksum=checksum)
    assert document_version(checksum) == f"sha256:{checksum[:16]}"
    assert point_id_for_chunk("chunk_x") == point_id_for_chunk("chunk_x")
    assert chunk_id_for_document("doc1", 3) == "chunk_doc1_0003"


def test_collection_validation():
    assert normalize_collection_id(None) == "rag_phase0"
    with pytest.raises(ValueError, match="tenant_id is required"):
        normalize_tenant_id(None)
    with pytest.raises(ValueError):
        normalize_collection_id("has space!")


def test_domain_models_require_explicit_tenant_identity():
    with pytest.raises(TypeError):
        Document(document_id="d", workspace_id="w", collection_id="c")
    with pytest.raises(TypeError):
        Chunk(chunk_id="c", document_id="d")
    with pytest.raises(TypeError):
        Collection(workspace_id="w", collection_id="c")


def test_lifecycle_and_delete_cascade():
    store = InMemoryKnowledgeStore()
    store.upsert_collection(Collection(workspace_id="w", collection_id="c", tenant_id="default", title="C"))
    doc = Document(document_id="d1", workspace_id="w", collection_id="c", tenant_id="default", status="processing")
    store.upsert_document(doc)
    store.replace_document_chunks("d1", [Chunk(chunk_id="chunk_d1_0000", document_id="d1", tenant_id="default", text="hi")])
    store.set_document_status("d1", "published")
    assert store.get_document("d1").status == "published"
    store.set_document_status("d1", "unpublished")
    assert store.delete_document("d1") == 1
    assert store.get_chunks("d1") == []  # no orphaned chunks
    with pytest.raises(ValueError):
        store.set_document_status("d1", "published")  # deleted stays deleted
    with pytest.raises(ValueError):
        store.set_document_status("d1", "bogus")


def test_collections_are_isolated_when_tenants_reuse_workspace_and_name():
    store = InMemoryKnowledgeStore()
    store.upsert_collection(Collection(workspace_id="w", collection_id="c", tenant_id="tenant-a", title="A"))
    store.upsert_collection(Collection(workspace_id="w", collection_id="c", tenant_id="tenant-b", title="B"))

    assert store.get_collection("w", "c", tenant_id="tenant-a").title == "A"
    assert store.get_collection("w", "c", tenant_id="tenant-b").title == "B"
    with pytest.raises(TypeError):
        store.get_collection("w", "c")
    assert [item.title for item in store.list_collections("w", tenant_id="tenant-a")] == ["A"]
    assert [item.title for item in store.list_collections("w", tenant_id="tenant-b")] == ["B"]
    with pytest.raises(ValueError, match="tenant_id is required"):
        store.list_collections("w", tenant_id=None)
    with pytest.raises(TypeError):
        store.list_collections("w")


def test_document_listing_is_workspace_scoped_sorted_and_hides_deleted():
    store = InMemoryKnowledgeStore()
    store.upsert_document(Document(document_id="b", workspace_id="w", collection_id="c1", tenant_id="default"))
    store.upsert_document(Document(document_id="a", workspace_id="w", collection_id="c2", tenant_id="default"))
    store.upsert_document(Document(document_id="foreign", workspace_id="other", collection_id="c1", tenant_id="default"))
    store.upsert_document(Document(document_id="gone", workspace_id="w", collection_id="c1", tenant_id="default"))
    store.delete_document("gone")

    assert [document.document_id for document in store.list_documents("w", tenant_id="default")] == ["a", "b"]
    assert [document.document_id for document in store.list_documents("w", "c1", tenant_id="default")] == ["b"]
    assert store.list_documents("other", tenant_id="default")[0].document_id == "foreign"
    with pytest.raises(TypeError):
        store.list_documents("w")
    with pytest.raises(ValueError, match="tenant_id is required"):
        store.list_documents("w", tenant_id=None)


def test_payload_contract_and_drift():
    doc = Document(document_id="d", workspace_id="w", collection_id="c", tenant_id="default",
                   document_version="sha256:abc",
                   content_checksum="abc", display_filename="f.pdf", title="T",
                   embedding_model="text-embedding-3-small")
    chunk = Chunk(chunk_id="chunk_d_0000", document_id="d", tenant_id="default", text="hello", page_start=2)
    payload = build_point_payload(chunk=chunk, document=doc)
    assert validate_payload(payload) == []
    assert payload["page_start"] == 2 and payload["schema_version"] == "rag-contract-v1"
    assert payload["ingestion_version"] == "sha256:abc"
    assert payload["object_ref"] == "f.pdf"
    assert set(REQUIRED_PAYLOAD_FIELDS) >= set(payload) - {
        "document_filename", "qdrant_collection", "object_key",
    }
    broken = {k: v for k, v in payload.items() if k != "checksum"}
    assert validate_payload(broken) == ["checksum"]

    mismatched_chunk = replace(chunk, tenant_id="tenant-b")
    with pytest.raises(ValueError, match="tenant_id must match"):
        build_point_payload(chunk=mismatched_chunk, document=doc)

    tenantless_document = replace(doc, tenant_id=None)
    with pytest.raises(ValueError, match="tenant_id is required"):
        build_point_payload(chunk=chunk, document=tenantless_document)


def test_lineage_payload_serializes_the_exact_published_version_and_validates_drift():
    document = Document(
        document_id="doc-lineage",
        workspace_id="workspace-a",
        collection_id="collection-a",
        tenant_id="tenant-a",
        document_version="document-v7",
        ingestion_version="ingestion-v3",
        object_ref="s3://private/tenant-a/workspace-a/source-v3.pdf",
        created_at="2026-09-09T12:00:00Z",
        published_at="2026-09-09T12:03:00Z",
        parser_version="parser-v2",
        chunker_version="chunker-v4",
        embedding_model="text-embedding-3-small",
        embedding_version="embedding-v5",
    )
    chunk = Chunk(
        chunk_id="chunk-lineage-0000",
        document_id=document.document_id,
        tenant_id=document.tenant_id,
        text="version-bound evidence",
        checksum="sha256:chunk",
        index_version="qdrant-index-v2",
    )

    payload = build_point_payload(chunk=chunk, document=document)

    assert all(field in payload for field in LINEAGE_PAYLOAD_FIELDS)
    assert {field: payload[field] for field in LINEAGE_PAYLOAD_FIELDS} == {
        "document_id": "doc-lineage",
        "document_version": "document-v7",
        "ingestion_version": "ingestion-v3",
        "parser_version": "parser-v2",
        "chunker_version": "chunker-v4",
        "embedding_model": "text-embedding-3-small",
        "embedding_version": "embedding-v5",
        "index_version": "qdrant-index-v2",
        "checksum": "sha256:chunk",
        "object_ref": "s3://private/tenant-a/workspace-a/source-v3.pdf",
        "created_at": "2026-09-09T12:00:00Z",
        "published_at": "2026-09-09T12:03:00Z",
    }
    assert payload["tenant_id"] == "tenant-a"
    assert payload["workspace_id"] == "workspace-a"
    assert payload["collection_id"] == "collection-a"
    assert payload["object_key"] == payload["object_ref"]
    assert validate_payload(payload) == []

    without_object_ref = {key: value for key, value in payload.items() if key != "object_ref"}
    assert validate_payload(without_object_ref) == ["object_ref"]
    blank_ingestion = {**payload, "ingestion_version": ""}
    assert validate_payload(blank_ingestion) == ["ingestion_version"]
