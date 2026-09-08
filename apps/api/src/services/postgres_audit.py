"""Tenant-scoped PostgreSQL audit sink.

Audit writes are sanitized before they reach the database and use short-lived
injected connections. The sink never owns a pool, reads environment variables,
or returns raw database errors to the API.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import contextmanager
from datetime import datetime
import json
from typing import Iterator, Protocol
import uuid

from services.audit import _ALLOWED_FIELDS
from services.sqlite_audit import _sanitise_event


class DbConnection(Protocol):
    def cursor(self) -> object: ...
    def commit(self) -> object: ...
    def rollback(self) -> object: ...
    def close(self) -> object: ...


class PostgresAuditError(RuntimeError):
    def __init__(self, code: str = "audit_unavailable") -> None:
        self.code = code if code in {"audit_unavailable", "invalid_input", "closed"} else "audit_unavailable"
        super().__init__(self.code)


def _row_dict(cursor: object, row: object) -> dict[str, object]:
    if isinstance(row, Mapping):
        return {str(key): value for key, value in row.items()}
    description = getattr(cursor, "description", None) or ()
    names = [item[0] for item in description if isinstance(item, (tuple, list)) and item]
    return dict(zip(names, row if isinstance(row, (tuple, list)) else ()))


def _json_value(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return dict(decoded) if isinstance(decoded, Mapping) else {}
    return {}


def _text(value: object, *, maximum: int = 512, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise PostgresAuditError("invalid_input")
    value = value.strip()
    if not value:
        if required:
            raise PostgresAuditError("invalid_input")
        return None
    if len(value) > maximum or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise PostgresAuditError("invalid_input")
    return value


class PostgresAuditSink:
    """Best-effort durable audit sink with server-side tenant filtering."""

    def __init__(self, connection_factory: Callable[[], DbConnection], *, close_connections: bool = True) -> None:
        if not callable(connection_factory):
            raise PostgresAuditError("invalid_input")
        self._connection_factory = connection_factory
        self._close_connections = close_connections
        self._closed = False

    @contextmanager
    def _session(self, *, write: bool = False) -> Iterator[tuple[DbConnection, object]]:
        if self._closed:
            raise PostgresAuditError("closed")
        connection: DbConnection | None = None
        cursor: object | None = None
        try:
            connection = self._connection_factory()
            if connection is None:
                raise PostgresAuditError()
            cursor = connection.cursor()
            yield connection, cursor
            if write:
                connection.commit()
        except PostgresAuditError:
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
            raise PostgresAuditError() from None
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
            raise PostgresAuditError()
        execute(query, params)

    @staticmethod
    def _one(cursor: object) -> dict[str, object] | None:
        row = getattr(cursor, "fetchone", lambda: None)()
        return None if row is None else _row_dict(cursor, row)

    @staticmethod
    def _many(cursor: object) -> list[dict[str, object]]:
        return [_row_dict(cursor, row) for row in getattr(cursor, "fetchall", lambda: [])()]

    def append(self, event: object) -> bool:
        prepared = _sanitise_event(event)
        if prepared is None:
            return False
        sanitized, _encoded = prepared
        try:
            tenant_id = _text(sanitized.get("tenant_id"), required=True)
            action = _text(sanitized.get("action"), maximum=256, required=True)
            columns = {
                "actor_user_id": _text(sanitized.get("actor_user_id")),
                "target_type": _text(sanitized.get("target_type")),
                "target_id": _text(sanitized.get("target_id")),
                "workspace_id": _text(sanitized.get("workspace_id")),
                "request_id": _text(sanitized.get("request_id")),
            }
        except PostgresAuditError:
            return False
        metadata = {
            key: value for key, value in sanitized.items()
            if key in _ALLOWED_FIELDS and key not in {"tenant_id", "action", *columns}
        }
        try:
            with self._session(write=True) as (_connection, cursor):
                self._execute(cursor, """
                    INSERT INTO rick_audit_events
                        (event_id, tenant_id, actor_user_id, action, target_type, target_id,
                         workspace_id, request_id, metadata, occurred_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,CAST(%s AS jsonb),NOW())
                """, (
                    f"audit-{uuid.uuid4().hex}", tenant_id, columns["actor_user_id"], action,
                    columns["target_type"], columns["target_id"], columns["workspace_id"],
                    columns["request_id"], json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                ))
        except PostgresAuditError:
            return False
        return True

    def emit(self, event: object) -> bool:
        return self.append(event)

    def list(self, *, tenant_id: str, workspace_id: str | None = None,
             limit: int = 50, order: str = "desc") -> list[dict[str, object]]:
        tenant = _text(tenant_id, maximum=128, required=True)
        workspace = _text(workspace_id, maximum=128)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1_000:
            raise PostgresAuditError("invalid_input")
        direction = {"asc": "ASC", "ascending": "ASC", "oldest": "ASC", "desc": "DESC", "descending": "DESC", "newest": "DESC"}.get((order or "").strip().lower())
        if direction is None:
            raise PostgresAuditError("invalid_input")
        clauses = ["tenant_id=%s"]
        params: list[object] = [tenant]
        if workspace is not None:
            clauses.append("(workspace_id IS NULL OR workspace_id=%s)")
            params.append(workspace)
        with self._session() as (_connection, cursor):
            self._execute(cursor, f"""
                SELECT event_id, tenant_id, actor_user_id, action, target_type, target_id,
                       workspace_id, request_id, metadata, occurred_at
                FROM rick_audit_events
                WHERE {' AND '.join(clauses)}
                ORDER BY occurred_at {direction}, event_id {direction}
                LIMIT %s
            """, tuple(params + [limit]))
            rows = self._many(cursor)
        result: list[dict[str, object]] = []
        for row in rows:
            item = {
                key: row[key] for key in (
                    "action", "actor_user_id", "target_id", "target_type", "tenant_id",
                    "workspace_id", "request_id",
                ) if row.get(key) is not None
            }
            item.update(_json_value(row.get("metadata")))
            occurred = row.get("occurred_at")
            if isinstance(occurred, datetime):
                item["occurred_at"] = occurred.isoformat()
            elif occurred is not None:
                item["occurred_at"] = occurred
            result.append(item)
        return result

    def health_check(self) -> bool:
        try:
            with self._session() as (_connection, cursor):
                self._execute(cursor, "SELECT 1")
                return self._one(cursor) is not None
        except PostgresAuditError:
            return False

    def close(self) -> None:
        self._closed = True


PostgresAuditStore = PostgresAuditSink

__all__ = ["DbConnection", "PostgresAuditError", "PostgresAuditSink", "PostgresAuditStore"]
