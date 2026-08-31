from __future__ import annotations

from fastapi import Cookie, Depends, Header, HTTPException

from models.schemas import EnterpriseSession, RetrievalContext
from services.authorization import (
    allowed_collection_ids_for_user,
    canonical_role,
    permission_granted,
)
from services.rag_contract import normalize_collection_id
from services.admin_service import log_admin_event
from services.enterprise_service import (
    SESSION_COOKIE_NAME,
    bootstrap_session,
    extract_session_token,
    get_session as get_enterprise_session,
)

ROLE_ORDER = {"VETERINARIAN": 0, "KNOWLEDGE_MANAGER": 1, "PLATFORM_ADMIN": 2}


def enterprise_session_from_authorization(
    authorization: str | None = Header(default=None, alias="Authorization"),
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> EnterpriseSession:
    return EnterpriseSession(**get_enterprise_session(session_cookie or extract_session_token(authorization)))


def coerce_session(session: object) -> EnterpriseSession:
    if isinstance(session, EnterpriseSession):
        return session
    return EnterpriseSession(**bootstrap_session())


def require_authenticated_session(session: EnterpriseSession) -> EnterpriseSession:
    session = coerce_session(session)
    if not session.authenticated or session.session_state != "active":
        raise HTTPException(status_code=401, detail={"error": "unauthorized", "message": "Active session required"})
    return session


def require_min_role(session: EnterpriseSession, role: str) -> EnterpriseSession:
    session = require_authenticated_session(session)
    if ROLE_ORDER.get(canonical_role(session.user.role), 0) < ROLE_ORDER.get(canonical_role(role), 0):
        raise HTTPException(status_code=403, detail={"error": "forbidden", "message": f"{role} role required"})
    return session


def audit_access_denied(
    session: EnterpriseSession,
    *,
    reason: str,
    required_permission: str | None = None,
    target_type: str = "route",
    target_id: str = "unknown",
    workspace_id: str | None = None,
) -> None:
    actor = session.user if session.authenticated else None
    log_admin_event(
        actor_user_id=actor.user_id if actor else "anonymous",
        actor_email=actor.email if actor else "",
        actor_role=actor.role if actor else "anonymous",
        action="auth.access_denied",
        target_type=target_type,
        target_id=target_id,
        tenant_id=session.active_tenant.tenant_id if session.authenticated else None,
        metadata={
            "workspace_id": workspace_id,
            "required_permission": required_permission,
            "reason": reason,
        },
    )


def session_has_permission(session: EnterpriseSession, permission: str) -> bool:
    return permission_granted(
        role=session.user.role,
        permissions=session.user.permissions,
        required=permission,
    )


def require_permission(
    session: EnterpriseSession,
    permission: str,
    *,
    workspace_id: str | None = None,
    target_type: str = "permission",
    target_id: str | None = None,
) -> EnterpriseSession:
    session = require_authenticated_session(coerce_session(session))
    if not session_has_permission(session, permission):
        audit_access_denied(
            session,
            reason="missing_permission",
            required_permission=permission,
            target_type=target_type,
            target_id=target_id or permission,
            workspace_id=workspace_id,
        )
        raise HTTPException(
            status_code=403,
            detail={"error": "forbidden", "message": f"Permission '{permission}' required"},
        )
    return session


def require_admin(session: EnterpriseSession = Depends(enterprise_session_from_authorization)) -> EnterpriseSession:
    return require_permission(session, "observability.read", target_type="permission", target_id="observability.read")


def require_operator(session: EnterpriseSession = Depends(enterprise_session_from_authorization)) -> EnterpriseSession:
    return require_min_role(session, "operator")


def require_workspace_access(
    workspace_id: str,
    session: EnterpriseSession = Depends(enterprise_session_from_authorization),
) -> EnterpriseSession:
    session = require_authenticated_session(coerce_session(session))
    if session.active_tenant.workspace_id != workspace_id:
        audit_access_denied(
            session,
            reason="workspace_forbidden",
            target_type="workspace",
            target_id=workspace_id,
            workspace_id=workspace_id,
        )
        raise HTTPException(
            status_code=403,
            detail={
                "error": "workspace_forbidden",
                "message": f"Workspace '{workspace_id}' is not active for tenant '{session.active_tenant.tenant_id}'",
            },
        )
    return session


def build_retrieval_context(
    session: EnterpriseSession,
    *,
    workspace_id: str,
    collection_id: str | None = None,
) -> RetrievalContext:
    """Build the server-side retrieval scope; request bodies cannot widen it."""
    session = require_workspace_access(workspace_id, require_authenticated_session(coerce_session(session)))
    allowed = allowed_collection_ids_for_user(session.user)
    requested_collection = normalize_collection_id(collection_id) if collection_id else None
    if requested_collection and "*" not in allowed and requested_collection not in allowed:
        audit_access_denied(
            session,
            reason="collection_forbidden",
            required_permission="collections.read",
            target_type="collection",
            target_id=requested_collection,
            workspace_id=workspace_id,
        )
        raise HTTPException(
            status_code=403,
            detail={"error": "collection_forbidden", "message": "Collection is not authorized for this identity"},
        )
    return RetrievalContext(
        user_id=session.user.user_id,
        workspace_id=workspace_id,
        allowed_collection_ids=[requested_collection] if requested_collection else allowed,
        permissions=session.user.permissions,
    )


def resolve_workspace_scope(
    workspace_id: str | None,
    session: object,
    required_role: str | None = None,
    required_permission: str | None = None,
) -> str | None:
    if not isinstance(workspace_id, str):
        workspace_id = None
    coerced = require_authenticated_session(coerce_session(session))
    if required_role:
        require_min_role(coerced, required_role)
    if required_permission:
        require_permission(coerced, required_permission, workspace_id=workspace_id or coerced.active_tenant.workspace_id)
    target_workspace = workspace_id or coerced.active_tenant.workspace_id
    require_workspace_access(target_workspace, coerced)
    return target_workspace


def resolve_admin_workspace_scope(
    workspace_id: str | None,
    session: object,
    *,
    required_permission: str,
) -> str:
    """Resolve an admin target without allowing a manager to cross workspaces.

    Platform administrators may inspect an explicitly requested workspace. All
    other administrators remain bound to their active tenant/workspace, even
    when their role has the requested operational permission.
    """
    coerced = require_authenticated_session(coerce_session(session))
    target_workspace = workspace_id or coerced.active_tenant.workspace_id
    require_permission(coerced, required_permission, workspace_id=target_workspace)
    if canonical_role(coerced.user.role) != "PLATFORM_ADMIN":
        require_workspace_access(target_workspace, coerced)
    return target_workspace
