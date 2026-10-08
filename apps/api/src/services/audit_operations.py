"""Mandatory operation ledger, owner transactions and non-repeating recovery.

The journal owns replay and outcome; a telemetry emitter is not that owner.
PostgreSQL completion rows reuse the existing admin audit outbox projector.
"""

from contextlib import contextmanager, nullcontext
from copy import deepcopy
import hashlib
import json
from threading import RLock, Lock
from weakref import WeakValueDictionary
from pathlib import Path
import os
import fcntl
import uuid
from datetime import datetime, timezone

from fastapi.responses import JSONResponse

from core.errors import ApiError, ERROR_CODES
from services.audit import emit_required


_BOOTSTRAP_LOCK = RLock()
_MAX_RECORD_BYTES = 64 * 1024
_UNRESOLVED = ("in_progress", "reconciliation_required")
# An advisory DB session may disappear while its Python callback is still alive.
# Only this interpreter can prove absence of one of its registered executors.
_PROCESS_OWNER = uuid.uuid4().hex
_LIVE_EXECUTIONS = {}


def _process_owner():
    return f"{_PROCESS_OWNER}:{os.getpid()}"


@contextmanager
def _track_execution(operation_id):
    with _BOOTSTRAP_LOCK:
        _LIVE_EXECUTIONS[operation_id] = _LIVE_EXECUTIONS.get(operation_id, 0) + 1
    try:
        yield
    finally:
        with _BOOTSTRAP_LOCK:
            count = _LIVE_EXECUTIONS[operation_id] - 1
            if count:
                _LIVE_EXECUTIONS[operation_id] = count
            else:
                del _LIVE_EXECUTIONS[operation_id]


class _ExecutionGuard:
    def __init__(self, check):
        self._check = check

    def assert_held(self):
        try:
            if self._check() is not True:
                raise ApiError("provider_unavailable")
        except Exception:
            raise ApiError("provider_unavailable") from None


def _encoded(value):
    try:
        text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        if len(text.encode()) > _MAX_RECORD_BYTES:
            raise ValueError()
        return text
    except (ValueError, TypeError, RecursionError):
        raise ApiError("provider_unavailable") from None


def input_digest(value):
    """Bind an idempotency key to inputs without persisting their contents."""
    return hashlib.sha256(_encoded(value).encode()).hexdigest()


def source_digest(source):
    if isinstance(source, str):
        return hashlib.sha256(source.encode()).hexdigest()
    if isinstance(source, bytes):
        return hashlib.sha256(source).hexdigest()
    stream = getattr(source, "file", None)
    if stream is None:
        raise ApiError("validation_error")
    offset = stream.tell()
    digest = hashlib.sha256()
    try:
        stream.seek(0)
        while chunk := stream.read(64 * 1024):
            digest.update(chunk)
    finally:
        stream.seek(offset)
    return digest.hexdigest()


