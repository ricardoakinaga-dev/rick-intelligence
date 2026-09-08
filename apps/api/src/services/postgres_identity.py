"""Tenant-scoped identity facade backed by the canonical PostgreSQL stores.

The facade keeps API orchestration and error translation out of the canonical
identity package. It is intentionally injectable: constructing it does not
import a driver or open a connection. Local password login uses the existing
PBKDF2 format for migration compatibility; D02 still decides whether local
credentials remain in the deployed identity model.
"""

from __future__ import annotations

from collections.abc import Callable
import time
import uuid

from rick_authorization import (
    CANONICAL_ROLES,
    LEGACY_ROLE_ALIASES,
    canonical_role,
    permission_granted,
)
from rick_contracts.security import SessionSnapshot
from rick_identity import (
    IdentityError,
    IdentityProviderImpl,
    Pbkdf2Verifier,
    PostgresIdentityError,
    PostgresRecoveryStore,
    PostgresSessionStore,
    PostgresUserStore,
    hash_password,
)


def _role(value: str) -> str:
    candidate = (value or "").strip().lower()
    result = candidate.upper() if candidate.upper() in CANONICAL_ROLES else LEGACY_ROLE_ALIASES.get(candidate)
    if result not in CANONICAL_ROLES:
        raise ValueError("invalid role")
    return result


def _api_error(exc: PostgresIdentityError):
    from core.errors import ApiError

    code = {
        "invalid_input": "validation_error",
        "conflict": "conflict",
        "not_found": "not_found",
        "identity_unavailable": "provider_unavailable",
    }.get(exc.code, "provider_unavailable")
    return ApiError(code)


