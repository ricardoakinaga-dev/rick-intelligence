"""Knowledge store protocol + hermetic in-memory implementation.

Lifecycle: draft → processing → published; unpublish keeps metadata+index refs
but excludes from retrieval; delete removes metadata, chunks and index refs
(no orphaned chunks). Upsert by stable IDs is idempotent.
"""

from __future__ import annotations

from typing import Iterable, Protocol

from rick_knowledge.models import DOCUMENT_STATUSES, Chunk, Collection, Document


class KnowledgeStore(Protocol):
    def upsert_collection(self, collection: Collection) -> None: ...
    def get_collection(
        self,
        workspace_id: str,
        collection_id: str,
        *,
        tenant_id: str,
    ) -> Collection | None: ...
    def list_collections(self, workspace_id: str, *, tenant_id: str) -> list[Collection]: ...
    def upsert_document(self, document: Document) -> None: ...
    def get_document(
        self,
        document_id: str,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> Document | None: ...
    def list_documents(
        self,
        workspace_id: str,
        collection_id: str | None = None,
        *,
        tenant_id: str,
        after_document_id: str | None = None,
        limit: int | None = None,
        statuses: Iterable[str] | None = None,
        allowed_collection_ids: Iterable[str] | None = None,
    ) -> list[Document]: ...
    def set_document_status(self, document_id: str, status: str) -> None: ...
    def delete_document(self, document_id: str) -> int: ...
    def replace_document_chunks(self, document_id: str, chunks: list[Chunk]) -> None: ...
    def get_chunks(self, document_id: str) -> list[Chunk]: ...


class InMemoryKnowledgeStore:
    def __init__(self) -> None:
        # Tenant is part of collection identity. A workspace and collection
        # name may legitimately be reused by independent tenants.
        self._collections: dict[tuple[str, str, str], Collection] = {}
        self._documents: dict[str, Document] = {}
        self._chunks: dict[str, list[Chunk]] = {}

    def upsert_collection(self, collection: Collection) -> None:
        if collection.status not in {"active", "archived"}:
            raise ValueError("unknown collection status")
        self._collections[(collection.tenant_id, collection.workspace_id, collection.collection_id)] = collection

    def get_collection(
        self,
        workspace_id: str,
        collection_id: str,
        *,
        tenant_id: str,
    ) -> Collection | None:
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("tenant_id is required")
        return self._collections.get((tenant_id.strip(), workspace_id, collection_id))

    def list_collections(self, workspace_id: str, *, tenant_id: str) -> list[Collection]:
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("tenant_id is required")
        tenant = tenant_id.strip()
        return sorted(
            (
                c for (_tenant, ws, _), c in self._collections.items()
                if ws == workspace_id and c.tenant_id == tenant
            ),
            key=lambda c: c.collection_id,
        )

    def upsert_document(self, document: Document) -> None:
        if document.status not in DOCUMENT_STATUSES:
            raise ValueError(f"unknown document status: {document.status}")
        self._documents[document.document_id] = document

    def get_document(
        self,
        document_id: str,
        *,
        tenant_id: str | None = None,
        workspace_id: str | None = None,
    ) -> Document | None:
        document = self._documents.get(document_id)
        if document is None:
            return None
        if tenant_id is not None and document.tenant_id != tenant_id:
            return None
        if workspace_id is not None and document.workspace_id != workspace_id:
            return None
        return document

    def list_documents(
        self,
        workspace_id: str,
        collection_id: str | None = None,
        *,
        tenant_id: str,
        after_document_id: str | None = None,
        limit: int | None = None,
        statuses: Iterable[str] | None = None,
        allowed_collection_ids: Iterable[str] | None = None,
    ) -> list[Document]:
        """Return visible documents in one workspace, in stable order.

        Deleted documents remain as tombstones so their stable identity cannot
        be resurrected accidentally, but they are not part of a read/list
        surface. Collection filtering is optional for application-level ACL
        narrowing.
        """
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("tenant_id is required")
        tenant = tenant_id.strip()
        status_filter = set(statuses) if statuses is not None else None
        collection_scope = set(allowed_collection_ids) if allowed_collection_ids is not None else None
        documents = sorted(
            (
                document
                for document in self._documents.values()
                if document.workspace_id == workspace_id
                and document.tenant_id == tenant
                and (collection_id is None or document.collection_id == collection_id)
                and (
                    collection_scope is None
                    or "*" in collection_scope
                    or document.collection_id in collection_scope
                )
                and document.status != "deleted"
                and (status_filter is None or document.status in status_filter)
            ),
            key=lambda document: document.document_id,
        )
        if after_document_id is not None:
            documents = [document for document in documents if document.document_id > after_document_id]
        if limit is not None:
            if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
                raise ValueError("limit must be a non-negative integer")
            documents = documents[:limit]
        return documents

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
