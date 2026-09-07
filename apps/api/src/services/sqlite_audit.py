"""Local, file-backed audit sink using only the Python standard library.

This adapter is deliberately local durability plumbing.  It does not claim to
be the production audit store or to replace the external-store gate.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from itertools import islice
import json
import math
from pathlib import Path
import re
import sqlite3
from threading import RLock
from typing import Iterator

from services.audit import _ALLOWED_FIELDS, _SAFE_STRING, _strip_url_credentials


SCHEMA_VERSION = 1
DEFAULT_RETENTION = 10_000
_REDACTED = "[REDACTED]"
_MAX_SANITIZE_DEPTH = 32

# Key-based redaction is intentional: arbitrary strings are kept useful for
# audit search, while credential-bearing fields are never persisted verbatim.
_SENSITIVE_KEY_STEMS = (
    "password",
    "passwd",
    "passphrase",
    "secret",
    "token",
    "authorization",
    "cookie",
    "credential",
    "apikey",
    "privatekey",
    "csrf",
)
_SENSITIVE_KEY_SUFFIXES = ("token", "secret", "password", "apikey", "privatekey")
_SENSITIVE_VALUE_MARKERS = (
    "authorization", "bearer ", "api key", "apikey", "cookie", "credential",
    "password", "passphrase", "private document", "document content", "prompt",
    "secret", "token=", "reset token", "access token",
)
_MAX_STRING_LENGTH = 512
_MAX_EVENT_BYTES = 64 * 1024
_MAX_CONTAINER_ITEMS = 64
_MAX_KEY_LENGTH = 128
_NO_ACTION_ALLOWED_FIELDS = frozenset({"sequence", "writer", "payload", "second"})
_ORDER_ALIASES = {
    "asc": "ASC",
    "ascending": "ASC",
    "oldest": "ASC",
    "oldest_first": "ASC",
    "desc": "DESC",
    "descending": "DESC",
    "newest": "DESC",
    "newest_first": "DESC",
}


def _normalise_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", key.casefold()).strip("_")


def _is_sensitive_key(key: str) -> bool:
    normalised = _normalise_key(key)
    compact = normalised.replace("_", "")
    if not normalised:
        return False
    if any(
        normalised == stem
        or normalised.startswith(f"{stem}_")
        or compact.startswith(stem)
        for stem in _SENSITIVE_KEY_STEMS
    ):
        return True
    return any(compact.endswith(suffix) for suffix in _SENSITIVE_KEY_SUFFIXES)


def _sanitise_value(value: object, *, active: set[int], depth: int) -> object:
    """Copy JSON-compatible values while rejecting unsafe object graphs."""

    if depth > _MAX_SANITIZE_DEPTH:
        raise ValueError("audit event nesting is too deep")
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, str):
        cleaned = value[:_MAX_STRING_LENGTH]
        if "://" in cleaned:
            cleaned = _strip_url_credentials(cleaned)
            if cleaned is None:
                return _REDACTED
        lowered = cleaned.casefold()
        if any(marker in lowered for marker in _SENSITIVE_VALUE_MARKERS):
            return _REDACTED
        if _SAFE_STRING.fullmatch(cleaned) is None:
            return _REDACTED
        return cleaned
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("audit event contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in active:
            raise ValueError("audit event contains a cycle")
        active.add(identity)
        try:
            result: dict[str, object] = {}
            for key, item in islice(value.items(), _MAX_CONTAINER_ITEMS):
                if not isinstance(key, str):
                    raise ValueError("audit event keys must be strings")
                result[key[:_MAX_KEY_LENGTH]] = (
                    _REDACTED
                    if _is_sensitive_key(key)
                    else _sanitise_value(item, active=active, depth=depth + 1)
                )
            return result
        finally:
            active.remove(identity)
    if isinstance(value, (list, tuple)):
        identity = id(value)
        if identity in active:
            raise ValueError("audit event contains a cycle")
        active.add(identity)
        try:
            return [
                _sanitise_value(item, active=active, depth=depth + 1)
                for item in islice(value, _MAX_CONTAINER_ITEMS)
            ]
        finally:
            active.remove(identity)
    raise ValueError(f"unsupported audit event value: {type(value).__name__}")


def _sanitise_event(event: object) -> tuple[dict[str, object], str] | None:
    """Return a detached dict and canonical JSON, or ``None`` for bad input."""

    if not isinstance(event, Mapping):
        return None
    # Every event is projected before persistence.  Action-bearing API events
    # use the canonical audit schema; the small no-action diagnostic subset is
    # retained only for adapter-level counters and is bounded by the same
    # recursive sanitizer below.  Unknown fields never cross this boundary.
    action = event.get("action")
    if "action" in event:
        if not isinstance(action, str) or not action or _SAFE_STRING.fullmatch(action) is None:
            return None
        allowed = _ALLOWED_FIELDS
    else:
        allowed = _NO_ACTION_ALLOWED_FIELDS
    event = {key: event[key] for key in allowed if key in event}
    if not event:
        return None
    try:
        sanitised = _sanitise_value(event, active=set(), depth=0)
        if not isinstance(sanitised, dict):
            return None
        encoded = json.dumps(
            sanitised,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        if len(encoded.encode("utf-8")) > _MAX_EVENT_BYTES:
            return None
    except Exception:
        return None
    return sanitised, encoded


class SQLiteAuditSink:
    """Transactional local audit sink with bounded, restart-safe history.

    ``append`` is best-effort and returns ``False`` for malformed events or a
    storage failure.  ``emit`` keeps the existing sink contract and deliberately
    does not raise into a request path.
    """

    def __init__(
        self,
        path: str | Path,
        max_events: int = DEFAULT_RETENTION,
        *,
        retention: int | None = None,
    ) -> None:
        if retention is not None:
            if max_events != DEFAULT_RETENTION and max_events != retention:
                raise ValueError("max_events and retention disagree")
            max_events = retention
        self._max_events = self._validate_retention(max_events)
        self.retention = self._max_events
        self.max_events = self._max_events
        self._lock = RLock()
        self._closed = False
        self._file_backed = str(path) != ":memory:"
        self.path = str(path)
        self._database_path: Path | None = None

        if self._file_backed:
            self._database_path = self._prepare_file_path(Path(path).expanduser())
            connection_path = str(self._database_path)
        else:
            connection_path = ":memory:"

        self._connection = sqlite3.connect(
            connection_path,
            check_same_thread=False,
            isolation_level=None,
            timeout=30.0,
        )
        self._connection.row_factory = sqlite3.Row
        try:
            self._connection.execute("PRAGMA busy_timeout = 30000")
            self._connection.execute("PRAGMA foreign_keys = ON")
            if self._file_backed:
                journal_mode = str(
                    self._connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
                ).lower()
                if journal_mode != "wal":
                    raise RuntimeError("SQLite audit database did not enter WAL mode")
                self._connection.execute("PRAGMA synchronous = FULL")
            self._initialize()
            self._tighten_file_permissions()
        except Exception:
            self._connection.close()
            raise

    @staticmethod
    def _validate_retention(value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError("audit retention must be a positive integer")
        return value

    @staticmethod
    def _prepare_file_path(path: Path) -> Path:
        if path.name in {"", ".", ".."} or path.exists() and path.is_dir():
            raise ValueError("SQLite audit path must be a file")
        if path.is_symlink():
            raise ValueError("SQLite audit path must not be a symlink")

        parent = path.parent
        # A bare relative filename would otherwise chmod the shared process
        # working directory. Require that directory to already be private.
        if parent == Path("."):
            parent = Path.cwd()
            if not parent.is_dir() or (parent.stat().st_mode & 0o077):
                raise ValueError("bare audit filename requires a private working directory")
        if parent == Path(parent.anchor) or parent == Path("/"):
            raise ValueError("SQLite audit database needs a dedicated private parent")
        if parent.is_symlink():
            raise ValueError("SQLite audit parent must not be a symlink")
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not parent.is_dir():
            raise ValueError("SQLite audit parent must be a directory")
        parent.chmod(0o700)

        # Resolve only after preparing the parent; this retains a relative path
        # for SQLite while making the returned path unambiguous for permissions.
        return path

    def _tighten_file_permissions(self, *, strict: bool = True) -> None:
        if not self._file_backed or self._database_path is None:
            return
        try:
            self._database_path.chmod(0o600)
        except OSError:
            if strict:
                raise
            return
        # WAL/SHM files are transient, but are kept private whenever SQLite has
        # created them. The 0700 directory is the second containment boundary.
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = Path(f"{self._database_path}{suffix}")
            try:
                if sidecar.exists() and not sidecar.is_symlink():
                    sidecar.chmod(0o600)
            except OSError:
                pass

    def _initialize(self) -> None:
        with self._transaction():
            current = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
            if current not in (0, SCHEMA_VERSION):
                raise RuntimeError(f"unsupported audit schema version: {current}")
            if current == 0:
                self._connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS audit_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                self._connection.execute(
                    "CREATE INDEX IF NOT EXISTS audit_events_id_idx ON audit_events (id)"
                )
                self._connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            else:
                columns = {
                    str(row[1])
                    for row in self._connection.execute("PRAGMA table_info(audit_events)")
                }
                if not {"id", "event_json", "created_at"}.issubset(columns):
                    raise RuntimeError("audit schema version is missing required columns")
            self._trim_locked()

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield
            except Exception:
                try:
                    self._connection.rollback()
                except sqlite3.Error:
                    pass
                raise
            else:
                try:
                    self._connection.commit()
                except Exception:
                    try:
                        self._connection.rollback()
                    except sqlite3.Error:
                        pass
                    raise
                # Permission maintenance happens after the durable commit and
                # must not turn a successful append into a reported failure.
                self._tighten_file_permissions(strict=False)

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="microseconds")

    def _trim_locked(self) -> None:
        self._connection.execute(
            """
            DELETE FROM audit_events
            WHERE id NOT IN (
                SELECT id FROM audit_events ORDER BY id DESC LIMIT ?
            )
            """,
            (self._max_events,),
        )

    def append(self, event: object) -> bool:
        """Sanitise and atomically append one event, enforcing retention."""

        prepared = _sanitise_event(event)
        if prepared is None:
            return False
        sanitised, encoded = prepared
        del sanitised  # The canonical JSON is the persisted representation.
        try:
            with self._transaction():
                self._connection.execute(
                    "INSERT INTO audit_events (event_json, created_at) VALUES (?, ?)",
                    (encoded, self._timestamp()),
                )
                self._trim_locked()
        except Exception:
            # Audit must not break the request path; the transaction context has
            # already rolled back any partial insert before this return.
            return False
        return True

    def append_event(self, event: object) -> bool:
        """Compatibility spelling for callers that name the operation explicitly."""

        return self.append(event)

    def emit(self, event: object) -> None:
        """Best-effort sink interface used by the API audit hooks."""

        self.append(event)

    @staticmethod
    def _normalise_order(order: str) -> str:
        if not isinstance(order, str):
            raise ValueError("audit order must be asc or desc")
        try:
            return _ORDER_ALIASES[order.strip().casefold()]
        except KeyError:
            raise ValueError("audit order must be asc or desc") from None

    @staticmethod
    def _validate_limit(limit: int | None) -> int | None:
        if limit is None:
            return None
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise ValueError("audit limit must be a non-negative integer")
        return limit

    def list_events(
        self,
        limit: int | None = None,
        order: str = "desc",
        *,
        newest_first: bool | None = None,
    ) -> list[dict[str, object]]:
        """Read detached event dicts ordered by insertion id."""

        limit = self._validate_limit(limit)
        if newest_first is not None:
            if not isinstance(newest_first, bool):
                raise ValueError("newest_first must be boolean")
            requested = "DESC" if newest_first else "ASC"
            normalised = self._normalise_order(order)
            if order != "desc" and normalised != requested:
                raise ValueError("order and newest_first disagree")
            direction = requested
        else:
            direction = self._normalise_order(order)
        if limit == 0:
            return []

        query = f"SELECT event_json FROM audit_events ORDER BY id {direction}"
        parameters: tuple[object, ...] = ()
        if limit is not None:
            query += " LIMIT ?"
            parameters = (limit,)
        with self._lock:
            rows = self._connection.execute(query, parameters).fetchall()

        events: list[dict[str, object]] = []
        for row in rows:
            try:
                decoded = json.loads(row["event_json"])
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(decoded, dict):
                events.append(decoded)
        return events

    def list(
        self,
        limit: int | None = None,
        order: str = "desc",
        *,
        newest_first: bool | None = None,
    ) -> list[dict[str, object]]:
        """Short spelling for :meth:`list_events`."""

        return self.list_events(limit=limit, order=order, newest_first=newest_first)

    @property
    def events(self) -> list[dict[str, object]]:
        """Expose the in-memory sink-compatible view in oldest-first order."""

        return self.list_events(order="asc")

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._connection.close()
                self._closed = True

    def __enter__(self) -> "SQLiteAuditSink":
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()


# The sink name is the factory-facing contract; the alias keeps the adapter
# usable from code that calls the durable component a store.
SQLiteAuditStore = SQLiteAuditSink


__all__ = ["DEFAULT_RETENTION", "SCHEMA_VERSION", "SQLiteAuditSink", "SQLiteAuditStore"]
