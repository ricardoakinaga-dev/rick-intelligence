"""Admin routes — explicit permission per group; skeletons + selected real routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from core.errors import ApiError
from dependencies.identity import require_permission
from dependencies.services import get_providers
from services.ingestion_service import safe_job_json

router = APIRouter(tags=["Admin"])
_PUBLIC_USER_FIELDS = ("user_id", "email", "role", "canonical_role", "tenant_id", "workspace_id", "status")


def _public_user(item: object) -> dict:
    if isinstance(item, dict):
        return {key: item[key] for key in _PUBLIC_USER_FIELDS if key in item}
    return {
        key: getattr(item, key)
        for key in _PUBLIC_USER_FIELDS
        if getattr(item, key, None) is not None
    }


def _required_tenant(context: dict) -> str:
    tenant_id = context.get("tenant_id")
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ApiError("forbidden")
    return tenant_id


@router.get("/api/v1/admin/users")
def list_users(request: Request, session=Depends(require_permission("users.manage"))):
    from routes.knowledge import _job_field, _scope

    providers = get_providers(request)
    identity = providers.identity
    list_method = getattr(identity, "list_users", None)
    if not callable(list_method):
        raise ApiError("provider_unavailable")
    context = _scope(session)
    tenant_id = _required_tenant(context)
    raw_items = [
        item for item in list(list_method() or [])
        if _job_field(item, "tenant_id", None) == tenant_id
    ]
    items = [_public_user(item) for item in raw_items]
    return {"items": items, "total": len(items)}


class CreateUserRequest(BaseModel):
    email: str = Field(min_length=3, max_length=256)
    role: str = Field(min_length=1, max_length=64)
    tenant_id: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=256)


@router.post("/api/v1/admin/users", status_code=201)
def create_user(payload: CreateUserRequest, request: Request, session=Depends(require_permission("users.manage"))):
    from routes.knowledge import _scope

    providers = get_providers(request)
    create = getattr(providers.identity, "create_user", None)
    if not callable(create):
        raise ApiError("provider_unavailable")
    context = _scope(session)
    tenant_id = _required_tenant(context)
    if payload.tenant_id.strip() != tenant_id:
        raise ApiError("forbidden")
    user = create(email=payload.email, role=payload.role, tenant_id=tenant_id, password=payload.password)
    return {"status": "created", "user": _public_user(user)}


@router.get("/api/v1/admin/sessions")
def admin_sessions(session=Depends(require_permission("sessions.revoke"))):
    return {"items": [], "total": 0}


class AdminRevokeRequest(BaseModel):
    user_id: str | None = None
    session_id: str | None = None
    revoke_all: bool = False


@router.post("/api/v1/admin/sessions/revoke")
def admin_revoke(payload: AdminRevokeRequest, request: Request, session=Depends(require_permission("sessions.revoke"))):
    providers = get_providers(request)
    if not payload.user_id and not payload.session_id:
        raise ApiError("validation_error")
    try:
        revoke_by_id = getattr(providers.identity, "revoke_session_by_id", None)
        if payload.session_id and not payload.user_id and callable(revoke_by_id):
            revoked = int(revoke_by_id(actor=session, session_id=payload.session_id))
        else:
            revoke = getattr(providers.identity, "revoke", None)
            if not callable(revoke):
                raise ApiError("provider_unavailable")
            revoked = int(revoke(
                actor=session,
                target_token=None,
                target_session_id=payload.session_id,
                target_user_id=payload.user_id,
                revoke_all=payload.revoke_all,
            ))
        if providers.audit_sink is not None and revoked:
            providers.audit_sink.emit({"action": "auth.session_revoked", "actor_user_id": session.user_id,  # type: ignore[union-attr]
                                       "target_id": payload.user_id or payload.session_id,
                                       "tenant_id": session.tenant_id})
    except ApiError:
        raise
    except Exception:
        raise ApiError("provider_unavailable") from None
    return {"revoked": revoked}


@router.get("/api/v1/admin/roles")
def list_roles(session=Depends(require_permission("users.manage"))):
    return {"items": ["PLATFORM_ADMIN", "KNOWLEDGE_MANAGER", "VETERINARIAN"], "total": 3}


@router.get("/api/v1/admin/jobs")
def list_jobs(request: Request, session=Depends(require_permission("runtime.manage"))):
    # Lifecycle state is injected by the integrator.  Keep the unconfigured
    # fallback empty, but never manufacture job data here.
    from routes.knowledge import _ingestion_service, _job_field, _job_visible, _scope

    service = _ingestion_service(request)
    if service is None:
        items = []
    else:
        method = getattr(service, "list_jobs", None)
        if not callable(method):
            items = []
        else:
            context = _scope(session)
            tenant_id = _required_tenant(context)
            try:
                raw_items = method(
                    tenant_id=tenant_id,
                    workspace_id=context["workspace_id"],
                    allowed_collection_ids=context.get("allowed_collection_ids", []),
                    limit=100,
                )
            except TypeError:
                try:
                    raw_items = method(limit=100)
                except TypeError:
                    raw_items = method()
            raw_items = [
                item for item in list(raw_items or [])
                if _job_visible(item, context)
            ]
            items = [safe_job_json(item) for item in list(raw_items or [])[:100]]
    return {"items": items, "total": len(items), "metadata": {"execution": "process-local", "durability": "process-local"}}


@router.get("/api/v1/admin/audit")
def list_audit(request: Request, session=Depends(require_permission("audit.read"))):
    from routes.knowledge import _job_field, _scope
    from services.audit import _ALLOWED_FIELDS

    providers = get_providers(request)
    sink = providers.audit_sink
    context = _scope(session)
    tenant_id = _required_tenant(context)
    list_events = getattr(sink, "list", None)
    if callable(list_events):
        try:
            events = list(list_events(limit=50, order="desc") or [])
        except (TypeError, ValueError):
            events = []
    else:
        events = list(getattr(sink, "events", []) or [])[-50:]
    events = [
        {
            key: event[key]
            for key in _ALLOWED_FIELDS
            if isinstance(event, dict) and key in event
        }
        for event in events
        if _job_field(event, "tenant_id", None) == tenant_id
    ]
    # Never expose secrets: sinks sanitize at emission and this route applies
    # an allowlist plus the server-derived tenant boundary before returning the
    # bounded view. Events without an explicit tenant are not tenant-visible.
    return {"items": events, "total": len(events)}


@router.get("/api/v1/admin/system")
def system_info(session=Depends(require_permission("runtime.manage"))):
    return {"status": "ok", "version": "1.6.0", "api_version": "v1"}
