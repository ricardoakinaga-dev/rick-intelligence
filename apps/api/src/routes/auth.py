"""Auth routes — thin HTTP layer over the identity provider."""

from __future__ import annotations

import hashlib
import inspect
import logging
import secrets
from typing import Literal

from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel, Field
from fastapi.responses import JSONResponse

from core.errors import ApiError, envelope
from core.rate_limit import check_rate_limit_async, ensure_rate_limiter_async, rate_limit_key, server_rate_request_id
from core.security import resolve_session_cookie
from dependencies.identity import get_current_session, require_authenticated
from dependencies.services import Providers, get_providers
from models import SessionSnapshot
from services.audit import emit_required
from services.audit_event import make_audit_event
from services.identity_results import ResetEffect
from services.identity_offload import (
    ensure_identity_operation_current, identity_login_port, identity_offload_options,
    identity_session_port, identity_token_port, run_identity,
)

router = APIRouter(tags=["Auth"])
_logger = logging.getLogger(__name__)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=256)
    password: str = Field(min_length=1, max_length=256)
    tenant_id: str = Field(min_length=1, max_length=128)
    workspace_id: str | None = Field(default=None, min_length=1, max_length=128)


class RecoveryRequest(BaseModel):
    email: str = Field(min_length=3, max_length=256)
    tenant_id: str | None = Field(default=None, max_length=128)


async def _recovery_rate_limiter(providers: Providers, request: Request) -> object:
    return await ensure_rate_limiter_async(providers, **identity_offload_options(request))


async def _public_rate_allowed(limiter: object, request: Request, payload: LoginRequest | RecoveryRequest, *, operation: str, limit: int, tenant_limit: int | None) -> bool:
    # Independent buckets: rotating account/tenant cannot reset the IP window;
    # rotating IP cannot reset the account window. Hash typed segments, not PII.
    tenant = payload.tenant_id.strip() if payload.tenant_id is not None else None
    account = payload.email.strip().casefold()
    host = request.client.host if request.client else ""
    buckets = [(rate_limit_key(operation + ":ip", host), limit),
               (rate_limit_key(operation + ":account", tenant, account), limit)]
    if tenant_limit is not None:
        buckets.append((rate_limit_key(operation + ":tenant", tenant), tenant_limit))
    try:
        for key, ceiling in buckets:
            if not await check_rate_limit_async(limiter, key, limit_per_min=ceiling,
                                                request_id=server_rate_request_id(request),
                                                 **identity_offload_options(request)):
                return False
    except Exception:
        raise ApiError("provider_unavailable") from None
    return True


async def _recovery_rate_allowed(providers: Providers, request: Request, payload: RecoveryRequest) -> bool:
    if providers.settings.environment == "production" and getattr(providers, "rate_limiter", None) is None:
        raise ApiError("provider_unavailable")
    return await _public_rate_allowed(await _recovery_rate_limiter(providers, request), request, payload,
                                     operation="recovery", limit=providers.settings.recovery_rate_limit_per_min,
                                     tenant_limit=providers.settings.recovery_tenant_rate_limit_per_min)


def _recovery_response(request: Request) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content=envelope("rate_limited", "Too many requests.", getattr(request.state, "request_id", "unknown")),
        headers={"Retry-After": "60"},
    )


def _deliver_password_reset(
    providers: Providers,
    payload: RecoveryRequest,
    token: str | None,
    *,
    request_id: str | None = None,
) -> None:
    """Best-effort handoff that never turns account resolution into an oracle."""
    if token is None:
        return
    try:
        delivery = getattr(providers, "password_reset_delivery", None)
        if delivery is None:
            return
        method = getattr(delivery, "deliver_password_reset", None)
        if not callable(method):
            raise TypeError("password reset delivery port is unavailable")
        accepted = method(
            email=payload.email,
            tenant_id=payload.tenant_id,
            token=token,
        )
        if inspect.isawaitable(accepted):
            close = getattr(accepted, "close", None)
            if callable(close):
                close()
            raise TypeError("password reset delivery must complete synchronously")
        if accepted is False:
            raise RuntimeError("password reset delivery rejected the handoff")
    except Exception as exc:
        # Recovery responses stay identical for resolvable and unresolvable
        # accounts, including when an injected delivery port is unhealthy.
        # Do not log the email, tenant, reset token, or exception text.
        _logger.warning(
            "password reset delivery failed request_id=%s error_type=%s",
            request_id if isinstance(request_id, str) and request_id else "unknown",
            type(exc).__name__,
        )


