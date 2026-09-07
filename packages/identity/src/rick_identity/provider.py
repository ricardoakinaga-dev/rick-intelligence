"""Canonical identity provider: lifecycle + snapshots; policy delegated to rick_authorization.

Snapshot authority:
- Modern sessions persist an explicit `permissions` list + version 1 +
  state AUTHORITATIVE/MIGRATED. That list is final — the engine is always
  consulted with authoritative semantics, so removals can never be re-granted.
- Sessions without a snapshot (state LEGACY_UNMIGRATED) are migrated exactly
  once: derive from role+overrides, persist, mark MIGRATED.

Invalidation: logout / expiry / revoked / disabled user / password_version or
role_version newer than the session's captured versions.
"""

from __future__ import annotations

import time

from rick_authorization import (
    AUTHORIZATION_SNAPSHOT_VERSION,
    allowed_collection_ids_for_user,
    canonical_role,
    legacy_role_label,
    normalize_permission_overrides,
    permissions_for_role,
)
from rick_identity.passwords import verify_password_hash


class IdentityError(Exception):
    def __init__(self, code: str = "unauthorized"):
        super().__init__(code)
        self.code = code


class Pbkdf2Verifier:
    def verify(self, user_record: dict, password: str) -> bool:
        stored = user_record.get("password_hash") or ""
        return bool(stored) and verify_password_hash(stored, password)


class PlainTestVerifier:
    """TEST-ONLY verifier. Refused in production mode (fail-closed startup)."""

    def verify(self, user_record: dict, password: str) -> bool:
        return bool(password) and user_record.get("password_plain") == password


def _required_tenant_id(value: object) -> str:
    """Return an explicit tenant binding or fail closed."""

    if not isinstance(value, str) or not value.strip():
        raise IdentityError("forbidden")
    return value.strip()


def _anonymous_snapshot() -> dict:
    return {
        "authenticated": False,
        "session_state": "anonymous",
        "user_id": None,
        "email": None,
        "role": None,
        "canonical_role": None,
        "permissions": [],
        "authorization_snapshot_version": AUTHORIZATION_SNAPSHOT_VERSION,
        "authorization_state": "AUTHORITATIVE",
        "tenant_id": None,
        "workspace_id": None,
        "session_id": None,
        "allowed_collection_ids": [],
    }