class PostgresIdentityProvider:
    """Persistent identity implementation for an explicitly composed runtime.

    production_safe defaults to false because D02 has not selected the
    deployed IdP/local-password policy. A deployment composition may set it
    only after that policy and credential source have been approved; the
    application factory still requires all other external providers.
    """

    def __init__(
        self,
        connection_factory: Callable[[], object],
        *,
        session_ttl_seconds: int = 8 * 3600,
        recovery_ttl_seconds: int = 15 * 60,
        production_safe: bool = False,
    ) -> None:
        if not callable(connection_factory):
            raise ValueError("connection factory is required")
        self.production_safe = bool(production_safe)
        self.mode = "postgres"
        self._users = PostgresUserStore(connection_factory)
        self._sessions = PostgresSessionStore(connection_factory, ttl_seconds=session_ttl_seconds)
        self._recovery = PostgresRecoveryStore(connection_factory, ttl_seconds=recovery_ttl_seconds)
        self._provider = IdentityProviderImpl(
            users=self._users,
            sessions=self._sessions,
            verifier=Pbkdf2Verifier(),
        )
        self._login_attempts: dict[str, list[float]] = {}

    def health_check(self) -> bool:
        return self._users.health_check()

    def check_login_rate(self, key: str, *, limit_per_min: int) -> None:
        from core.errors import ApiError

        if (
            not isinstance(key, str)
            or not key.strip()
            or isinstance(limit_per_min, bool)
            or not isinstance(limit_per_min, int)
            or limit_per_min <= 0
        ):
            raise ApiError("validation_error")
        now = time.monotonic()
        window = [item for item in self._login_attempts.get(key, []) if now - item < 60]
        if len(window) >= limit_per_min:
            raise ApiError("rate_limited")
        window.append(now)
        self._login_attempts[key] = window

    @staticmethod
    def _to_snapshot(data: dict) -> SessionSnapshot:
        if data.get("authenticated") and not isinstance(data.get("tenant_id"), str):
            return SessionSnapshot(authenticated=False, session_state="anonymous", tenant_id=None)
        return SessionSnapshot(
            **{key: value for key, value in data.items() if key in SessionSnapshot.model_fields}
        )

    def login(self, *, email, password, tenant_id, ip, user_agent) -> dict:
        try:
            return self._provider.login(
                email=email,
                password=password,
                tenant_id=tenant_id,
                ip=ip,
                user_agent=user_agent,
            )
        except IdentityError as exc:
            from core.errors import ApiError

            raise ApiError(exc.code) from None
        except PostgresIdentityError as exc:
            raise _api_error(exc) from None

    def validate_token(self, token: str | None) -> SessionSnapshot:
        try:
            return self._to_snapshot(self._provider.validate_session(token))
        except PostgresIdentityError:
            # Authentication fails closed while readiness reports storage
            # outage; it never becomes an anonymous cross-tenant fallback.
            return SessionSnapshot(authenticated=False, session_state="anonymous", tenant_id=None)

    def logout(self, token: str | None) -> None:
        try:
            self._provider.logout(token)
        except PostgresIdentityError:
            return

    def _user_for_actor(self, actor, user_id: str) -> dict:
        from core.errors import ApiError

        tenant_id = getattr(actor, "tenant_id", None)
        user = (
            self._users.get_by_id_for_tenant(user_id, tenant_id)
            if isinstance(tenant_id, str)
            else None
        )
        if user is None:
            raise ApiError("forbidden")
        return user

    @staticmethod
    def _require_actor_permission(actor, required: str) -> None:
        from core.errors import ApiError

        tenant_id = getattr(actor, "tenant_id", None)
        permissions = getattr(actor, "permissions", ())
        role = getattr(actor, "canonical_role", None) or getattr(actor, "role", None)
        if (
            not isinstance(tenant_id, str)
            or not tenant_id.strip()
            or not permission_granted(
                role=role,
                permissions=permissions if not isinstance(permissions, str) else (permissions,),
                required=required,
                authoritative=True,
            )
        ):
            raise ApiError("forbidden")

    def list_users(self, *, tenant_id: str | None = None, workspace_id: str | None = None) -> list[dict]:
        try:
            return [
                dict(item)
                for item in self._users.list_users(tenant_id=tenant_id, workspace_id=workspace_id)
            ]
        except PostgresIdentityError as exc:
            raise _api_error(exc) from None

    def list_sessions(self, user_id: str) -> list[dict]:
        try:
            user = self._users.get_by_id(user_id)
            tenant_id = user.get("tenant_id") if isinstance(user, dict) else None
            if not isinstance(tenant_id, str) or not tenant_id.strip():
                return []
            return self._sessions.list_for_user(user_id, tenant_id=tenant_id)
        except PostgresIdentityError as exc:
            raise _api_error(exc) from None

    def list_sessions_for_actor(self, actor) -> list[dict]:
        tenant_id = getattr(actor, "tenant_id", None)
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            return []
        try:
            records = self._sessions.records(tenant_id=tenant_id, limit=100)
            result = []
            for record in records:
                user_id = record.get("user_id")
                user = (
                    self._users.get_by_id_for_tenant(user_id, tenant_id)
                    if isinstance(user_id, str)
                    else None
                )
                if user is None:
                    continue
                result.append(
                    {
                        "session_id": record.get("session_id"),
                        "user_id": user_id,
                        "email": user.get("email"),
                        "tenant_id": tenant_id,
                        "workspace_id": record.get("workspace_id") or user.get("workspace_id"),
                        "created_at": record.get("created_at"),
                        "last_seen_at": record.get("last_seen_at"),
                        "expires_at": record.get("expires_at"),
                        "revoked": record.get("revoked_at") is not None,
                    }
                )
            return result
        except PostgresIdentityError as exc:
            raise _api_error(exc) from None

    def create_user(self, *, email: str, role: str, tenant_id: str, password: str) -> dict:
        from core.errors import ApiError

        normalized_email = (email or "").strip().casefold()
        if (
            len(normalized_email) < 3
            or len(normalized_email) > 256
            or not isinstance(password, str)
            or len(password) < 8
        ):
            raise ApiError("validation_error")
        try:
            normalized_role = _role(role)
        except ValueError:
            raise ApiError("validation_error", "Unknown role.") from None
        try:
            if self._users.get_by_email(normalized_email) is not None:
                raise ApiError("conflict")
            record = {
                "user_id": f"user-{uuid.uuid4().hex[:16]}",
                "email": normalized_email,
                "role": normalized_role,
                "tenant_id": tenant_id,
                "workspace_id": "default",
                "status": "active",
                "permission_overrides": {"add": [], "remove": []},
                "authorized_collection_ids": [],
                "password_version": 1,
                "role_version": 1,
                "password_hash": hash_password(password),
            }
            self._users.save(record)
            return self._provider.get_user(record["user_id"]) or {
                "user_id": record["user_id"],
                "email": normalized_email,
                "role": normalized_role,
            }
        except ApiError:
            raise
        except PostgresIdentityError as exc:
            raise _api_error(exc) from None

    def update_user(
        self,
        *,
        actor,
        user_id: str,
        email: str | None = None,
        role: str | None = None,
        workspace_id: str | None = None,
        authorized_collection_ids: list[str] | None = None,
        permission_overrides: dict | None = None,
    ) -> dict:
        from core.errors import ApiError

        try:
            self._require_actor_permission(actor, "users.manage")
            user = dict(self._user_for_actor(actor, user_id))
            tenant_id = str(actor.tenant_id)
            if email is not None:
                normalized = email.strip().casefold()
                existing = self._users.get_by_email(normalized)
                if not normalized or (
                    existing is not None and existing.get("user_id") != user_id
                ):
                    raise ApiError("conflict")
                user["email"] = normalized
            if role is not None:
                try:
                    normalized_role = _role(role)
                except ValueError:
                    raise ApiError("validation_error") from None
                if canonical_role(user.get("role")) != normalized_role:
                    if (
                        canonical_role(user.get("role")) == "PLATFORM_ADMIN"
                        and self._users.count_active_platform_admins(tenant_id) <= 1
                    ):
                        raise ApiError(
                            "conflict",
                            "The last active administrator cannot lose administrator access.",
                        )
                    user["role"] = normalized_role
                    user["role_version"] = int(user.get("role_version", 1)) + 1
            if workspace_id is not None:
                # D01 still governs multi-membership semantics. The current
                # adapter has one authoritative membership projection; do not
                # silently create a second membership row.
                workspace = workspace_id.strip()
                if workspace != str(user.get("workspace_id") or "default"):
                    raise ApiError(
                        "conflict",
                        "Changing membership workspace requires the approved tenant policy.",
                    )
            if authorized_collection_ids is not None:
                clean = sorted(
                    {
                        item.strip()
                        for item in authorized_collection_ids
                        if isinstance(item, str) and item.strip()
                    }
                )
                if clean != list(user.get("authorized_collection_ids") or []):
                    user["authorized_collection_ids"] = clean
                    user["role_version"] = int(user.get("role_version", 1)) + 1
            if (
                permission_overrides is not None
                and permission_overrides != user.get("permission_overrides")
            ):
                user["permission_overrides"] = permission_overrides
                user["role_version"] = int(user.get("role_version", 1)) + 1
            self._users.save(user)
            return self._provider.get_user(user_id) or {"user_id": user_id}
        except ApiError:
            raise
        except PostgresIdentityError as exc:
            raise _api_error(exc) from None

    def deactivate_user(self, *, actor, user_id: str) -> int:
        from core.errors import ApiError

        try:
            self._require_actor_permission(actor, "users.manage")
            user = dict(self._user_for_actor(actor, user_id))
            if user.get("status", "active") != "active":
                return 0
            if (
                canonical_role(user.get("role")) == "PLATFORM_ADMIN"
                and self._users.count_active_platform_admins(str(actor.tenant_id)) <= 1
            ):
                raise ApiError("conflict", "The last active administrator cannot be disabled.")
            user["status"] = "disabled"
            user["password_version"] = int(user.get("password_version", 1)) + 1
            self._users.save(user)
            return self._sessions.revoke_user(
                user_id,
                tenant_id=str(actor.tenant_id),
                reason="user_disabled",
            )
        except ApiError:
            raise
        except PostgresIdentityError as exc:
            raise _api_error(exc) from None

    def reset_password(self, *, actor, user_id: str, password: str) -> int:
        from core.errors import ApiError

        if not isinstance(password, str) or len(password) < 8:
            raise ApiError("validation_error")
        try:
            self._require_actor_permission(actor, "users.manage")
            user = dict(self._user_for_actor(actor, user_id))
            user["password_hash"] = hash_password(password)
            user["password_version"] = int(user.get("password_version", 1)) + 1
            self._users.save(user)
            return self._sessions.revoke_user(
                user_id,
                tenant_id=str(actor.tenant_id),
                reason="password_reset",
            )
        except ApiError:
            raise
        except PostgresIdentityError as exc:
            raise _api_error(exc) from None

    def issue_password_reset(self, *, email: str, tenant_id: str | None) -> str | None:
        try:
            user = (
                self._users.get_by_email_for_tenant(email, tenant_id)
                if tenant_id
                else self._users.get_by_email(email)
            )
            if not isinstance(user, dict):
                return None
            user_tenant = user.get("tenant_id")
            workspace = user.get("workspace_id")
            if not isinstance(user_tenant, str) or not isinstance(workspace, str):
                return None
            return self._recovery.issue(
                user_id=str(user["user_id"]),
                tenant_id=user_tenant,
                workspace_id=workspace,
            )
        except PostgresIdentityError as exc:
            raise _api_error(exc) from None

    def consume_password_reset(self, *, token: str, new_password: str) -> int:
        from core.errors import ApiError

        if not isinstance(new_password, str) or len(new_password) < 8:
            raise ApiError("validation_error")
        try:
            claim = self._recovery.consume(token)
            if not claim:
                raise ApiError("validation_error", "Invalid or expired reset token.")
            user_id = claim.get("user_id")
            tenant_id = claim.get("tenant_id")
            user = (
                self._users.get_by_id_for_tenant(user_id, tenant_id)
                if isinstance(user_id, str) and isinstance(tenant_id, str)
                else None
            )
            if user is None or user.get("status", "active") != "active":
                raise ApiError("validation_error", "Invalid or expired reset token.")
            updated = dict(user)
            updated["password_hash"] = hash_password(new_password)
            updated["password_version"] = int(updated.get("password_version", 1)) + 1
            self._users.save(updated)
            return self._sessions.revoke_user(
                user_id,
                tenant_id=tenant_id,
                reason="password_recovery",
            )
        except ApiError:
            raise
        except PostgresIdentityError as exc:
            raise _api_error(exc) from None

    def revoke_session_by_id(self, *, actor, session_id: str) -> int:
        from core.errors import ApiError

        tenant_id = getattr(actor, "tenant_id", None)
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ApiError("forbidden")
        self._require_actor_permission(actor, "sessions.revoke")
        try:
            return self._sessions.revoke_session_by_id(session_id, tenant_id=tenant_id)
        except PostgresIdentityError as exc:
            raise _api_error(exc) from None

    def revoke(self, *, actor, target_token, target_session_id, target_user_id, revoke_all) -> int:
        from core.errors import ApiError

        actor_id = getattr(actor, "user_id", None)
        target_id = target_user_id or actor_id
        tenant_id = getattr(actor, "tenant_id", None)
        if not isinstance(target_id, str) or not isinstance(tenant_id, str):
            raise ApiError("forbidden")
        if target_id != actor_id and not permission_granted(
            role=None,
            permissions=list(getattr(actor, "permissions", None) or []),
            required="sessions.revoke",
            authoritative=True,
        ):
            raise ApiError("forbidden")
        try:
            self._user_for_actor(actor, target_id)
            if revoke_all:
                return self._sessions.revoke_user(target_id, tenant_id=tenant_id)
            if target_session_id:
                record = self._sessions.get_by_session_id(
                    target_session_id,
                    tenant_id=tenant_id,
                )
                if record is None or record.get("user_id") != target_id:
                    raise ApiError("forbidden")
                return self._sessions.revoke_session_by_id(
                    target_session_id,
                    tenant_id=tenant_id,
                )
            if target_token:
                record = self._sessions.get(target_token)
                if (
                    record is None
                    or record.get("user_id") != target_id
                    or record.get("tenant_id") != tenant_id
                ):
                    raise ApiError("forbidden")
                return self._provider.revoke_session(target_token)
            return 0
        except ApiError:
            raise
        except PostgresIdentityError as exc:
            raise _api_error(exc) from None


__all__ = ["PostgresIdentityProvider"]