def _issue_password_reset_neutrally(
    identity: object,
    payload: RecoveryRequest,
    *,
    request_id: str | None = None,
) -> str | None:
    """Hide identity-resolution and token-store failures behind the neutral API response."""

    try:
        issue = getattr(identity, "issue_password_reset", None)
        if not callable(issue):
            return None
        token = issue(email=payload.email, tenant_id=payload.tenant_id)
        if token is None:
            return None
        if not isinstance(token, str) or not token.strip() or len(token) > 512:
            raise TypeError("password reset issuer returned an invalid token")
        return token
    except Exception as exc:
        # A lookup/write error for a resolvable account must not distinguish
        # it from an unknown or ambiguous address at this public boundary.
        _logger.warning(
            "password reset issuance failed request_id=%s error_type=%s",
            request_id if isinstance(request_id, str) and request_id else "unknown",
            type(exc).__name__,
        )
        return None


def _reset_handoff(providers: Providers, payload: RecoveryRequest, request_id: str | None) -> None:
    token = _issue_password_reset_neutrally(providers.identity, payload, request_id=request_id)
    _deliver_password_reset(providers, payload, token, request_id=request_id)


def _public_session(snapshot: SessionSnapshot) -> dict[str, object]:
    return {
        "authenticated": snapshot.authenticated, "user_id": snapshot.user_id, "email": snapshot.email,
        "role": snapshot.role, "canonical_role": snapshot.canonical_role,
        "tenant_id": snapshot.tenant_id, "workspace_id": snapshot.workspace_id,
        "session_id": snapshot.session_id, "session_token": None,
        "permissions": list(snapshot.permissions),
    }


async def _login_rate_allowed(providers: Providers, request: Request, payload: LoginRequest) -> bool:
    """Apply login throttling through the app-owned limiter boundary.

    Identity implementations may be external and are not allowed to define a
    process-local fallback for this security control.  Local/test composition
    receives the explicit in-memory limiter; production must inject a shared
    implementation through ``Providers.rate_limiter``.
    """

    configured = getattr(providers, "rate_limiter", None)
    if providers.settings.environment == "production" and configured is None:
        raise ApiError("provider_unavailable")
    allowed = await _public_rate_allowed(await ensure_rate_limiter_async(providers, **identity_offload_options(request)), request, payload,
                                         operation="login", limit=providers.settings.login_rate_limit_per_min,
                                         tenant_limit=providers.settings.login_tenant_rate_limit_per_min)
    if not allowed:
        raise ApiError("rate_limited")
    return True


def _cookie_same_site(value: str) -> Literal["lax", "strict", "none"]:
    if value == "strict":
        return "strict"
    if value == "lax":
        return "lax"
    if value == "none":
        return "none"
    raise ApiError("provider_unavailable")


