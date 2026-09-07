"""Identity facade — orchestration only, calls packages/identity + packages/authorization.

THREADS NO POLICY: role maps, permission tables, alias rules and effective
resolution all live in the canonical packages. This module wires stores,
selects the credential verifier per RICK_IDENTITY_MODE (fail-closed in
production with the test verifier), seeds hermetic demo users only outside
production, and translates canonical snapshots to the API boundary model.

Provider modes:
- test/dev: PlainTestVerifier + seeded demo users (never production).
- production: PBKDF2 verifier for isolated verifier tests; the API factory
  requires an injected external identity provider and never seeds users.
"""

from __future__ import annotations

import os
import time
import uuid

from rick_authorization import permission_granted
from rick_contracts.security import SessionSnapshot
from rick_identity import (
    IdentityProviderImpl,
    InMemorySessionStore,
    InMemoryUserStore,
    Pbkdf2Verifier,
    PlainTestVerifier,
)
from rick_identity.passwords import hash_password


def _mode() -> str:
    return (os.getenv("RICK_IDENTITY_MODE") or "dev").strip().lower()


class InMemoryIdentityProvider:
    """Hermetic provider for tests/dev. Policy-free: delegates everything."""

    def __init__(self, *, mode: str | None = None, verifier: object | None = None) -> None:
        self.mode = (mode or _mode()).lower()
        self.production_safe = False
        self._users = InMemoryUserStore()
        self._sessions = InMemorySessionStore()
        if verifier is None:
            verifier = Pbkdf2Verifier() if self.mode == "production" else PlainTestVerifier()
        if self.mode == "production" and isinstance(verifier, PlainTestVerifier):
            raise RuntimeError("Refusing to start: test credential verifier selected in production mode.")
        self._provider = IdentityProviderImpl(users=self._users, sessions=self._sessions, verifier=verifier)  # type: ignore[arg-type]
        self._login_attempts: dict[str, list[float]] = {}
        self._seed_demo_users()

    # -- seed data (DATA, not policy: grants/overrides resolved by canonical engine) --
    def _seed_demo_users(self) -> None:
        # This provider is intentionally hermetic. Production must inject a
        # real external identity implementation; never create a universal
        # password or demo account in a production-shaped process.
        if self.mode == "production":
            return
        seeds = [
            {"user_id": "admin", "email": "admin@example.com", "role": "PLATFORM_ADMIN",
             "tenant_id": "default", "workspace_id": "default",
             "permission_overrides": {"add": [], "remove": []}, "authorized_collection_ids": []},
            {"user_id": "km", "email": "km@example.com", "role": "KNOWLEDGE_MANAGER",
             "tenant_id": "default", "workspace_id": "default",
             "permission_overrides": {"add": [], "remove": []}, "authorized_collection_ids": []},
            {"user_id": "vet", "email": "vet@example.com", "role": "VETERINARIAN",
             "tenant_id": "default", "workspace_id": "default",
             "permission_overrides": {"add": [], "remove": []}, "authorized_collection_ids": ["rag_phase0"]},
        ]
        for record in seeds:
            record = {**record, "password_plain": "password123"}
            self._users.seed({**record, "status": "active", "password_version": 1, "role_version": 1})

    # -- rate limiting (transport-level, not RBAC policy) --
    def check_login_rate(self, key: str, *, limit_per_min: int) -> None:
        from core.errors import ApiError

        now = time.monotonic()
        window = [t for t in self._login_attempts.get(key, []) if now - t < 60]
        if len(window) >= limit_per_min:
            raise ApiError("rate_limited")
        window.append(now)
        self._login_attempts[key] = window

    # -- delegation ------------------------------------------------------
    def _to_snapshot(self, data: dict) -> SessionSnapshot:
        if data.get("authenticated") and (
            not isinstance(data.get("tenant_id"), str) or not data["tenant_id"].strip()
        ):
            return SessionSnapshot(authenticated=False, session_state="anonymous", tenant_id=None)
        return SessionSnapshot(**{k: v for k, v in data.items() if k in SessionSnapshot.model_fields})

    def login(self, *, email, password, tenant_id, ip, user_agent) -> dict:
        from core.errors import ApiError

        from rick_identity import IdentityError

        try:
            return self._provider.login(email=email, password=password, tenant_id=tenant_id, ip=ip, user_agent=user_agent)
        except IdentityError as exc:
            raise ApiError(exc.code)

    def validate_token(self, token: str | None) -> SessionSnapshot:
        return self._to_snapshot(self._provider.validate_session(token))

    def logout(self, token: str | None) -> None:
        self._provider.logout(token)

    def list_sessions(self, user_id: str) -> list[dict]:
        user = self._users.get_by_id(user_id)
        tenant_id = (user or {}).get("tenant_id")
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            return []
        return [
            {**item, "tenant_id": tenant_id}
            for item in self._provider.list_sessions(user_id)
            if isinstance(item, dict)
        ]

    def list_users(self) -> list[dict]:
        """Return the store's redacted user view; never expose credentials."""
        records = getattr(self._users, "_by_id", {})
        if not isinstance(records, dict):
            return []
        items = []
        for user_id in records:
            user = self._provider.get_user(user_id)
            if user is not None:
                items.append(user)
        return items

    def create_user(self, *, email: str, role: str, tenant_id: str, password: str) -> dict:
        """Create a real hermetic user; external providers own production writes."""
        from core.errors import ApiError

        normalized_email = (email or "").strip().lower()
        if self._users.get_by_email(normalized_email) is not None:
            raise ApiError("conflict")
        record = {
            "user_id": f"user-{uuid.uuid4().hex[:16]}",
            "email": normalized_email,
            "role": role,
            "tenant_id": tenant_id,
            "workspace_id": "default",
            "status": "active",
            "permission_overrides": {"add": [], "remove": []},
            "authorized_collection_ids": [],
            "password_version": 1,
            "role_version": 1,
        }
        if self.mode == "production":
            record["password_hash"] = hash_password(password)
        else:
            record["password_plain"] = password
        self._users.save(record)
        return self._provider.get_user(record["user_id"]) or {
            "user_id": record["user_id"], "email": normalized_email, "role": role,
        }

    def revoke_session_by_id(self, *, actor, session_id: str) -> int:
        """Resolve a session identifier without exposing bearer tokens."""
        for token in list(self._sessions._sessions):
            record = self._sessions.get(token)
            if record and record.get("session_id") == session_id:
                self._assert_same_tenant(actor, record.get("user_id"))
                return self._provider.revoke_session(token)
        return 0

    def _assert_same_tenant(self, actor, user_id: str | None) -> None:
        from core.errors import ApiError

        target = self._users.get_by_id(user_id or "")
        actor_tenant = getattr(actor, "tenant_id", None)
        target_tenant = target.get("tenant_id") if isinstance(target, dict) else None
        if (
            not isinstance(actor_tenant, str)
            or not actor_tenant.strip()
            or not isinstance(target_tenant, str)
            or not target_tenant.strip()
            or target_tenant != actor_tenant
        ):
            raise ApiError("forbidden")

    def revoke(self, *, actor, target_token, target_session_id, target_user_id, revoke_all) -> int:
        from core.errors import ApiError

        target_uid = target_user_id or getattr(actor, "user_id", None)
        if target_uid != getattr(actor, "user_id", None) and not permission_granted(
            role=None, permissions=list(getattr(actor, "permissions", None) or []),
            required="sessions.revoke", authoritative=True,
        ):
            raise ApiError("forbidden")
        self._assert_same_tenant(actor, target_uid)
        if revoke_all:
            # Owner-safe: cross-user revoke-all already gated above.
            count = 0
            for token in list(self._sessions.tokens_for_user(target_uid)):
                count += self._provider.revoke_session(token)
            return count
        token = target_token
        if target_session_id:
            token = next(
                (t for t in self._sessions.tokens_for_user(target_uid)
                 if (self._sessions.get(t) or {}).get("session_id") == target_session_id),
                None,
            )
            if token is None:
                raise ApiError("forbidden")
        if token:
            record = self._sessions.get(token)
            if record is None or record.get("user_id") != target_uid:
                raise ApiError("forbidden")
            return self._provider.revoke_session(token)
        return 0
