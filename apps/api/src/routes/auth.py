"""Auth routes — thin HTTP layer over the identity provider."""

from __future__ import annotations

import hashlib
import inspect

from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel, Field
from fastapi.responses import JSONResponse

from core.errors import ApiError, envelope
from core.rate_limit import check_rate_limit, ensure_rate_limiter
from core.security import resolve_session_cookie
from dependencies.identity import get_current_session, require_authenticated
from dependencies.services import get_providers
from services.audit import emit_required

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


def _deliver_password_reset(providers, payload: RecoveryRequest, token: str | None) -> None:
    """Hand a reset token to an injected delivery port without returning it."""
    delivery = getattr(providers, "password_reset_delivery", None)
    if delivery is None or token is None:
        return
    method = getattr(delivery, "deliver_password_reset", None)
    if not callable(method):
        raise ApiError("provider_unavailable")
    try:
        accepted = method(
            email=payload.email,
            tenant_id=payload.tenant_id,
            token=token,
        )
        if inspect.isawaitable(accepted) or accepted is False:
            raise ApiError("provider_unavailable")
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError("provider_unavailable") from exc


def _public_session(snapshot) -> dict:
    return {
        "authenticated": snapshot.authenticated, "user_id": snapshot.user_id, "email": snapshot.email,
        "role": snapshot.role, "canonical_role": snapshot.canonical_role,
        "tenant_id": snapshot.tenant_id, "workspace_id": snapshot.workspace_id,
        "session_id": snapshot.session_id, "session_token": None,
        "permissions": list(snapshot.permissions),
    }


def _login_rate_allowed(providers, request: Request, payload: LoginRequest) -> bool:
    """Apply login throttling through the app-owned limiter boundary.

    Identity implementations may be external and are not allowed to define a
    process-local fallback for this security control.  Local/test composition
    receives the explicit in-memory limiter; production must inject a shared
    implementation through ``Providers.rate_limiter``.
    """

    configured = getattr(providers, "rate_limiter", None)
    if providers.settings.environment == "production" and configured is None:
        raise ApiError("provider_unavailable")
    raw_key = ":".join(
        (
            "login",
            payload.tenant_id.strip(),
            payload.email.strip().casefold(),
            (request.client.host if request.client else None) or "",
        )
    )
    key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    try:
        allowed = check_rate_limit(
            ensure_rate_limiter(providers),
            key,
            limit_per_min=providers.settings.login_rate_limit_per_min,
        )
    except TypeError as exc:
        raise ApiError("provider_unavailable") from exc
    if not allowed:
        raise ApiError("rate_limited")
    return True


@router.post("/api/v1/auth/login")
def login(payload: LoginRequest, request: Request, response: Response):
    providers = get_providers(request)
    identity = providers.identity
    _login_rate_allowed(providers, request, payload)
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
    emit_required(providers.audit_sink, {
        "action": "auth.logout", "actor_user_id": session.user_id,
        "request_id": getattr(request.state, "request_id", None),
        "tenant_id": session.tenant_id, "workspace_id": session.workspace_id,
    })
    providers.identity.logout(token)  # type: ignore[union-attr]
    response.delete_cookie(key=providers.settings.session_cookie_name, path="/")
    return {"status": "signed_out"}


@router.get("/api/v1/auth/me")
def me(session=Depends(require_authenticated)):
    return _public_session(session)


@router.get("/api/v1/session")
def get_session(session=Depends(require_authenticated)):
    return _public_session(session)


@router.post("/api/v1/auth/recovery")
def recovery(payload: RecoveryRequest, request: Request):
    providers = get_providers(request)
    if not _recovery_rate_allowed(providers, request, payload):
        return _recovery_response(request)
    issue = getattr(providers.identity, "issue_password_reset", None)
    if callable(issue):
        token = issue(email=payload.email, tenant_id=payload.tenant_id)
        _deliver_password_reset(providers, payload, token)
    # Neutral response whether or not the identity exists.
    return {"status": "queued"}


@router.post("/api/v1/auth/request-password-reset")
def request_reset(payload: RecoveryRequest, request: Request):
    providers = get_providers(request)
    if not _recovery_rate_allowed(providers, request, payload):
        return _recovery_response(request)
    issue = getattr(providers.identity, "issue_password_reset", None)
    if callable(issue):
        token = issue(email=payload.email, tenant_id=payload.tenant_id)
        _deliver_password_reset(providers, payload, token)
    return {"status": "queued"}


class ConfirmResetRequest(BaseModel):
    token: str = Field(min_length=1, max_length=512)
    new_password: str = Field(min_length=8, max_length=256)


@router.post("/api/v1/auth/confirm-password-reset")
def confirm_reset(payload: ConfirmResetRequest, request: Request):
    consume = getattr(get_providers(request).identity, "consume_password_reset", None)
    if not callable(consume):
        raise ApiError("validation_error", "Invalid or expired reset token.")
    revoked = consume(token=payload.token, new_password=payload.new_password)
    return {"status": "reset", "revoked_sessions": int(revoked)}
