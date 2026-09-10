"""Authenticated collections, documents, and ingestion lifecycle routes."""

from __future__ import annotations

import inspect
from itertools import islice
from collections.abc import Mapping
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from core.errors import ApiError
from core.middleware import RequestTooLarge, is_request_too_large
from dependencies.identity import require_authenticated
from dependencies.services import get_providers
from services.audit import emit_required
from services.authorization_service import build_retrieval_context, filter_collection_items, has_permission
from services.ingestion_service import IngestionApplicationService, safe_job_json
from services.json_boundary import decode_request_json

router = APIRouter(tags=["Knowledge"])

# Legacy stub path (rollback when RICK_API_ROOT_KNOWLEDGE=0 or store unavailable).
_DEMO_COLLECTIONS = [
    {"collection_id": "rag_phase0", "title": "Canonical collection", "workspace_id": "default", "tenant_id": "default"},
    {"collection_id": "vet-library", "title": "Veterinary library", "workspace_id": "default", "tenant_id": "default"},
]

_DEMO_DOCUMENTS = [
    {
        "document_id": "doc-stub-1",
        "title": "Stub document",
        "collection_id": "rag_phase0",
        "workspace_id": "default",
        "tenant_id": "default",
    },
]

_MIME_BY_EXTENSION = {
    ".txt": frozenset({"text/plain", "application/octet-stream"}),
    ".md": frozenset({"text/markdown", "text/plain", "text/x-markdown", "application/octet-stream"}),
    ".pdf": frozenset({"application/pdf", "application/octet-stream"}),
    ".docx": frozenset({
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
        "application/octet-stream",
    }),
}


class _UploadRequestTooLarge(Exception):
    """Internal signal for a chunked multipart body over the API limit."""


def _bounded_upload_receive(request: Request, max_bytes: int):
    """Wrap Starlette's receive channel without buffering the request body."""
    original_receive = request._receive
    received_bytes = 0

    async def receive():
        nonlocal received_bytes
        message = await original_receive()
        if message.get("type") == "http.request":
            body = message.get("body", b"") or b""
            received_bytes += len(body)
            if received_bytes > max_bytes:
                raise _UploadRequestTooLarge
        return message

    return original_receive, receive


def _validate_multipart_type(filename: object, content_type: object) -> None:
    """Reject a known incompatible MIME hint; extension/parser stay authoritative."""
    if not isinstance(filename, str) or not isinstance(content_type, str):
        return
    normalized_type = content_type.split(";", 1)[0].strip().lower()
    if not normalized_type:
        return
    suffix = Path(filename).suffix.lower()
    allowed = _MIME_BY_EXTENSION.get(suffix)
    if allowed is not None and normalized_type not in allowed:
        raise ApiError("unsupported_media_type")


def _knowledge_service(request: Request):
    """Preferred root path; None falls back to the legacy stub lists (DUAL + rollback)."""
    from services.knowledge_service import KnowledgeApplicationService, root_knowledge_enabled

    if not root_knowledge_enabled():
        return None
    providers = get_providers(request)
    store = getattr(providers, "knowledge", None)
    if store is None:
        return None
    return KnowledgeApplicationService(store)


def _requested_workspace(session: object, requested: str | None = None) -> str:
    return requested or getattr(session, "workspace_id", None) or "default"


def _scope(session: object, *, workspace_id: str | None = None, collection_id: str | None = None) -> dict:
    """Build scope exclusively from the session plus a narrowing request."""
    context = build_retrieval_context(
        session,
        workspace_id=_requested_workspace(session, workspace_id),
        collection_id=collection_id,
    )
    if _context_tenant(context) is None:
        raise ApiError("forbidden")
    return context


def _context_tenant(context: Mapping[str, Any]) -> str | None:
    """Return only an explicit, non-empty tenant from a trusted scope."""
    tenant_id = context.get("tenant_id")
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        return None
    return tenant_id.strip()


