"""Knowledge application service — thin orchestration over packages/knowledge.

Preferred path for collections/document-metadata reads (DUAL with rollback via
RICK_API_ROOT_KNOWLEDGE=0). Heavy upload/worker behavior stays legacy-gated.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from rick_authorization import can_access_collection
from rick_knowledge import (
    Chunk,
    Collection,
    Document,
    build_point_payload,
    content_checksum,
    normalize_tenant_id,
    point_id_for_chunk,
)


def root_knowledge_enabled() -> bool:
    return (os.getenv("RICK_API_ROOT_KNOWLEDGE") or "1").strip() != "0"


_DEMO_SEED = (
    Collection(workspace_id="default", collection_id="rag_phase0", tenant_id="default",
               title="Canonical collection"),
    Collection(workspace_id="default", collection_id="vet-library", tenant_id="default",
               title="Veterinary library"),
)

_DEMO_DOCS = (
    Document(document_id="doc-stub-1", workspace_id="default", collection_id="rag_phase0",
             tenant_id="default", title="Stub document", display_filename="stub.pdf",
             filename="stub.pdf", status="published"),
)

_DEMO_TEXT = (
    "Mastite bovina exige higiene rigorosa na ordenha, isolamento do animal "
    "afetado e avaliação veterinária antes da escolha do tratamento."
)


def _field(item: object, name: str) -> object:
    if isinstance(item, Mapping):
        return item.get(name)
    return getattr(item, name, None)


def _required_tenant_id(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("tenant_id is required")
    return normalize_tenant_id(value)


def seed_demo_corpus(store) -> None:
    for collection in _DEMO_SEED:
        store.upsert_collection(collection)
    for document in _DEMO_DOCS:
        store.upsert_document(document)


def seed_demo_points(store, embeddings) -> list[dict]:
    """Create a tiny published fixture for local root-path verification only."""

    document = store.get_document("doc-stub-1")
    if document is None:
        return []
    checksum = content_checksum(_DEMO_TEXT)
    chunk = Chunk(
        chunk_id="chunk-stub-1",
        document_id=document.document_id,
        tenant_id="default",
        chunk_index=0,
        text=_DEMO_TEXT,
        page_start=1,
        page_end=1,
        section="Veterinary protocol",
        checksum=checksum,
        embedding_version="demo-v1",
    )
    store.replace_document_chunks(document.document_id, [chunk])
    document.document_version = "demo-v1"
    document.content_checksum = checksum
    document.status = "published"
    document.embedding_model = getattr(embeddings, "model", "hash-stub-1536")
    document.embedding_version = "demo-v1"
    payload = build_point_payload(chunk=chunk, document=document)
    vector = embeddings.embed([_DEMO_TEXT])[0]
    return [{"point_id": point_id_for_chunk(chunk.chunk_id), "vector": vector, "payload": payload}]


class KnowledgeApplicationService:
    def __init__(self, store) -> None:
        self.store = store

    def list_collections(self, *, workspace_id: str, allowed: list[str], tenant_id: str) -> list[dict]:
        tenant = _required_tenant_id(tenant_id)
        items = []
        for collection in self.store.list_collections(workspace_id, tenant_id=tenant):
            collection_id = _field(collection, "collection_id")
            if (
                _field(collection, "tenant_id") != tenant
                or _field(collection, "workspace_id") != workspace_id
                or not isinstance(collection_id, str)
            ):
                continue
            items.append({
                "collection_id": collection_id,
                "title": _field(collection, "title") or "",
                "workspace_id": workspace_id,
            })
        return [i for i in items if can_access_collection(allowed=allowed, collection_id=i["collection_id"])]

    def get_document(
        self, *, document_id: str, workspace_id: str, allowed: list[str], tenant_id: str
    ) -> dict | None:
        document = self.store.get_document(document_id)
        tenant = _required_tenant_id(tenant_id)
        if (
            document is None
            or _field(document, "workspace_id") != workspace_id
            or _field(document, "tenant_id") != tenant
        ):
            return None
        # Processing/failed/unpublished records are job state, not published
        # library content. Keeping them out of public reads prevents a partial
        # ingest from becoming a document or existence oracle.
        if _field(document, "status") != "published":
            return None
        collection_id = _field(document, "collection_id")
        if not can_access_collection(allowed=allowed, collection_id=collection_id if isinstance(collection_id, str) else None):
            return None
        return {
            "document_id": _field(document, "document_id"),
            "title": _field(document, "title"),
            "collection_id": collection_id,
            "workspace_id": workspace_id,
            "status": "published",
            "source_type": _field(document, "source_type"),
            "mime_type": _field(document, "mime_type"),
            "document_version": _field(document, "document_version"),
            "content_checksum": _field(document, "content_checksum"),
            "tenant_id": tenant,
        }

    def list_documents(
        self,
        *,
        workspace_id: str,
        allowed: list[str],
        tenant_id: str,
        collection_id: str | None = None,
        after_document_id: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        """Return authorized document metadata in stable store order."""
        allowed_scope = list(allowed)
        tenant = _required_tenant_id(tenant_id)
        try:
            documents = self.store.list_documents(
                workspace_id,
                collection_id=collection_id,
                tenant_id=tenant,
                after_document_id=after_document_id,
                limit=limit,
                statuses=("published",),
                allowed_collection_ids=allowed_scope,
            )
        except TypeError:
            # A store that cannot accept the tenant/ACL contract is not safe
            # to query through this boundary. An unscoped compatibility call
            # would turn a signature mismatch into a cross-tenant read.
            return []
        items: list[dict] = []
        for document in documents:
            document_tenant = _field(document, "tenant_id")
            document_workspace = _field(document, "workspace_id")
            collection_id = _field(document, "collection_id")
            if (
                _field(document, "status") != "published"
                or document_tenant != tenant
                or document_workspace != workspace_id
                or not isinstance(collection_id, str)
            ):
                continue
            if not can_access_collection(allowed=allowed_scope, collection_id=collection_id):
                continue
            items.append({
                "document_id": _field(document, "document_id"),
                "title": _field(document, "title"),
                "collection_id": collection_id,
                "workspace_id": workspace_id,
                "status": "published",
                "source_type": _field(document, "source_type"),
                "mime_type": _field(document, "mime_type"),
                "document_version": _field(document, "document_version"),
                "content_checksum": _field(document, "content_checksum"),
                "tenant_id": tenant,
            })
        if after_document_id:
            items = [item for item in items if item["document_id"] > after_document_id]
        return items if limit is None else items[:limit]

    def count_documents(
        self,
        *,
        workspace_id: str,
        allowed: list[str],
        tenant_id: str,
        collection_id: str | None = None,
    ) -> int:
        return len(
            self.list_documents(
                workspace_id=workspace_id,
                allowed=allowed,
                tenant_id=tenant_id,
                collection_id=collection_id,
            )
        )
