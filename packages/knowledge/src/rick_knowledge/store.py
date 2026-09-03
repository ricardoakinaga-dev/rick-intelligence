"""Knowledge store protocol + hermetic in-memory implementation.

Lifecycle: draft → processing → published; unpublish keeps metadata+index refs
but excludes from retrieval; delete removes metadata, chunks and index refs
(no orphaned chunks). Upsert by stable IDs is idempotent.
"""

from __future__ import annotations

from typing import Protocol

from rick_knowledge.models import DOCUMENT_STATUSES, Chunk, Collection, Document


class KnowledgeStore(Protocol):
    def upsert_collection(self, collection: Collection) -> None: ...
    def get_collection(self, workspace_id: str, collection_id: str) -> Collection | None: ...
    def list_collections(self, workspace_id: str) -> list[Collection]: ...
    def upsert_document(self, document: Document) -> None: ...
    def get_document(self, document_id: str) -> Document | None: ...
    def set_document_status(self, document_id: str, status: str) -> None: ...
    def delete_document(self, document_id: str) -> int: ...
    def replace_document_chunks(self, document_id: str, chunks: list[Chunk]) -> None: ...
    def get_chunks(self, document_id: str) -> list[Chunk]: ...


class InMemoryKnowledgeStore:
    def __init__(self) -> None:
        self._collections: dict[tuple[str, str], Collection] = {}
        self._documents: dict[str, Document] = {}
        self._chunks: dict[str, list[Chunk]] = {}

    def upsert_collection(self, collection: Collection) -> None:
        self._collections[(collection.workspace_id, collection.collection_id)] = collection

    def get_collection(self, workspace_id: str, collection_id: str) -> Collection | None:
        return self._collections.get((workspace_id, collection_id))

    def list_collections(self, workspace_id: str) -> list[Collection]:
        return sorted(
            (c for (ws, _), c in self._collections.items() if ws == workspace_id),
            key=lambda c: c.collection_id,
        )

    def upsert_document(self, document: Document) -> None:
        if document.status not in DOCUMENT_STATUSES:
            raise ValueError(f"unknown document status: {document.status}")
        self._documents[document.document_id] = document

    def get_document(self, document_id: str) -> Document | None:
        return self._documents.get(document_id)

    def set_document_status(self, document_id: str, status: str) -> None:
        if status not in DOCUMENT_STATUSES:
            raise ValueError(f"unknown document status: {status}")
        document = self._documents.get(document_id)
        if document is None:
            raise KeyError(document_id)
        # No resurrection of deleted documents; no published<-deleted shortcuts.
        if document.status == "deleted" and status != "deleted":
            raise ValueError("deleted documents cannot transition; ingest a new version")
        document.status = status

    def delete_document(self, document_id: str) -> int:
        chunks = self._chunks.pop(document_id, [])
        document = self._documents.get(document_id)
        if document is not None:
            document.status = "deleted"
        return len(chunks)

    def replace_document_chunks(self, document_id: str, chunks: list[Chunk]) -> None:
        if document_id not in self._documents:
            raise KeyError(document_id)
        self._chunks[document_id] = list(chunks)

    def get_chunks(self, document_id: str) -> list[Chunk]:
        return list(self._chunks.get(document_id, []))
