"""Bounded PostgreSQL projection worker for administrative audit outbox rows.

The outbox row and its audit projection are updated transactionally. Concurrent
workers rely on PostgreSQL row locks rather than process-local coordination.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Callable, Protocol

from services.audit import _ALLOWED_FIELDS
from services.sqlite_audit import _sanitise_event


_EVENT_TYPE = "admin.audit.completion"
_MAX_BATCH_SIZE = 1_000
_MAX_ATTEMPTS = 64
_MAX_EVENT_BYTES = 64 * 1024
_BASE_BACKOFF_SECONDS = 1.0
_MAX_BACKOFF_SECONDS = 300.0
_AUDIT_COLUMNS = frozenset(
    {
        "actor_user_id",
        "target_type",
        "target_id",
        "workspace_id",
        "request_id",
    }
)


class _Connection(Protocol):
    def cursor(self) -> object: ...
    def commit(self) -> object: ...
    def rollback(self) -> object: ...
    def close(self) -> object: ...


class _ProjectionError(RuntimeError):
    """A payload cannot be projected without disclosing its contents."""


def _row_dict(cursor: object, row: object) -> dict[str, object]:
    if isinstance(row, Mapping):
        return {str(key): value for key, value in row.items()}
    description = getattr(cursor, "description", None) or ()
    names: list[str] = []
    for item in description:
        name = getattr(item, "name", None)
        if not isinstance(name, str) and isinstance(item, (tuple, list)) and item:
            name = item[0]
        if isinstance(name, str):
            names.append(name)
    return dict(zip(names, row if isinstance(row, (tuple, list)) else ()))


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _ProjectionError()
        result[key] = value
    return result


def _reject_non_finite(_value: str) -> object:
    raise _ProjectionError()


def _payload_mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            raise _ProjectionError() from None
    if not isinstance(value, str):
        raise _ProjectionError()
    try:
        encoded = value.encode("utf-8")
        if len(encoded) > _MAX_EVENT_BYTES:
            raise _ProjectionError()
        decoded = json.loads(
            value,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite,
        )
    except _ProjectionError:
        raise
    except Exception:
        raise _ProjectionError() from None
    if not isinstance(decoded, Mapping):
        raise _ProjectionError()
    return decoded


def _audit_text(value: object, *, maximum: int = 512, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise _ProjectionError()
    value = value.strip()
    if not value:
        if required:
            raise _ProjectionError()
        return None
    if len(value) > maximum or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise _ProjectionError()
    return value


def _event_id(value: object) -> str:
    candidate = _audit_text(value, maximum=512, required=True)
    if candidate is None:
        raise _ProjectionError()
    return candidate


def _metadata_json(value: object) -> dict[str, object] | None:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if not isinstance(value, str):
        return None
    try:
        if len(value.encode("utf-8")) > _MAX_EVENT_BYTES:
            return None
        decoded = json.loads(
            value,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite,
        )
    except Exception:
        return None
    return dict(decoded) if isinstance(decoded, Mapping) else None


class PostgresAdminAuditReconciler:
    """Project due administrative-completion events into ``rick_audit_events``.

    A batch is one PostgreSQL transaction. ``FOR UPDATE SKIP LOCKED`` lets
    multiple worker processes divide the pending rows. If any row fails
    validation or insertion, that transaction is rolled back and the failed
    row's bounded retry state is recorded through a fresh transaction.
    """

    def __init__(
        self,
        connection_factory: Callable[[], _Connection | None],
        *,
        batch_size: int = 100,
        max_attempts: int = 8,
    ) -> None:
        if not callable(connection_factory):
            raise ValueError("connection_factory must be callable")
        if (
            isinstance(batch_size, bool)
            or not isinstance(batch_size, int)
            or not 1 <= batch_size <= _MAX_BATCH_SIZE
        ):
            raise ValueError("batch_size is out of range")
        if (
            isinstance(max_attempts, bool)
            or not isinstance(max_attempts, int)
            or not 1 <= max_attempts <= _MAX_ATTEMPTS
        ):
            raise ValueError("max_attempts is out of range")
        self._connection_factory = connection_factory
        self.batch_size = batch_size
        self.max_attempts = max_attempts

    @staticmethod
    def _execute(cursor: object, query: str, params: tuple[object, ...] = ()) -> None:
        execute = getattr(cursor, "execute", None)
        if not callable(execute):
            raise _ProjectionError()
        execute(query, params)

    @staticmethod
    def _one(cursor: object) -> dict[str, object] | None:
        row = getattr(cursor, "fetchone", lambda: None)()
        return None if row is None else _row_dict(cursor, row)

    @staticmethod
    def _close(resource: object | None) -> None:
        close = getattr(resource, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    @staticmethod
    def _rollback(connection: object | None) -> None:
        rollback = getattr(connection, "rollback", None)
        if callable(rollback):
            try:
                rollback()
            except Exception:
                pass

    @staticmethod
    def _failure_key(row: Mapping[str, object]) -> str | None:
        value = row.get("event_id")
        return value if isinstance(value, str) else None

    @staticmethod
    def _failure_keys(rows: tuple[dict[str, object], ...]) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                key for row in rows
                if (key := PostgresAdminAuditReconciler._failure_key(row)) is not None
            )
        )

    def _prepare_event(
        self,
        row: Mapping[str, object],
    ) -> tuple[str, str, str | None, str, str | None, str | None, str | None, str | None, str]:
        event_id = _event_id(row.get("event_id"))
        outbox_tenant = _audit_text(row.get("tenant_id"), required=True)
        prepared = _sanitise_event(_payload_mapping(row.get("payload")))
        if prepared is None:
            raise _ProjectionError()
        event, _encoded = prepared
        tenant_id = _audit_text(event.get("tenant_id"), required=True)
        if tenant_id != outbox_tenant:
            raise _ProjectionError()
        action = _audit_text(event.get("action"), maximum=256, required=True)
        columns = {
            field: _audit_text(event.get(field))
            for field in _AUDIT_COLUMNS
        }
        metadata = {
            key: value
            for key, value in event.items()
            if key in _ALLOWED_FIELDS
            and key not in {"tenant_id", "action", *_AUDIT_COLUMNS}
        }
        try:
            metadata_json = json.dumps(
                metadata,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError):
            raise _ProjectionError() from None
        if len(metadata_json.encode("utf-8")) > _MAX_EVENT_BYTES:
            raise _ProjectionError()
        return (
            event_id,
            tenant_id,
            columns["actor_user_id"],
            action,
            columns["target_type"],
            columns["target_id"],
            columns["workspace_id"],
            columns["request_id"],
            metadata_json,
        )

    def _same_existing_event(self, cursor: object, expected: tuple[object, ...]) -> bool:
        event_id = expected[0]
        self._execute(
            cursor,
            """
            SELECT event_id, tenant_id, actor_user_id, action, target_type,
                   target_id, workspace_id, request_id, metadata
            FROM rick_audit_events
            WHERE event_id=%s
            """,
            (event_id,),
        )
        existing = self._one(cursor)
        if existing is None:
            return False
        names = (
            "event_id", "tenant_id", "actor_user_id", "action", "target_type",
            "target_id", "workspace_id", "request_id",
        )
        if any(existing.get(name) != value for name, value in zip(names, expected[:8])):
            return False
        observed_metadata = _metadata_json(existing.get("metadata"))
        expected_metadata = _metadata_json(expected[8])
        return observed_metadata is not None and observed_metadata == expected_metadata

    def _project(self, cursor: object, row: Mapping[str, object]) -> str:
        expected = self._prepare_event(row)
        self._execute(
            cursor,
            """
            INSERT INTO rick_audit_events
                (event_id, tenant_id, actor_user_id, action, target_type, target_id,
                 workspace_id, request_id, metadata, occurred_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,CAST(%s AS jsonb),NOW())
            ON CONFLICT (event_id) DO NOTHING
            RETURNING event_id
            """,
            expected,
        )
        if self._one(cursor) is None and not self._same_existing_event(cursor, expected):
            raise _ProjectionError()
        event_id = expected[0]
        self._execute(
            cursor,
            """
            UPDATE rick_outbox
            SET published_at=NOW(), last_error_code=NULL
            WHERE event_id=%s AND event_type=%s
              AND published_at IS NULL AND dead_lettered_at IS NULL
            RETURNING event_id
            """,
            (event_id, _EVENT_TYPE),
        )
        if self._one(cursor) is None:
            raise _ProjectionError()
        return event_id

    def _record_failures(self, event_ids: tuple[str, ...]) -> None:
        if not event_ids:
            return
        connection: _Connection | None = None
        cursor: object | None = None
        try:
            connection = self._connection_factory()
            if connection is None:
                return
            cursor = connection.cursor()
            for event_id in event_ids:
                self._execute(
                    cursor,
                    """
                    SELECT attempts
                    FROM rick_outbox
                    WHERE event_id=%s AND event_type=%s
                      AND published_at IS NULL AND dead_lettered_at IS NULL
                    FOR UPDATE
                    """,
                    (event_id, _EVENT_TYPE),
                )
                observed = self._one(cursor)
                if observed is None:
                    continue
                attempts_value = observed.get("attempts", 0)
                if isinstance(attempts_value, bool) or not isinstance(attempts_value, int) or attempts_value < 0:
                    attempts_value = 0
                attempts = attempts_value + 1
                dead = attempts >= self.max_attempts
                backoff = min(
                    _BASE_BACKOFF_SECONDS * (2 ** min(attempts - 1, 16)),
                    _MAX_BACKOFF_SECONDS,
                )
                self._execute(
                    cursor,
                    """
                    UPDATE rick_outbox
                    SET attempts=%s,
                        last_error_code='audit_projection_failed',
                        available_at=CASE WHEN %s THEN available_at
                                          ELSE NOW() + (%s * INTERVAL '1 second') END,
                        dead_lettered_at=CASE WHEN %s THEN NOW() ELSE NULL END
                    WHERE event_id=%s AND event_type=%s
                      AND published_at IS NULL AND dead_lettered_at IS NULL
                    RETURNING attempts
                    """,
                    (attempts, dead, backoff, dead, event_id, _EVENT_TYPE),
                )
                self._one(cursor)
            connection.commit()
        except Exception:
            self._rollback(connection)
        finally:
            self._close(cursor)
            self._close(connection)

    def process_once(self) -> int:
        """Project one due batch; failures stay private and retry durably."""

        connection: _Connection | None = None
        cursor: object | None = None
        rows: tuple[dict[str, object], ...] = ()
        selected = False
        current_event_id: str | None = None
        failure_ids: tuple[str, ...] = ()
        published = 0
        failed = False
        try:
            connection = self._connection_factory()
            if connection is None:
                return 0
            cursor = connection.cursor()
            self._execute(
                cursor,
                """
                SELECT event_id, tenant_id, payload, attempts
                FROM rick_outbox
                WHERE event_type=%s
                  AND published_at IS NULL
                  AND dead_lettered_at IS NULL
                  AND available_at <= NOW()
                ORDER BY created_at ASC, event_id ASC
                LIMIT %s
                FOR UPDATE SKIP LOCKED
                """,
                (_EVENT_TYPE, self.batch_size),
            )
            raw_rows = getattr(cursor, "fetchall", lambda: [])()
            rows = tuple(_row_dict(cursor, row) for row in raw_rows)
            selected = True
            for row in rows:
                current_event_id = self._failure_key(row)
                self._project(cursor, row)
                published += 1
                current_event_id = None
            connection.commit()
            return published
        except Exception:
            failed = True
            self._rollback(connection)
            if current_event_id is not None:
                failure_ids = (current_event_id,)
            elif selected and rows:
                # A commit failure can be ambiguous. Only still-unpublished
                # rows are incremented by the follow-up transaction.
                failure_ids = self._failure_keys(rows)
        finally:
            self._close(cursor)
            self._close(connection)
        if failed:
            self._record_failures(failure_ids)
            return 0
        return published

    def health_check(self) -> bool:
        """Return a bounded database probe without exposing driver errors."""

        connection: _Connection | None = None
        cursor: object | None = None
        try:
            connection = self._connection_factory()
            if connection is None:
                return False
            cursor = connection.cursor()
            self._execute(
                cursor,
                """
                SELECT available_at, dead_lettered_at, manual_retry_count
                FROM rick_outbox
                LIMIT 0
                """,
            )
            self._execute(cursor, "SELECT 1")
            healthy = getattr(cursor, "fetchone", lambda: None)() is not None
            if healthy:
                connection.commit()
            else:
                self._rollback(connection)
            return healthy
        except Exception:
            self._rollback(connection)
            return False
        finally:
            self._close(cursor)
            self._close(connection)


__all__ = ["PostgresAdminAuditReconciler"]