class OperationLedger:
    def __init__(self, sink, factory=None, sqlite_owner=None):
        from services.postgres_audit import PostgresAuditSink
        from services.sqlite_audit import SQLiteAuditSink

        self.sink = sink
        self.sqlite_owner = sqlite_owner
        self.factory = factory or (sink._connection_factory if sqlite_owner is None and isinstance(sink, PostgresAuditSink) else None)
        self.sqlite = (sqlite_owner is not None or isinstance(sink, SQLiteAuditSink)) and self.factory is None
        self.sqlite_store = sqlite_owner or sink
        if self.sqlite:
            try:
                with self.sqlite_store._transaction():
                    self.sqlite_store._connection.execute("CREATE TABLE IF NOT EXISTS api_audit_operations (operation_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
                    if sqlite_owner is not None:
                        self.sqlite_store._connection.execute("CREATE TABLE IF NOT EXISTS api_audit_completions (event_id TEXT PRIMARY KEY, event_json TEXT NOT NULL, projected INTEGER NOT NULL DEFAULT 0)")
            except Exception:
                raise ApiError("provider_unavailable") from None
        if self.factory is None and not self.sqlite:
            if sink is None or not callable(getattr(sink, "emit", None)):
                raise ApiError("provider_unavailable")
            with _BOOTSTRAP_LOCK:
                if not hasattr(sink, "_operation_records"):
                    sink._operation_records = {}
                    sink._operation_lock = RLock()

    @contextmanager
    def execution_guard(self, operation_id):
        """Exclude terminal reconciliation from a live workflow, across adapter handles."""
        if self.factory is not None:
            connection = None
            acquired = False
            try:
                connection = self.factory()
                with self.cursor(connection) as cursor:
                    cursor.execute("SET LOCAL statement_timeout = '2000ms'")
                    cursor.execute("SELECT pg_try_advisory_lock(hashtext(%s), hashtext(%s)) AS held",
                        ("rick.api.audit.execution", operation_id))
                    from services.postgres_audit import _row_dict
                    row = cursor.fetchone()
                    acquired = row is not None and _row_dict(cursor, row).get("held") is True
                connection.commit()  # Session lock survives short journal transactions.
            except BaseException as exc:
                if connection is not None:
                    try:
                        connection.close()
                    except Exception:
                        pass
                if not isinstance(exc, Exception):
                    raise
                raise ApiError("provider_unavailable") from None

            def held():
                with self.cursor(connection) as cursor:
                    cursor.execute("SET LOCAL statement_timeout = '2000ms'")
                    cursor.execute("""SELECT EXISTS (
                        SELECT 1 FROM pg_locks WHERE locktype='advisory' AND pid=pg_backend_pid()
                          AND classid::bigint=(hashtext(%s)::bigint & 4294967295)
                          AND objid::bigint=(hashtext(%s)::bigint & 4294967295)
                          AND objsubid=2 AND granted) AS held""",
                        ("rick.api.audit.execution", operation_id))
                    row = cursor.fetchone()
                    present = row is not None and _row_dict(cursor, row).get("held") is True
                connection.commit()
                return present
            try:
                yield _ExecutionGuard(held) if acquired else None
            finally:
                try:
                    if acquired:
                        with self.cursor(connection) as cursor:
                            cursor.execute("SET LOCAL statement_timeout = '2000ms'")
                            cursor.execute("SELECT pg_advisory_unlock(hashtext(%s), hashtext(%s))",
                                ("rick.api.audit.execution", operation_id))
                        connection.commit()
                except Exception:
                    pass  # Closing our dedicated session also releases its locks.
                finally:
                    try:
                        connection.close()
                    except Exception:
                        pass
            return
        if self.sqlite and self.sqlite_store.path != ":memory:":
            directory = Path(str(Path(self.sqlite_store.path).resolve()) + ".audit-execution")
            descriptor = None
            acquired = False
            try:
                directory.mkdir(mode=0o700, exist_ok=True)
                name = hashlib.sha256(operation_id.encode()).hexdigest() + ".lock"
                descriptor = os.open(directory / name, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except BlockingIOError:
                    pass
            except Exception:
                if descriptor is not None:
                    os.close(descriptor)
                raise ApiError("provider_unavailable") from None
            try:
                yield _ExecutionGuard(lambda: acquired) if acquired else None
            finally:
                if acquired:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                os.close(descriptor)
            return
        holder = self.sqlite_store if self.sqlite else self.sink
        with _BOOTSTRAP_LOCK:
            if not hasattr(holder, "_execution_locks"):
                holder._execution_locks = WeakValueDictionary()
            mutex = holder._execution_locks.get(operation_id)
            if mutex is None:
                mutex = Lock()
                holder._execution_locks[operation_id] = mutex
        acquired = mutex.acquire(blocking=False)
        try:
            yield _ExecutionGuard(mutex.locked) if acquired else None
        finally:
            if acquired:
                mutex.release()

    def executor_absent(self, record):
        """Called only while recovery holds execution_guard and the journal lock.

        Memory/SQLite guards cannot expire behind a live callback. PostgreSQL
        session locks can: require an owner in this interpreter and its live
        execution registry as well. Foreign/legacy PostgreSQL owners stay fenced.
        """
        if self.factory is None:
            return True
        with _BOOTSTRAP_LOCK:
            return (record.get("execution", {}).get("process_owner") == _process_owner()
                    and record["operation_id"] not in _LIVE_EXECUTIONS)

    @contextmanager
    def transaction(self, borrowed=None):
        if self.factory is not None:
            connection = borrowed
            owns = connection is None
            try:
                if owns:
                    connection = self.factory()
                if connection is None:
                    raise ApiError("provider_unavailable")
                yield connection
                if owns:
                    connection.commit()
            except BaseException:
                if owns and connection is not None:
                    connection.rollback()
                raise
            finally:
                if owns and connection is not None:
                    connection.close()
        elif self.sqlite:
            if self.sqlite_owner is not None and borrowed is not None:
                yield borrowed
            else:
                with self.sqlite_store._transaction():
                    yield self.sqlite_store._connection
        else:
            with self.sink._operation_lock:
                before = deepcopy(self.sink._operation_records)
                events = deepcopy(getattr(self.sink, "events", None))
                try:
                    yield None
                except BaseException:
                    self.sink._operation_records = before
                    if isinstance(events, list):
                        self.sink.events[:] = events
                    raise

    @contextmanager
    def cursor(self, connection):
        cursor = connection.cursor()
        try:
            yield cursor
        finally:
            cursor.close()

    def get(self, connection, operation_id, *, lock=False):
        if self.factory is not None:
            from services.postgres_audit import _row_dict
            from services.json_boundary import decode_bounded_json
            with self.cursor(connection) as cursor:
                if lock:
                    cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))", ("rick.api.audit.operation", operation_id))
                cursor.execute("SELECT payload FROM rick_outbox WHERE event_id=%s AND event_type='api.audit.operation'", (operation_id,))
                row = cursor.fetchone()
                if row is None:
                    return None
                payload = _row_dict(cursor, row).get("payload")
                decoded = decode_bounded_json(payload, None, max_bytes=_MAX_RECORD_BYTES)
                if not isinstance(decoded, dict):
                    raise ApiError("provider_unavailable")
                return decoded
        if self.sqlite:
            row = connection.execute("SELECT payload FROM api_audit_operations WHERE operation_id=?", (operation_id,)).fetchone()
            if row is None:
                return None
            from services.json_boundary import decode_bounded_json
            decoded = decode_bounded_json(row[0], None, max_bytes=_MAX_RECORD_BYTES)
            if not isinstance(decoded, dict):
                raise ApiError("provider_unavailable")
            return decoded
        return deepcopy(self.sink._operation_records.get(operation_id))

    def save(self, connection, record):
        encoded = _encoded(record)
        operation_id = record["operation_id"]
        if self.factory is not None:
            with self.cursor(connection) as cursor:
                cursor.execute("""
                    INSERT INTO rick_outbox (event_id,tenant_id,aggregate_type,aggregate_id,event_type,payload)
                    VALUES (%s,%s,'api_operation',%s,'api.audit.operation',CAST(%s AS jsonb))
                    ON CONFLICT (event_id) DO UPDATE SET payload=EXCLUDED.payload
                    WHERE rick_outbox.event_type='api.audit.operation'
                """, (operation_id, record["event"]["tenant_id"], operation_id, encoded))
                if cursor.rowcount != 1:
                    raise ApiError("provider_unavailable")
        elif self.sqlite:
            connection.execute("INSERT INTO api_audit_operations VALUES (?,?) ON CONFLICT(operation_id) DO UPDATE SET payload=excluded.payload", (operation_id, encoded))
        else:
            if operation_id not in self.sink._operation_records and len(self.sink._operation_records) >= 10_000:
                raise ApiError("provider_unavailable")
            self.sink._operation_records[operation_id] = json.loads(encoded)

    def append_outcome(self, connection, record):
        from services.sqlite_audit import _sanitise_event

        event = {**record["event"], "status": record["status"], "correlation_id": record["operation_id"]}
        if record.get("error_code"):
            event["error_code"] = record["error_code"]
        prepared = _sanitise_event(event)
        if prepared is None:
            raise ApiError("provider_unavailable")
        event, encoded = prepared
        if self.factory is not None:
            # The ledger is the admission trail; only outcomes enter the existing projector.
            if record["status"] in _UNRESOLVED:
                return
            with self.cursor(connection) as cursor:
                cursor.execute("""
                    INSERT INTO rick_outbox (event_id,tenant_id,aggregate_type,aggregate_id,event_type,payload)
                    VALUES (%s,%s,'api_operation',%s,'admin.audit.completion',CAST(%s AS jsonb))
                    ON CONFLICT (event_id) DO NOTHING
                """, (record["operation_id"] + "-" + record["status"], event["tenant_id"], record["operation_id"], encoded))
        elif self.sqlite:
            if self.sqlite_owner is not None:
                if record["status"] not in _UNRESOLVED:
                    connection.execute("INSERT INTO api_audit_completions(event_id,event_json) VALUES (?,?) ON CONFLICT(event_id) DO NOTHING",
                        (record["operation_id"] + "-" + record["status"], encoded))
            else:
                connection.execute("INSERT INTO audit_events(event_json,created_at) VALUES (?,?)", (encoded, self.sink._timestamp()))
                self.sink._trim_locked()
        else:
            emit_required(self.sink, event)

    def deliver_local(self):
        """Bounded at-least-once projection; owner completion is already committed."""
        if self.sqlite_owner is None:
            return
        try:
            with self.transaction() as connection:
                rows = connection.execute("SELECT event_id,event_json FROM api_audit_completions WHERE projected=0 ORDER BY rowid LIMIT 100").fetchall()
                for row in rows:
                    emit_required(self.sink, json.loads(row[1]))
                    connection.execute("UPDATE api_audit_completions SET projected=1 WHERE event_id=?", (row[0],))
        except Exception:
            pass  # Delivery is retried by a subsequent operation/status read.

    def pending(self, session, limit, *, operator=False):
        """Enumerate the durable recovery owner, even when the caller lost its response."""
        with self.transaction() as connection:
            if self.factory is not None:
                from services.postgres_audit import _row_dict
                from services.json_boundary import decode_bounded_json
                with self.cursor(connection) as cursor:
                    cursor.execute("""SELECT payload FROM rick_outbox
                        WHERE event_type='api.audit.operation' AND tenant_id=%s
                          AND payload->'event'->>'workspace_id'=%s
                          AND (%s OR payload->'event'->>'actor_user_id'=%s)
                          AND payload->>'status' IN ('in_progress','reconciliation_required')
                        ORDER BY created_at,event_id LIMIT %s""",
                        (session.tenant_id, session.workspace_id, operator, session.user_id, limit))
                    return [decode_bounded_json(_row_dict(cursor, row).get("payload"), None, max_bytes=_MAX_RECORD_BYTES)
                            for row in cursor.fetchall()]
            if self.sqlite:
                rows = connection.execute("""SELECT payload FROM api_audit_operations
                    WHERE json_extract(payload,'$.event.tenant_id')=?
                      AND json_extract(payload,'$.event.workspace_id')=?
                      AND (? OR json_extract(payload,'$.event.actor_user_id')=?)
                      AND json_extract(payload,'$.status') IN ('in_progress','reconciliation_required')
                    ORDER BY rowid LIMIT ?""", (session.tenant_id, session.workspace_id, operator, session.user_id, limit)).fetchall()
                return [json.loads(row[0]) for row in rows]
            return [deepcopy(record) for record in self.sink._operation_records.values()
                    if record["status"] in _UNRESOLVED and record["event"]["tenant_id"] == session.tenant_id
                    and record["event"]["workspace_id"] == session.workspace_id
                    and (operator or record["event"]["actor_user_id"] == session.user_id)][:limit]

    def delivery_status(self, record):
        if record["status"] == "in_progress":
            return {"status": "awaiting_execution_outcome"}
        if record["status"] == "reconciliation_required":
            return {"status": "awaiting_reconciliation"}
        event_id = record["operation_id"] + "-" + record["status"]
        if self.factory is not None:
            from services.postgres_audit import _row_dict
            with self.transaction() as connection, self.cursor(connection) as cursor:
                cursor.execute("SELECT published_at,attempts,dead_lettered_at FROM rick_outbox WHERE event_id=%s AND event_type='admin.audit.completion'", (event_id,))
                row = cursor.fetchone()
                if row is None:
                    return {"event_id": event_id, "status": "missing_completion"}
                value = _row_dict(cursor, row)
                status = "published" if value.get("published_at") else "dead_lettered" if value.get("dead_lettered_at") else "projection_pending"
                return {"event_id": event_id, "status": status, "attempts": value.get("attempts", 0)}
        if self.sqlite_owner is not None:
            with self.transaction() as connection:
                row = connection.execute("SELECT projected FROM api_audit_completions WHERE event_id=?", (event_id,)).fetchone()
                return {"event_id": event_id, "status": "missing_completion" if row is None else "published" if row[0] else "projection_pending"}
        return {"status": "published"}


