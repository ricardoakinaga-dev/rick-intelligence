"""PostgreSQL-backed identity stores using an injected DB-API connection.

The adapter stores only a hash of the session bearer. It does not import a
database driver, create a pool, or expose connection/error details; those
choices stay in the application composition root.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import secrets
import time
from typing import Iterator, Protocol


class DbConnection(Protocol):
    def cursor(self) -> object: ...
    def commit(self) -> object: ...
    def rollback(self) -> object: ...
    def close(self) -> object: ...


class PostgresIdentityError(RuntimeError):
    """Safe identity-store failure code."""

    def __init__(self, code: str = "identity_unavailable") -> None:
        self.code = code if code in {"identity_unavailable", "invalid_input", "conflict", "not_found"} else "identity_unavailable"
        super().__init__(self.code)


def _row_dict(cursor: object, row: object) -> dict[str, object]:
    if isinstance(row, Mapping):
        return {str(key): value for key, value in row.items()}
    description = getattr(cursor, "description", None) or ()
    names = [item[0] for item in description if isinstance(item, (tuple, list)) and item]
    return dict(zip(names, row if isinstance(row, (tuple, list)) else ()))


def _json(value: object, default: object) -> object:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return default
        return parsed
    return default


def _epoch(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.timestamp()
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _required(value: object, *, maximum: int = 256) -> str:
    if not isinstance(value, str):
        raise PostgresIdentityError("invalid_input")
    value = value.strip()
    if not value or len(value) > maximum or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise PostgresIdentityError("invalid_input")
    return value


class _PostgresStoreBase:
    def __init__(self, connection_factory: Callable[[], DbConnection], *, close_connections: bool = True) -> None:
        if not callable(connection_factory):
            raise PostgresIdentityError("invalid_input")
        self._connection_factory = connection_factory
        self._close_connections = close_connections

    @contextmanager
    def _session(self, *, write: bool = False) -> Iterator[tuple[DbConnection, object]]:
        connection: DbConnection | None = None
        cursor: object | None = None
        try:
            connection = self._connection_factory()
            if connection is None:
                raise PostgresIdentityError()
            cursor = connection.cursor()
            yield connection, cursor
            if write:
                connection.commit()
        except PostgresIdentityError:
            if write and connection is not None:
                try:
                    connection.rollback()
                except Exception:
                    pass
            raise
        except Exception:
            if write and connection is not None:
                try:
                    connection.rollback()
                except Exception:
                    pass
            raise PostgresIdentityError() from None
        finally:
            if cursor is not None:
                close = getattr(cursor, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        pass
            if self._close_connections and connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

    @staticmethod
    def _execute(cursor: object, query: str, params: tuple[object, ...] = ()) -> None:
        execute = getattr(cursor, "execute", None)
        if not callable(execute):
            raise PostgresIdentityError()
        execute(query, params)

    @staticmethod
    def _fetchone(cursor: object) -> dict[str, object] | None:
        row = getattr(cursor, "fetchone", lambda: None)()
        return None if row is None else _row_dict(cursor, row)

    @staticmethod
    def _fetchall(cursor: object) -> list[dict[str, object]]:
        return [_row_dict(cursor, row) for row in getattr(cursor, "fetchall", lambda: [])()]

    def health_check(self) -> bool:
        try:
            with self._session() as (_connection, cursor):
                self._execute(cursor, "SELECT 1")
                return self._fetchone(cursor) is not None
        except PostgresIdentityError:
            return False


class PostgresUserStore(_PostgresStoreBase):
    """User plus tenant-membership repository for ``IdentityProviderImpl``."""

    _SELECT = """
        SELECT u.user_id, u.external_subject, u.email, u.status,
               u.password_hash, u.password_version, u.role_version,
               m.tenant_id, m.workspace_id, m.role,
               m.status AS membership_status, m.permission_overrides,
               m.authorized_collection_ids
        FROM rick_users u
        LEFT JOIN rick_memberships m ON m.user_id = u.user_id
    """

    @staticmethod
    def _record(row: Mapping[str, object]) -> dict[str, object]:
        record: dict[str, object] = {
            "user_id": row.get("user_id"),
            "external_subject": row.get("external_subject"),
            "email": row.get("email"),
            "status": row.get("status", "active"),
            "password_version": int(row.get("password_version") or 1),
            "role_version": int(row.get("role_version") or 1),
        }
        if row.get("password_hash"):
            record["password_hash"] = row["password_hash"]
        if row.get("tenant_id") is not None:
            record.update({
                "tenant_id": row.get("tenant_id"),
                "workspace_id": row.get("workspace_id"),
                "role": row.get("role"),
                "membership_status": row.get("membership_status", "active"),
                "permission_overrides": _json(row.get("permission_overrides"), {"add": [], "remove": []}),
                "authorized_collection_ids": _json(row.get("authorized_collection_ids"), []),
            })
        return record

    def get_by_email(self, email: str) -> dict | None:
        try:
            value = _required(email, maximum=256).casefold()
        except PostgresIdentityError:
            return None
        with self._session() as (_connection, cursor):
            self._execute(cursor, self._SELECT + " WHERE lower(u.email) = %s ORDER BY m.tenant_id, m.workspace_id LIMIT 1", (value,))
            row = self._fetchone(cursor)
        return self._record(row) if row else None

    def get_by_email_for_tenant(self, email: str, tenant_id: str) -> dict | None:
        try:
            value = _required(email, maximum=256).casefold()
            tenant = _required(tenant_id, maximum=128)
        except PostgresIdentityError:
            return None
        with self._session() as (_connection, cursor):
            self._execute(cursor, self._SELECT + " WHERE lower(u.email) = %s AND m.tenant_id = %s LIMIT 1", (value, tenant))
            row = self._fetchone(cursor)
        return self._record(row) if row else None

    def get_by_id(self, user_id: str) -> dict | None:
        try:
            value = _required(user_id)
        except PostgresIdentityError:
            return None
        with self._session() as (_connection, cursor):
            self._execute(cursor, self._SELECT + " WHERE u.user_id = %s ORDER BY m.tenant_id, m.workspace_id LIMIT 1", (value,))
            row = self._fetchone(cursor)
        return self._record(row) if row else None

    def get_by_id_for_tenant(self, user_id: str, tenant_id: str) -> dict | None:
        """Resolve one membership projection at the caller's tenant boundary."""
        try:
            value = _required(user_id)
            tenant = _required(tenant_id, maximum=128)
        except PostgresIdentityError:
            return None
        with self._session() as (_connection, cursor):
            self._execute(
                cursor,
                self._SELECT + " WHERE u.user_id = %s AND m.tenant_id = %s LIMIT 1",
                (value, tenant),
            )
            row = self._fetchone(cursor)
        return self._record(row) if row else None

    def count_active_platform_admins(self, tenant_id: str) -> int:
        """Count active administrators in one tenant at the SQL boundary."""
        tenant = _required(tenant_id, maximum=128)
        with self._session() as (_connection, cursor):
            self._execute(
                cursor,
                """
                SELECT COUNT(*) AS count
                  FROM rick_users u
                  JOIN rick_memberships m ON m.user_id = u.user_id
                 WHERE m.tenant_id = %s
                   AND m.role = 'PLATFORM_ADMIN'
                   AND m.status = 'active'
                   AND u.status = 'active'
                """,
                (tenant,),
            )
            row = self._fetchone(cursor)
        try:
            return max(0, int((row or {}).get("count", 0) or 0))
        except (TypeError, ValueError):
            raise PostgresIdentityError() from None

    def list_users(self, *, tenant_id: str | None = None, workspace_id: str | None = None) -> list[dict]:
        clauses: list[str] = []
        params: list[object] = []
        if tenant_id is not None:
            clauses.append("m.tenant_id = %s")
            params.append(_required(tenant_id, maximum=128))
        if workspace_id is not None:
            clauses.append("m.workspace_id = %s")
            params.append(_required(workspace_id, maximum=128))
        suffix = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._session() as (_connection, cursor):
            self._execute(cursor, self._SELECT + suffix + " ORDER BY u.user_id, m.tenant_id, m.workspace_id LIMIT 1000", tuple(params))
            rows = self._fetchall(cursor)
        # A user may have several memberships. The identity facade should not
        # expose duplicate profile rows in an admin list, so keep the first
        # deterministic membership projection.
        result: dict[str, dict] = {}
        for row in rows:
            record = self._record(row)
            if isinstance(record.get("user_id"), str):
                result.setdefault(record["user_id"], record)
        return list(result.values())

    def save(self, record: dict) -> None:
        user_id = _required(record.get("user_id"))
        email = _required(record.get("email"), maximum=256).casefold()
        tenant = _required(record.get("tenant_id"), maximum=128)
        workspace = _required(record.get("workspace_id", "default"), maximum=128)
        role = _required(record.get("role"), maximum=64).upper()
        status = _required(record.get("status", "active"), maximum=32).lower()
        if status not in {"active", "disabled", "pending"} or role not in {"PLATFORM_ADMIN", "KNOWLEDGE_MANAGER", "VETERINARIAN"}:
            raise PostgresIdentityError("invalid_input")
        overrides = record.get("permission_overrides", {"add": [], "remove": []})
        grants = record.get("authorized_collection_ids", [])
        password_hash = record.get("password_hash")
        if password_hash is not None and not isinstance(password_hash, str):
            raise PostgresIdentityError("invalid_input")
        with self._session(write=True) as (_connection, cursor):
            self._execute(cursor, """
                INSERT INTO rick_users
                    (user_id, external_subject, email, status, password_hash, password_version, role_version)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    external_subject = EXCLUDED.external_subject, email = EXCLUDED.email,
                    status = EXCLUDED.status, password_hash = EXCLUDED.password_hash,
                    password_version = EXCLUDED.password_version, role_version = EXCLUDED.role_version,
                    updated_at = NOW()
            """, (user_id, record.get("external_subject"), email, status, password_hash,
                   int(record.get("password_version", 1)), int(record.get("role_version", 1))))
            self._execute(cursor, """
                INSERT INTO rick_memberships
                    (tenant_id, user_id, workspace_id, role, status, permission_overrides, authorized_collection_ids)
                VALUES (%s, %s, %s, %s, %s, CAST(%s AS jsonb), CAST(%s AS jsonb))
                ON CONFLICT (tenant_id, user_id, workspace_id) DO UPDATE SET
                    role = EXCLUDED.role, status = EXCLUDED.status,
                    permission_overrides = EXCLUDED.permission_overrides,
                    authorized_collection_ids = EXCLUDED.authorized_collection_ids, updated_at = NOW()
            """, (tenant, user_id, workspace, role, "active" if status == "active" else "disabled",
                   json.dumps(overrides, ensure_ascii=False, sort_keys=True),
                   json.dumps(grants, ensure_ascii=False, sort_keys=True)))


