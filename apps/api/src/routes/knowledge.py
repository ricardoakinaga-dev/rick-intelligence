"""Knowledge routes: collections / documents / ingestion skeletons delegating to adapters."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from core.errors import ApiError
from dependencies.identity import require_authenticated
from dependencies.services import get_providers
from services.authorization_service import build_retrieval_context, filter_collection_items, has_permission

router = APIRouter(tags=["Knowledge"])

# Legacy stub path (rollback when RICK_API_ROOT_KNOWLEDGE=0 or store unavailable).
_DEMO_COLLECTIONS = [
    {"collection_id": "rag_phase0", "title": "Canonical collection", "workspace_id": "default"},
    {"collection_id": "vet-library", "title": "Veterinary library", "workspace_id": "default"},
]

_DEMO_DOCUMENTS = [
    {"document_id": "doc-stub-1", "title": "Stub document", "collection_id": "rag_phase0", "workspace_id": "default"},
]


def _knowledge_service():
    """Preferred root path; None falls back to the legacy stub lists (DUAL + rollback)."""
    from services.knowledge_service import KnowledgeApplicationService, root_knowledge_enabled

    if not root_knowledge_enabled():
        return None
    providers = get_providers()
    store = getattr(providers, "knowledge", None)
    if store is None:
        return None
    return KnowledgeApplicationService(store)


@router.get("/api/v1/collections")
def list_collections(session=Depends(require_authenticated)):
    if not has_permission(session, "collections.read"):
        raise ApiError("forbidden")
    ctx = build_retrieval_context(session, workspace_id=session.workspace_id or "default")
    service = _knowledge_service()
    if service is not None:
        items = service.list_collections(workspace_id=session.workspace_id or "default",
                                         allowed=list(ctx["allowed_collection_ids"]))
        return {"items": items, "total": len(items)}
    return {"items": filter_collection_items(_DEMO_COLLECTIONS, ctx), "total": len(filter_collection_items(_DEMO_COLLECTIONS, ctx))}


@router.get("/api/v1/documents")
def list_documents(session=Depends(require_authenticated)):
    # Library browsing is KM/platform-only; VET has sources.read but not library.browse/documents.read.
    if not has_permission(session, "documents.read"):
        raise ApiError("forbidden")
    ctx = build_retrieval_context(session, workspace_id=session.workspace_id or "default")
    items = filter_collection_items(_DEMO_DOCUMENTS, ctx)
    return {"items": items, "page": 1, "page_size": 20, "total": len(items), "next_cursor": None}


@router.get("/api/v1/documents/{document_id}")
def get_document(document_id: str, session=Depends(require_authenticated)):
    if not has_permission(session, "documents.read"):
        raise ApiError("forbidden")
    ctx = build_retrieval_context(session, workspace_id=session.workspace_id or "default")
    service = _knowledge_service()
    if service is not None:
        item = service.get_document(document_id=document_id, workspace_id=session.workspace_id or "default",
                                    allowed=list(ctx["allowed_collection_ids"]))
        if item is None:
            raise ApiError("not_found")
        return item
    items = filter_collection_items(_DEMO_DOCUMENTS, ctx)
    for item in items:
        if item["document_id"] == document_id:
            return item
    raise ApiError("not_found")


class UploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=256)
    collection_id: str = Field(min_length=1, max_length=128)


@router.post("/api/v1/documents/upload", status_code=201)
def upload_document(payload: UploadRequest, session=Depends(require_authenticated)):
    if not has_permission(session, "documents.upload"):
        raise ApiError("forbidden")
    # ACL narrowing enforced; heavy ingestion behavior stays in legacy adapter (Phase 1.4).
    build_retrieval_context(session, workspace_id=session.workspace_id or "default", collection_id=payload.collection_id)
    try:
        providers = get_providers()
        if providers.audit_sink is not None:
            providers.audit_sink.emit({"action": "document.upload", "actor_user_id": session.user_id,  # type: ignore[union-attr]
                                       "target_id": payload.filename, "workspace_id": session.workspace_id})
    except Exception:
        pass
    return {"status": "accepted", "filename": payload.filename, "collection_id": payload.collection_id}


class ReindexRequest(BaseModel):
    collection_id: str = Field(min_length=1, max_length=128)


@router.post("/api/v1/ingestion/reindex")
def reindex(payload: ReindexRequest, session=Depends(require_authenticated)):
    if not has_permission(session, "reindex.run"):
        raise ApiError("forbidden")
    build_retrieval_context(session, workspace_id=session.workspace_id or "default", collection_id=payload.collection_id)
    return {"status": "queued", "collection_id": payload.collection_id}
