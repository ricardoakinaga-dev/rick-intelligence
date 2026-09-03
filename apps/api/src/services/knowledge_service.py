"""Knowledge application service — thin orchestration over packages/knowledge.

Preferred path for collections/document-metadata reads (DUAL with rollback via
RICK_API_ROOT_KNOWLEDGE=0). Heavy upload/worker behavior stays legacy-gated.
"""

from __future__ import annotations

import os

from rick_authorization import can_access_collection
from rick_knowledge import Collection, Document


def root_knowledge_enabled() -> bool:
    return (os.getenv("RICK_API_ROOT_KNOWLEDGE") or "1").strip() != "0"


_DEMO_SEED = (
    Collection(workspace_id="default", collection_id="rag_phase0", title="Canonical collection"),
    Collection(workspace_id="default", collection_id="vet-library", title="Veterinary library"),
)

_DEMO_DOCS = (
    Document(document_id="doc-stub-1", workspace_id="default", collection_id="rag_phase0",
             title="Stub document", display_filename="stub.pdf", filename="stub.pdf", status="published"),
)


def seed_demo_corpus(store) -> None:
    for collection in _DEMO_SEED:
        store.upsert_collection(collection)
    for document in _DEMO_DOCS:
        store.upsert_document(document)


class KnowledgeApplicationService:
    def __init__(self, store) -> None:
        self.store = store

    def list_collections(self, *, workspace_id: str, allowed: list[str]) -> list[dict]:
        items = [
            {"collection_id": c.collection_id, "title": c.title, "workspace_id": c.workspace_id}
            for c in self.store.list_collections(workspace_id)
        ]
        return [i for i in items if can_access_collection(allowed=allowed, collection_id=i["collection_id"])]

    def get_document(self, *, document_id: str, workspace_id: str, allowed: list[str]) -> dict | None:
        document = self.store.get_document(document_id)
        if document is None or document.workspace_id != workspace_id:
            return None
        if document.status == "deleted":
            return None
        if not can_access_collection(allowed=allowed, collection_id=document.collection_id):
            return None
        return {"document_id": document.document_id, "title": document.title,
                "collection_id": document.collection_id, "workspace_id": document.workspace_id}