class PostgresSessionStore(_PostgresStoreBase):
    """Server-side session repository with hashed bearer storage."""

    def __init__(
        self,
        connection_factory: Callable[[], DbConnection],
        *,
        ttl_seconds: int = 8 * 3600,
        close_connections: bool = True,
    ) -> None:
        super().__init__(connection_factory, close_connections=close_connections)
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not 60 <= ttl_seconds <= 7 * 24 * 3600:
            raise PostgresIdentityError("invalid_input")
        self.ttl_seconds = ttl_seconds

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _snapshot(record: Mapping[str, object]) -> str:
        payload = {
            key: record.get(key)
            for key in (
                "email", "role", "canonical_role", "permissions",
                "authorization_snapshot_version", "authorization_state",
                "allowed_collection_ids",
            )
            if record.get(key) is not None
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _record(row: Mapping[str, object]) -> dict[str, object]:
        snapshot = _json(row.get("authorization_snapshot"), {})
        result: dict[str, object] = {
            "session_id": row.get("session_id"),
            "user_id": row.get("user_id"),
            "tenant_id": row.get("tenant_id"),
            "workspace_id": row.get("workspace_id"),
            "created_at": _epoch(row.get("created_at")),
            "last_seen_at": _epoch(row.get("last_seen_at")),
            "expires_at": _epoch(row.get("expires_at")) or 0.0,
            "revoked_at": _epoch(row.get("revoked_at")),
            "revoke_reason": row.get("revoke_reason"),
            "password_version": int(row.get("password_version") or 1),
            "role_version": int(row.get("role_version") or 1),
        }
        if isinstance(snapshot, Mapping):
            result.update({key: snapshot[key] for key in (
                "email", "role", "canonical_role", "permissions",
                "authorization_snapshot_version", "authorization_state",
                "allowed_collection_ids",
            ) if key in snapshot})
        return result

    def create(self, record: dict) -> str:
        token = secrets.token_urlsafe(32)
        user_id = _required(record.get("user_id"))
        tenant = _required(record.get("tenant_id"), maximum=128)
        workspace = _required(record.get("workspace_id"), maximum=128)
        session_id = _required(record.get("session_id") or f"oidc-session-{secrets.token_hex(8)}")
        now = time.time()
        expires = record.get("expires_at")
        try:
            expires_at = float(expires) if expires is not None else now + self.ttl_seconds
        except (TypeError, ValueError):
            raise PostgresIdentityError("invalid_input") from None
        with self._session(write=True) as (_connection, cursor):
            self._execute(cursor, """
                INSERT INTO rick_sessions
                    (session_id, token_hash, tenant_id, user_id, workspace_id,
                     authorization_snapshot, password_version, role_version,
                     created_at, last_seen_at, expires_at)
                VALUES (%s, %s, %s, %s, %s, CAST(%s AS jsonb), %s, %s,
                        to_timestamp(%s), to_timestamp(%s), to_timestamp(%s))
            """, (session_id, self._token_hash(token), tenant, user_id, workspace,
                   self._snapshot(record), int(record.get("password_version", 1)),
                   int(record.get("role_version", 1)), now, now, expires_at))
        return token

    def get(self, token: str) -> dict | None:
        try:
            token = _required(token, maximum=4096)
        except PostgresIdentityError:
            return None
        with self._session() as (_connection, cursor):
            self._execute(cursor, "SELECT * FROM rick_sessions WHERE token_hash = %s LIMIT 1", (self._token_hash(token),))
            row = self._fetchone(cursor)
        return self._record(row) if row else None

    def delete(self, token: str) -> None:
        self.revoke(token, reason="manual_revoke")

    def revoke(self, token: str, *, reason: str = "manual_revoke") -> int:
        try:
            token = _required(token, maximum=4096)
            reason = _required(reason, maximum=128)
        except PostgresIdentityError:
            return 0
        with self._session(write=True) as (_connection, cursor):
            self._execute(cursor, "UPDATE rick_sessions SET revoked_at = COALESCE(revoked_at, NOW()), revoke_reason = %s WHERE token_hash = %s AND revoked_at IS NULL", (reason, self._token_hash(token)))
            return max(0, int(getattr(cursor, "rowcount", 0) or 0))

    def tokens_for_user(self, _user_id: str) -> list[str]:
        """Raw tokens are unrecoverable; bulk methods are used for revocation."""
        return []

    def list_for_user(self, user_id: str, *, tenant_id: str | None = None, limit: int = 100) -> list[dict]:
        user_id = _required(user_id)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1_000:
            raise PostgresIdentityError("invalid_input")
        if tenant_id is None:
            query = "SELECT * FROM rick_sessions WHERE user_id = %s ORDER BY created_at DESC, session_id LIMIT %s"
            params: tuple[object, ...] = (user_id, limit)
        else:
            tenant = _required(tenant_id, maximum=128)
            query = "SELECT * FROM rick_sessions WHERE user_id = %s AND tenant_id = %s ORDER BY created_at DESC, session_id LIMIT %s"
            params = (user_id, tenant, limit)
        with self._session() as (_connection, cursor):
            self._execute(cursor, query, params)
            rows = self._fetchall(cursor)
        return [self._record(row) for row in rows]

    def revoke_user(self, user_id: str, *, tenant_id: str | None = None, reason: str = "manual_revoke") -> int:
        user_id = _required(user_id)
        reason = _required(reason, maximum=128)
        if tenant_id is None:
            query = "UPDATE rick_sessions SET revoked_at = COALESCE(revoked_at, NOW()), revoke_reason = %s WHERE user_id = %s AND revoked_at IS NULL"
            params: tuple[object, ...] = (reason, user_id)
        else:
            query = "UPDATE rick_sessions SET revoked_at = COALESCE(revoked_at, NOW()), revoke_reason = %s WHERE user_id = %s AND tenant_id = %s AND revoked_at IS NULL"
            params = (reason, user_id, _required(tenant_id, maximum=128))
        with self._session(write=True) as (_connection, cursor):
            self._execute(cursor, query, params)
            return max(0, int(getattr(cursor, "rowcount", 0) or 0))

    def touch(self, token: str) -> None:
        try:
            token = _required(token, maximum=4096)
        except PostgresIdentityError:
            return
        now = time.time()
        with self._session(write=True) as (_connection, cursor):
            self._execute(cursor, "UPDATE rick_sessions SET last_seen_at = to_timestamp(%s), expires_at = to_timestamp(%s) WHERE token_hash = %s AND revoked_at IS NULL", (now, now + self.ttl_seconds, self._token_hash(token)))

    def records(self, *, tenant_id: str | None = None, limit: int = 100) -> list[dict]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1_000:
            raise PostgresIdentityError("invalid_input")
        if tenant_id is None:
            query = "SELECT * FROM rick_sessions ORDER BY created_at DESC, session_id LIMIT %s"
            params: tuple[object, ...] = (limit,)
        else:
            query = "SELECT * FROM rick_sessions WHERE tenant_id = %s ORDER BY created_at DESC, session_id LIMIT %s"
            params = (_required(tenant_id, maximum=128), limit)
        with self._session() as (_connection, cursor):
            self._execute(cursor, query, params)
            rows = self._fetchall(cursor)
        return [self._record(row) for row in rows]

    def revoke_session_by_id(self, session_id: str, *, tenant_id: str, reason: str = "manual_revoke") -> int:
        session_id = _required(session_id)
        tenant = _required(tenant_id, maximum=128)
        reason = _required(reason, maximum=128)
        with self._session(write=True) as (_connection, cursor):
            self._execute(
                cursor,
                """
                UPDATE rick_sessions
                   SET revoked_at = COALESCE(revoked_at, NOW()), revoke_reason = %s
                 WHERE session_id = %s AND tenant_id = %s AND revoked_at IS NULL
                """,
                (reason, session_id, tenant),
            )
            return max(0, int(getattr(cursor, "rowcount", 0) or 0))

    def get_by_session_id(self, session_id: str, *, tenant_id: str | None = None) -> dict | None:
        session_id = _required(session_id)
        if tenant_id is None:
            query = "SELECT * FROM rick_sessions WHERE session_id = %s LIMIT 1"
            params: tuple[object, ...] = (session_id,)
        else:
            query = "SELECT * FROM rick_sessions WHERE session_id = %s AND tenant_id = %s LIMIT 1"
            params = (session_id, _required(tenant_id, maximum=128))
        with self._session() as (_connection, cursor):
            self._execute(cursor, query, params)
            row = self._fetchone(cursor)
        return self._record(row) if row else None


class PostgresRecoveryStore(_PostgresStoreBase):
    """Single-use password recovery token repository.

    Only SHA-256 token digests are written. Delivery is deliberately outside
    this adapter; the caller receives the raw token once and decides which
    approved delivery port owns it.
    """

    def __init__(
        self,
        connection_factory: Callable[[], DbConnection],
        *,
        ttl_seconds: int = 15 * 60,
        close_connections: bool = True,
    ) -> None:
        super().__init__(connection_factory, close_connections=close_connections)
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not 60 <= ttl_seconds <= 24 * 3600:
            raise PostgresIdentityError("invalid_input")
        self.ttl_seconds = ttl_seconds

    def issue(self, *, user_id: str, tenant_id: str, workspace_id: str) -> str:
        user_id = _required(user_id)
        tenant_id = _required(tenant_id, maximum=128)
        workspace_id = _required(workspace_id, maximum=128)
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._session(write=True) as (_connection, cursor):
            self._execute(
                cursor,
                """
                INSERT INTO rick_password_reset_tokens
                    (token_hash, tenant_id, user_id, workspace_id, expires_at)
                VALUES (%s, %s, %s, %s, to_timestamp(%s))
                """,
                (hashlib.sha256(token.encode("utf-8")).hexdigest(), tenant_id, user_id,
                 workspace_id, now + self.ttl_seconds),
            )
        return token

    def consume(self, token: str) -> dict[str, object] | None:
        token = _required(token, maximum=512)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self._session(write=True) as (_connection, cursor):
            self._execute(
                cursor,
                """
                UPDATE rick_password_reset_tokens
                   SET consumed_at = NOW()
                 WHERE token_hash = %s
                   AND consumed_at IS NULL
                   AND expires_at > NOW()
                RETURNING tenant_id, user_id, expires_at
                """,
                (token_hash,),
            )
            row = self._fetchone(cursor)
        return row


__all__ = [
    "DbConnection", "PostgresIdentityError", "PostgresRecoveryStore", "PostgresSessionStore", "PostgresUserStore",
]
