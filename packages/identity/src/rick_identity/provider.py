"""Canonical identity provider: lifecycle + snapshots; policy delegated to rick_authorization.

Snapshot authority:
- Modern sessions persist an explicit `permissions` list + version 1 +
  state AUTHORITATIVE/MIGRATED. That immutable snapshot is the maximum scope;
  validation intersects it with current user authority, never restoring a
  snapshot removal through role defaults or newly added grants.
- Sessions without a snapshot (state LEGACY_UNMIGRATED) are migrated exactly
  once: derive from current user authority, preserve legacy session ceilings,
  persist, mark MIGRATED.

Invalidation: logout / expiry / revoked / disabled user / password_version or
role_version newer than the session's captured versions.
"""

from __future__ import annotations

import copy
import time

from rick_authorization import (
    AUTHORIZATION_SNAPSHOT_VERSION,
    allowed_collection_ids_for_user,
    canonical_role,
    authorization_grants_for_user,
    intersect_grants,
    legacy_role_label,
    normalize_permission_overrides,
    permissions_for_role,
)
from rick_identity.passwords import verify_password_hash
from rick_identity.snapshots import known_role, legacy_snapshot, valid_authorization_snapshot


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


def _required_workspace_id(value: object) -> str:
    """Return an explicit workspace binding or fail closed."""

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
        tenant_lookup = getattr(self.users, "get_by_email_for_tenant", None)
        if not callable(tenant_lookup):
            raise IdentityError("unauthorized")
        user = tenant_lookup(email, tenant_id)
        if user is None or not self.verifier.verify(user, password):
            raise IdentityError("unauthorized")
        if (
            user.get("status", "active") != "active"
            or user.get("membership_status", "active") != "active"
        ):
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
            "workspace_id": _required_workspace_id(user.get("workspace_id", "default")),
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
        record = copy.deepcopy(record)
        if not valid_authorization_snapshot(record):
            return _anonymous_snapshot()
        now = time.time()
        if record.get("revoked_at") is not None or now >= record.get("expires_at", 0):
            return _anonymous_snapshot()
        try:
            session_tenant = _required_tenant_id(record.get("tenant_id"))
            session_workspace = _required_workspace_id(record.get("workspace_id", "default"))
        except IdentityError:
            return _anonymous_snapshot()
        scoped_lookup = getattr(self.users, "get_by_id_for_tenant_workspace", None)
        if not callable(scoped_lookup):
            return _anonymous_snapshot()
        user = scoped_lookup(
            record.get("user_id") or "", session_tenant, session_workspace
        )
        if (
            user is None
            or user.get("status", "active") != "active"
            or user.get("membership_status", "active") != "active"
        ):
            return _anonymous_snapshot()
        try:
            user_tenant = _required_tenant_id(user.get("tenant_id"))
            session_tenant = _required_tenant_id(record.get("tenant_id"))
        except IdentityError:
            return _anonymous_snapshot()
        if session_tenant != user_tenant:
            return _anonymous_snapshot()
        try:
            user_workspace = user.get("workspace_id", "default")
            session_workspace = record.get("workspace_id", "default")
            if (
                not isinstance(user_workspace, str)
                or not user_workspace.strip()
                or not isinstance(session_workspace, str)
                or not session_workspace.strip()
                or user_workspace.strip() != session_workspace.strip()
            ):
                return _anonymous_snapshot()
        except (AttributeError, TypeError):
            return _anonymous_snapshot()
        if user.get("password_version", 1) != record.get("password_version", 1):
            return _anonymous_snapshot()  # password change invalidates
        if user.get("role_version", 1) != record.get("role_version", 1):
            return _anonymous_snapshot()  # role change invalidates
        if not known_role(user.get("role")):
            return _anonymous_snapshot()
        current_role = canonical_role(user["role"])
        # Explicit one-time migration for legacy records without a snapshot.
        if legacy_snapshot(record):
            if "role" in record:
                old_defaults = permissions_for_role(record["role"])
                current_defaults = permissions_for_role(current_role)
                if intersect_grants(old_defaults, current_defaults) != current_defaults:
                    return _anonymous_snapshot()  # a role promotion needs a fresh login
            migrated = self._migrate_legacy_record(record, user)
            persist = getattr(self.sessions, "update_authorization_snapshot", None)
            if not callable(persist) or not persist(token, expected=record, snapshot=migrated):
                return _anonymous_snapshot()
            record = {**record, **migrated}
        elif record["canonical_role"] != current_role:
            return _anonymous_snapshot()  # role changes must not rely on a port bumping versions
        # Public validation rechecks revocations even for ports that preserve
        # version numbers. The stored modern snapshot remains an immutable
        # ceiling: neither its explicit removals nor finite scope can widen.
        current = authorization_grants_for_user(user)
        record["permissions"] = intersect_grants(record["permissions"], current["permissions"])
        record["allowed_collection_ids"] = intersect_grants(
            record["allowed_collection_ids"], current["allowed_collection_ids"],
        )
        self.sessions.touch(token)
        return self._snapshot(record)

    def _migrate_legacy_record(self, record: dict, user: dict) -> dict:
        role = canonical_role(user.get("role"))
        overrides = normalize_permission_overrides(user.get("permission_overrides"))
        permissions = permissions_for_role(role, overrides)
        if "role" in record:
            permissions = intersect_grants(permissions_for_role(record["role"]), permissions)
        collections = allowed_collection_ids_for_user(user)
        if "allowed_collection_ids" in record:
            previous = allowed_collection_ids_for_user({
                "authorized_collection_ids": record["allowed_collection_ids"],
            })
            collections = intersect_grants(previous, collections)
        return {
            "role": legacy_role_label(role),
            "canonical_role": role,
            "permissions": permissions,
            "authorization_snapshot_version": AUTHORIZATION_SNAPSHOT_VERSION,
            "authorization_state": "MIGRATED",
            "allowed_collection_ids": collections,
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
            "workspace_id": record.get("workspace_id", "default"),
            "session_id": record.get("session_id"),
            "allowed_collection_ids": list(record.get("allowed_collection_ids") or []),
        }

    # -- lifecycle -------------------------------------------------------
    def logout(self, token: str | None) -> None:
        if token:
            self.sessions.delete(token)

    def list_sessions(self, user_id: str) -> list[dict]:
        listed = getattr(self.sessions, "list_for_user", None)
        if callable(listed):
            return list(listed(user_id) or [])
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
        revoke = getattr(self.sessions, "revoke", None)
        if callable(revoke):
            return int(revoke(token, reason="manual_revoke"))
        self.sessions.delete(token)
        return 1

    def revoke_user_sessions(self, user_id: str, *, reason: str = "manual_revoke") -> int:
        revoke_all = getattr(self.sessions, "revoke_user", None)
        if callable(revoke_all):
            return int(revoke_all(user_id, reason=reason))
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
