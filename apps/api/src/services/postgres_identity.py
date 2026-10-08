"""Tenant-scoped identity facade backed by the canonical PostgreSQL stores.

The facade keeps API orchestration and error translation out of the canonical
identity package. It is intentionally injectable: constructing it does not
import a driver or open a connection. Local password login uses the existing
PBKDF2 format for migration compatibility; D02 still decides whether local
credentials remain in the deployed identity model.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import contextmanager, nullcontext
import json
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


def _active_platform_admin(user: Mapping[str, object]) -> bool:
    return (
        canonical_role(user.get("role")) == "PLATFORM_ADMIN"
        and user.get("status", "active") == "active"
        and user.get("membership_status", "active") == "active"
    )


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
        self._connection_factory = connection_factory
        self.supports_atomic_admin_audit = True
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

    def refresh_authorization_context(self, *, context: Mapping[str, object]) -> dict[str, object] | None:
        """Read the exact current membership before replay or publication."""
        user_id = context.get("user_id")
        tenant_id = context.get("tenant_id")
        workspace_id = context.get("workspace_id")
        if any(
            not isinstance(value, str) or not value.strip()
            for value in (user_id, tenant_id, workspace_id)
        ):
            return None
        scoped_lookup = getattr(self._users, "get_by_id_for_tenant_workspace", None)
        if not callable(scoped_lookup):
            return None
        try:
            user = scoped_lookup(user_id, tenant_id, workspace_id)
        except PostgresIdentityError:
            return None
        if not isinstance(user, Mapping):
            return None
        if (
            user.get("user_id") != user_id
            or user.get("tenant_id") != tenant_id
            or user.get("workspace_id", "default") != workspace_id
            or user.get("status", "active") != "active"
            or user.get("membership_status", "active") != "active"
        ):
            return None
        from services.authorization_service import refresh_context_from_user

        return refresh_context_from_user(context, user)

    def logout(self, token: str | None) -> None:
        try:
            self._provider.logout(token)
        except PostgresIdentityError:
            return

    def _user_for_actor(self, actor, user_id: str, *, connection=None) -> dict:
        from core.errors import ApiError

        tenant_id = getattr(actor, "tenant_id", None)
        user = (
            self._users.get_by_id_for_tenant(user_id, tenant_id, connection=connection)
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

    def admin_target_in_scope(self, *, user_id: str, tenant_id: str, workspace_id: str) -> bool:
        """Check an exact membership; the mutation repeats this check atomically."""
        try:
            return self._users.get_by_id_for_tenant_workspace(user_id, tenant_id, workspace_id) is not None
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

    def create_user(
        self,
        *,
        email: str,
        role: str,
        tenant_id: str,
        password: str,
        actor=None,
        request_id: str | None = None,
    ) -> dict:
        """Create with the completion outbox; unscoped legacy calls fail closed."""
        from core.errors import ApiError

        if actor is None:
            raise ApiError("provider_unavailable")
        user, _event_id = self.admin_create_user(
            actor=actor,
            email=email,
            role=role,
            tenant_id=tenant_id,
            password=password,
            request_id=request_id,
        )
        return user

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
        user, _event_id = self.admin_update_user(
            actor=actor,
            user_id=user_id,
            email=email,
            role=role,
            workspace_id=workspace_id,
            authorized_collection_ids=authorized_collection_ids,
            permission_overrides=permission_overrides,
        )
        return user

    def deactivate_user(self, *, actor, user_id: str) -> int:
        revoked, _event_id = self.admin_deactivate_user(actor=actor, user_id=user_id)
        return revoked

    def reset_password(self, *, actor, user_id: str, password: str) -> int:
        revoked, _event_id = self.admin_reset_password(
            actor=actor,
            user_id=user_id,
            password=password,
        )
        return revoked

    @contextmanager
    def _admin_transaction(self, tenant_id: str):
        """Own the transaction for an admin mutation and its durable audit row."""
        from core.errors import ApiError

        connection = None
        cursor = None
        try:
            connection = self._connection_factory()
            if connection is None:
                raise PostgresIdentityError()
            cursor = connection.cursor()
            # Serialize tenant admin changes so two simultaneous requests cannot
            # both remove the last active administrator. A second advisory lock
            # makes the pending-audit capacity check global and race-free.
            self._users._execute(
                cursor,
                "SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
                ("rick.identity.admin", tenant_id),
            )
            self._users._execute(
                cursor,
                "SELECT pg_advisory_xact_lock(hashtext(%s), 0)",
                ("rick.admin.audit.backlog",),
            )
            self._users._execute(
                cursor,
                """
                SELECT COUNT(*) AS count
                  FROM rick_outbox
                 WHERE event_type = 'admin.audit.completion'
                   AND published_at IS NULL
                """,
            )
            row = self._users._fetchone(cursor) or {}
            try:
                pending_count = int(row.get("count", 0) or 0)
            except (TypeError, ValueError):
                raise PostgresIdentityError() from None
            if pending_count >= 10_000:
                raise ApiError("provider_unavailable")
            yield connection
            connection.commit()
        except (ApiError, PostgresIdentityError):
            if connection is not None:
                try:
                    connection.rollback()
                except Exception:
                    pass
            raise
        except BaseException as exc:
            if connection is not None:
                try:
                    connection.rollback()
                except Exception:
                    pass
            if not isinstance(exc, Exception):
                raise
            raise PostgresIdentityError() from None
        finally:
            if cursor is not None:
                close = getattr(cursor, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        pass
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

    @contextmanager
    def _recovery_transaction(self):
        """Keep token consumption, credential change and session revocation atomic."""
        from core.errors import ApiError

        connection = None
        try:
            connection = self._connection_factory()
            if connection is None:
                raise PostgresIdentityError()
            yield connection
            connection.commit()
        except (ApiError, PostgresIdentityError):
            if connection is not None:
                try:
                    connection.rollback()
                except Exception:
                    pass
            raise
        except Exception:
            if connection is not None:
                try:
                    connection.rollback()
                except Exception:
                    pass
            raise PostgresIdentityError() from None
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

    @staticmethod
    def _admin_tenant(actor, requested_tenant: str | None = None) -> str:
        from core.errors import ApiError

        PostgresIdentityProvider._require_actor_permission(actor, "users.manage")
        actor_tenant = getattr(actor, "tenant_id", None)
        if not isinstance(actor_tenant, str) or not actor_tenant.strip():
            raise ApiError("forbidden")
        tenant = actor_tenant.strip()
        if requested_tenant is not None and requested_tenant.strip() != tenant:
            raise ApiError("forbidden")
        return tenant

    @staticmethod
    def _admin_workspace(actor) -> str:
        from core.errors import ApiError

        workspace = getattr(actor, "workspace_id", None)
        if not isinstance(workspace, str) or not workspace.strip() or len(workspace.strip()) > 128:
            raise ApiError("forbidden")
        return workspace.strip()

    def _lock_account_in_exact_workspace(
        self, *, user_id: str, tenant_id: str, workspace_id: str, connection: object
    ) -> dict:
        """Guard global credentials behind the actor's exact membership and tenant boundary."""
        from core.errors import ApiError

        if not self._users.lock_user_for_update(user_id, connection=connection):
            raise ApiError("forbidden")
        if self._users.has_membership_outside_tenant(
            user_id, tenant_id, connection=connection,
        ):
            raise ApiError("forbidden")
        user = self._users.get_by_id_for_tenant_workspace(
            user_id, tenant_id, workspace_id, connection=connection,
        )
        if user is None:
            raise ApiError("forbidden")
        return dict(user)

    @staticmethod
    def _admin_request_id(value: str | None) -> str | None:
        if value is None:
            return None
        from rick_identity.postgres import _required

        return _required(value, maximum=128)

    def _append_admin_completion(
        self,
        connection: object,
        *,
        action: str,
        actor,
        tenant_id: str,
        target_id: str,
        request_id: str | None,
    ) -> str:
        from rick_identity.postgres import _required

        event_id = f"audit-{uuid.uuid4().hex}"
        actor_user_id = _required(getattr(actor, "user_id", None))
        workspace = getattr(actor, "workspace_id", None)
        if workspace is not None:
            workspace = _required(workspace, maximum=128)
        target_id = _required(target_id)
        payload = {
            "action": action,
            "actor_user_id": actor_user_id,
            "target_type": "user",
            "target_id": target_id,
            "tenant_id": tenant_id,
            "workspace_id": workspace,
            "request_id": request_id,
            "status": "completed",
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with self._users._session(connection=connection) as (_connection, cursor):
            self._users._execute(
                cursor,
                """
                INSERT INTO rick_outbox
                    (event_id, tenant_id, aggregate_type, aggregate_id, event_type, payload)
                VALUES (%s, %s, 'rick_user', %s, 'admin.audit.completion', CAST(%s AS jsonb))
                """,
                (event_id, tenant_id, target_id, encoded),
            )
        return event_id

    def admin_create_user(
        self,
        *,
        actor,
        email: str,
        role: str,
        tenant_id: str,
        password: str,
        request_id: str | None = None,
        connection=None,
    ) -> tuple[dict, str | None]:
        """Create a user and its completion audit outbox event atomically."""
        from core.errors import ApiError

        tenant = self._admin_tenant(actor, tenant_id)
        workspace = self._admin_workspace(actor)
        normalized_email = (email or "").strip().casefold()
        if len(normalized_email) < 3 or len(normalized_email) > 256 or not isinstance(password, str) or len(password) < 8:
            raise ApiError("validation_error")
        try:
            normalized_role = _role(role)
        except ValueError:
            raise ApiError("validation_error", "Unknown role.") from None
        borrowed = connection is not None
        try:
            with (nullcontext(connection) if borrowed else self._admin_transaction(tenant)) as connection:
                if self._users.get_by_email(normalized_email, connection=connection) is not None:
                    raise ApiError("conflict")
                record = {
                    "user_id": f"user-{uuid.uuid4().hex[:16]}",
                    "email": normalized_email,
                    "role": normalized_role,
                    "tenant_id": tenant,
                    "workspace_id": workspace,
                    "status": "active",
                    "permission_overrides": {"add": [], "remove": []},
                    "authorized_collection_ids": [],
                    "password_version": 1,
                    "role_version": 1,
                    "password_hash": hash_password(password),
                }
                self._users.save(record, connection=connection)
                request = self._admin_request_id(request_id)
                event_id = None if borrowed else self._append_admin_completion(
                    connection,
                    action="admin.user_created",
                    actor=actor,
                    tenant_id=tenant,
                    target_id=record["user_id"],
                    request_id=request,
                )
                user = self._users.get_by_id_for_tenant(record["user_id"], tenant, connection=connection)
                if user is None:
                    raise PostgresIdentityError()
            return user, event_id
        except ApiError:
            raise
        except PostgresIdentityError as exc:
            raise _api_error(exc) from None

    def admin_update_user(
        self,
        *,
        actor,
        user_id: str,
        request_id: str | None = None,
        email: str | None = None,
        role: str | None = None,
        workspace_id: str | None = None,
        authorized_collection_ids: list[str] | None = None,
        permission_overrides: dict | None = None,
        connection=None,
    ) -> tuple[dict, str | None]:
        """Update a user and its completion audit outbox event atomically."""
        from core.errors import ApiError

        tenant = self._admin_tenant(actor)
        workspace = self._admin_workspace(actor)
        borrowed = connection is not None
        try:
            with (nullcontext(connection) if borrowed else self._admin_transaction(tenant)) as connection:
                # save() upserts global credentials along with the membership
                # projection. Lock before reading it on every PATCH, including
                # empty/workspace-only updates, so recovery cannot be undone by
                # a stale full-row snapshot.
                user = self._lock_account_in_exact_workspace(
                    user_id=user_id, tenant_id=tenant, workspace_id=workspace, connection=connection,
                )
                if email is not None:
                    normalized = email.strip().casefold()
                    if not normalized or len(normalized) > 256:
                        raise ApiError("validation_error")
                    existing = self._users.get_by_email(normalized, connection=connection)
                    if existing is not None and existing.get("user_id") != user_id:
                        raise ApiError("conflict")
                    user["email"] = normalized
                if role is not None:
                    try:
                        normalized_role = _role(role)
                    except ValueError:
                        raise ApiError("validation_error") from None
                    if canonical_role(user.get("role")) != normalized_role:
                        if _active_platform_admin(user) and self._users.count_active_platform_admins(
                            tenant, workspace_id=workspace, connection=connection,
                        ) <= 1:
                            raise ApiError("conflict", "The last active administrator cannot lose administrator access.")
                        user["role"] = normalized_role
                        user["role_version"] = int(user.get("role_version", 1)) + 1
                if workspace_id is not None:
                    workspace = workspace_id.strip()
                    if workspace != str(user.get("workspace_id") or "default"):
                        raise ApiError("conflict", "Changing membership workspace requires the approved tenant policy.")
                if authorized_collection_ids is not None:
                    clean = sorted({item.strip() for item in authorized_collection_ids if isinstance(item, str) and item.strip()})
                    if clean != list(user.get("authorized_collection_ids") or []):
                        user["authorized_collection_ids"] = clean
                        user["role_version"] = int(user.get("role_version", 1)) + 1
                if permission_overrides is not None and permission_overrides != user.get("permission_overrides"):
                    user["permission_overrides"] = permission_overrides
                    user["role_version"] = int(user.get("role_version", 1)) + 1
                self._users.save(user, connection=connection)
                event_id = None if borrowed else self._append_admin_completion(
                    connection,
                    action="admin.user_updated",
                    actor=actor,
                    tenant_id=tenant,
                    target_id=user_id,
                    request_id=self._admin_request_id(request_id),
                )
                updated = self._users.get_by_id_for_tenant_workspace(
                    user_id, tenant, workspace, connection=connection,
                )
                if updated is None:
                    raise PostgresIdentityError()
            return updated, event_id
        except ApiError:
            raise
        except PostgresIdentityError as exc:
            raise _api_error(exc) from None

    def admin_deactivate_user(
        self, *, actor, user_id: str, request_id: str | None = None, connection=None
    ) -> tuple[int, str | None]:
        """Disable one workspace membership, revoke its sessions and queue audit atomically."""
        from core.errors import ApiError

        tenant = self._admin_tenant(actor)
        workspace = self._admin_workspace(actor)
        borrowed = connection is not None
        try:
            with (nullcontext(connection) if borrowed else self._admin_transaction(tenant)) as connection:
                user = self._users.get_by_id_for_tenant_workspace(
                    user_id, tenant, workspace, connection=connection,
                )
                if user is None:
                    raise ApiError("forbidden")
                if user.get("membership_status", "active") == "active":
                    if _active_platform_admin(user) and self._users.count_active_platform_admins(
                        tenant, workspace_id=workspace, connection=connection,
                    ) <= 1:
                        raise ApiError("conflict", "The last active administrator cannot be disabled.")
                    if not self._users.update_membership_status(
                        user_id=user_id,
                        tenant_id=tenant,
                        workspace_id=workspace,
                        status="disabled",
                        connection=connection,
                    ):
                        raise ApiError("forbidden")
                revoked = self._sessions.revoke_user(
                    user_id, tenant_id=tenant, workspace_id=workspace,
                    reason="user_disabled", connection=connection,
                )
                event_id = None if borrowed else self._append_admin_completion(
                    connection,
                    action="admin.user_deactivated",
                    actor=actor,
                    tenant_id=tenant,
                    target_id=user_id,
                    request_id=self._admin_request_id(request_id),
                )
            return revoked, event_id
        except ApiError:
            raise
        except PostgresIdentityError as exc:
            raise _api_error(exc) from None

    def admin_reset_password(
        self, *, actor, user_id: str, password: str, request_id: str | None = None
    ) -> tuple[int, str]:
        """Reset credentials, revoke sessions and queue audit atomically."""
        from core.errors import ApiError

        if not isinstance(password, str) or len(password) < 8:
            raise ApiError("validation_error")
        tenant = self._admin_tenant(actor)
        workspace = self._admin_workspace(actor)
        password_hash = hash_password(password)
        try:
            with self._admin_transaction(tenant) as connection:
                user = self._lock_account_in_exact_workspace(
                    user_id=user_id, tenant_id=tenant, workspace_id=workspace, connection=connection,
                )
                user["password_hash"] = password_hash
                user["password_version"] = int(user.get("password_version", 1)) + 1
                self._users.save(user, connection=connection)
                revoked = self._sessions.revoke_user(
                    user_id, reason="password_reset", connection=connection
                )
                event_id = self._append_admin_completion(
                    connection,
                    action="admin.user_access_reset",
                    actor=actor,
                    tenant_id=tenant,
                    target_id=user_id,
                    request_id=self._admin_request_id(request_id),
                )
            return revoked, event_id
        except ApiError:
            raise
        except PostgresIdentityError as exc:
            raise _api_error(exc) from None

    def get_admin_audit_status(self, *, actor, event_id: str) -> dict | None:
        from core.errors import ApiError
        from rick_identity.postgres import _required

        self._require_actor_permission(actor, "audit.read")
        tenant = getattr(actor, "tenant_id", None)
        if not isinstance(tenant, str) or not tenant.strip():
            raise ApiError("forbidden")
        event = _required(event_id, maximum=128)
        workspace = getattr(actor, "workspace_id", None)
        if isinstance(workspace, str) and workspace.strip():
            workspace_clause = "AND (payload->>'workspace_id' IS NULL OR payload->>'workspace_id' = %s)"
            params = (event, tenant, workspace.strip())
        else:
            workspace_clause = "AND payload->>'workspace_id' IS NULL"
            params = (event, tenant)
        try:
            with self._users._session() as (_connection, cursor):
                self._users._execute(
                    cursor,
                    f"""
                    SELECT event_id, attempts, published_at, dead_lettered_at,
                           manual_retry_count
                      FROM rick_outbox
                     WHERE event_id = %s AND tenant_id = %s
                       AND event_type = 'admin.audit.completion'
                       {workspace_clause}
                    """,
                    params,
                )
                row = self._users._fetchone(cursor)
            if row is None:
                return None
            published = row.get("published_at") is not None
            dead = row.get("dead_lettered_at") is not None
            return {
                "event_id": event,
                "status": "published" if published else "dead_lettered" if dead else "pending",
                "attempts": max(0, int(row.get("attempts", 0) or 0)),
                "manual_retry_count": max(0, int(row.get("manual_retry_count", 0) or 0)),
                "can_retry": dead and not published and int(row.get("manual_retry_count", 0) or 0) < 3,
            }
        except ApiError:
            raise
        except PostgresIdentityError as exc:
            raise _api_error(exc) from None

    def retry_admin_audit_event(self, *, actor, event_id: str) -> bool:
        from core.errors import ApiError
        from rick_identity.postgres import _required

        self._require_actor_permission(actor, "users.manage")
        tenant = getattr(actor, "tenant_id", None)
        if not isinstance(tenant, str) or not tenant.strip():
            raise ApiError("forbidden")
        event = _required(event_id, maximum=128)
        workspace = getattr(actor, "workspace_id", None)
        if isinstance(workspace, str) and workspace.strip():
            workspace_clause = "AND (payload->>'workspace_id' IS NULL OR payload->>'workspace_id' = %s)"
            params = (event, tenant, workspace.strip())
        else:
            workspace_clause = "AND payload->>'workspace_id' IS NULL"
            params = (event, tenant)
        try:
            with self._users._session(write=True) as (_connection, cursor):
                self._users._execute(
                    cursor,
                    f"""
                    UPDATE rick_outbox
                       SET attempts = 0, available_at = NOW(), last_error_code = NULL,
                           dead_lettered_at = NULL, manual_retry_count = manual_retry_count + 1
                     WHERE event_id = %s AND tenant_id = %s
                       AND event_type = 'admin.audit.completion'
                       AND published_at IS NULL AND dead_lettered_at IS NOT NULL
                       AND manual_retry_count < 3
                       {workspace_clause}
                    """,
                    params,
                )
                return max(0, int(getattr(cursor, "rowcount", 0) or 0)) == 1
        except PostgresIdentityError as exc:
            raise _api_error(exc) from None

    def issue_password_reset(self, *, email: str, tenant_id: str | None) -> str | None:
        try:
            if tenant_id is None:
                resolver = getattr(self._users, "get_unique_active_by_email", None)
                user = resolver(email) if callable(resolver) else None
            elif not isinstance(tenant_id, str) or not tenant_id.strip():
                return None
            else:
                resolver = getattr(self._users, "get_by_email_for_tenant", None)
                user = resolver(email, tenant_id.strip()) if callable(resolver) else None
            if not isinstance(user, dict):
                return None
            if (
                user.get("status", "active") != "active"
                or user.get("membership_status", "active") != "active"
            ):
                return None
            user_tenant = user.get("tenant_id")
            workspace = user.get("workspace_id")
            user_id = user.get("user_id")
            if (
                not isinstance(user_id, str)
                or not user_id.strip()
                or not isinstance(user_tenant, str)
                or not user_tenant.strip()
                or not isinstance(workspace, str)
                or not workspace.strip()
            ):
                return None
            return self._recovery.issue(
                user_id=user_id,
                tenant_id=user_tenant,
                workspace_id=workspace,
            )
        except PostgresIdentityError as exc:
            raise _api_error(exc) from None

    def consume_password_reset(self, *, token: str, new_password: str) -> int:
        from core.errors import ApiError

        if not isinstance(new_password, str) or len(new_password) < 8:
            raise ApiError("validation_error")
        password_hash = hash_password(new_password)
        try:
            with self._recovery_transaction() as connection:
                claim = self._recovery.consume(token, connection=connection)
                if not claim:
                    raise ApiError("validation_error", "Invalid or expired reset token.")
                user_id = claim.get("user_id")
                tenant_id = claim.get("tenant_id")
                workspace_id = claim.get("workspace_id")
                scoped_values_are_valid = (
                    isinstance(user_id, str)
                    and isinstance(tenant_id, str)
                    and isinstance(workspace_id, str)
                )
                account_locked = (
                    self._users.lock_user_for_update(user_id, connection=connection)
                    if scoped_values_are_valid
                    else False
                )
                user = (
                    self._users.get_by_id_for_tenant_workspace_for_update(
                        user_id, tenant_id, workspace_id, connection=connection,
                    )
                    if account_locked
                    else None
                )
                if (
                    user is None
                    or user.get("status", "active") != "active"
                    or user.get("membership_status", "active") != "active"
                ):
                    raise ApiError("validation_error", "Invalid or expired reset token.")
                if not self._users.update_password_credentials(
                    user_id=user_id, password_hash=password_hash, connection=connection,
                ):
                    raise ApiError("validation_error", "Invalid or expired reset token.")
                # Password credentials and password_version are global to the
                # user, so invalidate every tenant/workspace session atomically.
                return self._sessions.revoke_user(
                    user_id,
                    reason="password_recovery",
                    connection=connection,
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

    @property
    def audit_connection_factory(self):
        return self._connection_factory

    def audit_transaction(self, actor):
        from core.errors import ApiError
        tenant_id = getattr(actor, "tenant_id", None)
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ApiError("forbidden")
        return self._admin_transaction(tenant_id)

    def grant_collection_in_transaction(self, *, actor, user_id, collection_id, granted, connection):
        from core.errors import ApiError
        self._require_actor_permission(actor, "collections.manage")
        user = self._users.get_by_id_for_tenant_workspace_for_update(
            user_id, actor.tenant_id, actor.workspace_id, connection=connection,
        )
        if user is None:
            raise ApiError("not_found")
        grants = [item for item in (user.get("authorized_collection_ids") or []) if item != collection_id]
        if granted:
            grants.append(collection_id)
        user["authorized_collection_ids"] = grants
        user["role_version"] = int(user.get("role_version") or 1) + 1
        self._users.save(user, connection=connection)
        return {"user_id": user_id, "collection_id": collection_id, "granted": granted}

    def revoke_in_transaction(self, *, actor, target_token, target_session_id, target_user_id, revoke_all, connection) -> int:
        from core.errors import ApiError
        target_id = target_user_id or actor.user_id
        if target_id != actor.user_id:
            self._require_actor_permission(actor, "sessions.revoke")
        self._user_for_actor(actor, target_id, connection=connection)
        if revoke_all:
            return self._sessions.revoke_user(target_id, tenant_id=actor.tenant_id, connection=connection)
        if not target_session_id and not target_token:
            return 0
        field = "session_id" if target_session_id else "token_hash"
        value = target_session_id or self._sessions._token_hash(target_token)
        with self._sessions._session(write=True, connection=connection) as (_, cursor):
            self._sessions._execute(cursor, f"SELECT user_id FROM rick_sessions WHERE {field}=%s AND tenant_id=%s FOR UPDATE", (value, actor.tenant_id))
            row = self._sessions._fetchone(cursor)
            if row is None or row.get("user_id") != target_id:
                raise ApiError("forbidden")
            self._sessions._execute(cursor, f"UPDATE rick_sessions SET revoked_at=NOW(), revoke_reason=%s WHERE {field}=%s AND tenant_id=%s AND user_id=%s AND revoked_at IS NULL", ("manual_revoke", value, actor.tenant_id, target_id))
            return max(0, int(cursor.rowcount))

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