def _factory(owner):
    return getattr(owner, "audit_connection_factory", None)


def operation_response(record):
    return JSONResponse(status_code=202, content={
        **(record.get("result") or {}), "audit_operation_id": record["operation_id"],
        "audit_status": record["status"], "reconciliation_required": record["status"] == "reconciliation_required",
    })


def run_operation(*, request, session, action, target_id, inputs, callback, owner=None, transaction=None, success_status=None):
    """Execute at most once, sharing the durable owner's transaction when available."""
    from dependencies.services import get_providers

    providers = get_providers(request)
    event = {"action": action, "actor_user_id": session.user_id, "tenant_id": session.tenant_id,
             "workspace_id": session.workspace_id, "target_id": target_id,
             "request_id": getattr(request.state, "request_id", None)}
    from services.sqlite_audit import _sanitise_event
    prepared = _sanitise_event(event)
    if prepared is None:
        raise ApiError("provider_unavailable")
    safe_event, _ = prepared
    if any(safe_event.get(field) != event[field] for field in ("tenant_id", "workspace_id", "actor_user_id")):
        raise ApiError("provider_unavailable")
    event = safe_event
    key = request.headers.get("idempotency-key")
    if key is not None and (not key.strip() or len(key) > 128 or any(ord(c) < 33 or ord(c) > 126 for c in key)):
        raise ApiError("validation_error")
    key = key or uuid.uuid4().hex
    operation_id = "auditop-" + input_digest([session.tenant_id, session.workspace_id, session.user_id, action, key])
    record = {"operation_id": operation_id, "event": event, "fingerprint": input_digest([target_id, inputs]),
              "status": "in_progress", "result": None,
              "execution": {"id": uuid.uuid4().hex, "phase": "admitted", "process_owner": _process_owner()},
              "created_at": datetime.now(timezone.utc).isoformat()}
    ledger = OperationLedger(providers.audit_sink, _factory(owner), getattr(owner, "audit_sqlite_owner", None))
    atomic = transaction is not None
    if atomic:
        record["execution"]["phase"] = "atomic"
    started = False

    def completed_response(previous):
        result = deepcopy(previous["result"])
        if previous.get("response_status") is not None:
            return JSONResponse(status_code=previous["response_status"], content=result)
        return result

    def replay(connection):
        previous = ledger.get(connection, operation_id, lock=True)
        if previous is None:
            return None
        if previous.get("fingerprint") != record["fingerprint"]:
            raise ApiError("conflict")
        if previous.get("status") == "failed":
            raise ApiError(previous.get("error_code", "internal_error"))
        if previous.get("status") == "completed":
            return completed_response(previous)
        return operation_response(previous)

    with (nullcontext() if atomic else _track_execution(operation_id)), \
            (nullcontext(None) if atomic else ledger.execution_guard(operation_id)) as guard:
        # A replay must not wait on a live callback's execution guard.
        if not atomic and guard is None:
            with ledger.transaction() as connection:
                previous = replay(connection)
            if previous is None:
                raise ApiError("conflict")  # Guard acquired before first admission became visible.
            return previous
        try:
            if atomic:
                with transaction() as owner_connection:
                    with ledger.transaction(owner_connection) as connection:
                        previous = replay(connection)
                        if previous is not None:
                            return previous
                        ledger.save(connection, record)
                        ledger.append_outcome(connection, record)
                        started = True
                        result = callback(owner_connection)
                        if success_status is not None:
                            record["response_status"] = success_status
                            result = {**result, "audit_status": "pending",
                                      "audit_event_id": operation_id + "-completed",
                                      "reconciliation_required": True,
                                      "request_id": event.get("request_id")}
                        record.update(status="completed", result=result)
                        record["execution"]["phase"] = "returned"
                        ledger.save(connection, record)
                        ledger.append_outcome(connection, record)
            else:
                with ledger.transaction() as connection:
                    previous = replay(connection)
                    if previous is not None:
                        return previous
                    ledger.save(connection, record)
                    ledger.append_outcome(connection, record)
                guard.assert_held()
                # Durable no-dispatch boundary: cancellation/reconciliation of an
                # admitted record fences a stale executor before invoking any effect.
                with ledger.transaction() as connection:
                    previous = ledger.get(connection, operation_id, lock=True)
                    if (previous is None or previous.get("status") != "in_progress"
                            or previous.get("execution") != record["execution"]):
                        raise ApiError("conflict")
                    record["execution"]["phase"] = "dispatched"
                    ledger.save(connection, record)
                guard.assert_held()
                started = True
                result = callback(None)
                record.update(status="completed", result=result)
                record["execution"]["phase"] = "returned"
                try:
                    with ledger.transaction() as connection:
                        previous = ledger.get(connection, operation_id, lock=True)
                        if (previous is None or previous.get("status") != "in_progress"
                                or previous.get("execution", {}).get("id") != record["execution"]["id"]):
                            raise ApiError("conflict")
                        ledger.save(connection, record)
                        ledger.append_outcome(connection, record)
                except Exception:
                    record.update(status="reconciliation_required", error_code="provider_unavailable")
                    try:
                        with ledger.transaction() as connection:
                            previous = ledger.get(connection, operation_id, lock=True)
                            if (previous is not None and previous.get("status") == "in_progress"
                                    and previous.get("execution", {}).get("id") == record["execution"]["id"]):
                                ledger.save(connection, record)
                    except Exception:
                        pass  # The admitted/dispatched owner state remains durable.
                    return operation_response(record)
        except BaseException as exc:
            code = getattr(exc, "code", "provider_unavailable" if atomic or not started else "internal_error")
            if code not in ERROR_CODES:
                code = "provider_unavailable" if atomic or not started else "internal_error"
            failure = {**record, "status": "failed" if atomic or not started else "reconciliation_required",
                       "error_code": code, "result": None,
                       "execution": {**record["execution"], "phase": "rolled_back" if atomic else "uncertain" if started else "not_started"}}
            try:
                with ledger.transaction() as connection:
                    previous = ledger.get(connection, operation_id, lock=True)
                    if previous is None or (previous.get("fingerprint") == record["fingerprint"]
                            and previous.get("status") in _UNRESOLVED):
                        ledger.save(connection, failure)
                        ledger.append_outcome(connection, failure)
            except Exception:
                pass  # Never replace a prior terminal outcome or redispatch an uncertain callback.
            if isinstance(exc, ApiError) or not isinstance(exc, Exception):
                raise
            raise ApiError("provider_unavailable" if atomic or not started else code) from None
        ledger.deliver_local()
        return completed_response(record)