def _ingestion_service(request: Request):
    """Return the injected application service, with a narrow integration shim.

    The normal integrator contract is ``Providers.ingestion`` containing an
    ``IngestionApplicationService``. Accepting the package service as a
    fallback keeps a small hermetic fixture usable without moving provider
    construction into this route module.
    """
    from services.knowledge_service import root_knowledge_enabled

    if not root_knowledge_enabled():
        return None
    providers = get_providers(request)
    candidate = getattr(providers, "ingestion", None)
    if candidate is None:
        return None
    lifecycle_lock = getattr(request.app.state, "lifecycle_shutdown_lock", None)
    lock_context = lifecycle_lock if lifecycle_lock is not None else nullcontext()
    with lock_context:
        if any(
            getattr(request.app.state, name, False)
            for name in (
                "lifecycle_shutdown_started",
                "lifecycle_shutdown_in_progress",
                "lifecycle_shutdown_complete",
            )
        ):
            # A lazy wrapper created after the lifespan snapshot would own an
            # executor and staging directory that shutdown could never see.
            return None
        if callable(getattr(candidate, "upload", None)) and callable(getattr(candidate, "get_status", None)):
            return candidate
        if callable(getattr(candidate, "ingest", None)):
            cached = getattr(providers, "_api_ingestion_service", None)
            if cached is not None:
                return cached

            def refresh() -> None:
                retrieval = getattr(providers, "retrieval", None)
                refresh_method = getattr(retrieval, "refresh", None)
                if callable(refresh_method):
                    refresh_method()
                    return
                # The current hermetic retrieval facade exposes attach_points;
                # use it only when the injected canonical service exposes its
                # in-memory vector points. No live provider is initialized here.
                attach = getattr(retrieval, "attach_points", None)
                vectors = getattr(candidate, "vectors", None)
                all_points = getattr(vectors, "all_points", None)
                if callable(attach) and callable(all_points):
                    try:
                        points = all_points(limit=100_000)
                    except TypeError:
                        points = all_points()
                    snapshot = list(islice(points, 100_001))
                    if len(snapshot) > 100_000:
                        raise ValueError("complete point snapshot exceeds read limit")
                    attach(snapshot)

            cached = IngestionApplicationService(
                candidate,
                refresh_callback=refresh,
                event_sink=getattr(request.app.state, "telemetry", None),
            )
            # The wrapper is constructed by this application, even though the
            # canonical ingestion provider is caller-owned. Register only the
            # wrapper so the root lifespan can stop its local executor and clean
            # its temporary staging without closing the injected provider.
            runtime_owned = getattr(request.app.state, "owned_runtime_resources", None)
            if isinstance(runtime_owned, list) and all(item is not cached for item in runtime_owned):
                runtime_owned.append(cached)
            shutdown_owned = getattr(request.app.state, "owned_shutdown_resources", None)
            if isinstance(shutdown_owned, list) and all(item is not cached for item in shutdown_owned):
                shutdown_owned.append(cached)
            owned_resources = getattr(request.app.state, "owned_resources", None)
            if isinstance(owned_resources, list) and all(item is not cached for item in owned_resources):
                owned_resources.append(cached)
            try:
                setattr(providers, "_api_ingestion_service", cached)
            except Exception:
                pass
            return cached
    return None


def _api_ingestion_error(exc: object) -> None:
    """Translate a lifecycle failure without relying on module identity.

    Some differential tests intentionally unload/reload the ``services``
    package to isolate the preserved child implementation. Matching the
    stable error code instead of a class object keeps the API fail-safe across
    that legitimate module-boundary operation.
    """
    code = getattr(exc, "code", None)
    if code not in {
        "validation_error", "unsupported_media_type", "request_too_large",
        "not_found", "storage_unavailable", "provider_timeout",
        "provider_unavailable", "vector_store_unavailable", "lock_unavailable",
        "ingestion_failed", "recovery_required", "conflict",
    }:
        code = "ingestion_failed"
    raise ApiError(code) from None


def _job_field(job: object, name: str, default: Any = None) -> Any:
    if isinstance(job, Mapping):
        return job.get(name, default)
    return getattr(job, name, default)


def _job_visible(job: object, context: dict) -> bool:
    tenant_id = _job_field(job, "tenant_id")
    workspace_id = _job_field(job, "workspace_id")
    collection_id = _job_field(job, "collection_id")
    if not all(isinstance(value, str) and value for value in (tenant_id, workspace_id, collection_id)):
        return False
    context_tenant = _context_tenant(context)
    if context_tenant is None or tenant_id != context_tenant:
        return False
    if workspace_id != context.get("workspace_id"):
        return False
    collection = collection_id
    allowed = set(context.get("allowed_collection_ids") or [])
    return collection in allowed or "*" in allowed


