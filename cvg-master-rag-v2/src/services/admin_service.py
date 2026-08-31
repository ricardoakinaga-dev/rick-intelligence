"""
Enterprise admin store for tenants and users.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from copy import deepcopy
from datetime import datetime, timezone
from typing import Optional

from services.enterprise_store import (
    ADMIN_EVENTS_PATH,
    append_admin_event,
    load_admin_state,
    reset_admin_state_store,
    reset_session_state,
    save_admin_state,
)

# ─── Password hashing ────────────────────────────────────────────────────────
# PBKDF2-SHA256 per-user salt.
# Legacy $2b$ format preserved for existing demo users.
# Global salt NOT used for new hashes.

_DEMO_SALT = "fluxpay2024_rag_salt_v1"

ROLE_ALIASES = {
    "admin": "super_admin",
}

ROLE_PERMISSIONS: dict[str, list[str]] = {
    "super_admin": [
        "*",
    ],
    "admin_rag": [
        "documents.read",
        "documents.upload",
        "search.execute",
        "query.execute",
        "observability.read",
        "audit.read",
        "ingestion.run",
        "reindex.run",
        "corpus.audit",
        "corpus.repair",
        "runtime.manage",
    ],
    "auditor": [
        "documents.read",
        "search.execute",
        "query.execute",
        "observability.read",
        "audit.read",
        "corpus.audit",
    ],
    "operator": [
        "documents.read",
        "documents.upload",
        "search.execute",
        "query.execute",
        "observability.read",
        "ingestion.run",
    ],
    "viewer": [
        "documents.read",
        "search.execute",
        "query.execute",
    ],
}

DEFAULT_ROLE = "viewer"


def hash_password(password: str, salt_hex: str | None = None) -> str:
    """
    Hash a password with a per-user salt using PBKDF2-SHA256.
    Returns the full portable hash string: $pbkdf2$<salt_hex>$<hash_hex>
    """
    if salt_hex is None:
        salt_hex = secrets.token_hex(16)  # 16 bytes = 32 hex chars
    salt_bytes = salt_hex.encode("utf-8")
    key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_bytes,
        iterations=100_000,
    )
    return f"$pbkdf2${salt_hex}${key.hex()}"


def verify_password(user: dict, password: str) -> bool:
    """
    Verify a password against the stored hash.
    Handles three formats:
    - $pbkdf2$<salt_hex>$<hash_hex>  (new per-user salt)
    - $pbkdf2$<hash_hex>             (global salt, no migration)
    - $2b$12$<salt+hash>              (legacy demo users)
    """
    stored_hash = user.get("password_hash", "")
    if not stored_hash:
        return False
    try:
        if stored_hash.startswith("$pbkdf2$"):
            parts = stored_hash.split("$")
            if len(parts) == 4:
                # New format: $pbkdf2$<salt_hex>$<hash_hex>
                salt_hex = parts[2]
                stored_hex = parts[3]
                salt_bytes = salt_hex.encode("utf-8")
            elif len(parts) == 3:
                # Global-salt format: $pbkdf2$<hash_hex> (no migration)
                salt_bytes = _DEMO_SALT.encode("utf-8")
                stored_hex = parts[2]
            else:
                return False
            computed_hex = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                salt_bytes,
                iterations=100_000,
            ).hex()
            return secrets.compare_digest(computed_hex, stored_hex)
        # Legacy format: $2b$12$<salt+hash> (for existing demo users)
        if stored_hash.startswith("$2b$12$"):
            parts = stored_hash.split("$")
            if len(parts) == 4:
                salt_and_hash = parts[3]
                salt = salt_and_hash[:22]
                expected = salt_and_hash[22:]
                test = hashlib.sha256((salt + password).encode()).hexdigest()[:43]
                return secrets.compare_digest(test, expected)
        return False
    except Exception:
        return False

DEFAULT_TENANTS = [
    {
        "tenant_id": "default",
        "name": "Workspace Principal",
        "workspace_id": "default",
        "plan": "enterprise",
        "status": "active",
        "operational_retention_mode": "keep_latest",
        "operational_retention_hours": 24,
    },
    {
        "tenant_id": "acme-lab",
        "name": "Acme Lab",
        "workspace_id": "acme-lab",
        "plan": "business",
        "status": "active",
        "operational_retention_mode": "keep_latest",
        "operational_retention_hours": 24,
    },
    {
        "tenant_id": "northwind",
        "name": "Northwind Pilot",
        "workspace_id": "northwind",
        "plan": "starter",
        "status": "active",
        "operational_retention_mode": "keep_latest",
        "operational_retention_hours": 24,
    },
]

DEFAULT_USERS = [
    {
        "user_id": "user-admin",
        "name": "Sara Super Admin",
        "email": "admin@demo.local",
        "password_hash": "$2b$12$demo_salt_fluxpay2024e2fc2e9bfca2ee7ff37f14290c6cb494ecec791da32b",
        "role": "super_admin",
        "tenant_id": "default",
        "status": "active",
        "password_changed_at": "2026-01-01T00:00:00Z",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "must_change_password": False,
    },
    {
        "user_id": "user-admin-rag",
        "name": "Rita RAG Admin",
        "email": "adminrag@demo.local",
        "password_hash": "$2b$12$demo_salt_fluxpay2024e2fc2e9bfca2ee7ff37f14290c6cb494ecec791da32b",
        "role": "admin_rag",
        "tenant_id": "default",
        "status": "active",
        "password_changed_at": "2026-01-01T00:00:00Z",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "must_change_password": False,
    },
    {
        "user_id": "user-auditor",
        "name": "Alice Auditor",
        "email": "auditor@demo.local",
        "password_hash": "$2b$12$demo_salt_fluxpay2024e2fc2e9bfca2ee7ff37f14290c6cb494ecec791da32b",
        "role": "auditor",
        "tenant_id": "default",
        "status": "active",
        "password_changed_at": "2026-01-01T00:00:00Z",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "must_change_password": False,
    },
    {
        "user_id": "user-operator",
        "name": "Omar Operator",
        "email": "operator@demo.local",
        "password_hash": "$2b$12$demo_salt_fluxpay2024e2fc2e9bfca2ee7ff37f14290c6cb494ecec791da32b",
        "role": "operator",
        "tenant_id": "default",
        "status": "active",
        "password_changed_at": "2026-01-01T00:00:00Z",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "must_change_password": False,
    },
    {
        "user_id": "user-viewer",
        "name": "Vera Viewer",
        "email": "viewer@demo.local",
        "password_hash": "$2b$12$demo_salt_fluxpay2024e2fc2e9bfca2ee7ff37f14290c6cb494ecec791da32b",
        "role": "viewer",
        "tenant_id": "default",
        "status": "active",
        "password_changed_at": "2026-01-01T00:00:00Z",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "must_change_password": False,
    },
]

DEFAULT_ADMIN_STATE = {
    "tenants": deepcopy(DEFAULT_TENANTS),
    "users": deepcopy(DEFAULT_USERS),
}


def _load_state() -> dict:
    state = load_admin_state(DEFAULT_ADMIN_STATE)
    normalized = _normalize_admin_state(state)
    if normalized != state:
        save_admin_state(normalized)
    return normalized


def _save_state(state: dict) -> None:
    save_admin_state(_normalize_admin_state(state))


def normalize_role(role: str | None) -> str:
    normalized = str(role or DEFAULT_ROLE).strip().lower()
    normalized = ROLE_ALIASES.get(normalized, normalized)
    return normalized if normalized in ROLE_PERMISSIONS else DEFAULT_ROLE


def resolve_permissions_for_role(role: str | None, overrides: dict | None = None) -> list[str]:
    normalized_role = normalize_role(role)
    base = list(ROLE_PERMISSIONS.get(normalized_role, ROLE_PERMISSIONS[DEFAULT_ROLE]))
    if "*" in base:
        return ["*"]

    resolved = set(base)
    payload = overrides if isinstance(overrides, dict) else {}
    for permission in payload.get("add", []) if isinstance(payload.get("add"), list) else []:
        if isinstance(permission, str) and permission.strip():
            resolved.add(permission.strip())
    for permission in payload.get("remove", []) if isinstance(payload.get("remove"), list) else []:
        if isinstance(permission, str) and permission.strip():
            resolved.discard(permission.strip())
    return sorted(resolved)


def user_has_permission(user: dict, permission: str) -> bool:
    permissions = resolve_permissions_for_role(user.get("role"), user.get("permission_overrides"))
    return "*" in permissions or permission in permissions


def _normalize_user(user: dict) -> dict:
    normalized = deepcopy(user)
    normalized["email"] = str(normalized.get("email", "")).strip().lower()
    normalized["role"] = normalize_role(normalized.get("role"))
    normalized["status"] = normalized.get("status") or "invited"
    normalized["tenant_id"] = normalized.get("tenant_id") or "default"
    normalized["must_change_password"] = bool(normalized.get("must_change_password", False))
    normalized["permission_overrides"] = normalized.get("permission_overrides") if isinstance(normalized.get("permission_overrides"), dict) else {}
    normalized["created_at"] = normalized.get("created_at") or normalized.get("password_changed_at") or "2026-01-01T00:00:00Z"
    normalized["updated_at"] = normalized.get("updated_at") or normalized["created_at"]
    normalized["permissions"] = resolve_permissions_for_role(normalized["role"], normalized["permission_overrides"])
    return normalized


def _normalize_admin_state(state: dict) -> dict:
    normalized = deepcopy(state)
    tenants = normalized.get("tenants")
    users = normalized.get("users")
    normalized["tenants"] = tenants if isinstance(tenants, list) else deepcopy(DEFAULT_TENANTS)
    normalized["users"] = [_normalize_user(item) for item in users] if isinstance(users, list) else deepcopy(DEFAULT_USERS)
    return normalized


def validate_password_policy(password: str, *, email: str = "", current_password: str | None = None) -> None:
    candidate = str(password or "")
    normalized_email = email.strip().lower()
    if len(candidate) < 12:
        raise ValueError("password_policy_too_short")
    if normalized_email and candidate.strip().lower() == normalized_email:
        raise ValueError("password_policy_matches_email")
    classes = 0
    if re.search(r"[a-z]", candidate):
        classes += 1
    if re.search(r"[A-Z]", candidate):
        classes += 1
    if re.search(r"[0-9]", candidate):
        classes += 1
    if re.search(r"[^A-Za-z0-9]", candidate):
        classes += 1
    if classes < 2:
        raise ValueError("password_policy_not_complex_enough")
    if current_password is not None and secrets.compare_digest(candidate, current_password):
        raise ValueError("password_policy_reused_current_password")


def reset_admin_state() -> None:
    reset_admin_state_store(DEFAULT_ADMIN_STATE)
    reset_session_state()
    from services.enterprise_service import reset_rate_limit_state

    reset_rate_limit_state()


def list_tenants() -> list[dict]:
    from services.document_registry import get_corpus_overview

    state = _load_state()
    tenants: list[dict] = []
    for tenant in state["tenants"]:
        tenant = {
            **tenant,
            "operational_retention_mode": tenant.get("operational_retention_mode", "keep_latest"),
            "operational_retention_hours": int(tenant.get("operational_retention_hours", 24) or 24),
        }
        overview = get_corpus_overview(tenant["workspace_id"])
        tenants.append(
            {
                **tenant,
                "document_count": overview.get("documents", 0),
            }
        )
    return tenants


def _find_tenant_index(tenant_id: str) -> Optional[int]:
    state = _load_state()
    for index, tenant in enumerate(state["tenants"]):
        if tenant["tenant_id"] == tenant_id:
            return index
    return None


def get_tenant(tenant_id: str) -> Optional[dict]:
    for tenant in list_tenants():
        if tenant["tenant_id"] == tenant_id:
            return tenant
    return None


def create_tenant(payload: dict) -> dict:
    state = _load_state()
    tenant_id = payload["tenant_id"]
    if any(item["tenant_id"] == tenant_id for item in state["tenants"]):
        raise ValueError(f"tenant_exists:{tenant_id}")
    if any(item["workspace_id"] == payload["workspace_id"] for item in state["tenants"]):
        raise ValueError(f"workspace_exists:{payload['workspace_id']}")
    tenant = {
        "tenant_id": tenant_id,
        "name": payload["name"],
        "workspace_id": payload["workspace_id"],
        "plan": payload.get("plan", "starter"),
        "status": payload.get("status", "active"),
        "operational_retention_mode": payload.get("operational_retention_mode", "keep_latest"),
        "operational_retention_hours": int(payload.get("operational_retention_hours", 24) or 24),
    }
    state["tenants"].append(tenant)
    _save_state(state)
    return next(item for item in list_tenants() if item["tenant_id"] == tenant_id)


def update_tenant(tenant_id: str, payload: dict) -> dict:
    state = _load_state()
    index = next((idx for idx, item in enumerate(state["tenants"]) if item["tenant_id"] == tenant_id), None)
    if index is None:
        raise KeyError(tenant_id)
    tenant = state["tenants"][index]
    next_workspace = payload.get("workspace_id")
    if next_workspace is not None and any(
        item["workspace_id"] == next_workspace and item["tenant_id"] != tenant_id for item in state["tenants"]
    ):
        raise ValueError(f"workspace_exists:{next_workspace}")
    for field in ("name", "workspace_id", "plan", "status", "operational_retention_mode", "operational_retention_hours"):
        value = payload.get(field)
        if value is not None:
            tenant[field] = int(value) if field == "operational_retention_hours" else value
    _save_state(state)
    return next(item for item in list_tenants() if item["tenant_id"] == tenant_id)


def get_tenant_by_workspace(workspace_id: str) -> Optional[dict]:
    for tenant in list_tenants():
        if tenant["workspace_id"] == workspace_id:
            return tenant
    return None


def list_users() -> list[dict]:
    return [deepcopy(_normalize_user(item)) for item in _load_state()["users"]]


def _find_user_index(user_id: str) -> Optional[int]:
    state = _load_state()
    for index, user in enumerate(state["users"]):
        if user["user_id"] == user_id:
            return index
    return None


def get_user(user_id: str) -> Optional[dict]:
    for user in list_users():
        if user["user_id"] == user_id:
            return user
    return None


def get_user_by_email(email: str) -> Optional[dict]:
    normalized_email = email.strip().lower()
    for user in list_users():
        if user["email"].strip().lower() == normalized_email:
            return user
    return None


def _ensure_tenant_exists(tenant_id: str) -> None:
    if get_tenant(tenant_id) is None:
        raise KeyError(tenant_id)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _utc_now().isoformat().replace("+00:00", "Z")


def create_user(payload: dict) -> dict:
    state = _load_state()
    user_id = payload["user_id"]
    if any(item["user_id"] == user_id for item in state["users"]):
        raise ValueError(f"user_exists:{user_id}")
    if get_user_by_email(payload["email"]) is not None:
        raise ValueError(f"user_email_exists:{payload['email']}")
    _ensure_tenant_exists(payload["tenant_id"])
    password = payload.get("password")
    email = str(payload["email"]).strip().lower()
    validate_password_policy(password, email=email)
    role = normalize_role(payload.get("role"))
    now = _now_iso()
    user = {
        "user_id": user_id,
        "name": payload["name"],
        "email": email,
        "role": role,
        "tenant_id": payload.get("tenant_id", "default"),
        "status": payload.get("status", "invited"),
        "password_changed_at": now,
        "created_at": now,
        "updated_at": now,
        "must_change_password": bool(payload.get("status", "invited") != "active"),
        "permission_overrides": {},
    }
    if password:
        salt_hex = secrets.token_hex(16)
        user["password_salt"] = salt_hex
        user["password_hash"] = hash_password(password, salt_hex)
    state["users"].append(user)
    _save_state(state)
    return _normalize_user(user)


def update_user(user_id: str, payload: dict) -> dict:
    state = _load_state()
    index = next((idx for idx, item in enumerate(state["users"]) if item["user_id"] == user_id), None)
    if index is None:
        raise KeyError(user_id)
    user = state["users"][index]
    previous_role = normalize_role(user.get("role"))
    next_tenant = payload.get("tenant_id")
    if next_tenant is not None:
        _ensure_tenant_exists(next_tenant)
    next_email = payload.get("email")
    if next_email is not None and any(
        item["email"].strip().lower() == next_email.strip().lower() and item["user_id"] != user_id
        for item in state["users"]
    ):
        raise ValueError(f"user_email_exists:{next_email}")
    next_role = normalize_role(payload.get("role")) if payload.get("role") is not None else None
    if (
        previous_role == "super_admin"
        and next_role is not None
        and next_role != "super_admin"
        and (
            payload.get("approve_sensitive_change") is not True
            or not str(payload.get("approval_ticket") or "").strip()
        )
    ):
        raise ValueError("role_change_requires_approval")
    if next_email is not None:
        user["email"] = next_email.strip().lower()
    for field in ("name", "email", "role", "tenant_id", "status"):
        value = payload.get(field)
        if value is not None:
            if field == "status" and value != user.get("status"):
                user["status_changed_at"] = _now_iso()
                if value == "disabled":
                    user["deactivated_at"] = user["status_changed_at"]
            if field == "role" and value != previous_role:
                user["role_changed_at"] = _now_iso()
            user[field] = next_role if field == "role" else (value.strip().lower() if field == "email" else value)
    if payload.get("password") is not None:
        validate_password_policy(payload["password"], email=user.get("email", ""))
        salt_hex = secrets.token_hex(16)
        user["password_salt"] = salt_hex
        user["password_hash"] = hash_password(payload["password"], salt_hex)
        user["password_changed_at"] = _now_iso()
        user["must_change_password"] = False
    if payload.get("must_change_password") is not None:
        user["must_change_password"] = bool(payload["must_change_password"])
    user["role"] = normalize_role(user.get("role"))
    user["updated_at"] = _now_iso()
    _save_state(state)
    return _normalize_user(user)


def delete_tenant(tenant_id: str) -> bool:
    state = _load_state()
    index = next((idx for idx, item in enumerate(state["tenants"]) if item["tenant_id"] == tenant_id), None)
    if index is None:
        return False
    if tenant_id == "default":
        raise ValueError("tenant_protected:default")
    if any(user["tenant_id"] == tenant_id for user in state["users"]):
        raise ValueError(f"tenant_in_use:{tenant_id}")
    from services.document_registry import get_corpus_overview

    tenant = state["tenants"][index]
    overview = get_corpus_overview(tenant["workspace_id"])
    if int(overview.get("documents", 0) or 0) > 0:
        raise ValueError(f"tenant_has_documents:{tenant_id}")
    state["tenants"].pop(index)
    _save_state(state)
    return True


def delete_user(user_id: str) -> bool:
    state = _load_state()
    index = next((idx for idx, item in enumerate(state["users"]) if item["user_id"] == user_id), None)
    if index is None:
        return False
    state["users"].pop(index)
    _save_state(state)
    return True


def set_user_password(user_id: str, new_password: str, *, must_change_password: bool = False) -> dict:
    state = _load_state()
    index = next((idx for idx, item in enumerate(state["users"]) if item["user_id"] == user_id), None)
    if index is None:
        raise KeyError(user_id)
    user = state["users"][index]
    validate_password_policy(new_password, email=user.get("email", ""))
    salt_hex = secrets.token_hex(16)
    user["password_salt"] = salt_hex
    user["password_hash"] = hash_password(new_password, salt_hex)
    user["password_changed_at"] = _now_iso()
    user["updated_at"] = _now_iso()
    user["must_change_password"] = bool(must_change_password)
    if user.get("status") == "invited":
        user["status"] = "active"
        user["status_changed_at"] = _now_iso()
    _save_state(state)
    return _normalize_user(user)


def get_accessible_tenants(user: dict) -> list[dict]:
    if normalize_role(user.get("role")) == "super_admin":
        return [tenant for tenant in list_tenants() if tenant["status"] == "active"]
    tenant = get_tenant(user["tenant_id"])
    if not tenant or tenant["status"] != "active":
        return []
    return [tenant]


def can_access_tenant(user: dict, tenant_id: str) -> bool:
    return any(tenant["tenant_id"] == tenant_id for tenant in get_accessible_tenants(user))


def _sanitize_admin_metadata(metadata: dict | None) -> dict:
    payload = deepcopy(metadata or {})
    for key, value in list(payload.items()):
        if "password" in key.lower():
            payload[key] = "[redacted]"
        elif "token" in key.lower():
            payload[key] = "[redacted]"
        elif isinstance(value, dict):
            payload[key] = _sanitize_admin_metadata(value)
    return payload


def list_admin_events(
    limit: int = 50,
    offset: int = 0,
    action: str | None = None,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
) -> dict:
    events: list[dict] = []
    if ADMIN_EVENTS_PATH.exists():
        with ADMIN_EVENTS_PATH.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if action and event.get("action") != action:
                    continue
                if tenant_id is not None and event.get("tenant_id") != tenant_id:
                    continue
                if workspace_id is not None:
                    metadata = event.get("metadata") or {}
                    event_workspace_id = metadata.get("workspace_id") if isinstance(metadata, dict) else None
                    if event_workspace_id != workspace_id and event.get("target_id") != workspace_id:
                        continue
                event["metadata"] = _sanitize_admin_metadata(event.get("metadata"))
                events.append(event)

    events.sort(key=lambda item: item.get("timestamp") or "", reverse=True)
    total = len(events)
    return {
        "items": events[offset : offset + limit],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def log_admin_event(
    *,
    actor_user_id: str,
    actor_email: str,
    actor_role: str,
    action: str,
    target_type: str,
    target_id: str,
    tenant_id: str | None = None,
    metadata: dict | None = None,
) -> None:
    append_admin_event(
        {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "type": "admin_event",
            "actor_user_id": actor_user_id,
            "actor_email": actor_email,
            "actor_role": actor_role,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "tenant_id": tenant_id,
            "metadata": metadata or {},
        }
    )
