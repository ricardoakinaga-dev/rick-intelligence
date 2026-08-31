from models.schemas import Chunk, RetrievalContext, SearchRequest
from services.rag_contract import (
    CANONICAL_COLLECTION_ID,
    DENSE_VECTOR_NAME,
    RAG_SCHEMA_VERSION,
    canonical_payload_required_fields,
    content_checksum,
    document_id_for_content,
    point_id_for_chunk,
    normalize_collection_id,
    validate_canonical_payload,
)
from services.vector_service import (
    _build_citation_payload,
    _build_qdrant_filter,
    _filter_trusted_qdrant_points,
    _retrieval_collection_scope,
)


def test_contract_aliases_and_deterministic_identity_are_stable():
    assert normalize_collection_id("cvg_master_rag") == CANONICAL_COLLECTION_ID
    assert normalize_collection_id("rickvet_documents") == CANONICAL_COLLECTION_ID
    checksum = content_checksum("conteúdo clínico")
    first = document_id_for_content(
        workspace_id="default",
        collection_id="cvg_master_rag",
        checksum=checksum,
    )
    assert first == document_id_for_content(
        workspace_id="default",
        collection_id=CANONICAL_COLLECTION_ID,
        checksum=checksum,
    )
    assert point_id_for_chunk("chunk-document-0000") == point_id_for_chunk("chunk-document-0000")
    assert first != document_id_for_content(
        workspace_id="other",
        collection_id=CANONICAL_COLLECTION_ID,
        checksum=checksum,
    )


def test_canonical_payload_requires_every_cross_service_field():
    payload = {field: None for field in canonical_payload_required_fields()}
    assert validate_canonical_payload(payload) == []
    payload.pop("checksum")
    assert validate_canonical_payload(payload) == ["checksum"]


def test_retrieval_scope_preserves_wildcard_and_rejects_requested_collection():
    wildcard = RetrievalContext(workspace_id="default", allowed_collection_ids=["*"])
    assert _retrieval_collection_scope(
        SearchRequest(query="x", workspace_id="default", collection_id="cvg_master_rag"),
        wildcard,
    ) == [CANONICAL_COLLECTION_ID]

    restricted = RetrievalContext(workspace_id="default", allowed_collection_ids=["collection_a"])
    assert _retrieval_collection_scope(
        SearchRequest(query="x", workspace_id="default", collection_id="collection_b"),
        restricted,
    ) == ["__forbidden_collection__"]


def test_qdrant_filter_binds_workspace_and_logical_collection():
    query_filter = _build_qdrant_filter(
        "workspace-a",
        allowed_collection_ids=["cvg_master_rag"],
    )
    dumped = query_filter.model_dump(exclude_none=True)
    assert dumped["must"][0]["key"] == "workspace_id"
    assert dumped["must"][1]["key"] == "collection_id"
    assert dumped["must"][1]["match"]["any"] == [CANONICAL_COLLECTION_ID]


def test_qdrant_results_are_revalidated_after_server_side_filtering():
    from types import SimpleNamespace

    def point(workspace_id: str, collection_id: str):
        return SimpleNamespace(
            payload={
                "workspace_id": workspace_id,
                "collection_id": collection_id,
                "chunk_id": f"{workspace_id}-{collection_id}",
                "document_id": "doc-1",
                "text": "conteúdo",
            }
        )

    trusted = _filter_trusted_qdrant_points(
        [point("workspace-a", "rag_phase0"), point("workspace-b", "rag_phase0"), point("workspace-a", "other")],
        workspace_id="workspace-a",
        allowed_collection_ids=[CANONICAL_COLLECTION_ID],
    )
    assert len(trusted) == 1
    assert trusted[0].payload["workspace_id"] == "workspace-a"


def test_citation_payload_is_canonical_for_a_chunk():
    chunk = Chunk(
        chunk_id="chunk-citation-0000",
        document_id="doc-citation",
        workspace_id="default",
        chunk_index=0,
        text="parvovirose e tratamento",
        start_char=0,
        end_char=27,
        created_at="2026-08-30T00:00:00Z",
        embedding_model="text-embedding-3-small",
        metadata={"collection_id": "cvg_master_rag"},
    )
    payload = _build_citation_payload(chunk, "default")
    assert payload["schema_version"] == RAG_SCHEMA_VERSION
    assert payload["collection_id"] == CANONICAL_COLLECTION_ID
    assert payload["embedding_model"] == "text-embedding-3-small"
    assert payload["text"] == chunk.text
    assert DENSE_VECTOR_NAME == "dense"