def _service_status(service: object, job_id: str, context: dict) -> object | None:
    getter = getattr(service, "get_status", None) or getattr(service, "status", None)
    if not callable(getter):
        return None
    tenant_id = _context_tenant(context)
    if tenant_id is None:
        return None
    try:
        job = getter(
            job_id,
            tenant_id=tenant_id,
            workspace_id=context["workspace_id"],
            allowed_collection_ids=context.get("allowed_collection_ids", []),
        )
    except TypeError:
        # Small explicit test doubles may expose only get_status(job_id). The
        # second check is mandatory so a double cannot bypass route ACL.
        job = getter(job_id)
    if job is None or not _job_visible(job, context):
        return None
    return job


def _job_envelope(job: object, *, cancelled: bool | None = None) -> dict[str, Any]:
    safe = safe_job_json(job)
    document_id = safe.get("document_id")
    document = None
    if document_id:
        document = {
            "document_id": document_id,
            "workspace_id": safe.get("workspace_id"),
            "collection_id": safe.get("collection_id"),
            "status": safe.get("status"),
        }
    response: dict[str, Any] = {
        "status": safe["status"],
        "job": safe,
        "document": document,
        # Top-level IDs/status retain the small pre-lifecycle client shape;
        # nested objects are the canonical envelope for new clients.
        "job_id": safe["job_id"],
        "document_id": document_id,
    }
    if cancelled is not None:
        response["cancelled"] = cancelled
    return response


def _public_document(item: object) -> dict[str, Any]:
    """Whitelist document metadata; never serialize chunks or source paths."""
    output: dict[str, Any] = {}
    for name in (
        "document_id",
        "title",
        "collection_id",
        "workspace_id",
        "status",
        "source_type",
        "mime_type",
        "document_version",
        "content_checksum",
    ):
        value = item.get(name) if isinstance(item, Mapping) else getattr(item, name, None)
        if value is not None:
            output[name] = value
    return output


def _knowledge_documents(
    service: object,
    context: dict,
    *,
    limit: int | None = None,
    cursor: str | None = None,
    collection_id: str | None = None,
) -> list[dict[str, Any]]:
    """Read documents from the injected knowledge application/store path."""
    tenant_id = _context_tenant(context)
    if tenant_id is None:
        return []
    list_method = getattr(service, "list_documents", None)
    if callable(list_method):
        try:
            raw_items = list_method(
                workspace_id=context["workspace_id"],
                tenant_id=tenant_id,
                allowed=list(context.get("allowed_collection_ids") or []),
                collection_id=collection_id,
                after_document_id=cursor,
                limit=limit,
            )
        except TypeError:
            try:
                raw_items = list_method(
                    workspace_id=context["workspace_id"],
                    tenant_id=tenant_id,
                    allowed=list(context.get("allowed_collection_ids") or []),
                )
            except TypeError:
                # Never fall back to a workspace-only legacy read: the
                # tenant/ACL contract is mandatory at this boundary.
                return []
        items = []
        for item in list(raw_items or []):
            public = _public_document(item)
            if (
                public.get("status") == "published"
                and _job_field(item, "tenant_id") == tenant_id
            ):
                items.append(public)
        items = filter_collection_items(items, context)
        if cursor:
            items = [item for item in items if item.get("document_id", "") > cursor]
        return items if limit is None else items[:limit]

    # KnowledgeApplicationService currently exposes get_document and its
    # injected in-memory store exposes metadata through this private map, but
    # has no list_documents protocol method yet. Ask the application service to
    # authorize each metadata record before returning it.
    store = getattr(service, "store", None)
    documents = getattr(store, "_documents", None)
    if not isinstance(documents, Mapping):
        return []
    get_method = getattr(service, "get_document", None)
    if not callable(get_method):
        return []
    items: list[dict[str, Any]] = []
    for raw in documents.values():
        document_id = _job_field(raw, "document_id")
        if not isinstance(document_id, str) or _job_field(raw, "status") == "deleted":
            continue
        try:
            item = get_method(
                document_id=document_id,
                workspace_id=context["workspace_id"],
                tenant_id=tenant_id,
                allowed=list(context.get("allowed_collection_ids") or []),
            )
        except TypeError:
            # A document getter that cannot accept the tenant/ACL contract is
            # not safe to query through this boundary. Never downgrade to an
            # unscoped compatibility call that could leak another tenant.
            continue
        if (
            item is not None
            and _job_field(item, "tenant_id") == tenant_id
        ):
            items.append(_public_document(item))
    items = filter_collection_items(items, context)
    if cursor:
        items = [item for item in items if item.get("document_id", "") > cursor]
    return items if limit is None else items[:limit]


