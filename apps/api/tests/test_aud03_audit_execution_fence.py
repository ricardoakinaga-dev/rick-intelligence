"""Rework2: exclusion is physical; lost locks never prove absence of an effect."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
import json
import multiprocessing
import sys
from threading import Event, Lock, current_thread
from types import SimpleNamespace
import uuid

import pytest

from core.errors import ApiError
from dependencies.services import Providers
from routes import knowledge
from services.audit import InMemoryAuditSink
from services.audit_operations import OperationLedger, collection_owner, collection_transaction, input_digest, run_operation
from services.postgres_audit import PostgresAuditSink
from services.sqlite_audit import SQLiteAuditSink
from test_aud03_atomic_audit import actor, request
from test_aud03_audit_postgres_live import lab, runtime, fail_completed_outbox
from apps.api.tests.support import make_settings


@pytest.fixture(params=["memory", "sqlite", "postgres"])
def backend(request, tmp_path):
    kind = request.param
    connect = request.getfixturevalue("lab") if kind == "postgres" else None
    path = tmp_path / "audit.db"
    sink = InMemoryAuditSink() if kind == "memory" else SQLiteAuditSink(path) if kind == "sqlite" else PostgresAuditSink(connect)
    p = Providers(settings=make_settings(), audit_sink=sink)
    def independent():
        return Providers(settings=make_settings(), audit_sink=SQLiteAuditSink(path) if kind == "sqlite" else PostgresAuditSink(connect) if kind == "postgres" else sink)
    yield SimpleNamespace(kind=kind, connect=connect, providers=p, independent=independent)
    if kind == "sqlite":
        sink.close()


def oid(key):
    return "auditop-" + input_digest(["default", "default", "admin", "document.delete", key])


def invoke(p, key, callback):
    return run_operation(request=request(p, key), session=actor(), action="document.delete", target_id="doc", inputs={}, callback=callback)


def reconcile(p, operation_id, resolution="no_effect"):
    return knowledge.audit_operation_reconcile(operation_id,
        knowledge.AuditReconciliationRequest(resolution=resolution, evidence_ref="fence-proof"), request(p), actor())


@pytest.mark.parametrize("resolution", ["no_effect", "effect_confirmed"])
def test_independent_operator_is_excluded_while_callback_is_running(backend, resolution):
    entered, release = Event(), Event()
    effects = []
    key = uuid.uuid4().hex
    def callback(_):
        entered.set()
        assert release.wait(10)
        effects.append("deleted")
        return {"deleted": True}
    p2 = backend.independent()
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(invoke, backend.providers, key, callback)
            assert entered.wait(5)
            try:
                status = knowledge.audit_operation_status(oid(key), request(p2), actor())
                assert status["audit_status"] == "in_progress"
                assert status["execution"]["phase"] == "dispatched"
                with pytest.raises(ApiError) as busy:
                    reconcile(p2, oid(key), resolution)
                assert busy.value.code == "conflict"
                replay = invoke(p2, key, lambda _: pytest.fail("duplicate dispatch"))
                assert replay.status_code == 202
                assert effects == []
            finally:
                release.set()
            assert future.result(5) == {"deleted": True}
        assert effects == ["deleted"]
        assert knowledge.audit_operation_status(oid(key), request(p2), actor())["audit_status"] == "completed"
        with OperationLedger(p2.audit_sink).execution_guard(oid(key)) as guard:
            assert guard is not None
            guard.assert_held()
    finally:
        release.set()
        if backend.kind == "sqlite":
            p2.audit_sink.close()


def test_external_effect_outliving_callback_error_cannot_be_declared_absent(backend):
    release = Event()
    effects = []
    key = uuid.uuid4().hex
    with ThreadPoolExecutor(max_workers=1) as external:
        def remote():
            assert release.wait(10)
            effects.append("late-remote-effect")
        future = external.submit(remote)
        try:
            def callback(_):
                raise ApiError("provider_timeout")
            with pytest.raises(ApiError):
                invoke(backend.providers, key, callback)
            with OperationLedger(backend.providers.audit_sink).execution_guard(oid(key)) as guard:
                assert guard is not None  # Lock absence alone is insufficient.
            with pytest.raises(ApiError) as refused:
                reconcile(backend.providers, oid(key))
            assert refused.value.code == "conflict"
        finally:
            release.set()
        future.result(5)
    assert effects == ["late-remote-effect"]
    assert knowledge.audit_operation_status(oid(key), request(backend.providers), actor())["audit_status"] == "reconciliation_required"
    assert invoke(backend.providers, key, lambda _: pytest.fail("redispatch")).status_code == 202


def test_duplicate_operator_proof_is_safe_after_result_write_failure(backend):
    p = backend.providers
    if backend.kind == "memory":
        original = p.audit_sink.emit
        p.audit_sink.emit = lambda event: False if event.get("status") == "completed" else original(event)
    elif backend.kind == "sqlite":
        p.audit_sink._connection.execute("CREATE TRIGGER reject_complete BEFORE INSERT ON audit_events WHEN json_extract(NEW.event_json,'$.status')='completed' BEGIN SELECT RAISE(ABORT,'synthetic'); END")
    else:
        fail_completed_outbox(backend.connect)
    key = uuid.uuid4().hex
    assert invoke(p, key, lambda _: {"deleted": True}).status_code == 202
    def operator(_):
        p2 = backend.independent()
        try:
            try:
                return reconcile(p2, oid(key), "effect_confirmed")
            except ApiError as exc:
                assert exc.code == "conflict"
                return None
        finally:
            if backend.kind == "sqlite":
                p2.audit_sink.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(operator, range(2)))
    assert any(result is not None for result in results)
    first = reconcile(p, oid(key), "effect_confirmed")
    assert reconcile(p, oid(key), "effect_confirmed") == first
    if backend.kind == "postgres":
        with backend.connect() as db:
            count = db.execute("SELECT count(*) FROM rick_outbox WHERE event_type='admin.audit.completion' AND payload->>'status'='reconciled_effect_confirmed'").fetchone()[0]
    else:
        count = sum(event.get("status") == "reconciled_effect_confirmed" for event in p.audit_sink.events)
    assert count == 1


def sqlite_child(path, key, channel, admission_only=False):
    """Spawned OS process; shares a real SQLite ledger but no Python mutex."""
    p = Providers(settings=make_settings(), audit_sink=SQLiteAuditSink(path))
    if admission_only:
        ledger = OperationLedger(p.audit_sink)
        with ledger.execution_guard(oid(key)):
            with ledger.transaction() as db:
                ledger.save(db, {"operation_id": oid(key), "status": "in_progress", "result": None,
                    "fingerprint": input_digest(["doc", {}]), "execution": {"id": "orphan", "phase": "admitted"},
                    "event": {"action": "document.delete", "actor_user_id": "admin", "tenant_id": "default", "workspace_id": "default", "target_id": "doc"}})
            channel.send("admitted")
            channel.recv()
    else:
        def callback(_):
            channel.send("dispatched")
            channel.recv()
            return {"deleted": True}
        channel.send(invoke(p, key, callback))
    p.audit_sink.close()


# pytest importlib mode creates a tests.* name unavailable to a fresh interpreter.
# Keep the spawn target importable through the explicit API/tests PYTHONPATH.
sys.modules.setdefault("test_aud03_audit_execution_fence", sys.modules[__name__])
sqlite_child.__module__ = "test_aud03_audit_execution_fence"


@pytest.mark.parametrize("crash", [False, True])
def test_sqlite_guard_and_dispatch_state_cross_process_boundary(tmp_path, crash):
    path, key = str(tmp_path / "audit.db"), uuid.uuid4().hex
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe()
    process = ctx.Process(target=sqlite_child, args=(path, key, child))
    process.start()
    p = Providers(settings=make_settings(), audit_sink=SQLiteAuditSink(path))
    try:
        assert parent.poll(10) and parent.recv() == "dispatched"
        with pytest.raises(ApiError) as busy:
            reconcile(p, oid(key))
        assert busy.value.code == "conflict"
        if crash:
            process.kill(); process.join(5)
            with OperationLedger(p.audit_sink).execution_guard(oid(key)) as guard:
                assert guard is not None
            with pytest.raises(ApiError) as unknown:
                reconcile(p, oid(key), "no_effect")
            assert unknown.value.code == "conflict"
            # The terminated local process no longer owns the physical flock.
            # Operator confirmation can close the outcome; absence of an effect
            # still cannot be inferred from the lock becoming free.
            assert reconcile(p, oid(key), "effect_confirmed")["audit_status"] == "reconciled_effect_confirmed"
            assert invoke(p, key, lambda _: pytest.fail("orphan redispatch")).status_code == 202
        else:
            parent.send("resume")
            assert parent.poll(5) and parent.recv() == {"deleted": True}
            process.join(5)
            assert process.exitcode == 0
            assert knowledge.audit_operation_status(oid(key), request(p), actor())["audit_status"] == "completed"
    finally:
        if process.is_alive():
            process.kill(); process.join(5)
        parent.close(); child.close(); p.audit_sink.close()


def test_sqlite_crash_before_dispatch_can_be_cancelled_without_effect(tmp_path):
    path, key = str(tmp_path / "audit.db"), uuid.uuid4().hex
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe()
    process = ctx.Process(target=sqlite_child, args=(path, key, child, True))
    process.start()
    p = Providers(settings=make_settings(), audit_sink=SQLiteAuditSink(path))
    try:
        assert parent.poll(10) and parent.recv() == "admitted"
        process.kill(); process.join(5)
        assert reconcile(p, oid(key))["audit_status"] == "reconciled_no_effect"
        assert invoke(p, key, lambda _: pytest.fail("cancelled admission dispatched")).status_code == 202
    finally:
        if process.is_alive():
            process.kill(); process.join(5)
        parent.close(); child.close(); p.audit_sink.close()


def test_callback_cancellation_records_uncertainty_and_releases_guard(backend):
    key = uuid.uuid4().hex
    def cancelled(_):
        raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        invoke(backend.providers, key, cancelled)
    status = knowledge.audit_operation_status(oid(key), request(backend.providers), actor())
    assert status["audit_status"] == "reconciliation_required"
    assert status["execution"]["phase"] == "uncertain"
    with OperationLedger(backend.providers.audit_sink).execution_guard(oid(key)) as guard:
        assert guard is not None
    with pytest.raises(ApiError):
        reconcile(backend.providers, oid(key))


class ConnectionProxy:
    def __init__(self, connection, intercept):
        self.connection, self.intercept = connection, intercept
    def __getattr__(self, name):
        return getattr(self.connection, name)
    def cursor(self):
        return CursorProxy(self.connection.cursor(), self.intercept, self.connection)


class CursorProxy:
    def __init__(self, cursor, intercept, connection):
        self.cursor, self.intercept, self.connection = cursor, intercept, connection
    def __getattr__(self, name):
        return getattr(self.cursor, name)
    def execute(self, query, params=()):
        self.intercept(query, params, self.connection, self.cursor)
        return self.cursor.execute(query, params)


@pytest.mark.parametrize("boundary", ["admitted", "dispatched"])
def test_pg_session_loss_never_allows_late_callback_behind_no_effect(lab, boundary):
    entered, release = Event(), Event()
    pids, reads, effects = [], [], []
    key = uuid.uuid4().hex
    def intercept(query, params, connection, cursor):
        if not current_thread().name.startswith("executor"):
            return
        if "pg_try_advisory_lock" in query:
            pids.append(connection.info.backend_pid)
        if boundary == "admitted" and "SELECT payload FROM rick_outbox" in query:
            reads.append(True)
            if len(reads) == 2:
                # Guard health check already succeeded. Freeze immediately before
                # dispatch CAS, then terminate only this test's owned guard session.
                entered.set()
                assert release.wait(10)
    def connect():
        return ConnectionProxy(lab(), intercept)
    p = Providers(settings=make_settings(), audit_sink=PostgresAuditSink(connect))
    operator = Providers(settings=make_settings(), audit_sink=PostgresAuditSink(lab))
    def callback(_):
        if boundary == "dispatched":
            entered.set()
            assert release.wait(10)
        effects.append("effect")
        return {"deleted": True}
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="executor") as pool:
        future = pool.submit(invoke, p, key, callback)
        assert entered.wait(5)
        try:
            assert len(pids) == 1
            with lab() as db:
                assert db.execute("SELECT pg_terminate_backend(%s)", (pids[0],)).fetchone()[0]
            if boundary == "admitted":
                cancelled = reconcile(operator, oid(key))
                assert cancelled["audit_status"] == "reconciled_no_effect"
            else:
                for resolution in ("no_effect", "effect_confirmed"):
                    with pytest.raises(ApiError) as denied:
                        reconcile(operator, oid(key), resolution)
                    assert denied.value.code == "conflict"
                assert invoke(operator, key, lambda _: pytest.fail("lost-session redispatch")).status_code == 202
        finally:
            release.set()
        if boundary == "admitted":
            with pytest.raises(ApiError):
                future.result(5)
            assert effects == []
            assert knowledge.audit_operation_status(oid(key), request(operator), actor())["audit_status"] == "reconciled_no_effect"
        else:
            assert future.result(5) == {"deleted": True}
            assert effects == ["effect"]
            assert knowledge.audit_operation_status(oid(key), request(operator), actor())["audit_status"] == "completed"
    with OperationLedger(operator.audit_sink).execution_guard(oid(key)) as guard:
        assert guard is not None


def test_pg_dispatch_write_timeout_prevents_callback_and_releases_session(lab):
    def intercept(query, params, connection, cursor):
        if "INSERT INTO rick_outbox" in query and "api.audit.operation" in query:
            payload = json.loads(params[-1])
            if payload.get("execution", {}).get("phase") == "dispatched":
                cursor.execute("SET LOCAL statement_timeout = '100ms'")
                cursor.execute("SELECT pg_sleep(1)")
    def connect():
        return ConnectionProxy(lab(), intercept)
    p = Providers(settings=make_settings(), audit_sink=PostgresAuditSink(connect))
    key = uuid.uuid4().hex
    with pytest.raises(ApiError) as timeout:
        invoke(p, key, lambda _: pytest.fail("dispatch after journal timeout"))
    assert timeout.value.code == "provider_unavailable"
    status = knowledge.audit_operation_status(oid(key), request(p), actor())
    assert status["audit_status"] == "failed"
    assert status["execution"]["phase"] == "not_started"
    with OperationLedger(PostgresAuditSink(lab)).execution_guard(oid(key)) as guard:
        assert guard is not None


def test_pg_cancellation_during_guard_acquisition_closes_owned_session(lab):
    connections = []
    class CancelOnCommit(ConnectionProxy):
        def commit(self):
            self.connection.commit()
            raise asyncio.CancelledError()
    def connect():
        db = lab()
        connections.append(db)
        return CancelOnCommit(db, lambda *_: None)
    key = uuid.uuid4().hex
    with pytest.raises(asyncio.CancelledError):
        with OperationLedger(PostgresAuditSink(connect)).execution_guard(oid(key)):
            pytest.fail("cancelled admission entered")
    assert len(connections) == 1 and connections[0].closed
    with OperationLedger(PostgresAuditSink(lab)).execution_guard(oid(key)) as guard:
        assert guard is not None


def test_atomic_pg_cancellation_rolls_back_membership_and_owned_connection(lab):
    p = runtime(lab)
    original = deepcopy(p.identity._users.get_by_id_for_tenant("vet", "default"))
    def callback(connection):
        p.identity.grant_collection_in_transaction(actor=actor(), user_id="vet", collection_id="new", granted=True, connection=connection)
        raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        run_operation(request=request(p, "atomic-cancel"), session=actor(), action="collection.grant_updated",
            target_id="vet", inputs={}, owner=p.identity, transaction=lambda: p.identity.audit_transaction(actor()), callback=callback)
    current = p.identity._users.get_by_id_for_tenant("vet", "default")
    assert current["authorized_collection_ids"] == original["authorized_collection_ids"]
    assert current["role_version"] == original["role_version"]
    with lab() as db:
        assert db.execute("SELECT count(*) FROM rick_outbox WHERE payload->>'status'='completed'").fetchone()[0] == 0


def test_pg_collection_cancellation_rolls_back_without_closing_retained_owner(lab):
    from rick_knowledge import Collection, PostgresKnowledgeStore
    p = runtime(lab)
    connections, owner_connections = [], []
    def connect():
        db = lab()
        connections.append(db)
        return db
    store = PostgresKnowledgeStore(connect, close_connections=False, created_by="admin")
    def callback(connection):
        owner_connections.append(connection)
        store.upsert_collection(Collection(tenant_id="default", workspace_id="default", collection_id="cancelled", title="Cancelled"))
        raise asyncio.CancelledError()
    try:
        with pytest.raises(asyncio.CancelledError):
            run_operation(request=request(p, "collection-cancel"), session=actor(), action="collection.create",
                target_id="cancelled", inputs={}, owner=collection_owner(store),
                transaction=lambda: collection_transaction(store, tenant_id="default", workspace_id="default", collection_id="cancelled"), callback=callback)
        assert len(owner_connections) == 1 and not owner_connections[0].closed
        assert owner_connections[0].info.transaction_status.name == "IDLE"
        assert owner_connections[0].execute("SELECT count(*) FROM rick_collections WHERE collection_id='cancelled'").fetchone()[0] == 0
        assert store.get_collection("default", "cancelled", tenant_id="default") is None
        with store.collection_guard(tenant_id="default", workspace_id="default", collection_id="cancelled"):
            pass
    finally:
        for connection in connections:
            connection.close()


def test_legacy_unknown_record_does_not_gain_a_no_effect_proof(backend):
    key = uuid.uuid4().hex
    ledger = OperationLedger(backend.providers.audit_sink)
    record = {"operation_id": oid(key), "fingerprint": input_digest(["doc", {}]), "status": "reconciliation_required", "result": None,
              "event": {"action": "document.delete", "actor_user_id": "admin", "target_id": "doc", "tenant_id": "default", "workspace_id": "default"}}
    with ledger.transaction() as connection:
        ledger.save(connection, record)
    with pytest.raises(ApiError) as unknown:
        reconcile(backend.providers, oid(key))
    assert unknown.value.code == "conflict"