@router.post("/api/v1/auth/login", response_model=None)
async def login(payload: LoginRequest, request: Request, response: Response) -> dict[str, object]:
    providers = get_providers(request)
    identity = identity_login_port(providers.identity)
    await _login_rate_allowed(providers, request, payload)
    try:
        result = await run_identity(request, identity.login,
            email=payload.email, password=payload.password, tenant_id=payload.tenant_id,
            workspace_id=payload.workspace_id,
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    except ApiError:
        await run_identity(request, _audit, "auth.login_failed", None, request)
        raise
    token = result["session_token"]
    response.set_cookie(
        key=providers.settings.session_cookie_name, value=token, max_age=providers.settings.session_ttl_seconds,
        httponly=True, secure=providers.settings.session_cookie_secure,
        samesite=_cookie_same_site(providers.settings.session_cookie_samesite), path="/",
    )
    # Per-session CSRF nonce (double-submit). This cookie is intentionally
    # NOT HttpOnly so the browser can read it and echo it back in the CSRF
    # header; it is bound to the session lifetime and SameSite=strict.
    csrf_nonce = secrets.token_urlsafe(32)
    response.set_cookie(
        key=providers.settings.csrf_cookie_name, value=csrf_nonce, max_age=providers.settings.session_ttl_seconds,
        httponly=False, secure=providers.settings.session_cookie_secure,
        samesite="strict", path="/",
    )
    snapshot = await run_identity(request, identity.validate_token, token)
    await run_identity(request, _audit,
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
            emitter = getattr(providers.audit_sink, "emit", None)
            if not callable(emitter):
                raise TypeError("audit sink has no emit port")
            emitter({"action": action, "actor_user_id": actor,
                     "request_id": getattr(request.state, "request_id", None),
                     "tenant_id": tenant_id})
    except Exception as exc:
        # Audit failures are operationally significant, but logging must not
        # capture payloads, credentials, tokens, or exception text supplied by
        # an identity/audit backend.
        _logger.warning(
            "auth audit emission failed action=%s request_id=%s error_type=%s",
            action,
            getattr(request.state, "request_id", None),
            type(exc).__name__,
        )


def _clear_session_cookies(response: Response | JSONResponse, providers: Providers) -> None:
    response.delete_cookie(key=providers.settings.session_cookie_name, path="/")
    response.delete_cookie(key=providers.settings.csrf_cookie_name, path="/")


def _indeterminate(request: Request, response: Response | JSONResponse, providers: Providers) -> JSONResponse:
    """The effect may have been applied; never claim signed_out/completed."""
    result = JSONResponse(
        status_code=503,
        content=envelope("result_indeterminate", "", getattr(request.state, "request_id", "unknown")),
    )
    _clear_session_cookies(result, providers)
    return result


def _audit_operation_id(action: str, request_id: str) -> str:
    material = f"{action}\x1f{request_id}".encode("utf-8")
    return f"op-{hashlib.sha256(material).hexdigest()[:32]}"


def _supports_keyword(method: object, name: str) -> bool:
    if not callable(method):
        return False
    try:
        parameters = inspect.signature(method).parameters
    except (TypeError, ValueError):
        return False
    return name in parameters or any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )


def _begin_audit_operation(
    providers: Providers,
    request: Request,
    action: str,
    *,
    tenant_id: str | None = None,
    actor_user_id: str | None = None,
    workspace_id: str | None = None,
) -> str | None:
    store = getattr(providers, "audit_operations", None)
    if store is None:
        return None
    request_id = getattr(request.state, "request_id", None)
    if not isinstance(request_id, str) or not request_id.strip():
        raise ApiError("provider_unavailable")
    operation_id = _audit_operation_id(action, request_id)
    try:
        store.begin(
            operation_id=operation_id,
            action=action,
            request_id=request_id,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            workspace_id=workspace_id,
        )
    except Exception:
        raise ApiError("provider_unavailable") from None
    request.state.audit_operation_id = operation_id
    return operation_id


def _mark_audit_effect(
    providers: Providers,
    operation_id: str | None,
    *,
    user_id: str | None = None,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
) -> bool:
    if not operation_id:
        return True
    store = getattr(providers, "audit_operations", None)
    if store is None:
        return True
    try:
        return bool(store.mark_effect(
            operation_id,
            tenant_id=tenant_id,
            actor_user_id=user_id,
            workspace_id=workspace_id,
        ))
    except Exception:
        return False


def _ack_audit_operation(providers: Providers, operation_id: str | None) -> bool:
    if not operation_id:
        return True
    store = getattr(providers, "audit_operations", None)
    if store is None:
        return True
    try:
        return bool(store.acknowledge(operation_id))
    except Exception:
        return False


def _indeterminate_audit_operation(providers: Providers, operation_id: str | None, code: str) -> None:
    if not operation_id:
        return
    store = getattr(providers, "audit_operations", None)
    if store is None:
        return
    try:
        store.indeterminate(operation_id, code)
    except Exception:
        pass


def _fail_audit_operation(providers: Providers, operation_id: str | None, code: str) -> None:
    if not operation_id:
        return
    store = getattr(providers, "audit_operations", None)
    if store is None:
        return
    try:
        store.fail(operation_id, code)
    except Exception:
        pass


@router.post("/api/v1/auth/logout", response_model=None)
async def logout(request: Request, response: Response, session: SessionSnapshot = Depends(get_current_session)) -> dict[str, str] | JSONResponse:
    try:
        return await run_identity(request, _logout, request, response, session)
    except ApiError as exc:
        # For an authenticated logout, a provider failure leaves the effect
        # unknown (the worker may already have revoked). Do not claim success.
        if exc.code == "provider_unavailable" and session.authenticated:
            raise ApiError("result_indeterminate") from None
        raise


def _logout(request: Request, response: Response, session: SessionSnapshot) -> dict[str, str] | JSONResponse:
    providers = get_providers(request)
    identity = identity_token_port(providers.identity)
    token = resolve_session_cookie(request.cookies, providers.settings.session_cookie_name)
    if not token:
        auth = request.headers.get("authorization")
        if auth and auth.startswith("Bearer "):
            token = auth[len("Bearer "):].strip() or None
    if not session.authenticated:
        # Human-authorized cleanup-only policy: an absent/revoked session is not
        # a new revocation. Never invent a tenant or repair an earlier missing
        # completion record by claiming this no-op was an audited mutation.
        # Revalidate presented tokens: the dependency also maps malformed
        # authenticated-without-tenant snapshots to anonymous.
        if token and identity.validate_token(token).authenticated:
            raise ApiError("provider_unavailable")
        response.delete_cookie(key=providers.settings.session_cookie_name, path="/")
        response.delete_cookie(key=providers.settings.csrf_cookie_name, path="/")
        _logger.info("auth logout cleanup request_id=%s status=no_active_session",
                     getattr(request.state, "request_id", None))
        return {"status": "signed_out"}
    event = make_audit_event(
        "auth.logout",
        actor_user_id=session.user_id,
        request_id=getattr(request.state, "request_id", None),
        tenant_id=session.tenant_id,
        workspace_id=session.workspace_id,
    )
    operation_id = _begin_audit_operation(
        providers, request, "auth.logout",
        tenant_id=session.tenant_id, actor_user_id=session.user_id,
        workspace_id=session.workspace_id,
    )
    ensure_identity_operation_current()
    # The revocation is the effect and must not wait for telemetry. A no-op
    # adapter is not a revocation capability: validate that the authority
    # accepted by this API is gone before writing any effect record.
    identity_session_port(providers.identity).logout(token, operation_id=operation_id)
    if operation_id and not _mark_audit_effect(
        providers, operation_id, user_id=session.user_id,
        tenant_id=session.tenant_id, workspace_id=session.workspace_id,
    ):
        # A provider that cannot enroll the operation still had its effect
        # applied; mark the durable row indeterminate and do not claim success.
        _indeterminate_audit_operation(providers, operation_id, "effect_unknown")
        return _indeterminate(request, response, providers)
    if identity.validate_token(token).authenticated:
        raise ApiError("provider_unavailable")
    # Stage 1: write a non-terminal effect event. `completed` is reserved for
    # an acknowledged terminal outcome (ADR-024); this path never writes it.
    try:
        emit_required(providers.audit_sink, {**event, "status": "effect_applied"})
    except ApiError:
        # Effect applied, audit unconfirmed. Delete the already-dead cookie and
        # answer honestly with a request id; never claim signed_out/completed.
        return _indeterminate(request, response, providers)
    if not _ack_audit_operation(providers, operation_id):
        return _indeterminate(request, response, providers)
    _clear_session_cookies(response, providers)
    return {"status": "signed_out"}


@router.get("/api/v1/auth/me", response_model=None)
def me(session: SessionSnapshot = Depends(require_authenticated)) -> dict[str, object]:
    return _public_session(session)


@router.get("/api/v1/session", response_model=None)
def get_session(session: SessionSnapshot = Depends(require_authenticated)) -> dict[str, object]:
    return _public_session(session)


@router.post("/api/v1/auth/recovery", response_model=None)
async def recovery(payload: RecoveryRequest, request: Request) -> dict[str, str] | JSONResponse:
    providers = get_providers(request)
    if not await _recovery_rate_allowed(providers, request, payload):
        return _recovery_response(request)
    request_id = getattr(request.state, "request_id", None)
    try:
        await run_identity(request, _reset_handoff, providers, payload, request_id)
    except ApiError:
        # Issuance/delivery capacity or timeout must remain as neutral as a
        # lookup/store failure; this response never confirms account existence.
        pass
    # Neutral response whether or not the identity exists.
    return {"status": "queued"}


@router.post("/api/v1/auth/request-password-reset", response_model=None)
async def request_reset(payload: RecoveryRequest, request: Request) -> dict[str, str] | JSONResponse:
    providers = get_providers(request)
    if not await _recovery_rate_allowed(providers, request, payload):
        return _recovery_response(request)
    request_id = getattr(request.state, "request_id", None)
    try:
        await run_identity(request, _reset_handoff, providers, payload, request_id)
    except ApiError:
        # Issuance/delivery capacity or timeout must remain as neutral as a
        # lookup/store failure; this response never confirms account existence.
        pass
    return {"status": "queued"}


class ConfirmResetRequest(BaseModel):
    token: str = Field(min_length=1, max_length=512)
    new_password: str = Field(min_length=8, max_length=256)


def _consume_reset(identity: object, payload: ConfirmResetRequest, providers: Providers, request: Request) -> int:
    # Resolving an injected descriptor/__getattr__ is provider work too. Keep
    # lookup, invocation and result conversion in the same admitted worker.
    ensure_identity_operation_current()
    operation_id = _begin_audit_operation(providers, request, "auth.reset_effect")
    consume = getattr(identity, "consume_password_reset", None)
    ensure_identity_operation_current()
    if not callable(consume):
        raise ApiError("validation_error", "Invalid or expired reset token.")
    if operation_id and _supports_keyword(consume, "operation_id"):
        revoked = consume(token=payload.token, new_password=payload.new_password, operation_id=operation_id)
    else:
        revoked = consume(token=payload.token, new_password=payload.new_password)
    if inspect.isawaitable(revoked):
        close = getattr(revoked, "close", None)
        if callable(close):
            close()
        raise ApiError("provider_unavailable")
    ensure_identity_operation_current()
    if isinstance(revoked, bool):
        raise ApiError("provider_unavailable")
    try:
        value = int(revoked)
    except (TypeError, ValueError):
        raise ApiError("provider_unavailable") from None
    # Conversion and scope extraction stay inside the admitted worker; the
    # route only serializes the already-typed result.
    return ResetEffect(
        value,
        user_id=getattr(revoked, "user_id", None),
        tenant_id=getattr(revoked, "tenant_id", None),
        workspace_id=getattr(revoked, "workspace_id", None),
        operation_id=operation_id,
    )


@router.post("/api/v1/auth/confirm-password-reset", response_model=None)
async def confirm_reset(payload: ConfirmResetRequest, request: Request) -> dict[str, str | int] | JSONResponse:
    providers = get_providers(request)
    if providers.settings.environment == "production" and getattr(providers, "rate_limiter", None) is None:
        raise ApiError("provider_unavailable")
    limiter = await ensure_rate_limiter_async(providers, **identity_offload_options(request))
    # Reuse the approved public recovery budget; independent IP and opaque
    # token buckets do not require resolving (or disclosing) the token owner.
    host = request.client.host if request.client else ""
    try:
        for key in (rate_limit_key("reset-confirm:ip", host),
                    rate_limit_key("reset-confirm:token", payload.token)):
            if not await check_rate_limit_async(limiter, key,
                    limit_per_min=providers.settings.recovery_rate_limit_per_min,
                    request_id=server_rate_request_id(request),
                                                 **identity_offload_options(request)):
                return _recovery_response(request)
    except Exception:
        raise ApiError("provider_unavailable") from None
    try:
        revoked = await run_identity(request, _consume_reset, providers.identity, payload, providers, request)
    except ApiError as exc:
        # The claim transaction may have committed after the caller deadline.
        # Do not claim success or a clean failure; expose an indeterminate
        # outcome with the request id so the caller can verify by signing in.
        if exc.code == "provider_unavailable":
            raise ApiError("result_indeterminate") from None
        if exc.code == "validation_error":
            _fail_audit_operation(providers, getattr(request.state, "audit_operation_id", None), "invalid_token")
        raise
    operation_id = getattr(revoked, "operation_id", None)
    if operation_id and not _supports_keyword(
        getattr(providers.identity, "consume_password_reset", None), "operation_id"
    ):
        if not _mark_audit_effect(
            providers, operation_id,
            user_id=getattr(revoked, "user_id", None),
            tenant_id=getattr(revoked, "tenant_id", None),
            workspace_id=getattr(revoked, "workspace_id", None),
        ):
            _indeterminate_audit_operation(providers, operation_id, "effect_unknown")
            raise ApiError("result_indeterminate") from None
    # The audit sanitizer rejects values containing "password"; the public
    # action name stays credential-neutral.
    event = make_audit_event(
        "auth.reset_effect",
        request_id=getattr(request.state, "request_id", None),
        status="effect_applied",
        user_id=getattr(revoked, "user_id", None),
        tenant_id=getattr(revoked, "tenant_id", None),
        workspace_id=getattr(revoked, "workspace_id", None),
    )
    try:
        emit_required(providers.audit_sink, event)
    except ApiError:
        raise ApiError("result_indeterminate") from None
    if not _ack_audit_operation(providers, operation_id):
        raise ApiError("result_indeterminate") from None
    return {"status": "reset", "revoked_sessions": int(revoked)}