class UploadRequest(BaseModel):
    """Narrow JSON compatibility body; multipart is the primary contract."""

    filename: str = Field(min_length=1, max_length=256)
    collection_id: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=50 * 1024 * 1024)


class CollectionCreateRequest(BaseModel):
    collection_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=256)
    description: str = Field(default="", max_length=2_000)
    workspace_id: str | None = Field(default=None, max_length=128)


class CollectionUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=2_000)


@router.post("/api/v1/collections", status_code=201)
def create_collection(payload: CollectionCreateRequest, request: Request,
                      session=Depends(require_authenticated)):
    if not has_permission(session, "collections.manage"):
        raise ApiError("forbidden")
    service = _knowledge_service(request)
    if service is None:
        raise ApiError("provider_unavailable")
    context = _scope(session, workspace_id=payload.workspace_id)
    try:
        item = service.create_collection(
            workspace_id=context["workspace_id"], tenant_id=context["tenant_id"],
            collection_id=payload.collection_id, title=payload.title,
            description=payload.description,
        )
    except KeyError:
        raise ApiError("conflict") from None
    except ValueError:
        raise ApiError("validation_error") from None
    emit_required(get_providers(request).audit_sink, {
        "action": "collection.create", "actor_user_id": session.user_id,
        "target_id": payload.collection_id, "tenant_id": context["tenant_id"],
        "workspace_id": context["workspace_id"],
    })
    return item


@router.patch("/api/v1/collections/{collection_id}")
def update_collection(collection_id: str, payload: CollectionUpdateRequest, request: Request,
                      session=Depends(require_authenticated)):
    if not has_permission(session, "collections.manage"):
        raise ApiError("forbidden")
    service = _knowledge_service(request)
    if service is None:
        raise ApiError("provider_unavailable")
    context = _scope(session)
    try:
        item = service.update_collection(
            workspace_id=context["workspace_id"], tenant_id=context["tenant_id"],
            collection_id=collection_id, **payload.model_dump(exclude_unset=True),
        )
    except KeyError:
        raise ApiError("not_found") from None
    except ValueError:
        raise ApiError("conflict") from None
    return item


@router.post("/api/v1/collections/{collection_id}/archive")
def archive_collection(collection_id: str, request: Request,
                       session=Depends(require_authenticated)):
    if not has_permission(session, "collections.manage"):
        raise ApiError("forbidden")
    service = _knowledge_service(request)
    if service is None:
        raise ApiError("provider_unavailable")
    context = _scope(session)
    try:
        item = service.archive_collection(
            workspace_id=context["workspace_id"], tenant_id=context["tenant_id"],
            collection_id=collection_id,
        )
    except KeyError:
        raise ApiError("not_found") from None
    _audit_collection(request, "collection.archive", session, collection_id, context)
    return item


class CollectionGrantRequest(BaseModel):
    granted: bool


@router.put("/api/v1/collections/{collection_id}/grants/{user_id}")
def set_collection_grant(collection_id: str, user_id: str, payload: CollectionGrantRequest,
                         request: Request, session=Depends(require_authenticated)):
    if not has_permission(session, "collections.manage"):
        raise ApiError("forbidden")
    service = _knowledge_service(request)
    if service is None:
        raise ApiError("provider_unavailable")
    context = _scope(session, collection_id=collection_id)
    identity = get_providers(request).identity
    list_users = getattr(identity, "list_users", None)
    if not callable(list_users):
        raise ApiError("provider_unavailable")
    try:
        users = list_users(
            tenant_id=context["tenant_id"],
            workspace_id=context["workspace_id"],
        ) or []
    except TypeError:
        raise ApiError("provider_unavailable") from None
    target = next((item for item in users if _job_field(item, "user_id") == user_id), None)
    if target is None or _job_field(target, "tenant_id") != context["tenant_id"]:
        raise ApiError("not_found")
    current = list(_job_field(target, "authorized_collection_ids", []) or [])
    normalized = collection_id.strip()
    current = [item for item in current if item != normalized]
    if payload.granted:
        current.append(normalized)
    update = getattr(identity, "update_user", None)
    if not callable(update):
        raise ApiError("provider_unavailable")
    update(actor=session, user_id=user_id, authorized_collection_ids=current)
    _audit_collection(request, "collection.grant_updated", session, user_id, context)
    return {"user_id": user_id, "collection_id": normalized, "granted": payload.granted}


