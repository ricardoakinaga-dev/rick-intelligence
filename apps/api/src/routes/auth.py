"""Auth routes — thin HTTP layer over the identity provider."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel, Field

from core.errors import ApiError
from dependencies.identity import get_current_session, require_authenticated
from dependencies.services import get_providers

router = APIRouter(tags=["Auth"])


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=256)
    password: str = Field(min_length=1, max_length=256)
    tenant_id: str = Field(default="default", max_length=128)


class RecoveryRequest(BaseModel):
    email: str = Field(min_length=3, max_length=256)
    tenant_id: str | None = Field(default=None, max_length=128)


def _public_session(snapshot) -> dict:
    return {
        "authenticated": snapshot.authenticated, "user_id": snapshot.user_id, "email": snapshot.email,
        "role": snapshot.role, "canonical_role": snapshot.canonical_role,
        "tenant_id": snapshot.tenant_id, "workspace_id": snapshot.workspace_id,
        "session_id": snapshot.session_id, "session_token": None,
    }


@router.post("/api/v1/auth/login")
def login(payload: LoginRequest, request: Request, response: Response):
    providers = get_providers()
    identity = providers.identity
    # Rate limit (in-process default; Redis-backed interface ready).
    check = getattr(identity, "check_login_rate", None)
    if check is not None:
        check(f"login:{payload.email.lower()}", limit_per_min=providers.settings.login_rate_limit_per_min)
    try:
        result = identity.login(  # type: ignore[union-attr]
            email=payload.email, password=payload.password, tenant_id=payload.tenant_id,
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    except ApiError:
        _audit("auth.login_failed", None, request)
        raise
    token = result["session_token"]
    response.set_cookie(
        key=providers.settings.session_cookie_name, value=token, max_age=8 * 3600,
        httponly=True, secure=providers.settings.session_cookie_secure,
        samesite=providers.settings.session_cookie_samesite, path="/",
    )
    snapshot = identity.validate_token(token)  # type: ignore[union-attr]
    _audit("auth.login", snapshot.user_id if hasattr(snapshot, "user_id") else None, request)
    return _public_session(snapshot)


def _audit(action: str, actor: str | None, request: Request) -> None:
    try:
        providers = get_providers()
        if providers.audit_sink is not None:
            providers.audit_sink.emit({"action": action, "actor_user_id": actor,  # type: ignore[union-attr]
                                       "request_id": getattr(request.state, "request_id", None)})  # type: ignore[union-attr]
    except Exception:
        pass


@router.post("/api/v1/auth/logout")
def logout(request: Request, response: Response, session=Depends(get_current_session)):
    providers = get_providers()
    token = request.cookies.get(providers.settings.session_cookie_name)
    if not token:
        auth = request.headers.get("authorization")
        if auth and auth.startswith("Bearer "):
            token = auth[len("Bearer "):].strip() or None
    providers.identity.logout(token)  # type: ignore[union-attr]
    response.delete_cookie(key=providers.settings.session_cookie_name, path="/")
    _audit("auth.logout", session.user_id, request)
    return {"status": "signed_out"}


@router.get("/api/v1/auth/me")
def me(session=Depends(require_authenticated)):
    return _public_session(session)


@router.get("/api/v1/session")
def get_session(session=Depends(require_authenticated)):
    return _public_session(session)


@router.post("/api/v1/auth/recovery")
def recovery(payload: RecoveryRequest):
    # Neutral response whether or not the identity exists.
    return {"status": "queued"}


@router.post("/api/v1/auth/request-password-reset")
def request_reset(payload: RecoveryRequest):
    return {"status": "queued"}


class ConfirmResetRequest(BaseModel):
    token: str = Field(min_length=1, max_length=512)
    new_password: str = Field(min_length=8, max_length=256)


@router.post("/api/v1/auth/confirm-password-reset")
def confirm_reset(payload: ConfirmResetRequest):
    raise ApiError("validation_error", "Invalid or expired reset token.")
