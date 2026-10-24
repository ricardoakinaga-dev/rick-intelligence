"""Durable audit-operation outcomes for security effects (ADR-024).

The store owns one row per operation, keyed by ``(action, request_id)``. It is
connection-aware so the identity service can write the effect and the outcome
in the same transaction. It never opens a connection while importing and never
returns database errors to the HTTP boundary.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
import json
import re
from typing import Protocol

from services.postgres_audit import _row_dict


class DbConnection(Protocol):
    def cursor(self) -> object: ...  # pragma: no cover - structural protocol
    def commit(self) -> object: ...  # pragma: no cover
    def rollback(self) -> object: ...  # pragma: no cover
    def close(self) -> object: ...  # pragma: no cover


class AuditOperationError(RuntimeError):
    def __init__(self, code: str = "audit_operation_unavailable") -> None:
        self.code = code if code in {
            "audit_operation_unavailable", "invalid_input", "closed", "not_found",
        } else "audit_operation_unavailable"
        super().__init__(self.code)


STATES = frozenset({"requested", "effect_applied", "acknowledged", "indeterminate", "failed"})
_TERMINAL = frozenset({"acknowledged", "failed"})
_MAX_PAYLOAD_BYTES = 64 * 1024
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/+\-]{0,255}$")
_ERROR_CODE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


def _text(value: object, *, field: str, maximum: int = 256, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise AuditOperationError("invalid_input")
    value = value.strip()
    if not value:
        if required:
            raise AuditOperationError("invalid_input")
        return None
    if len(value) > maximum or _TOKEN.fullmatch(value) is None:
        raise AuditOperationError("invalid_input")
    return value


def _payload(value: object) -> str:
    if value is None:
        return "{}"
    if not isinstance(value, Mapping):
        raise AuditOperationError("invalid_input")
    try:
        encoded = json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        raise AuditOperationError("invalid_input") from None
    if len(encoded.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
        raise AuditOperationError("invalid_input")
    return encoded


class PostgresAuditOperationStore:
    def __init__(self, connection_factory: Callable[[], DbConnection], *, close_connections: bool = True) -> None:
        if not callable(connection_factory):
            raise AuditOperationError("invalid_input")
        self._connection_factory = connection_factory
        self._close_connections = close_connections
        self._closed = False

    def close(self) -> None:
        self._closed = True

    @contextmanager
    def _session(self, *, write: bool = False, connection: DbConnection | None = None) -> Iterator[tuple[DbConnection, object]]:
        owns_connection = connection is None
        cursor = None
        try:
            if owns_connection:
                if self._closed:
                    raise AuditOperationError("closed")
                connection = self._connection_factory()
            if connection is None:
                raise AuditOperationError()
            cursor = connection.cursor()
            yield connection, cursor
            if write and owns_connection:
                connection.commit()
        except AuditOperationError:
            if write and owns_connection and connection is not None:
                try:
                    connection.rollback()
                except Exception:
                    pass
            raise
        except Exception:
            if write and owns_connection and connection is not None:
                try:
                    connection.rollback()
                except Exception:
                    pass
            raise AuditOperationError() from None
        finally:
            if cursor is not None:
                close = getattr(cursor, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        pass
            if owns_connection and connection is not None and self._close_connections:
                close = getattr(connection, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        pass

    @staticmethod
    def _execute(cursor: object, query: str, params: tuple[object, ...] = ()) -> None:
        execute = getattr(cursor, "execute", None)
        if not callable(execute):
            raise AuditOperationError()
        execute(query, params)

    @staticmethod
    def _one(cursor: object) -> dict[str, object] | None:
        row = getattr(cursor, "fetchone", lambda: None)()
        return None if row is None else _row_dict(cursor, row)

    def _state(self, operation_id: str, *, connection: DbConnection | None = None) -> str | None:
        with self._session(connection=connection) as (_connection, cursor):
            self._execute(cursor, "SELECT state FROM rick_audit_operations WHERE operation_id = %s LIMIT 1", (operation_id,))
            row = self._one(cursor)
        state = row.get("state") if row else None
        return state if isinstance(state, str) and state in STATES else None

    def begin(
        self,
        *,
        operation_id: str,
        action: str,
        request_id: str,
        tenant_id: str | None = None,
        actor_user_id: str | None = None,
        workspace_id: str | None = None,
        payload: Mapping[str, object] | None = None,
        connection: DbConnection | None = None,
    ) -> None:
        operation_id = _text(operation_id, field="operation_id", required=True) or ""
        action = _text(action, field="action", required=True) or ""
        request_id = _text(request_id, field="request_id", required=True) or ""
        tenant_id = _text(tenant_id, field="tenant_id")
        actor_user_id = _text(actor_user_id, field="actor_user_id")
        workspace_id = _text(workspace_id, field="workspace_id")
        with self._session(write=True, connection=connection) as (_connection, cursor):
            self._execute(cursor, """
                INSERT INTO rick_audit_operations
                    (operation_id, action, request_id, tenant_id, actor_user_id,
                     workspace_id, state, payload)
                VALUES (%s,%s,%s,%s,%s,%s,'requested',CAST(%s AS jsonb))
                ON CONFLICT (action, request_id) DO NOTHING
            """, (operation_id, action, request_id, tenant_id, actor_user_id,
                   workspace_id, _payload(payload)))

    def mark_effect(
        self,
        operation_id: str,
        *,
        tenant_id: str | None = None,
        actor_user_id: str | None = None,
        workspace_id: str | None = None,
        connection: DbConnection | None = None,
    ) -> bool:
        operation_id = _text(operation_id, field="operation_id", required=True) or ""
        tenant_id = _text(tenant_id, field="tenant_id")
        actor_user_id = _text(actor_user_id, field="actor_user_id")
        workspace_id = _text(workspace_id, field="workspace_id")
        with self._session(write=True, connection=connection) as (_connection, cursor):
            self._execute(cursor, """
                UPDATE rick_audit_operations
                   SET state = 'effect_applied',
                       effect_at = COALESCE(effect_at, NOW()),
                       tenant_id = COALESCE(%s, tenant_id),
                       actor_user_id = COALESCE(%s, actor_user_id),
                       workspace_id = COALESCE(%s, workspace_id),
                       updated_at = NOW()
                 WHERE operation_id = %s
                   AND state IN ('requested','indeterminate')
            """, (tenant_id, actor_user_id, workspace_id, operation_id))
            if int(getattr(cursor, "rowcount", 0) or 0) > 0:
                return True
        return self._state(operation_id, connection=connection) in {"effect_applied", "acknowledged"}

    def acknowledge(self, operation_id: str, *, connection: DbConnection | None = None) -> bool:
        operation_id = _text(operation_id, field="operation_id", required=True) or ""
        with self._session(write=True, connection=connection) as (_connection, cursor):
            self._execute(cursor, """
                UPDATE rick_audit_operations
                   SET state = 'acknowledged',
                       acknowledged_at = COALESCE(acknowledged_at, NOW()),
                       updated_at = NOW()
                 WHERE operation_id = %s
                   AND state IN ('effect_applied','indeterminate','acknowledged')
            """, (operation_id,))
            if int(getattr(cursor, "rowcount", 0) or 0) > 0:
                return True
        return self._state(operation_id, connection=connection) == "acknowledged"

    def fail(self, operation_id: str, error_code: str = "projection_failed", *, connection: DbConnection | None = None) -> bool:
        operation_id = _text(operation_id, field="operation_id", required=True) or ""
        if not isinstance(error_code, str) or _ERROR_CODE.fullmatch(error_code) is None:
            raise AuditOperationError("invalid_input")
        with self._session(write=True, connection=connection) as (_connection, cursor):
            self._execute(cursor, """
                UPDATE rick_audit_operations
                   SET state = 'failed', attempts = attempts + 1,
                       last_error_code = %s, updated_at = NOW()
                 WHERE operation_id = %s AND state IN ('requested','effect_applied','indeterminate')
            """, (error_code, operation_id))
            return int(getattr(cursor, "rowcount", 0) or 0) > 0

    def retry(self, operation_id: str, error_code: str = "projection_failed", *, connection: DbConnection | None = None) -> bool:
        operation_id = _text(operation_id, field="operation_id", required=True) or ""
        if not isinstance(error_code, str) or _ERROR_CODE.fullmatch(error_code) is None:
            raise AuditOperationError("invalid_input")
        with self._session(write=True, connection=connection) as (_connection, cursor):
            self._execute(cursor, """
                UPDATE rick_audit_operations
                   SET state = 'indeterminate', attempts = attempts + 1,
                       last_error_code = %s, updated_at = NOW()
                 WHERE operation_id = %s AND state IN ('effect_applied','indeterminate')
            """, (error_code, operation_id))
            return int(getattr(cursor, "rowcount", 0) or 0) > 0

    def indeterminate(self, operation_id: str, error_code: str = "effect_unknown", *, connection: DbConnection | None = None) -> bool:
        operation_id = _text(operation_id, field="operation_id", required=True) or ""
        if not isinstance(error_code, str) or _ERROR_CODE.fullmatch(error_code) is None:
            raise AuditOperationError("invalid_input")
        with self._session(write=True, connection=connection) as (_connection, cursor):
            self._execute(cursor, """
                UPDATE rick_audit_operations
                   SET state = 'indeterminate', attempts = attempts + 1,
                       last_error_code = %s, updated_at = NOW()
                 WHERE operation_id = %s AND state IN ('requested','effect_applied','indeterminate')
            """, (error_code, operation_id))
            return int(getattr(cursor, "rowcount", 0) or 0) > 0

    def get(self, operation_id: str, *, connection: DbConnection | None = None) -> dict[str, object] | None:
        operation_id = _text(operation_id, field="operation_id", required=True) or ""
        with self._session(connection=connection) as (_connection, cursor):
            self._execute(cursor, "SELECT * FROM rick_audit_operations WHERE operation_id = %s LIMIT 1", (operation_id,))
            return self._one(cursor)

    def pending(
        self,
        *,
        limit: int = 100,
        older_than_seconds: int = 30,
        connection: DbConnection | None = None,
    ) -> list[dict[str, object]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1_000:
            raise AuditOperationError("invalid_input")
        if isinstance(older_than_seconds, bool) or not isinstance(older_than_seconds, int) or not 0 <= older_than_seconds <= 86_400:
            raise AuditOperationError("invalid_input")
        with self._session(connection=connection) as (_connection, cursor):
            self._execute(cursor, """
                SELECT * FROM rick_audit_operations
                 WHERE state IN ('effect_applied','indeterminate')
                   AND updated_at <= NOW() - (%s * INTERVAL '1 second')
                 ORDER BY updated_at ASC, operation_id ASC
                 LIMIT %s
            """, (older_than_seconds, limit))
            rows: list[object] = list(getattr(cursor, "fetchall", lambda: [])() or [])
            return [_row_dict(cursor, row) for row in rows]


__all__ = ["AuditOperationError", "PostgresAuditOperationStore", "STATES"]
