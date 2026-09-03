"""Session self-service routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from dependencies.identity import get_current_session, require_authenticated
from dependencies.services import get_providers

router = APIRouter(tags=["Auth"])


class RevokeRequest(BaseModel):
    session_token: str | None = None
    session_id: str | None = None
    user_id: str | None = None
    revoke_all: bool = False
    reason: str = "manual_revoke"


@router.get("/api/v1/auth/sessions")
def list_sessions(session=Depends(require_authenticated)):
    providers = get_providers()
    items = providers.identity.list_sessions(session.user_id)  # type: ignore[union-attr]
    return {"items": items, "total": len(items)}


@router.post("/api/v1/auth/sessions/revoke")
def revoke_sessions(payload: RevokeRequest, request: Request, session=Depends(require_authenticated)):
    from core.errors import ApiError

    if payload.session_token and payload.session_id:
        raise ApiError("validation_error", "Use session_id or session_token, not both.")
    providers = get_providers()
    current = request.cookies.get(providers.settings.session_cookie_name)
    if not current:
        auth = request.headers.get("authorization")
        if auth and auth.startswith("Bearer "):
            current = auth[len("Bearer "):].strip() or None
    revoked = providers.identity.revoke(  # type: ignore[union-attr]
        actor=session, target_token=payload.session_token or current,
        target_session_id=payload.session_id, target_user_id=payload.user_id, revoke_all=payload.revoke_all,
    )
    try:
        if providers.audit_sink is not None:
            providers.audit_sink.emit({"action": "auth.session_revoked", "actor_user_id": session.user_id,  # type: ignore[union-attr]
                                       "request_id": getattr(request.state, "request_id", None)})
    except Exception:
        pass
    return {"revoked": revoked}