class IdentityProviderImpl:
    def __init__(self, *, users, sessions, verifier, tenant_policy=None) -> None:
        self.users = users
        self.sessions = sessions
        self.verifier = verifier
        self.tenant_policy = tenant_policy or (lambda user, tenant_id: tenant_id == user.get("tenant_id"))

    # -- login -----------------------------------------------------------
    def login(self, *, email, password, tenant_id, ip, user_agent) -> dict:
        user = self.users.get_by_email(email)
        if user is None or not self.verifier.verify(user, password):
            raise IdentityError("unauthorized")
        if user.get("status", "active") != "active":
            raise IdentityError("forbidden")
        requested_tenant = _required_tenant_id(tenant_id)
        user_tenant = _required_tenant_id(user.get("tenant_id"))
        if user_tenant != requested_tenant or not self.tenant_policy(user, requested_tenant):
            raise IdentityError("forbidden")
        return self._issue_session(user, tenant_id=requested_tenant, ip=ip, user_agent=user_agent)

    def _issue_session(self, user: dict, *, tenant_id: str, ip, user_agent) -> dict:
        role = canonical_role(user.get("role"))
        overrides = normalize_permission_overrides(user.get("permission_overrides"))
        effective = permissions_for_role(role, overrides)
        record = {
            "user_id": user["user_id"],
            "email": user.get("email"),
            "role": legacy_role_label(role),
            "canonical_role": role,
            "permissions": effective,
            "authorization_snapshot_version": AUTHORIZATION_SNAPSHOT_VERSION,
            "authorization_state": "AUTHORITATIVE",
            "tenant_id": tenant_id,
            "workspace_id": user.get("workspace_id", "default"),
            "allowed_collection_ids": allowed_collection_ids_for_user(user),
            "password_version": user.get("password_version", 1),
            "role_version": user.get("role_version", 1),
            "ip": ip,
            "user_agent": (user_agent or "")[:256] if user_agent else None,
        }
        token = self.sessions.create(record)
        return {"session_token": token, "session_id": self.sessions.get(token)["session_id"], "user_id": user["user_id"]}

    # -- validation ------------------------------------------------------
    def validate_session(self, token: str | None) -> dict:
        if not token:
            return _anonymous_snapshot()
        record = self.sessions.get(token)
        if record is None:
            return _anonymous_snapshot()
        now = time.time()
        if record.get("revoked_at") is not None or now >= record.get("expires_at", 0):
            return _anonymous_snapshot()
        user = self.users.get_by_id(record.get("user_id") or "")
        if user is None or user.get("status", "active") != "active":
            return _anonymous_snapshot()
        try:
            user_tenant = _required_tenant_id(user.get("tenant_id"))
            session_tenant = _required_tenant_id(record.get("tenant_id"))
        except IdentityError:
            return _anonymous_snapshot()
        if session_tenant != user_tenant:
            return _anonymous_snapshot()
        if user.get("password_version", 1) != record.get("password_version", 1):
            return _anonymous_snapshot()  # password change invalidates
        if user.get("role_version", 1) != record.get("role_version", 1):
            return _anonymous_snapshot()  # role change invalidates
        # Explicit one-time migration for legacy records without a snapshot.
        if record.get("authorization_state") == "LEGACY_UNMIGRATED" or "permissions" not in record:
            migrated = self._migrate_legacy_record(record, user)
            record.update(migrated)
        self.sessions.touch(token)
        return self._snapshot(record)

    def _migrate_legacy_record(self, record: dict, user: dict) -> dict:
        role = canonical_role(record.get("role") or user.get("role"))
        overrides = normalize_permission_overrides(user.get("permission_overrides"))
        return {
            "canonical_role": role,
            "permissions": permissions_for_role(role, overrides),
            "authorization_snapshot_version": AUTHORIZATION_SNAPSHOT_VERSION,
            "authorization_state": "MIGRATED",
            "allowed_collection_ids": allowed_collection_ids_for_user(user),
            "password_version": user.get("password_version", 1),
            "role_version": user.get("role_version", 1),
        }

    def _snapshot(self, record: dict) -> dict:
        return {
            "authenticated": True,
            "session_state": "active",
            "user_id": record.get("user_id"),
            "email": record.get("email"),
            "role": record.get("role"),
            "canonical_role": record.get("canonical_role"),
            "permissions": list(record.get("permissions") or []),
            "authorization_snapshot_version": record.get(
                "authorization_snapshot_version", AUTHORIZATION_SNAPSHOT_VERSION
            ),
            "authorization_state": record.get("authorization_state", "AUTHORITATIVE"),
            "tenant_id": record.get("tenant_id"),
            "workspace_id": record.get("workspace_id"),
            "session_id": record.get("session_id"),
            "allowed_collection_ids": list(record.get("allowed_collection_ids") or []),
        }

    # -- lifecycle -------------------------------------------------------
    def logout(self, token: str | None) -> None:
        if token:
            self.sessions.delete(token)

    def list_sessions(self, user_id: str) -> list[dict]:
        items = []
        for token in self.sessions.tokens_for_user(user_id):
            record = self.sessions.get(token)
            if record is None:
                continue
            items.append(
                {
                    "session_id": record.get("session_id"),
                    "user_id": user_id,
                    "created_at": record.get("created_at"),
                    "revoked": record.get("revoked_at") is not None,
                }
            )
        return items

    def revoke_session(self, token: str) -> int:
        if self.sessions.get(token) is None:
            return 0
        self.sessions.delete(token)
        return 1

    def revoke_user_sessions(self, user_id: str, *, reason: str = "manual_revoke") -> int:
        tokens = self.sessions.tokens_for_user(user_id)
        for token in tokens:
            self.sessions.delete(token)
        return len(tokens)

    def get_user(self, user_id: str) -> dict | None:
        user = self.users.get_by_id(user_id)
        if user is None:
            return None
        redacted = {k: v for k, v in user.items() if k not in {"password_hash", "password_plain"}}
        return redacted
