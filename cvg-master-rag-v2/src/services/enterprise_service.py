"""
Enterprise session and tenancy contracts for the Phase 3 foundation.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from services.admin_service import (
    can_access_tenant,
    get_accessible_tenants,
    get_tenant,
    get_user,
    get_user_by_email,
    list_tenants,
    normalize_role,
    resolve_permissions_for_role,
    set_user_password,
    user_has_permission,
    verify_password,
)
from services.enterprise_store import (
    load_recovery_state,
    load_session_state,
    save_recovery_state,
    save_session_state,
    update_session_state,
)
from core.config import SESSION_TTL_HOURS

_RATE_LIMIT_BUCKETS: dict[str, list[float]] = {}


def reset_rate_limit_state() -> None:
    """Clear ephemeral in-memory throttling state."""
    _RATE_LIMIT_BUCKETS.clear()

SESSION_COOKIE_NAME = "cvg_master_rag_session"

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _default_tenant() -> dict:
    tenant = get_tenant("default")
    if tenant is not None:
        return tenant
    tenants = list_tenants()
    if tenants:
        return tenants[0]
    return {
        "tenant_id": "default",
        "name": "Workspace Principal",
        "workspace_id": "default",
        "plan": "enterprise",
        "status": "active",
        "document_count": 0,
    }


def _active_tenant_for_user(user: dict, tenant_id: str | None = None) -> dict:
    accessible = get_accessible_tenants(user)
    if not accessible:
        return _default_tenant()
    if tenant_id:
        for tenant in accessible:
            if tenant["tenant_id"] == tenant_id:
                return tenant
    return accessible[0]


def _build_authenticated_session(user: dict, tenant_id: str, session_token: str, expires_at: str) -> dict:
    normalized_role = normalize_role(user.get("role"))
    permissions = resolve_permissions_for_role(normalized_role, user.get("permission_overrides"))
    active_tenant = _active_tenant_for_user(user, tenant_id)
    return {
        "authenticated": True,
        "session_state": "active",
        "expires_at": expires_at,
        "session_token": session_token,
        "user": {
            "user_id": user["user_id"],
            "name": user["name"],
            "email": user["email"],
            "role": normalized_role,
            "permissions": permissions,
        },
        "active_tenant": active_tenant,
        "available_tenants": get_accessible_tenants(user),
        "message": "Sessão enterprise carregada com sucesso",
    }


def bootstrap_session() -> dict:
    tenant = _default_tenant()
    return {
        "authenticated": False,
        "session_state": "anonymous",
        "expires_at": None,
        "session_token": None,
        "user": {
            "user_id": "anonymous",
            "name": "Visitante",
            "email": "",
            "role": "viewer",
            "permissions": [],
        },
        "active_tenant": tenant,
        "available_tenants": list_tenants(),
        "message": "Sessão enterprise pronta para login.",
    }


def _load_sessions() -> dict[str, dict]:
    return load_session_state().get("sessions", {})


def _save_sessions(sessions: dict[str, dict]) -> None:
    save_session_state({"sessions": sessions})


def _load_recovery_requests() -> list[dict]:
    return load_recovery_state().get("requests", [])


def _save_recovery_requests(requests: list[dict]) -> None:
    payload = load_recovery_state()
    payload["requests"] = requests
    save_recovery_state(payload)


def _load_password_reset_tokens() -> list[dict]:
    return load_recovery_state().get("password_reset_tokens", [])


def _save_password_reset_tokens(tokens: list[dict]) -> None:
    payload = load_recovery_state()
    payload["password_reset_tokens"] = tokens
    save_recovery_state(payload)


def _check_rate_limit(namespace: str, key: str, *, max_attempts: int, window_seconds: int) -> None:
    now_ts = _utc_now().timestamp()
    bucket_key = f"{namespace}:{key}"
    attempts = [item for item in _RATE_LIMIT_BUCKETS.get(bucket_key, []) if (now_ts - item) <= window_seconds]
    _RATE_LIMIT_BUCKETS[bucket_key] = attempts
    if len(attempts) >= max_attempts:
        raise PermissionError(f"rate_limited:{namespace}")


def _record_rate_limit_attempt(namespace: str, key: str) -> None:
    bucket_key = f"{namespace}:{key}"
    attempts = _RATE_LIMIT_BUCKETS.get(bucket_key, [])
    attempts.append(_utc_now().timestamp())
    _RATE_LIMIT_BUCKETS[bucket_key] = attempts[-20:]


def _clear_rate_limit(namespace: str, key: str) -> None:
    _RATE_LIMIT_BUCKETS.pop(f"{namespace}:{key}", None)


def _hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _issue_password_reset_token(
    user: dict,
    *,
    tenant_id: str | None,
    requested_by: str,
    expires_in_minutes: int = 30,
) -> dict:
    tokens = _load_password_reset_tokens()
    now = _utc_now()
    target_tenant = tenant_id or user.get("tenant_id") or "default"
    token = secrets.token_urlsafe(24)
    record = {
        "reset_id": f"reset_{secrets.token_hex(8)}",
        "user_id": user["user_id"],
        "email": user["email"],
        "tenant_id": target_tenant,
        "token_hash": _hash_reset_token(token),
        "created_at": _to_iso(now),
        "expires_at": _to_iso(now + timedelta(minutes=max(5, expires_in_minutes))),
        "used_at": None,
        "requested_by": requested_by,
    }
    tokens.append(record)
    _save_password_reset_tokens(tokens)
    return {
        "reset_id": record["reset_id"],
        "token": token,
        "expires_at": record["expires_at"],
        "tenant_id": target_tenant,
    }


def _persist_session(user: dict, tenant_id: str, *, ip: str | None = None, user_agent: str | None = None) -> dict:
    session_token = secrets.token_urlsafe(32)
    expires_at = _to_iso(_utc_now() + timedelta(hours=SESSION_TTL_HOURS))
    normalized_role = normalize_role(user.get("role"))
    permissions = resolve_permissions_for_role(normalized_role, user.get("permission_overrides"))
    created_at = _to_iso(_utc_now())

    def mutate(state: dict) -> dict:
        sessions = state.get("sessions", {})
        sessions[session_token] = {
            "session_token": session_token,
            "user_id": user["user_id"],
            "tenant_id": tenant_id,
            "expires_at": expires_at,
            "created_at": created_at,
            "last_seen_at": created_at,
            "revoked_at": None,
            "revoked_reason": None,
            "ip": ip,
            "user_agent": user_agent,
            "role_snapshot": normalized_role,
            "permissions_snapshot": permissions,
        }
        state["sessions"] = sessions
        return state

    update_session_state(mutate)
    return _build_authenticated_session(user, tenant_id, session_token, expires_at)


def _prune_expired_sessions(sessions: dict[str, dict]) -> dict[str, dict]:
    now = _utc_now()
    active_sessions: dict[str, dict] = {}
    for token, payload in sessions.items():
        expires_at = payload.get("expires_at")
        if payload.get("revoked_at"):
            active_sessions[token] = payload
            continue
        if not expires_at:
            continue
        try:
            expires_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if expires_dt > now:
            active_sessions[token] = payload
    if active_sessions != sessions:
        _save_sessions(active_sessions)
    return active_sessions


def extract_session_token(authorization_header: str | None) -> str | None:
    if not authorization_header:
        return None
    scheme, _, token = authorization_header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


def get_session(session_token: str | None) -> dict:
    if not session_token:
        return bootstrap_session()
    outcome: dict = {}

    def mutate(state: dict) -> dict:
        sessions = _prune_expired_sessions(state.get("sessions", {}))
        state["sessions"] = sessions
        record = sessions.get(session_token)
        if not record:
            outcome["payload"] = {
                **bootstrap_session(),
                "session_state": "expired",
                "message": "Sessão inválida ou expirada. Faça login novamente.",
            }
            return state
        if record.get("revoked_at"):
            outcome["payload"] = {
                **bootstrap_session(),
                "session_state": "expired",
                "message": "Sessão revogada. Faça login novamente.",
            }
            return state

        user = get_user(record["user_id"])
        if not user or user.get("status") != "active":
            sessions.pop(session_token, None)
            outcome["payload"] = {
                **bootstrap_session(),
                "session_state": "expired",
                "message": "Sessão revogada. Faça login novamente.",
            }
            return state

        password_changed_at = user.get("password_changed_at")
        if password_changed_at:
            try:
                session_created = datetime.fromisoformat(record.get("created_at", "").replace("Z", "+00:00"))
                pw_changed = datetime.fromisoformat(password_changed_at.replace("Z", "+00:00"))
                if session_created < pw_changed:
                    sessions.pop(session_token, None)
                    outcome["payload"] = {
                        **bootstrap_session(),
                        "session_state": "expired",
                        "message": "Sessão revogada. Credenciais alteradas. Faça login novamente.",
                    }
                    return state
            except (ValueError, TypeError):
                pass

        status_changed_at = user.get("status_changed_at")
        if status_changed_at:
            try:
                session_created = datetime.fromisoformat(record.get("created_at", "").replace("Z", "+00:00"))
                status_changed = datetime.fromisoformat(status_changed_at.replace("Z", "+00:00"))
                if session_created < status_changed:
                    sessions.pop(session_token, None)
                    outcome["payload"] = {
                        **bootstrap_session(),
                        "session_state": "expired",
                        "message": "Sessão revogada. Status alterado. Faça login novamente.",
                    }
                    return state
            except (ValueError, TypeError):
                pass

        role_changed_at = user.get("role_changed_at")
        if role_changed_at:
            try:
                session_created = datetime.fromisoformat(record.get("created_at", "").replace("Z", "+00:00"))
                role_changed = datetime.fromisoformat(role_changed_at.replace("Z", "+00:00"))
                if session_created < role_changed:
                    sessions.pop(session_token, None)
                    outcome["payload"] = {
                        **bootstrap_session(),
                        "session_state": "expired",
                        "message": "Sessão revogada. Permissões alteradas. Faça login novamente.",
                    }
                    return state
            except (ValueError, TypeError):
                pass

        tenant_id = record.get("tenant_id") or user["tenant_id"]
        if not can_access_tenant(user, tenant_id):
            tenant_id = user["tenant_id"]
        record["last_seen_at"] = _to_iso(_utc_now())
        record["expires_at"] = _to_iso(_utc_now() + timedelta(hours=SESSION_TTL_HOURS))
        record["role_snapshot"] = normalize_role(user.get("role"))
        record["permissions_snapshot"] = resolve_permissions_for_role(user.get("role"), user.get("permission_overrides"))
        sessions[session_token] = record
        outcome["payload"] = _build_authenticated_session(user, tenant_id, session_token, record["expires_at"])
        return state

    update_session_state(mutate)
    return outcome["payload"]


def login(
    email: str,
    password: str,
    tenant_id: str | None = None,
    *,
    ip: str | None = None,
    user_agent: str | None = None,
) -> dict:
    normalized_email = email.strip().lower()
    rate_limit_key = f"{normalized_email}:{ip or 'unknown'}"
    _check_rate_limit("login", rate_limit_key, max_attempts=5, window_seconds=15 * 60)
    user = get_user_by_email(email)
    if not user:
        _record_rate_limit_attempt("login", rate_limit_key)
        raise ValueError("invalid_credentials")
    if user.get("status") != "active":
        _record_rate_limit_attempt("login", rate_limit_key)
        raise ValueError("inactive_user")
    if not verify_password(user, password):
        _record_rate_limit_attempt("login", rate_limit_key)
        raise ValueError("invalid_credentials")
    requested_tenant = tenant_id or user["tenant_id"]
    if not can_access_tenant(user, requested_tenant):
        _record_rate_limit_attempt("login", rate_limit_key)
        raise PermissionError(f"tenant_forbidden:{requested_tenant}")
    _clear_rate_limit("login", rate_limit_key)
    return _persist_session(user, requested_tenant, ip=ip, user_agent=user_agent)


def logout(session_token: str | None, *, reason: str = "logout") -> None:
    if not session_token:
        return
    def mutate(state: dict) -> dict:
        sessions = state.get("sessions", {})
        if session_token in sessions:
            sessions[session_token]["revoked_at"] = _to_iso(_utc_now())
            sessions[session_token]["revoked_reason"] = reason
        state["sessions"] = sessions
        return state

    update_session_state(mutate)


def switch_tenant(session_token: str | None, tenant_id: str) -> dict:
    if not session_token:
        raise PermissionError("missing_session")
    outcome: dict = {}

    def mutate(state: dict) -> dict:
        sessions = _prune_expired_sessions(state.get("sessions", {}))
        state["sessions"] = sessions
        record = sessions.get(session_token)
        if not record or record.get("revoked_at"):
            raise PermissionError("missing_session")
        user = get_user(record["user_id"])
        if not user or user.get("status") != "active" or not can_access_tenant(user, tenant_id):
            raise PermissionError(f"tenant_forbidden:{tenant_id}")
        record["tenant_id"] = tenant_id
        record["last_seen_at"] = _to_iso(_utc_now())
        record["expires_at"] = _to_iso(_utc_now() + timedelta(hours=SESSION_TTL_HOURS))
        record["role_snapshot"] = normalize_role(user.get("role"))
        record["permissions_snapshot"] = resolve_permissions_for_role(user.get("role"), user.get("permission_overrides"))
        sessions[session_token] = record
        outcome["payload"] = _build_authenticated_session(user, tenant_id, session_token, record["expires_at"])
        return state

    update_session_state(mutate)
    return outcome["payload"]


def queue_recovery(email: str, tenant_id: str | None = None, reason: str | None = None) -> dict:
    normalized_email = email.strip().lower()
    target_tenant = (tenant_id or "default").strip() or "default"
    detail = reason.strip() if reason and reason.strip() else "sem motivo informado"
    now = _to_iso(_utc_now())
    requests = _load_recovery_requests()
    user = get_user_by_email(normalized_email)
    tenant = get_tenant(target_tenant)

    existing = next(
        (
            item
            for item in requests
            if item.get("email") == normalized_email
            and item.get("tenant_id") == target_tenant
            and item.get("status") == "queued"
        ),
        None,
    )

    if existing is not None:
        existing["reason"] = detail
        existing["updated_at"] = now
        existing["attempts"] = int(existing.get("attempts", 1)) + 1
        existing["user_exists"] = user is not None
        existing["tenant_exists"] = tenant is not None
        recovery_id = existing["recovery_id"]
    else:
        recovery_id = f"recovery_{secrets.token_hex(8)}"
        requests.append(
            {
                "recovery_id": recovery_id,
                "email": normalized_email,
                "tenant_id": target_tenant,
                "reason": detail,
                "status": "queued",
                "attempts": 1,
                "created_at": now,
                "updated_at": now,
                "user_exists": user is not None,
                "tenant_exists": tenant is not None,
                "user_id": user.get("user_id") if user else None,
            }
        )

    _save_recovery_requests(requests)
    return {
        "status": "queued",
        "message": (
            f"Solicitação de recuperação registrada para {normalized_email} "
            f"no tenant {target_tenant}. Protocolo: {recovery_id}."
        ),
    }


def request_password_reset(email: str, tenant_id: str | None = None) -> dict:
    normalized_email = email.strip().lower()
    rate_limit_key = f"{normalized_email}:{tenant_id or 'default'}"
    _check_rate_limit("password-reset", rate_limit_key, max_attempts=3, window_seconds=15 * 60)
    user = get_user_by_email(normalized_email)
    if user and user.get("status") in {"active", "invited"}:
        requested_tenant = tenant_id or user.get("tenant_id")
        if can_access_tenant(user, requested_tenant or user.get("tenant_id", "default")):
            _issue_password_reset_token(
                user,
                tenant_id=requested_tenant,
                requested_by="self_service",
            )
    _record_rate_limit_attempt("password-reset", rate_limit_key)
    return {
        "status": "queued",
        "message": "Se a identidade existir e estiver apta, o reset será processado por canal controlado.",
    }


def change_password(user_id: str, current_password: str, new_password: str) -> dict:
    user = get_user(user_id)
    if not user:
        raise ValueError("user_not_found")
    if not verify_password(user, current_password):
        raise ValueError("invalid_current_password")
    if current_password == new_password:
        raise ValueError("password_policy_reused_current_password")
    return set_user_password(user_id, new_password, must_change_password=False)


def confirm_password_reset(token: str, new_password: str) -> dict:
    tokens = _load_password_reset_tokens()
    token_hash = _hash_reset_token(token)
    now = _utc_now()
    updated: list[dict] = []
    target: dict | None = None
    for item in tokens:
        expires_at = item.get("expires_at")
        if expires_at:
            try:
                expires_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            except ValueError:
                expires_dt = now - timedelta(seconds=1)
        else:
            expires_dt = now - timedelta(seconds=1)
        if item.get("used_at") is None and expires_dt > now and item.get("token_hash") == token_hash:
            target = item
        updated.append(item)
    if target is None:
        raise ValueError("invalid_or_expired_reset_token")
    user = get_user(target["user_id"])
    if not user:
        raise ValueError("invalid_or_expired_reset_token")
    set_user_password(user["user_id"], new_password, must_change_password=False)
    revoke_user_sessions(user["user_id"], reason="password_reset")
    for item in updated:
        if item.get("reset_id") == target["reset_id"]:
            item["used_at"] = _to_iso(now)
    _save_password_reset_tokens(updated)
    return {
        "status": "queued",
        "message": "Senha redefinida com sucesso. Faça login novamente.",
        "user_id": user["user_id"],
    }


def list_sessions_for_user(user_id: str, *, current_session_token: str | None = None) -> list[dict]:
    sessions = _load_sessions()
    items: list[dict] = []
    for record in sessions.values():
        if record.get("user_id") != user_id:
            continue
        role = normalize_role(record.get("role_snapshot"))
        permissions = record.get("permissions_snapshot")
        if not isinstance(permissions, list):
            target_user = get_user(user_id) or {"role": role}
            permissions = resolve_permissions_for_role(target_user.get("role"), target_user.get("permission_overrides"))
        items.append(
            {
                "session_token": record.get("session_token"),
                "user_id": user_id,
                "tenant_id": record.get("tenant_id") or "default",
                "role": role,
                "permissions": permissions,
                "created_at": record.get("created_at") or _to_iso(_utc_now()),
                "last_seen_at": record.get("last_seen_at"),
                "expires_at": record.get("expires_at") or _to_iso(_utc_now()),
                "revoked_at": record.get("revoked_at"),
                "revoked_reason": record.get("revoked_reason"),
                "current": record.get("session_token") == current_session_token,
                "ip": record.get("ip"),
                "user_agent": record.get("user_agent"),
            }
        )
    items.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return items


def revoke_session(session_token: str, *, reason: str = "manual_revoke") -> int:
    outcome = {"revoked": 0}

    def mutate(state: dict) -> dict:
        sessions = state.get("sessions", {})
        record = sessions.get(session_token)
        if not record or record.get("revoked_at"):
            return state
        record["revoked_at"] = _to_iso(_utc_now())
        record["revoked_reason"] = reason
        sessions[session_token] = record
        state["sessions"] = sessions
        outcome["revoked"] = 1
        return state

    update_session_state(mutate)
    return outcome["revoked"]


def revoke_user_sessions(user_id: str, *, reason: str = "manual_revoke", exclude_session_token: str | None = None) -> int:
    outcome = {"revoked": 0}

    def mutate(state: dict) -> dict:
        sessions = state.get("sessions", {})
        for token, record in sessions.items():
            if record.get("user_id") != user_id:
                continue
            if exclude_session_token and token == exclude_session_token:
                continue
            if record.get("revoked_at"):
                continue
            record["revoked_at"] = _to_iso(_utc_now())
            record["revoked_reason"] = reason
            sessions[token] = record
            outcome["revoked"] += 1
        state["sessions"] = sessions
        return state

    update_session_state(mutate)
    return outcome["revoked"]


def admin_issue_password_reset(user_id: str, *, requested_by: str, expires_in_minutes: int = 30) -> dict:
    user = get_user(user_id)
    if not user:
        raise KeyError(user_id)
    return _issue_password_reset_token(
        user,
        tenant_id=user.get("tenant_id"),
        requested_by=requested_by,
        expires_in_minutes=expires_in_minutes,
    )