@contextmanager
def collection_transaction(store, *, tenant_id, workspace_id, collection_id):
    """Acquire AUD11's public catalog fence before any owner mutation transaction."""
    with store.collection_guard(tenant_id=tenant_id, workspace_id=workspace_id, collection_id=collection_id.strip()):
        with _collection_owner_transaction(store) as connection:
            yield connection


@contextmanager
def _collection_owner_transaction(store):
    """Use the canonical store's existing owner transaction seam without editing its package."""
    from rick_knowledge import InMemoryKnowledgeStore, PostgresKnowledgeStore, SQLiteKnowledgeStore

    if isinstance(store, InMemoryKnowledgeStore):
        with store._mutation_lock:
            before = deepcopy(store._collections)
            try:
                yield None
            except BaseException:
                store._collections = before
                raise
    elif isinstance(store, SQLiteKnowledgeStore):
        with store.mutation_guard("audit:collection"), store._lock:
            try:
                with store._transaction():
                    yield store._connection
            except BaseException:
                store._connection.rollback()
                raise
    elif isinstance(store, PostgresKnowledgeStore):
        original_error = None
        try:
            with store._session(write=True) as (connection, _cursor):
                inherited = getattr(store._restore_sessions, "connection", None)
                store._restore_sessions.connection = connection
                try:
                    yield connection
                except BaseException as exc:
                    original_error = exc
                    # The package session handles ordinary Exceptions, while a
                    # cancellation can otherwise leave a retained owner in a
                    # transaction. Roll back here without closing that handle.
                    if not isinstance(exc, Exception):
                        try:
                            connection.rollback()
                        except Exception:
                            pass
                    raise
                finally:
                    store._restore_sessions.connection = inherited
        except BaseException:
            if original_error is not None:
                raise original_error
            raise
    else:
        raise ApiError("provider_unavailable")