def _audit_collection(request: Request, action: str, session, target_id: str, context: dict) -> None:
    emit_required(get_providers(request).audit_sink, {
        "action": action, "actor_user_id": session.user_id, "target_id": target_id,
        "tenant_id": context["tenant_id"], "workspace_id": context["workspace_id"],
    })


@router.get("/api/v1/collections")
def list_collections(request: Request, session=Depends(require_authenticated)):
    if not has_permission(session, "collections.read"):
        raise ApiError("forbidden")
    ctx = _scope(session)
    service = _knowledge_service(request)
    if service is not None:
        items = service.list_collections(
            workspace_id=ctx["workspace_id"],
            tenant_id=ctx["tenant_id"],
            allowed=list(ctx["allowed_collection_ids"]),
        )
        # Application service is the scope owner; keep the response a stable
        # collection DTO even when an injected store returns dataclasses.
    else:
        items = [
            item for item in filter_collection_items(_DEMO_COLLECTIONS, ctx)
            if _job_field(item, "tenant_id") == ctx["tenant_id"]
        ]
    return {"items": items, "total": len(items)}


@router.get("/api/v1/documents")
def list_documents(
    request: Request,
    session=Depends(require_authenticated),
    workspace_id: str | None = Query(default=None, max_length=128),
    collection_id: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=256),
):
    # Library browsing is KM/platform-only; VET has sources.read but not
    # library.browse/documents.read.
    if not has_permission(session, "documents.read"):
        raise ApiError("forbidden")
    ctx = _scope(session, workspace_id=workspace_id, collection_id=collection_id)
    service = _knowledge_service(request)
    normalized_collection_id = _normalize_collection(collection_id) if collection_id else None
    if service is not None:
        items = _knowledge_documents(
            service,
            ctx,
            limit=limit + 1,
            cursor=cursor,
            collection_id=normalized_collection_id,
        )
        count_method = getattr(service, "count_documents", None)
        if callable(count_method):
            try:
                total = int(
                    count_method(
                        workspace_id=ctx["workspace_id"],
                        tenant_id=ctx["tenant_id"],
                        allowed=list(ctx.get("allowed_collection_ids") or []),
                        collection_id=normalized_collection_id,
                    )
                )
            except (TypeError, ValueError):
                total = len(items)
        else:
            total = len(items)
    else:
        items = [
            item for item in filter_collection_items(_DEMO_DOCUMENTS, ctx)
            if _job_field(item, "tenant_id") == ctx["tenant_id"]
        ]
        if cursor:
            items = [item for item in items if item.get("document_id", "") > cursor]
        items = items[: limit + 1]
        total = len(items)
    has_more = len(items) > limit
    visible_items = items[:limit]
    next_cursor = visible_items[-1].get("document_id") if has_more and visible_items else None
    return {
        "items": visible_items,
        "page": 1,
        "page_size": limit,
        "total": total,
        "next_cursor": next_cursor,
    }


@router.get("/api/v1/documents/{document_id}")
def get_document(document_id: str, request: Request, session=Depends(require_authenticated)):
    if not has_permission(session, "documents.read"):
        raise ApiError("forbidden")
    ctx = _scope(session)
    service = _knowledge_service(request)
    if service is not None:
        item = service.get_document(
            document_id=document_id,
            workspace_id=ctx["workspace_id"],
            tenant_id=ctx["tenant_id"],
            allowed=list(ctx["allowed_collection_ids"]),
        )
        if item is None:
            raise ApiError("not_found")
        return _public_document(item)
    items = [
        item for item in filter_collection_items(_DEMO_DOCUMENTS, ctx)
        if _job_field(item, "tenant_id") == ctx["tenant_id"]
    ]
    for item in items:
        if item["document_id"] == document_id:
            return item
    raise ApiError("not_found")


@router.delete("/api/v1/documents/{document_id}")
def delete_document(document_id: str, request: Request, session=Depends(require_authenticated)):
    """Delete metadata and indexed points only within the caller's scope."""
    if not has_permission(session, "documents.manage"):
        raise ApiError("forbidden")
    ctx = _scope(session)
    service = _ingestion_service(request)
    if service is None:
        raise ApiError("not_found")
    delete_method = getattr(service, "delete_document", None)
    if not callable(delete_method):
        raise ApiError("storage_unavailable")
    try:
        result = delete_method(
            document_id,
            tenant_id=ctx["tenant_id"],
            workspace_id=ctx["workspace_id"],
            allowed_collection_ids=ctx.get("allowed_collection_ids", []),
        )
    except Exception as exc:
        _api_ingestion_error(exc)
    if result is None:
        raise ApiError("not_found")
    emit_required(get_providers(request).audit_sink, {
        "action": "document.delete",
        "actor_user_id": session.user_id,
        "target_id": document_id,
        "tenant_id": ctx["tenant_id"],
        "workspace_id": ctx["workspace_id"],
        "request_id": getattr(request.state, "request_id", None),
    })
    return result


