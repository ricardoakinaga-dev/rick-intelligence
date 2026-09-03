"""Retrieval application service — root engine behind an explicit flag.

RICK_API_ROOT_RETRIEVAL=1 routes platform chat evidence through the canonical
retrieval engine (in-memory index over the knowledge store). Default 0 in 1.4:
the chat default path stays unchanged; the flagged path is dual-tested.
Rollback: unset the flag.
"""

from __future__ import annotations

import os

from rick_retrieval import (
    BM25FReranker,
    DeterministicHashEmbedding,
    InMemoryBackend,
    RetrievalEngine,
    RetrievalOptions,
)


def root_retrieval_enabled() -> bool:
    return (os.getenv("RICK_API_ROOT_RETRIEVAL") or "0").strip() == "1"


class RetrievalApplicationService:
    def __init__(self, *, knowledge, vectors=None, embeddings=None) -> None:
        self.knowledge = knowledge
        self.embeddings = embeddings or DeterministicHashEmbedding()
        self.engine = RetrievalEngine(backend=InMemoryBackend(), reranker=BM25FReranker(),
                                      embed=self.embeddings.embed)
        self._indexed = False

    def _ensure_index(self) -> None:
        if self._indexed:
            return
        chunks = []
        for point in (getattr(self, "_points", []) or []):
            payload = point["payload"]
            chunks.append({
                "chunk_id": payload["chunk_id"], "document_id": payload["document_id"],
                "workspace_id": payload["workspace_id"], "collection_id": payload["collection_id"],
                "text": payload["text"], "vector": point["vector"],
                "page_start": payload.get("page_start"), "checksum": payload.get("checksum", ""),
            })
        self.engine.attach_index(chunks)
        self._indexed = True

    def attach_points(self, points: list[dict]) -> None:
        self._points = list(points)
        self._indexed = False

    def retrieve(self, *, query: str, context: dict, top_k: int = 3) -> list[dict]:
        self._ensure_index()
        result = self.engine.retrieve(query=query, context=context,
                                      options=RetrievalOptions(top_k=top_k, rerank=True))
        return [
            {"document_id": e["document_id"], "chunk_id": e["chunk_id"], "title": e["source"],
             "collection_id": e["collection_id"]}
            for e in result.evidence
        ]
