"""Admin routes — explicit permission per group; skeletons + selected real routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from core.errors import ApiError
from dependencies.identity import require_permission
from dependencies.services import get_providers
from services.audit import emit_required
from services.ingestion_service import safe_job_json

router = APIRouter(tags=["Admin"])
_PUBLIC_USER_FIELDS = (
    "user_id", "email", "role", "canonical_role", "tenant_id", "workspace_id", "status",
    "authorized_collection_ids", "permission_overrides",
)


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
    try:
        scoped_items = list_method(tenant_id=tenant_id, workspace_id=context.get("workspace_id"))
    except TypeError:
        raise ApiError("provider_unavailable") from None
    raw_items = [
        item for item in list(scoped_items or [])
        if _job_field(item, "tenant_id", None) == tenant_id
    ]
    items = [_public_user(item) for item in raw_items]
    return {"items": items, "total": len(items)}


class CreateUserRequest(BaseModel):
    email: str = Field(min_length=3, max_length=256)
    role: str = Field(min_length=1, max_length=64)
    tenant_id: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=256)


def _validated_role(value: str) -> str:
    from rick_authorization import CANONICAL_ROLES, LEGACY_ROLE_ALIASES

    candidate = (value or "").strip().lower()
    canonical = candidate.upper() if candidate.upper() in CANONICAL_ROLES else LEGACY_ROLE_ALIASES.get(candidate)
    if canonical not in CANONICAL_ROLES:
        raise ApiError("validation_error", "Unknown role.")
    return canonical


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
    user = create(email=payload.email, role=_validated_role(payload.role), tenant_id=tenant_id, password=payload.password)
    return {"status": "created", "user": _public_user(user)}


class UpdateUserRequest(BaseModel):
    email: str | None = Field(default=None, min_length=3, max_length=256)
    role: str | None = Field(default=None, min_length=1, max_length=64)
    workspace_id: str | None = Field(default=None, min_length=1, max_length=128)
    authorized_collection_ids: list[str] | None = Field(default=None, max_length=64)
    permission_overrides: dict | None = None


@router.patch("/api/v1/admin/users/{user_id}")
def update_user(user_id: str, payload: UpdateUserRequest, request: Request,
                session=Depends(require_permission("users.manage"))):
    providers = get_providers(request)
    update = getattr(providers.identity, "update_user", None)
    if not callable(update):
        raise ApiError("provider_unavailable")
    values = payload.model_dump(exclude_unset=True)
    if "role" in values and values["role"] is not None:
        values["role"] = _validated_role(values["role"])
    user = update(actor=session, user_id=user_id, **values)
    _audit_admin_event(request, "admin.user_updated", session, user_id)
    return {"status": "updated", "user": _public_user(user)}


@router.post("/api/v1/admin/users/{user_id}/deactivate")
def deactivate_user(user_id: str, request: Request,
                    session=Depends(require_permission("users.manage"))):
    providers = get_providers(request)
    deactivate = getattr(providers.identity, "deactivate_user", None)
    if not callable(deactivate):
        raise ApiError("provider_unavailable")
    revoked = deactivate(actor=session, user_id=user_id)
    _audit_admin_event(request, "admin.user_deactivated", session, user_id)
    return {"status": "disabled", "user_id": user_id, "revoked_sessions": revoked}


class ResetPasswordRequest(BaseModel):
    password: str = Field(min_length=8, max_length=256)


@router.post("/api/v1/admin/users/{user_id}/reset-password")
def reset_user_password(user_id: str, payload: ResetPasswordRequest, request: Request,
                        session=Depends(require_permission("users.manage"))):
    providers = get_providers(request)
    reset = getattr(providers.identity, "reset_password", None)
    if not callable(reset):
        raise ApiError("provider_unavailable")
    revoked = reset(actor=session, user_id=user_id, password=payload.password)
    _audit_admin_event(request, "admin.user_password_reset", session, user_id)
    return {"status": "reset", "user_id": user_id, "revoked_sessions": revoked}


def _audit_admin_event(request: Request, action: str, session, target_id: str) -> None:
    emit_required(get_providers(request).audit_sink, {
        "action": action, "actor_user_id": session.user_id, "target_id": target_id,
        "tenant_id": session.tenant_id, "workspace_id": session.workspace_id,
        "request_id": getattr(request.state, "request_id", None),
    })


@router.get("/api/v1/admin/sessions")
def admin_sessions(request: Request, session=Depends(require_permission("sessions.revoke"))):
    providers = get_providers(request)
    list_method = getattr(providers.identity, "list_sessions_for_actor", None)
    if not callable(list_method):
        raise ApiError("provider_unavailable")
    items = list_method(session)
    return {"items": items[:100], "total": len(items[:100])}


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
        if revoked:
            emit_required(providers.audit_sink, {
                "action": "auth.session_revoked", "actor_user_id": session.user_id,
                "target_id": payload.user_id or payload.session_id,
                "tenant_id": session.tenant_id, "workspace_id": session.workspace_id,
            })
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
                if not getattr(service, "allow_unscoped_legacy_listing", False):
                    raise ApiError("provider_unavailable") from None
                try:
                    raw_items = method(limit=100)
                except TypeError:
                    raw_items = method()
            raw_items = [
                item for item in list(raw_items or [])
                if _job_visible(item, context)
            ]
            items = [safe_job_json(item) for item in list(raw_items or [])[:100]]
    metadata = getattr(service, "runtime_metadata", None) if service is not None else None
    if not isinstance(metadata, dict):
        metadata = {"execution": "unconfigured", "durability": "unconfigured"}
    return {"items": items, "total": len(items), "metadata": dict(metadata)}


@router.get("/api/v1/admin/audit")
def list_audit(request: Request, session=Depends(require_permission("audit.read"))):
    from routes.knowledge import _job_field, _scope
    from services.audit import _ALLOWED_FIELDS

    providers = get_providers(request)
    sink = providers.audit_sink
    context = _scope(session)
    tenant_id = _required_tenant(context)
    list_events = getattr(sink, "list", None)
    if not callable(list_events):
        raise ApiError("provider_unavailable")
    try:
        events = list(list_events(
            limit=50, order="desc", tenant_id=tenant_id,
            workspace_id=context.get("workspace_id"),
        ) or [])
    except (TypeError, ValueError):
        raise ApiError("provider_unavailable") from None
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
def system_info(request: Request, session=Depends(require_permission("runtime.manage"))):
    return {"status": "ok", "version": "1.6.0", "api_version": "v1",
            "runtime": dict(request.app.state.runtime_diagnostics)}
