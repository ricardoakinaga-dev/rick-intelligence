"""Admin routes — explicit permission per group; skeletons + selected real routes."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from core.errors import ApiError
from dependencies.identity import require_permission
from dependencies.services import get_providers
from services.audit import emit_required
from services.audit_operations import run_operation, admin_reset_in_transaction, admin_revoke_in_transaction, admin_update_in_transaction, admin_mutation_in_transaction, admin_owner_transaction
from services.ingestion_service import safe_job_json

router = APIRouter(tags=["Admin"])
_PUBLIC_USER_FIELDS = (
    "user_id", "email", "role", "canonical_role", "tenant_id", "workspace_id", "status",
    "membership_status", "authorized_collection_ids", "permission_overrides",
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
    return tenant_id.strip()


def _required_workspace(context: dict) -> str:
    workspace_id = context.get("workspace_id")
    if (
        not isinstance(workspace_id, str)
        or not workspace_id.strip()
        or len(workspace_id.strip()) > 128
    ):
        raise ApiError("forbidden")
    return workspace_id.strip()


def _validate_update_scope(context: dict, values: dict) -> None:
    """Reject unscoped PATCHes before invoking either identity backend."""
    tenant_id = _required_tenant(context)
    workspace_id = _required_workspace(context)
    if values.get("tenant_id") is not None and values["tenant_id"].strip() != tenant_id:
        raise ApiError("forbidden")
    requested_workspace = values.get("workspace_id")
    if requested_workspace is not None:
        if (
            not isinstance(requested_workspace, str)
            or not requested_workspace.strip()
            or len(requested_workspace.strip()) > 128
            or requested_workspace.strip() != workspace_id
        ):
            raise ApiError("forbidden")


def _validate_target_scope(identity: object, context: dict, user_id: str) -> None:
    """Reject a target outside the actor's exact membership before audit emission."""
    check = getattr(identity, "admin_target_in_scope", None)
    if not callable(check):
        raise ApiError("provider_unavailable")
    if not check(
        user_id=user_id,
        tenant_id=_required_tenant(context),
        workspace_id=_required_workspace(context),
    ):
        raise ApiError("forbidden")


def _require_atomic_admin_audit(
    identity: object,
    atomic_method: object,
    *,
    environment: str | None,
) -> None:
    """Permit fallback only for an explicitly volatile development identity."""
    if getattr(identity, "supports_atomic_admin_audit", False) is True:
        if callable(atomic_method):
            return
        raise ApiError("provider_unavailable")
    mode = getattr(identity, "mode", None)
    mode = mode.strip().lower() if isinstance(mode, str) else None
    environment = environment.strip().lower() if isinstance(environment, str) else None
    if (
        getattr(identity, "durable_admin_mutations", None) is False
        and getattr(identity, "production_safe", None) is False
        and mode in {"dev", "test"}
        and environment in {"local", "dev", "test"}
    ):
        return
    raise ApiError("provider_unavailable")


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


@router.post(
    "/api/v1/admin/users",
    status_code=201,
    responses={202: {"description": "User committed; check audit_status for reconciliation or manual review."}},
)
def create_user(payload: CreateUserRequest, request: Request, session=Depends(require_permission("users.manage"))):
    from routes.knowledge import _scope

    providers = get_providers(request)
    identity = providers.identity
    atomic_create = getattr(identity, "admin_create_user", None)
    _require_atomic_admin_audit(
        identity, atomic_create,
        environment=getattr(getattr(providers, "settings", None), "environment", None),
    )
    create = getattr(providers.identity, "create_user", None)
    if not callable(atomic_create) and not callable(create):
        raise ApiError("provider_unavailable")
    context = _scope(session)
    tenant_id = _required_tenant(context)
    if payload.tenant_id.strip() != tenant_id:
        raise ApiError("forbidden")
    role = _validated_role(payload.role)
    transaction = admin_owner_transaction(identity, session)
    return run_operation(request=request, session=session, action="admin.user_created",
        target_id=None, inputs=payload.model_dump(), owner=identity,
        success_status=202 if callable(getattr(identity, "audit_connection_factory", None)) else None,
        transaction=transaction, callback=lambda connection: {
            "status": "created", "user": _public_user(admin_mutation_in_transaction(
                identity, action="create_user", actor=session, connection=connection,
                email=payload.email, role=role, tenant_id=tenant_id, password=payload.password)),
        })



