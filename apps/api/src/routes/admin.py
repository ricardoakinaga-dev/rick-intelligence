"""Admin routes — explicit permission per group; skeletons + selected real routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from core.errors import ApiError
from dependencies.identity import require_permission
from dependencies.services import get_providers

router = APIRouter(tags=["Admin"])


@router.get("/api/v1/admin/users")
def list_users(session=Depends(require_permission("users.manage"))):
    providers = get_providers()
    identity = providers.identity
    users = getattr(identity, "_users", {})
    items = [{"user_id": u["user_id"], "email": u["email"], "role": u["role"]} for u in users.values()] \
        if isinstance(users, dict) else []
    return {"items": items, "total": len(items)}


class CreateUserRequest(BaseModel):
    email: str = Field(min_length=3, max_length=256)
    role: str = Field(min_length=1, max_length=64)
    tenant_id: str = Field(default="default", max_length=128)


@router.post("/api/v1/admin/users", status_code=201)
def create_user(payload: CreateUserRequest, session=Depends(require_permission("users.manage"))):
    return {"status": "created", "email": payload.email, "role": payload.role}


@router.get("/api/v1/admin/sessions")
def admin_sessions(session=Depends(require_permission("sessions.revoke"))):
    return {"items": [], "total": 0}


class AdminRevokeRequest(BaseModel):
    user_id: str | None = None
    session_id: str | None = None
    revoke_all: bool = False


@router.post("/api/v1/admin/sessions/revoke")
def admin_revoke(payload: AdminRevokeRequest, session=Depends(require_permission("sessions.revoke"))):
    providers = get_providers()
    try:
        if providers.audit_sink is not None:
            providers.audit_sink.emit({"action": "auth.session_revoked", "actor_user_id": session.user_id,  # type: ignore[union-attr]
                                       "target_id": payload.user_id or payload.session_id})
    except Exception:
        pass
    return {"revoked": 0}


@router.get("/api/v1/admin/roles")
def list_roles(session=Depends(require_permission("users.manage"))):
    return {"items": ["PLATFORM_ADMIN", "KNOWLEDGE_MANAGER", "VETERINARIAN"], "total": 3}


@router.get("/api/v1/admin/jobs")
def list_jobs(session=Depends(require_permission("runtime.manage"))):
    return {"items": [], "total": 0}


@router.get("/api/v1/admin/audit")
def list_audit(session=Depends(require_permission("audit.read"))):
    providers = get_providers()
    sink = providers.audit_sink
    events = list(getattr(sink, "events", []) or [])[-50:]
    # Never expose secrets: audit events are already sanitized at emission.
    return {"items": events, "total": len(events)}


@router.get("/api/v1/admin/system")
def system_info(session=Depends(require_permission("runtime.manage"))):
    return {"status": "ok", "version": "1.3.0", "api_version": "v1"}