def collection_owner(store):
    from rick_knowledge import SQLiteKnowledgeStore
    if isinstance(store, SQLiteKnowledgeStore):
        from types import SimpleNamespace
        return SimpleNamespace(audit_sqlite_owner=store)
    factory = getattr(store, "_connection_factory", None)
    if factory is None:
        return store
    # Narrow API adapter facade, not a change to the canonical store's public protocol.
    from types import SimpleNamespace
    return SimpleNamespace(audit_connection_factory=factory)


def admin_owner_transaction(identity, actor):
    """Only native owners have a transaction whose rollback we can promise."""
    from services.identity_service import InMemoryIdentityProvider
    from services.postgres_identity import PostgresIdentityProvider
    if not isinstance(identity, (InMemoryIdentityProvider, PostgresIdentityProvider)):
        return None
    transaction = getattr(identity, "audit_transaction", None)
    if not callable(transaction):
        raise ApiError("provider_unavailable")
    return lambda: transaction(actor)


def admin_mutation_in_transaction(identity, *, action, actor, connection, **values):
    """Use native identity mutations on the operation ledger's owner connection."""
    from services.identity_service import InMemoryIdentityProvider
    from services.postgres_identity import PostgresIdentityProvider
    if isinstance(identity, PostgresIdentityProvider):
        identity._require_actor_permission(actor, "users.manage")
        value, _ = getattr(identity, "admin_" + action)(
            actor=actor, connection=connection, **values)
        return value
    if isinstance(identity, InMemoryIdentityProvider):
        return getattr(identity, action)(actor=actor, **values)
    # Custom callbacks use run_operation's admitted/dispatched journal workflow.
    # Their external effects cannot be rolled back by a native owner transaction.
    method = getattr(identity, action, None)
    if callable(method):
        return method(actor=actor, **values)
    method = getattr(identity, "admin_" + action, None)
    if callable(method):
        value, _ = method(actor=actor, **values)
        return value
    raise ApiError("provider_unavailable")


