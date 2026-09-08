"""Session self-service routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from core.security import resolve_session_cookie
from dependencies.identity import get_current_session, require_authenticated
from dependencies.services import get_providers
from services.audit import emit_required

router = APIRouter(tags=["Auth"])
_PUBLIC_SESSION_FIELDS = ("session_id", "user_id", "created_at", "revoked")


def _session_field(item: object, name: str, default: object = None) -> object:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _public_session(item: object) -> dict:
    return {
        name: _session_field(item, name)
        for name in _PUBLIC_SESSION_FIELDS
        if _session_field(item, name) is not None
    }


class RevokeRequest(BaseModel):
    session_token: str | None = None
    session_id: str | None = None
    user_id: str | None = None
    revoke_all: bool = False
    reason: str = "manual_revoke"


@router.get("/api/v1/auth/sessions")
def list_sessions(request: Request, session=Depends(require_authenticated)):
    providers = get_providers(request)
    raw_items = providers.identity.list_sessions(session.user_id)  # type: ignore[union-attr]
    items = []
    for item in list(raw_items or []):
        if _session_field(item, "user_id") != session.user_id:
            continue
        if _session_field(item, "tenant_id") != session.tenant_id:
            continue
        public = _public_session(item)
        if public.get("session_id"):
            items.append(public)
    return {"items": items, "total": len(items)}


@router.post("/api/v1/auth/sessions/revoke")
def revoke_sessions(payload: RevokeRequest, request: Request, session=Depends(require_authenticated)):
    from core.errors import ApiError

    if payload.session_token and payload.session_id:
        raise ApiError("validation_error", "Use session_id or session_token, not both.")
    providers = get_providers(request)
    current = resolve_session_cookie(request.cookies, providers.settings.session_cookie_name)
    if not current:
        auth = request.headers.get("authorization")
        if auth and auth.startswith("Bearer "):
            current = auth[len("Bearer "):].strip() or None
    revoked = providers.identity.revoke(  # type: ignore[union-attr]
        actor=session, target_token=payload.session_token or current,
        target_session_id=payload.session_id, target_user_id=payload.user_id, revoke_all=payload.revoke_all,
    )
    emit_required(providers.audit_sink, {
        "action": "auth.session_revoked", "actor_user_id": session.user_id,
        "request_id": getattr(request.state, "request_id", None),
        "tenant_id": session.tenant_id, "workspace_id": session.workspace_id,
    })
    return {"revoked": revoked}
