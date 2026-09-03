"""Identity + authorization FastAPI dependencies (centralized auth boundary)."""

from __future__ import annotations

from fastapi import Cookie, Depends, Header, Request

from core.errors import ApiError
from core.security import resolve_auth_precedence
from dependencies.services import get_providers
from models import SessionSnapshot


def _extract_bearer(authorization: str | None) -> str | None:
    if authorization and authorization.startswith("Bearer "):
        token = authorization[len("Bearer "):].strip()
        return token or None
    return None


async def get_current_session(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
    session_cookie: str | None = Cookie(default=None),
) -> SessionSnapshot:
    """Central session resolution. Cookie wins over Bearer (see security.resolve_auth_precedence)."""
    # Resolve cookie name from settings (default cookie if client used generic name).
    providers = get_providers()
    settings = providers.settings
    cookie_token = session_cookie
    # FastAPI Cookie(default=None) without alias captures nothing; read raw cookies manually.
    if not cookie_token:
        cookie_token = request.cookies.get(settings.session_cookie_name)
    bearer_token = _extract_bearer(authorization)
    token, _source = resolve_auth_precedence(cookie_token, bearer_token)
    identity = providers.identity
    snapshot = identity.validate_token(token)  # type: ignore[union-attr]
    # Attach server-derived identity to request context for logs/audit.
    ctx = getattr(request.state, "request_context", None)
    if ctx is not None and snapshot.authenticated:
        from dataclasses import replace

        request.state.request_context = replace(
            ctx, user_id=snapshot.user_id, session_id=snapshot.session_id,
            workspace_id=snapshot.workspace_id, tenant_id=snapshot.tenant_id,
        )
        from core.request_context import set_current

        set_current(request.state.request_context)
    return snapshot


def require_authenticated(session: SessionSnapshot = Depends(get_current_session)) -> SessionSnapshot:
    if not session.authenticated or session.session_state != "active":
        raise ApiError("unauthorized")
    return session


def require_permission(permission: str, *, target_type: str = "permission"):
    async def _dep(
        request: Request, session: SessionSnapshot = Depends(get_current_session)
    ) -> SessionSnapshot:
        if not session.authenticated or session.session_state != "active":
            raise ApiError("unauthorized")
        providers = get_providers()
        authz = providers.identity  # identity provider also exposes has_permission via service layer
        from services.authorization_service import has_permission

        if not has_permission(session, permission):
            try:
                audit = providers.audit_sink
                if audit is not None:
                    audit.emit(  # type: ignore[union-attr]
                        {
                            "action": "auth.access_denied",
                            "actor_user_id": session.user_id,
                            "target_type": target_type,
                            "target_id": permission,
                            "workspace_id": session.workspace_id,
                            "request_id": getattr(request.state, "request_id", None),
                        }
                    )
            except Exception:
                pass
            raise ApiError("forbidden")
        # Workspace scoping for admin routes is enforced in route via require_workspace helper.
        return session

    return _dep
