"""Knowledge application service — thin orchestration over packages/knowledge.

Preferred path for collections/document-metadata reads (DUAL with rollback via
RICK_API_ROOT_KNOWLEDGE=0). Heavy upload/worker behavior stays legacy-gated.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
import inspect
import re

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


def _scoped_store_call(method, *args, tenant_id: str, workspace_id: str):
    """Call a store only when it accepts the complete authorization scope."""

    try:
        parameters = inspect.signature(method).parameters.values()
    except (TypeError, ValueError):
        parameters = ()
    names = {parameter.name for parameter in parameters}
    supports_scope = {"tenant_id", "workspace_id"}.issubset(names) or any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters
    )
    if not supports_scope:
        raise TypeError("store read does not accept tenant/workspace scope")
    return method(*args, tenant_id=tenant_id, workspace_id=workspace_id)


def _required_tenant_id(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("tenant_id is required")
    return normalize_tenant_id(value)


_COLLECTION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


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
            status = _field(collection, "status") or "active"
            if status == "archived":
                continue
            items.append({
                "collection_id": collection_id,
                "title": _field(collection, "title") or "",
                "description": _field(collection, "description") or "",
                "workspace_id": workspace_id,
                "status": status,
                "version": _field(collection, "version") or 1,
            })
        return [i for i in items if can_access_collection(allowed=allowed, collection_id=i["collection_id"])]

    def list_managed_collections(self, *, workspace_id: str, tenant_id: str) -> list[dict]:
        """Return the tenant/workspace catalog for a manager, including archives."""
        tenant = _required_tenant_id(tenant_id)
        result = []
        for collection in self.store.list_collections(workspace_id, tenant_id=tenant):
            if _field(collection, "tenant_id") != tenant or _field(collection, "workspace_id") != workspace_id:
                continue
            result.append(self._public_collection(collection))
        return result

    @staticmethod
    def _public_collection(collection: object) -> dict:
        return {
            "collection_id": _field(collection, "collection_id"),
            "title": _field(collection, "title") or "",
            "description": _field(collection, "description") or "",
            "workspace_id": _field(collection, "workspace_id"),
            "tenant_id": _field(collection, "tenant_id"),
            "status": _field(collection, "status") or "active",
            "version": _field(collection, "version") or 1,
        }

    def create_collection(self, *, workspace_id: str, tenant_id: str, collection_id: str,
                          title: str, description: str = "") -> dict:
        tenant = _required_tenant_id(tenant_id)
        collection_id = (collection_id or "").strip()
        title = (title or "").strip()
        if not _COLLECTION_ID.fullmatch(collection_id) or not title or len(title) > 256:
            raise ValueError("collection is invalid")
        existing = self.store.get_collection(workspace_id, collection_id, tenant_id=tenant)
        if existing is not None:
            raise KeyError(collection_id)
        collection = Collection(
            workspace_id=workspace_id, collection_id=collection_id, tenant_id=tenant,
            title=title, description=(description or "").strip()[:2_000], status="active", version=1,
        )
        self.store.upsert_collection(collection)
        return self._public_collection(collection)

    def update_collection(self, *, workspace_id: str, tenant_id: str, collection_id: str,
                          title: str | None = None, description: str | None = None) -> dict:
        tenant = _required_tenant_id(tenant_id)
        collection = self.store.get_collection(workspace_id, collection_id, tenant_id=tenant)
        if collection is None:
            raise KeyError(collection_id)
        if getattr(collection, "status", "active") == "archived":
            raise ValueError("archived collection cannot be edited")
        if title is not None:
            title = title.strip()
            if not title or len(title) > 256:
                raise ValueError("collection title is invalid")
            collection.title = title
        if description is not None:
            collection.description = description.strip()[:2_000]
        collection.version = int(getattr(collection, "version", 1)) + 1
        self.store.upsert_collection(collection)
        return self._public_collection(collection)

    def archive_collection(self, *, workspace_id: str, tenant_id: str, collection_id: str) -> dict:
        tenant = _required_tenant_id(tenant_id)
        collection = self.store.get_collection(workspace_id, collection_id, tenant_id=tenant)
        if collection is None:
            raise KeyError(collection_id)
        collection.status = "archived"
        collection.version = int(getattr(collection, "version", 1)) + 1
        self.store.upsert_collection(collection)
        return self._public_collection(collection)

    def get_document(
        self, *, document_id: str, workspace_id: str, allowed: list[str], tenant_id: str
    ) -> dict | None:
        tenant = _required_tenant_id(tenant_id)
        getter = getattr(self.store, "get_document", None)
        if not callable(getter):
            return None
        document = _scoped_store_call(
            getter,
            document_id,
            tenant_id=tenant,
            workspace_id=workspace_id,
        )
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