class PermissionOverridesRequest(BaseModel):
    """Closed wire shape for additive/removal permission overrides."""

    model_config = ConfigDict(extra="forbid")
    add: list[str] = Field(default_factory=list, max_length=128)
    remove: list[str] = Field(default_factory=list, max_length=128)


class UpdateUserRequest(BaseModel):
    email: str | None = Field(default=None, min_length=3, max_length=256)
    role: str | None = Field(default=None, min_length=1, max_length=64)
    workspace_id: str | None = Field(default=None, min_length=1, max_length=128)
    authorized_collection_ids: list[str] | None = Field(default=None, max_length=64)
    permission_overrides: PermissionOverridesRequest | None = None


@router.patch(
    "/api/v1/admin/users/{user_id}",
    responses={202: {"description": "User committed; check audit_status for reconciliation or manual review."}},
)
def update_user(user_id: str, payload: UpdateUserRequest, request: Request,
                session=Depends(require_permission("users.manage"))):
    providers = get_providers(request)
    identity = providers.identity
    atomic_update = getattr(identity, "admin_update_user", None)
    _require_atomic_admin_audit(
        identity, atomic_update,
        environment=getattr(getattr(providers, "settings", None), "environment", None),
    )
    update = getattr(providers.identity, "update_user", None)
    if not callable(atomic_update) and not callable(update):
        raise ApiError("provider_unavailable")
    from routes.knowledge import _scope

    values = payload.model_dump(exclude_unset=True)
    context = _scope(session)
    _validate_update_scope(context, values)
    _validate_target_scope(identity, context, user_id)
    if "role" in values and values["role"] is not None:
        values["role"] = _validated_role(values["role"])
    transaction = admin_owner_transaction(identity, session)
    return run_operation(request=request, session=session, action="admin.user_updated",
        target_id=user_id, inputs=values, owner=identity,
        success_status=202 if callable(getattr(identity, "audit_connection_factory", None)) else None,
        transaction=transaction, callback=lambda connection: {
            "status": "updated", "user": _public_user(admin_update_in_transaction(
                identity, actor=session, user_id=user_id, values=values, connection=connection)),
        })


@router.post(
    "/api/v1/admin/users/{user_id}/deactivate",
    responses={202: {"description": "User disabled; check audit_status for reconciliation or manual review."}},
)
def deactivate_user(user_id: str, request: Request,
                    session=Depends(require_permission("users.manage"))):
    providers = get_providers(request)
    identity = providers.identity
    atomic_deactivate = getattr(identity, "admin_deactivate_user", None)
    _require_atomic_admin_audit(
        identity, atomic_deactivate,
        environment=getattr(getattr(providers, "settings", None), "environment", None),
    )
    deactivate = getattr(providers.identity, "deactivate_user", None)
    if not callable(atomic_deactivate) and not callable(deactivate):
        raise ApiError("provider_unavailable")
    from routes.knowledge import _scope

    _validate_target_scope(identity, _scope(session), user_id)
    transaction = admin_owner_transaction(identity, session)
    return run_operation(request=request, session=session, action="admin.user_deactivated",
        target_id=user_id, inputs={}, owner=identity,
        success_status=202 if callable(getattr(identity, "audit_connection_factory", None)) else None,
        transaction=transaction, callback=lambda connection: {
            "status": "disabled", "user_id": user_id,
            "revoked_sessions": admin_mutation_in_transaction(identity, action="deactivate_user",
                actor=session, user_id=user_id, connection=connection),
        })



class ResetPasswordRequest(BaseModel):
    password: str = Field(min_length=8, max_length=256)


@router.post(
    "/api/v1/admin/users/{user_id}/reset-password",
    responses={202: {"description": "Credentials reset; check audit_status for reconciliation or manual review."}},
)
def reset_user_password(user_id: str, payload: ResetPasswordRequest, request: Request,
                        session=Depends(require_permission("users.manage"))):
    providers = get_providers(request)
    identity = providers.identity
    atomic_reset = getattr(identity, "admin_reset_password", None)
    _require_atomic_admin_audit(
        identity, atomic_reset,
        environment=getattr(getattr(providers, "settings", None), "environment", None),
    )
    transaction = getattr(identity, "audit_transaction", None)
    if not callable(transaction):
        raise ApiError("provider_unavailable")
    from routes.knowledge import _scope

    _validate_target_scope(identity, _scope(session), user_id)
    return run_operation(request=request, session=session, action="admin.user_access_reset",
        target_id=user_id, inputs=payload.model_dump(), owner=identity,
        transaction=lambda: transaction(session), callback=lambda connection: {
            "status": "reset", "user_id": user_id,
            "revoked_sessions": admin_reset_in_transaction(identity, actor=session,
                user_id=user_id, password=payload.password, connection=connection),
        })