async def _request_json(request: Request) -> object:
    try:
        body = await request.body()
        settings = get_providers(request).settings
        if len(body) > settings.max_json_bytes:
            raise RequestTooLarge
        return decode_request_json(body, max_bytes=settings.max_json_bytes)
    except Exception as exc:
        if is_request_too_large(exc):
            raise ApiError("request_too_large") from None
        raise ApiError("validation_error") from None


def _request_context_values(request: Request) -> tuple[str | None, str | None]:
    return (
        getattr(request.state, "request_id", None),
        getattr(request.state, "correlation_id", None),
    )


@router.post(
    "/api/v1/documents/upload",
    status_code=202,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file", "collection_id"],
                        "properties": {
                            "file": {"type": "string", "format": "binary"},
                            "collection_id": {"type": "string", "minLength": 1, "maxLength": 128},
                        },
                        "additionalProperties": False,
                    }
                },
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["filename", "collection_id", "content"],
                        "properties": {
                            "filename": {"type": "string", "minLength": 1, "maxLength": 256},
                            "collection_id": {"type": "string", "minLength": 1, "maxLength": 128},
                            "content": {"type": "string", "minLength": 1, "maxLength": 52428800},
                        },
                        "additionalProperties": False,
                    }
                },
            },
        }
    },
)
async def upload_document(request: Request, session=Depends(require_authenticated)):
    # This guard deliberately precedes request.form()/source consumption. A
    # caller without the server permission cannot cause the lifecycle service
    # to read or stage an upload.
    if not has_permission(session, "documents.upload"):
        raise ApiError("forbidden")

    source: object
    filename: str | None
    collection_id: str | None
    upload_part: object | None = None
    content_type = (request.headers.get("content-type") or "").lower()
    if content_type.startswith("multipart/form-data"):
        settings = getattr(get_providers(request), "settings", None)
        max_upload_bytes = getattr(settings, "max_upload_bytes", 50 * 1024 * 1024)
        original_receive, bounded_receive = _bounded_upload_receive(request, max_upload_bytes)
        request._receive = bounded_receive
        try:
            form = await request.form()
        except _UploadRequestTooLarge:
            try:
                await request.close()
            except Exception:
                pass
            raise ApiError("request_too_large") from None
        except Exception as exc:
            if is_request_too_large(exc):
                raise ApiError("request_too_large") from None
            raise ApiError("validation_error") from None
        finally:
            request._receive = original_receive
        upload_part = form.get("file")
        filename = getattr(upload_part, "filename", None)
        collection_id = form.get("collection_id") if isinstance(form.get("collection_id"), str) else None
        if upload_part is None or (not callable(getattr(upload_part, "read", None)) and getattr(upload_part, "file", None) is None):
            raise ApiError("validation_error")
        try:
            _validate_multipart_type(filename, getattr(upload_part, "content_type", None))
        except ApiError:
            close = getattr(upload_part, "close", None)
            if callable(close):
                try:
                    closed = close()
                    if inspect.isawaitable(closed):
                        await closed
                except Exception:
                    pass
            raise
        source = upload_part
    elif content_type.startswith("application/json"):
        raw = await _request_json(request)
        try:
            payload = UploadRequest.model_validate(raw)
        except Exception:
            raise ApiError("validation_error") from None
        filename = payload.filename
        collection_id = payload.collection_id
        source = payload.content
    else:
        raise ApiError("unsupported_media_type")

    # Collection authorization is evaluated from the authenticated snapshot;
    # the client value can only narrow that server-derived scope.
    ctx = _scope(session, collection_id=collection_id)
    service = _ingestion_service(request)
    if service is None:
        raise ApiError("storage_unavailable")
    request_id, correlation_id = _request_context_values(request)
    try:
        result = await run_in_threadpool(
            getattr(service, "submit_upload", service.upload),
            source,
            filename=filename or "",
            collection_id=collection_id or "",
            tenant_id=ctx["tenant_id"],
            workspace_id=ctx["workspace_id"],
            request_id=request_id,
            correlation_id=correlation_id,
        )
    except Exception as exc:
        _api_ingestion_error(exc)
    finally:
        close = getattr(upload_part, "close", None)
        if callable(close):
            try:
                closed = close()
                if inspect.isawaitable(closed):
                    await closed
            except Exception:
                pass

    if not _job_visible(result, ctx):
        # The adapter result is untrusted even when the request was authorized;
        # do not expose a job whose scope drifted during upload.
        raise ApiError("ingestion_failed")
    response = _job_envelope(result)
    emit_required(get_providers(request).audit_sink, {
        "action": "document.upload",
        "actor_user_id": session.user_id,
        "target_id": response["job_id"],
        "tenant_id": ctx["tenant_id"],
        "workspace_id": ctx["workspace_id"],
        "request_id": request_id,
    })
    return response


