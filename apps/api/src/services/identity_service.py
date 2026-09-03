"""In-memory identity provider (default) + protocol. Legacy CVG adapter plugs in via RICK_API_USE_LEGACY."""

from __future__ import annotations

import hashlib
import secrets
import time
from typing import Protocol

from core.errors import ApiError
from models import SessionSnapshot

CANONICAL_PERMISSIONS = {
    "PLATFORM_ADMIN": ["*"],
    "KNOWLEDGE_MANAGER": [
        "chat.query", "history.read", "sources.read", "collections.read", "library.browse",
        "documents.read", "documents.upload", "documents.delete", "ingestion.run", "reindex.run",
        "observability.read", "audit.read",
    ],
    "VETERINARIAN": ["chat.query", "history.read", "sources.read", "collections.read"],
}

LEGACY_ROLE_MAP = {
    "admin": "PLATFORM_ADMIN", "super_admin": "PLATFORM_ADMIN",
    "operator": "KNOWLEDGE_MANAGER", "admin_rag": "KNOWLEDGE_MANAGER",
    "viewer": "VETERINARIAN", "veterinarian": "VETERINARIAN", "auditor": "VETERINARIAN",
}


def canonical_role(role: str | None) -> str:
    if not role:
        return "VETERINARIAN"
    role = role.strip()
    if role in CANONICAL_PERMISSIONS:
        return role
    return LEGACY_ROLE_MAP.get(role.lower(), "VETERINARIAN")


class IdentityProvider(Protocol):
    def login(self, *, email: str, password: str, tenant_id: str, ip: str | None, user_agent: str | None) -> dict: ...
    def validate_token(self, token: str | None) -> SessionSnapshot: ...
    def logout(self, token: str | None) -> None: ...
    def list_sessions(self, user_id: str) -> list[dict]: ...
    def revoke(self, *, actor: SessionSnapshot, target_token: str | None, target_session_id: str | None, target_user_id: str | None, revoke_all: bool) -> int: ...


class InMemoryIdentityProvider:
    """Hermetic default so apps/api is executable without legacy services.

    Seeded demo users (password `password123` is only for local/dev tests):
    - admin@example.com / PLATFORM_ADMIN
    - km@example.com / KNOWLEDGE_MANAGER
    - vet@example.com / VETERINARIAN (granted collections: [rag_phase0])
    """

    def __init__(self) -> None:
        self._users: dict[str, dict] = {}
        self._sessions: dict[str, dict] = {}
        self._login_attempts: dict[str, list[float]] = {}
        for email, role, collections in [
            ("admin@example.com", "PLATFORM_ADMIN", []),
            ("km@example.com", "KNOWLEDGE_MANAGER", []),
            ("vet@example.com", "VETERINARIAN", ["rag_phase0"]),
        ]:
            self._users[email] = {
                "user_id": email.split("@")[0],
                "email": email,
                "password": "password123",
                "role": role,
                "tenant_id": "default",
                "workspace_id": "default",
                "allowed_collection_ids": collections,
            }

    # -- rate limiting (in-process; Redis-backed limiter interface ready, see services/rate_limit) --
    def check_login_rate(self, key: str, *, limit_per_min: int) -> None:
        now = time.monotonic()
        window = [t for t in self._login_attempts.get(key, []) if now - t < 60]
        if len(window) >= limit_per_min:
            raise ApiError("rate_limited")
        window.append(now)
        self._login_attempts[key] = window

    def login(self, *, email, password, tenant_id, ip, user_agent) -> dict:
        user = self._users.get(email.strip().lower())
        if user is None or user["password"] != password:
            raise ApiError("unauthorized")
        if tenant_id not in ("default", user["tenant_id"]):
            raise ApiError("forbidden")
        token = secrets.token_urlsafe(32)
        session_id = hashlib.sha256(token.encode()).hexdigest()[:16]
        self._sessions[token] = {
            "session_id": session_id, "user_id": user["user_id"], "email": user["email"],
            "role": user["role"], "tenant_id": user["tenant_id"], "workspace_id": user["workspace_id"],
            "allowed_collection_ids": list(user["allowed_collection_ids"]), "created": time.time(),
        }
        return {"session_token": token, "session_id": session_id, "user": user}

    def validate_token(self, token: str | None) -> SessionSnapshot:
        if not token:
            return SessionSnapshot()
        record = self._sessions.get(token)
        if record is None:
            return SessionSnapshot()
        role = record["role"]
        return SessionSnapshot(
            authenticated=True, session_state="active", user_id=record["user_id"], email=record["email"],
            role=role.lower() if role == "VETERINARIAN" else role, canonical_role=canonical_role(role),
            permissions=list(CANONICAL_PERMISSIONS[canonical_role(role)]),
            tenant_id=record["tenant_id"], workspace_id=record["workspace_id"],
            session_id=record["session_id"], allowed_collection_ids=list(record["allowed_collection_ids"]),
        )

    def logout(self, token: str | None) -> None:
        if token:
            self._sessions.pop(token, None)

    def list_sessions(self, user_id: str) -> list[dict]:
        return [
            {"session_id": rec["session_id"], "user_id": rec["user_id"], "created": rec["created"]}
            for rec in self._sessions.values() if rec["user_id"] == user_id
        ]

    def _token_for_session_id(self, session_id: str) -> str | None:
        for token, rec in self._sessions.items():
            if rec["session_id"] == session_id:
                return token
        return None

    def revoke(self, *, actor, target_token, target_session_id, target_user_id, revoke_all) -> int:
        from services.authorization_service import has_permission

        target_uid = target_user_id or actor.user_id
        if target_uid != actor.user_id and not has_permission(actor, "sessions.revoke"):
            raise ApiError("forbidden")
        if revoke_all:
            tokens = [t for t, r in self._sessions.items() if r["user_id"] == target_uid]
            for t in tokens:
                self._sessions.pop(t, None)
            return len(tokens)
        token = target_token
        if target_session_id:
            token = self._token_for_session_id(target_session_id)
            if token is None:
                raise ApiError("forbidden")
        if token:
            rec = self._sessions.get(token)
            if rec is None or rec["user_id"] != target_uid:
                if target_uid != actor.user_id and not has_permission(actor, "sessions.revoke"):
                    raise ApiError("forbidden")
                if rec is None or rec["user_id"] != target_uid:
                    raise ApiError("forbidden")
            self._sessions.pop(token, None)
            return 1
        # revoke current session is handled by caller passing current token
        return 0
