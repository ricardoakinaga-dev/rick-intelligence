#!/usr/bin/env python3
"""Deterministic local Phase 0.5 RAG plumbing and provenance probe.

This deliberately replaces only the embedding/answer provider seams with
deterministic test doubles. It exercises the real CVG parser, chunker,
filesystem persistence, Qdrant named-vector indexing, scoped retrieval, query
response construction, provenance, and stable re-ingestion identity.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CVG_SRC = ROOT / "cvg-master-rag-v2" / "src"
if str(CVG_SRC) not in sys.path:
    sys.path.insert(0, str(CVG_SRC))

RUNTIME_ROOT = ROOT / ".runtime" / "phase05-e2e"
DOCUMENTS_ROOT = RUNTIME_ROOT / "documents"
SOURCE_ROOT = RUNTIME_ROOT / "source"
WORKSPACE_ID = "phase05-e2e"
FILENAME = "phase05-parvovirose.txt"
COLLECTION_ID = "rag_phase0"
SOURCE_TEXT = (
    "Parvovirose canina requer suporte clínico. "
    "A fluidoterapia e o monitoramento são medidas de suporte descritas neste documento."
)


def _configure_runtime():
    os.environ.setdefault("QDRANT_HOST", "127.0.0.1")
    os.environ.setdefault("QDRANT_PORT", "6337")
    os.environ.setdefault("QDRANT_COLLECTION", COLLECTION_ID)

    from services import document_registry, ingestion_service, vector_service

    DOCUMENTS_ROOT.mkdir(parents=True, exist_ok=True)
    SOURCE_ROOT.mkdir(parents=True, exist_ok=True)
    ingestion_service.DOCUMENTS_DIR = DOCUMENTS_ROOT
    document_registry.DOCUMENTS_DIR = DOCUMENTS_ROOT
    vector_service.DOCUMENTS_DIR = DOCUMENTS_ROOT
    vector_service._document_metadata_cache.clear()
    return document_registry, ingestion_service, vector_service


def _embedding(texts: list[str]) -> list[list[float]]:
    vector = [0.0] * 1536
    vector[0] = 1.0
    return [list(vector) for _ in texts]


def _count_points(vector_service, document_id: str) -> int:
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    client = vector_service.get_client()
    points, _ = client.scroll(
        collection_name=COLLECTION_ID,
        scroll_filter=Filter(
            must=[
                FieldCondition(key="workspace_id", match=MatchValue(value=WORKSPACE_ID)),
                FieldCondition(key="document_id", match=MatchValue(value=document_id)),
            ]
        ),
        limit=100,
        with_payload=True,
        with_vectors=False,
    )
    return len(points)


def _search(vector_service, *, collection_id: str = COLLECTION_ID):
    from models.schemas import RetrievalContext, SearchRequest

    context = RetrievalContext(
        user_id="phase05-veterinarian",
        workspace_id=WORKSPACE_ID,
        allowed_collection_ids=[COLLECTION_ID],
        permissions=["chat.query", "sources.read"],
    )
    request = SearchRequest(
        query="Qual suporte clínico é descrito para parvovirose canina?",
        workspace_id=WORKSPACE_ID,
        collection_id=collection_id,
        top_k=3,
        threshold=0.0,
        reranking=False,
        query_expansion_mode="off",
    )
    return vector_service.search_hybrid(request, retrieval_context=context)


def _answer_from_retrieved_result(vector_service, search_response):
    from models.schemas import QueryRequest
    from services import search_service

    def deterministic_answer(*, query, chunks, system_prompt=None):
        del query, system_prompt
        first = chunks[0]
        return (
            "A parvovirose canina requer suporte clínico, incluindo fluidoterapia "
            "e monitoramento.",
            [first["chunk_id"]],
            0,
        )

    original_execute = search_service._execute_search_with_context
    original_generate = search_service.generate_answer
    search_service._execute_search_with_context = lambda *args, **kwargs: search_response
    search_service.generate_answer = deterministic_answer
    try:
        context = search_service.RetrievalContext(
            user_id="phase05-veterinarian",
            workspace_id=WORKSPACE_ID,
            allowed_collection_ids=[COLLECTION_ID],
            permissions=["chat.query", "sources.read"],
        )
        return search_service.search_and_answer(
            QueryRequest(
                query="Qual suporte clínico é descrito para parvovirose canina?",
                workspace_id=WORKSPACE_ID,
                collection_id=COLLECTION_ID,
                top_k=3,
                threshold=0.0,
                reranking=False,
                query_expansion_mode="off",
            ),
            retrieval_context=context,
        )
    finally:
        search_service._execute_search_with_context = original_execute
        search_service.generate_answer = original_generate


def run_full() -> dict:
    _, ingestion_service, vector_service = _configure_runtime()
    vector_service.ensure_collection(collection_name=COLLECTION_ID)
    source_path = SOURCE_ROOT / FILENAME
    source_path.write_text(SOURCE_TEXT, encoding="utf-8")
    ingestion_service.get_embeddings_batch = _embedding

    first = ingestion_service.ingest_document(
        source_path,
        workspace_id=WORKSPACE_ID,
        original_filename=FILENAME,
        chunking_strategy="recursive",
        qdrant_collection=COLLECTION_ID,
    )
    second = ingestion_service.ingest_document(
        source_path,
        workspace_id=WORKSPACE_ID,
        original_filename=FILENAME,
        chunking_strategy="recursive",
        qdrant_collection=COLLECTION_ID,
    )
    vector_service._embed_query = lambda query: _embedding([query])[0]
    search_response = _search(vector_service)
    answer_response = _answer_from_retrieved_result(vector_service, search_response)

    denied = _search(vector_service, collection_id="collection-not-granted")
    try:
        from models.schemas import RetrievalContext, SearchRequest

        vector_service.search_hybrid(
            SearchRequest(query="escopo", workspace_id="other-workspace", top_k=1),
            retrieval_context=RetrievalContext(
                user_id="phase05-veterinarian",
                workspace_id=WORKSPACE_ID,
                allowed_collection_ids=[COLLECTION_ID],
                permissions=["chat.query"],
            ),
        )
    except PermissionError:
        workspace_mismatch_rejected = True
    else:
        workspace_mismatch_rejected = False

    malformed_path = SOURCE_ROOT / "malformed.exe"
    malformed_path.write_bytes(b"not a supported document")
    try:
        ingestion_service.ingest_document(
            malformed_path,
            workspace_id=WORKSPACE_ID,
            original_filename="malformed.exe",
            qdrant_collection=COLLECTION_ID,
        )
    except Exception as exc:  # expected parser boundary rejection
        malformed_rejected = exc.__class__.__name__
    else:
        malformed_rejected = None

    document_id = first.document_id
    points = _count_points(vector_service, document_id)
    result = {
        "status": "PASS",
        "runtime": {
            "workspace_id": WORKSPACE_ID,
            "collection_id": COLLECTION_ID,
            "embedding_mode": "deterministic_test_double",
            "answer_mode": "deterministic_test_generator",
        },
        "ingestion": {
            "first_status": first.status,
            "second_status": second.status,
            "document_id_first": first.document_id,
            "document_id_second": second.document_id,
            "stable_document_id": first.document_id == second.document_id,
            "chunk_count": first.chunk_count,
        },
        "retrieval": {
            "results": len(search_response.results),
            "low_confidence": search_response.low_confidence,
            "top_chunk_id": search_response.results[0].chunk_id if search_response.results else None,
            "top_collection_id": search_response.results[0].collection_id if search_response.results else None,
            "top_checksum_present": bool(search_response.results and search_response.results[0].checksum),
        },
        "answer": {
            "grounded": answer_response.grounded,
            "citation_coverage": answer_response.citation_coverage,
            "citations": len(answer_response.citations),
            "citation_collection_id": (
                answer_response.citations[0].collection_id
                if answer_response.citations
                else None
            ),
            "citation_checksum_present": bool(
                answer_response.citations and answer_response.citations[0].checksum
            ),
        },
        "idempotency": {
            "points_for_document": points,
            "no_duplicate_points": points == first.chunk_count,
        },
        "security": {
            "inaccessible_collection_returns_no_results": len(denied.results) == 0,
            "workspace_mismatch_rejected": workspace_mismatch_rejected,
            "malformed_extension_rejected_as": malformed_rejected,
        },
    }
    required = [
        result["ingestion"]["stable_document_id"],
        result["retrieval"]["results"] > 0,
        result["retrieval"]["top_collection_id"] == COLLECTION_ID,
        result["retrieval"]["top_checksum_present"],
        result["answer"]["grounded"],
        result["answer"]["citation_collection_id"] == COLLECTION_ID,
        result["answer"]["citation_checksum_present"],
        result["idempotency"]["no_duplicate_points"],
        result["security"]["inaccessible_collection_returns_no_results"],
        result["security"]["workspace_mismatch_rejected"],
        result["security"]["malformed_extension_rejected_as"] is not None,
    ]
    result["status"] = "PASS" if all(required) else "FAIL"
    return result


def run_restart() -> dict:
    _, _, vector_service = _configure_runtime()
    vector_service._embed_query = lambda query: _embedding([query])[0]
    response = _search(vector_service)
    return {
        "status": "PASS" if response.results else "FAIL",
        "results": len(response.results),
        "method": response.method,
        "workspace_id": WORKSPACE_ID,
        "collection_id": response.results[0].collection_id if response.results else None,
        "document_id": response.results[0].document_id if response.results else None,
        "checksum_present": bool(response.results and response.results[0].checksum),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("full", "restart"), default="full")
    args = parser.parse_args()
    result = run_full() if args.mode == "full" else run_restart()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