class ReindexRequest(BaseModel):
    document_id: str = Field(min_length=1, max_length=256)
    collection_id: str | None = Field(default=None, min_length=1, max_length=128)
    filename: str | None = Field(default=None, min_length=1, max_length=256)
    content: str | None = Field(default=None, min_length=1, max_length=50 * 1024 * 1024)


class RetryRequest(BaseModel):
    """A local retry always carries a fresh bounded source."""

    filename: str = Field(min_length=1, max_length=256)
    content: str = Field(min_length=1, max_length=50 * 1024 * 1024)


def _document_for_reindex(document_id: str, request: Request, *, tenant_id: str) -> object | None:
    service = _knowledge_service(request)
    if service is None:
        return None
    store = getattr(service, "store", None)
    getter = getattr(store, "get_document_for_tenant", None)
    if callable(getter):
        try:
            return getter(document_id, tenant_id=tenant_id)
        except Exception:
            return None
    getter = getattr(store, "get_document", None)
    if not callable(getter):
        return None
    document = getter(document_id)
    document_tenant = _job_field(document, "tenant_id")
    return document if isinstance(document_tenant, str) and document_tenant and document_tenant == tenant_id else None


def _normalize_collection(value: str) -> str:
    try:
        from rick_knowledge import normalize_collection_id

        return normalize_collection_id(value)
    except (ImportError, TypeError, ValueError):
        return value.strip()


@router.post(
    "/api/v1/ingestion/reindex",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["document_id"],
                        "properties": {
                            "document_id": {"type": "string", "minLength": 1, "maxLength": 256},
                            "collection_id": {"type": "string", "minLength": 1, "maxLength": 128},
                            "filename": {"type": "string", "minLength": 1, "maxLength": 256},
                            "content": {"type": "string", "minLength": 1, "maxLength": 52428800},
                        },
                        "additionalProperties": False,
                    }
                }
            },
        }
    },
)
async def reindex(request: Request, session=Depends(require_authenticated)):
    if not has_permission(session, "reindex.run"):
        raise ApiError("forbidden")
    raw = await _request_json(request)
    try:
        payload = ReindexRequest.model_validate(raw)
    except Exception:
        raise ApiError("validation_error") from None

    base_ctx = _scope(session)
    document = _document_for_reindex(
        payload.document_id, request, tenant_id=base_ctx["tenant_id"]
    )
    if document is None or _job_field(document, "status") == "deleted":
        # Same response for missing, foreign, and deleted documents.
        raise ApiError("not_found")
    document_workspace = getattr(document, "workspace_id", None)
    document_collection = getattr(document, "collection_id", None)
    if not isinstance(document_workspace, str) or not isinstance(document_collection, str):
        raise ApiError("not_found")
    requested_collection = payload.collection_id or document_collection
    if _normalize_collection(requested_collection) != _normalize_collection(document_collection):
        raise ApiError("not_found")
    try:
        ctx = _scope(session, workspace_id=document_workspace, collection_id=document_collection)
    except ApiError:
        # Do not turn a cross-workspace/collection probe into an existence
        # oracle. The caller receives the same generic missing-resource code.
        raise ApiError("not_found") from None

    service = _ingestion_service(request)
    if service is None:
        raise ApiError("storage_unavailable")
    request_id, correlation_id = _request_context_values(request)
    filename = payload.filename or getattr(document, "display_filename", None) or getattr(document, "filename", None) or "document.txt"
    try:
        result = await run_in_threadpool(
            service.reindex,
            payload.document_id,
            collection_id=document_collection,
            tenant_id=ctx["tenant_id"],
            workspace_id=ctx["workspace_id"],
            source=payload.content if payload.content is not None else None,
            filename=filename,
            request_id=request_id,
            correlation_id=correlation_id,
        )
    except Exception as exc:
        _api_ingestion_error(exc)
    if (
        not _job_visible(result, ctx)
        or not isinstance(_job_field(result, "document_id"), str)
        or not _job_field(result, "document_id")
    ):
        # The adapter result is an untrusted postcondition. Never serialize a
        # job whose scope or document identity drifted after authorization.
        raise ApiError("ingestion_failed")
    return _job_envelope(result)