def _audit_admin_event(request: Request, action: str, session, target_id: str | None,
                       *, status: str) -> None:
    emit_required(get_providers(request).audit_sink, {
        "action": action, "actor_user_id": session.user_id, "target_id": target_id,
        "tenant_id": session.tenant_id, "workspace_id": session.workspace_id,
        "request_id": getattr(request.state, "request_id", None), "status": status,
    })


def _atomic_admin_response(request: Request, event_id: str, result: dict):
    return JSONResponse(status_code=202, content={
        **result,
        "audit_status": "pending",
        "audit_event_id": event_id,
        "reconciliation_required": True,
        "request_id": getattr(request.state, "request_id", None),
    })


class _ManualReviewAdminEvent(BaseModel):
    action: str
    actor_user_id: str
    target_id: str | None
    tenant_id: str
    workspace_id: str | None
    request_id: str | None
    status: Literal["manual_review_required"] = "manual_review_required"
    reason: Literal["completion_audit_unavailable"] = "completion_audit_unavailable"


def _register_manual_review_event(request: Request, action: str, session, target_id: str | None) -> bool:
    from services.postgres_audit import PostgresAuditSink
    from services.sqlite_audit import SQLiteAuditSink

    sink = get_providers(request).audit_sink
    if not isinstance(sink, (SQLiteAuditSink, PostgresAuditSink)):
        return False
    if isinstance(sink, SQLiteAuditSink) and sink.path == ":memory:":
        return False
    try:
        pending = _ManualReviewAdminEvent(
            action=action, actor_user_id=session.user_id, target_id=target_id,
            tenant_id=session.tenant_id, workspace_id=session.workspace_id,
            request_id=getattr(request.state, "request_id", None),
        )
        return sink.append(pending.model_dump()) is True
    except Exception:
        return False


def _audit_admin_result(request: Request, action: str, session, target_id: str | None,
                        result: dict):
    try:
        _audit_admin_event(request, action, session, target_id, status="completed")
    except ApiError as exc:
        if exc.code != "provider_unavailable":
            raise
        registered = _register_manual_review_event(request, action, session, target_id)
        return JSONResponse(status_code=202, content={
            **result,
            "audit_status": "manual_review_required" if registered else "registration_failed",
            "reconciliation_required": True,
            "request_id": getattr(request.state, "request_id", None),
        })
    return result


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
    identity = providers.identity
    transaction = admin_owner_transaction(identity, session)
    if not callable(getattr(identity, "revoke_in_transaction", None)):
        raise ApiError("provider_unavailable")
    return run_operation(request=request, session=session, action="auth.session_revoked",
        target_id=payload.user_id or payload.session_id, inputs=payload.model_dump(), owner=identity,
        transaction=transaction, callback=lambda connection: {
            "revoked": int(admin_revoke_in_transaction(identity, actor=session,
                user_id=payload.user_id, session_id=payload.session_id,
                revoke_all=payload.revoke_all, connection=connection)),
        })


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


@router.get("/api/v1/admin/audit/{event_id}/status")
def admin_audit_status(
    event_id: str,
    request: Request,
    session=Depends(require_permission("audit.read")),
):
    get_status = getattr(get_providers(request).identity, "get_admin_audit_status", None)
    if not callable(get_status):
        raise ApiError("provider_unavailable")
    status = get_status(actor=session, event_id=event_id)
    if status is None:
        raise ApiError("not_found")
    return status


@router.post("/api/v1/admin/audit/{event_id}/retry")
def retry_admin_audit(
    event_id: str,
    request: Request,
    session=Depends(require_permission("users.manage")),
):
    retry = getattr(get_providers(request).identity, "retry_admin_audit_event", None)
    if not callable(retry):
        raise ApiError("provider_unavailable")
    if retry(actor=session, event_id=event_id) is not True:
        raise ApiError("conflict", "The audit event is not eligible for another retry.")
    return {"event_id": event_id, "status": "pending", "accepted": True}


@router.get("/api/v1/admin/system")
def system_info(request: Request, session=Depends(require_permission("runtime.manage"))):
    return {"status": "ok", "version": "1.6.0", "api_version": "v1",
            "runtime": dict(request.app.state.runtime_diagnostics)}