def admin_update_in_transaction(identity, *, actor, user_id, values, connection):
    return admin_mutation_in_transaction(identity, action="update_user", actor=actor,
        user_id=user_id, connection=connection, **values)


def admin_reset_in_transaction(identity, *, actor, user_id, password, connection):
    """Borrow existing identity owner/store seams; run_operation owns completion."""
    from services.identity_service import InMemoryIdentityProvider
    from services.postgres_identity import PostgresIdentityProvider
    if isinstance(identity, InMemoryIdentityProvider):
        return identity.reset_password(actor=actor, user_id=user_id, password=password)
    if isinstance(identity, PostgresIdentityProvider):
        from rick_identity import hash_password
        identity._require_actor_permission(actor, "users.manage")
        tenant = identity._admin_tenant(actor)
        workspace = identity._admin_workspace(actor)
        user = identity._lock_account_in_exact_workspace(
            user_id=user_id, tenant_id=tenant, workspace_id=workspace, connection=connection)
        user["password_hash"] = hash_password(password)
        user["password_version"] = int(user.get("password_version", 1)) + 1
        identity._users.save(user, connection=connection)
        return identity._sessions.revoke_user(user_id, reason="password_reset", connection=connection)
    raise ApiError("provider_unavailable")


def admin_revoke_in_transaction(identity, *, actor, user_id, session_id, revoke_all, connection):
    """Resolve identifier-only revocation within the existing owner boundary."""
    if session_id and not user_id:
        from services.identity_service import InMemoryIdentityProvider
        from services.postgres_identity import PostgresIdentityProvider
        if isinstance(identity, InMemoryIdentityProvider):
            return identity.revoke_session_by_id(actor=actor, session_id=session_id)
        if not isinstance(identity, PostgresIdentityProvider):
            raise ApiError("provider_unavailable")
        with identity._sessions._session(connection=connection) as (_, cursor):
            identity._sessions._execute(cursor,
                "SELECT user_id FROM rick_sessions WHERE session_id=%s AND tenant_id=%s FOR UPDATE",
                (session_id, actor.tenant_id))
            row = identity._sessions._fetchone(cursor)
        if row is None:
            return 0
        user_id = row["user_id"]
    return identity.revoke_in_transaction(actor=actor, target_token=None,
        target_session_id=session_id, target_user_id=user_id,
        revoke_all=revoke_all, connection=connection)