@router.get("/api/v1/ingestion/jobs/{job_id}")
def ingestion_job_status(job_id: str, request: Request, session=Depends(require_authenticated)):
    if not has_permission(session, "ingestion.run"):
        raise ApiError("forbidden")
    ctx = _scope(session)
    service = _ingestion_service(request)
    if service is None:
        raise ApiError("not_found")
    job = _service_status(service, job_id, ctx)
    if job is None:
        raise ApiError("not_found")
    return _job_envelope(job)


@router.post(
    "/api/v1/ingestion/jobs/{job_id}/retry",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["filename", "content"],
                        "properties": {
                            "filename": {"type": "string", "minLength": 1, "maxLength": 256},
                            "content": {"type": "string", "minLength": 1, "maxLength": 52428800},
                        },
                        "additionalProperties": False,
                    }
                }
            },
        }
    },
)
async def retry_ingestion_job(job_id: str, request: Request, session=Depends(require_authenticated)):
    if not has_permission(session, "ingestion.run"):
        raise ApiError("forbidden")
    ctx = _scope(session)
    service = _ingestion_service(request)
    if service is None:
        raise ApiError("not_found")
    before = _service_status(service, job_id, ctx)
    if before is None:
        raise ApiError("not_found")
    payload = await _request_json(request)
    try:
        retry_payload = RetryRequest.model_validate(payload)
    except Exception:
        raise ApiError("validation_error") from None
    retry_method = getattr(service, "retry", None)
    if not callable(retry_method):
        raise ApiError("conflict")
    request_id, correlation_id = _request_context_values(request)
    try:
        result = await run_in_threadpool(
            retry_method,
            job_id,
            source=retry_payload.content,
            filename=retry_payload.filename,
            tenant_id=ctx["tenant_id"],
            workspace_id=ctx["workspace_id"],
            allowed_collection_ids=ctx.get("allowed_collection_ids", []),
            request_id=request_id,
            correlation_id=correlation_id,
        )
    except Exception as exc:
        _api_ingestion_error(exc)
    if result is None:
        raise ApiError("not_found")
    if not _job_visible(result, ctx):
        raise ApiError("ingestion_failed")
    return _job_envelope(result)


@router.post("/api/v1/ingestion/jobs/{job_id}/cancel")
def cancel_ingestion_job(job_id: str, request: Request, session=Depends(require_authenticated)):
    if not has_permission(session, "ingestion.run"):
        raise ApiError("forbidden")
    ctx = _scope(session)
    service = _ingestion_service(request)
    if service is None:
        raise ApiError("not_found")
    before = _service_status(service, job_id, ctx)
    if before is None:
        raise ApiError("not_found")
    cancel_method = getattr(service, "cancel", None) or getattr(service, "cancel_job", None)
    if not callable(cancel_method):
        raise ApiError("not_found")
    try:
        result = cancel_method(
            job_id,
            tenant_id=ctx["tenant_id"],
            workspace_id=ctx["workspace_id"],
            allowed_collection_ids=ctx.get("allowed_collection_ids", []),
        )
    except TypeError:
        # A legacy cancel signature without the server-derived scope is not a
        # safe compatibility path: invoking it could mutate another tenant's
        # job before any response postcondition can be checked.
        raise ApiError("conflict") from None
    if isinstance(result, bool):
        after = _service_status(service, job_id, ctx) or before
        return _job_envelope(after, cancelled=result)
    if result is None:
        after = _service_status(service, job_id, ctx) or before
        return _job_envelope(after, cancelled=False)
    if not _job_visible(result, ctx):
        raise ApiError("ingestion_failed")
    return _job_envelope(result, cancelled=bool(_job_field(result, "cancelled", False)))
