"""Auth routes — thin HTTP layer over the identity provider."""

from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel, Field
from fastapi.responses import JSONResponse

from core.errors import ApiError, envelope
from core.rate_limit import check_rate_limit, ensure_rate_limiter
from core.security import resolve_session_cookie
from dependencies.identity import get_current_session, require_authenticated
from dependencies.services import get_providers

router = APIRouter(tags=["Auth"])


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=256)
    password: str = Field(min_length=1, max_length=256)
    tenant_id: str = Field(min_length=1, max_length=128)


class RecoveryRequest(BaseModel):
    email: str = Field(min_length=3, max_length=256)
    tenant_id: str | None = Field(default=None, max_length=128)


def _recovery_rate_limiter(providers):
    return ensure_rate_limiter(providers)


def _recovery_rate_allowed(providers, request: Request, payload: RecoveryRequest) -> bool:
    # Hash the composite key so email, tenant and network identity never enter
    # limiter diagnostics or a future shared backend as raw PII.
    client_host = request.client.host if request.client else ""
    raw_key = ":".join(
        (
            "recovery",
            (payload.tenant_id or "").strip(),
            payload.email.strip().casefold(),
            client_host or "",
        )
    )
    key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    try:
        return check_rate_limit(
            _recovery_rate_limiter(providers),
            key,
            limit_per_min=providers.settings.recovery_rate_limit_per_min,
        )
    except TypeError as exc:
        raise ApiError("internal_error") from exc


def _recovery_response(request: Request):
    return JSONResponse(
        status_code=429,
        content=envelope("rate_limited", "Too many requests.", getattr(request.state, "request_id", "unknown")),
        headers={"Retry-After": "60"},
    )


def _public_session(snapshot) -> dict:
    return {
        "authenticated": snapshot.authenticated, "user_id": snapshot.user_id, "email": snapshot.email,
        "role": snapshot.role, "canonical_role": snapshot.canonical_role,
        "tenant_id": snapshot.tenant_id, "workspace_id": snapshot.workspace_id,
        "session_id": snapshot.session_id, "session_token": None,
    }


@router.post("/api/v1/auth/login")
def login(payload: LoginRequest, request: Request, response: Response):
    providers = get_providers(request)
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
    _audit(
        "auth.login",
        snapshot.user_id if hasattr(snapshot, "user_id") else None,
        request,
        tenant_id=getattr(snapshot, "tenant_id", None),
    )
    return _public_session(snapshot)


def _audit(action: str, actor: str | None, request: Request, *, tenant_id: str | None = None) -> None:
    try:
        providers = get_providers(request)
        if providers.audit_sink is not None:
            providers.audit_sink.emit({"action": action, "actor_user_id": actor,  # type: ignore[union-attr]
                                       "request_id": getattr(request.state, "request_id", None),
                                       "tenant_id": tenant_id})  # type: ignore[union-attr]
    except Exception:
        pass


@router.post("/api/v1/auth/logout")
def logout(request: Request, response: Response, session=Depends(get_current_session)):
    providers = get_providers(request)
    token = resolve_session_cookie(request.cookies, providers.settings.session_cookie_name)
    if not token:
        auth = request.headers.get("authorization")
        if auth and auth.startswith("Bearer "):
            token = auth[len("Bearer "):].strip() or None
    providers.identity.logout(token)  # type: ignore[union-attr]
    response.delete_cookie(key=providers.settings.session_cookie_name, path="/")
    _audit("auth.logout", session.user_id, request, tenant_id=session.tenant_id)
    return {"status": "signed_out"}


@router.get("/api/v1/auth/me")
def me(session=Depends(require_authenticated)):
    return _public_session(session)


@router.get("/api/v1/session")
def get_session(session=Depends(require_authenticated)):
    return _public_session(session)


@router.post("/api/v1/auth/recovery")
def recovery(payload: RecoveryRequest, request: Request):
    if not _recovery_rate_allowed(get_providers(request), request, payload):
        return _recovery_response(request)
    # Neutral response whether or not the identity exists.
    return {"status": "queued"}


@router.post("/api/v1/auth/request-password-reset")
def request_reset(payload: RecoveryRequest, request: Request):
    if not _recovery_rate_allowed(get_providers(request), request, payload):
        return _recovery_response(request)
    return {"status": "queued"}


class ConfirmResetRequest(BaseModel):
    token: str = Field(min_length=1, max_length=512)
    new_password: str = Field(min_length=8, max_length=256)


@router.post("/api/v1/auth/confirm-password-reset")
def confirm_reset(payload: ConfirmResetRequest):
    raise ApiError("validation_error", "Invalid or expired reset token.")