def operation_ledger_for_request(request):
    from dependencies.services import get_providers
    providers = get_providers(request)
    factory = _factory(providers.identity)
    if factory is None:
        factory = getattr(getattr(providers, "knowledge", None), "_connection_factory", None)
    return OperationLedger(providers.audit_sink, factory)


def scoped_operation(request, session, operation_id):
    from services.authorization_service import has_permission
    from dependencies.services import get_providers
    from rick_knowledge import SQLiteKnowledgeStore
    providers = get_providers(request)
    store = getattr(providers, "knowledge", None)
    record = None
    if isinstance(store, SQLiteKnowledgeStore):
        ledger = OperationLedger(providers.audit_sink, sqlite_owner=store)
        with ledger.transaction() as connection:
            record = ledger.get(connection, operation_id)
    if record is None:
        ledger = operation_ledger_for_request(request)
        with ledger.transaction() as connection:
            record = ledger.get(connection, operation_id)
    event = record.get("event", {}) if record else {}
    if (not record or event.get("tenant_id") != session.tenant_id or event.get("workspace_id") != session.workspace_id
            or (event.get("actor_user_id") != session.user_id and not has_permission(session, "audit.read"))):
        raise ApiError("not_found")
    ledger.deliver_local()
    return ledger, record


def public_operation(record, ledger=None):
    result = {"audit_operation_id": record["operation_id"], "action": record["event"]["action"],
            "target_id": record["event"].get("target_id"), "audit_status": record["status"],
            "reconciliation_required": record["status"] == "reconciliation_required",
            "result": record.get("result"), "error_code": record.get("error_code"),
            "reconciliation": record.get("reconciliation"), "execution": record.get("execution")}
    if ledger is not None:
        result["delivery"] = ledger.delivery_status(record)
    return result


