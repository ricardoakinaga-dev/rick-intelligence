"""Identity facade — orchestration only, calls packages/identity + packages/authorization.

THREADS NO POLICY: role maps, permission tables, alias rules and effective
resolution all live in the canonical packages. This module wires stores,
selects the credential verifier per RICK_IDENTITY_MODE (fail-closed in
production with the test verifier), seeds hermetic demo users as DATA, and
translates canonical snapshots to the API boundary model.

Provider modes:
- test/dev: PlainTestVerifier + seeded demo users (never production).
- production: PBKDF2 verifier; startup FAILS if the test verifier is selected.
"""

from __future__ import annotations

import os
import time

from rick_authorization import permission_granted
from rick_contracts.security import SessionSnapshot
from rick_identity import (
    IdentityProviderImpl,
    InMemorySessionStore,
    InMemoryUserStore,
    Pbkdf2Verifier,
    PlainTestVerifier,
    hash_password,
)


def _mode() -> str:
    return (os.getenv("RICK_IDENTITY_MODE") or "dev").strip().lower()


class InMemoryIdentityProvider:
    """Hermetic provider for tests/dev. Policy-free: delegates everything."""

    def __init__(self, *, mode: str | None = None, verifier: object | None = None) -> None:
        self.mode = (mode or _mode()).lower()
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
            if self.mode == "production":
                record = {**record, "password_hash": hash_password("changeme-immediately")}
            else:
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
        return self._provider.list_sessions(user_id)

    def revoke(self, *, actor, target_token, target_session_id, target_user_id, revoke_all) -> int:
        from core.errors import ApiError

        target_uid = target_user_id or getattr(actor, "user_id", None)
        if target_uid != getattr(actor, "user_id", None) and not permission_granted(
            role=None, permissions=list(getattr(actor, "permissions", None) or []),
            required="sessions.revoke", authoritative=True,
        ):
            raise ApiError("forbidden")
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