def pending_operations(request, session, limit):
    from dependencies.services import get_providers
    from services.authorization_service import has_permission
    from rick_knowledge import SQLiteKnowledgeStore
    providers = get_providers(request)
    ledgers = [operation_ledger_for_request(request)]
    if isinstance(getattr(providers, "knowledge", None), SQLiteKnowledgeStore):
        ledgers.append(OperationLedger(providers.audit_sink, sqlite_owner=providers.knowledge))
    items = []
    for ledger in ledgers:
        records = ledger.pending(session, limit - len(items), operator=has_permission(session, "audit.read"))
        for record in records:
            if not isinstance(record, dict):
                raise ApiError("provider_unavailable")
            items.append(public_operation(record, ledger))
        if len(items) >= limit:
            break
    return {"items": items, "total": len(items)}


def reconcile_operation(request, session, operation_id, *, resolution, evidence_ref):
    """Record operator evidence; never call or automatically repeat the mutation."""
    from services.authorization_service import has_permission

    if not has_permission(session, "audit.read") or not has_permission(session, "users.manage"):
        raise ApiError("forbidden")
    ledger, scoped = scoped_operation(request, session, operation_id)
    proof = {"resolution": resolution, "evidence_ref": evidence_ref, "actor_user_id": session.user_id}
    with ledger.execution_guard(operation_id) as guard:
        if guard is None:
            raise ApiError("conflict")
        guard.assert_held()
        with ledger.transaction() as connection:
            record = ledger.get(connection, operation_id, lock=True)
            if record is None or record["event"] != scoped["event"]:
                raise ApiError("conflict")
            if record["status"].startswith("reconciled_"):
                previous = record.get("reconciliation", {})
                if any(previous.get(key) != value for key, value in proof.items()):
                    raise ApiError("conflict")
            else:
                phase = record.get("execution", {}).get("phase")
                if resolution == "no_effect":
                    # A free lock proves no current holder, not no future external
                    # effect. Only a durable pre-dispatch record can be cancelled.
                    if record["status"] not in _UNRESOLVED or phase != "admitted":
                        raise ApiError("conflict")
                elif record["status"] != "reconciliation_required":
                    # A lost outcome write (or local crash) can leave dispatched
                    # admission durable. Effect confirmation is safe only after
                    # proving that its callback is absent, never by lock expiry.
                    if (record["status"] != "in_progress" or phase != "dispatched"
                            or not ledger.executor_absent(record)):
                        raise ApiError("conflict")
                proof["recorded_at"] = datetime.now(timezone.utc).isoformat()
                record.update(status="reconciled_" + resolution, reconciliation=proof)
                record["event"]["reason"] = evidence_ref
                ledger.save(connection, record)
                ledger.append_outcome(connection, record)
        ledger.deliver_local()
        return public_operation(record, ledger)
