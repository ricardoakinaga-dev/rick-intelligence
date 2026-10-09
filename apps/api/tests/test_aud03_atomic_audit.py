"""AUD03-06 public mutation failures and authoritative operation outcomes."""

from types import SimpleNamespace

import pytest
from starlette.requests import Request

from core.errors import ApiError
from dependencies.services import Providers
from models import SessionSnapshot
from rick_authorization import permissions_for_role
from rick_knowledge import Collection, InMemoryKnowledgeStore
from routes import knowledge
from routes.sessions import RevokeRequest, revoke_sessions
from services.audit import InMemoryAuditSink
from services.identity_service import InMemoryIdentityProvider
from services.audit_operations import run_operation, OperationLedger
from services.sqlite_audit import SQLiteAuditSink
from apps.api.tests.support import make_settings


class BrokenAudit(InMemoryAuditSink):
    def emit(self, event):
        return False


def actor(role="PLATFORM_ADMIN", user_id="admin"):
    return SessionSnapshot(authenticated=True, session_state="active", user_id=user_id, tenant_id="default",
        workspace_id="default", role=role, canonical_role=role, permissions=permissions_for_role(role), allowed_collection_ids=["*"])


def request(providers, key=None):
    headers = [(b"idempotency-key", key.encode())] if key else []
    return Request({"type": "http", "method": "POST", "path": "/", "headers": headers,
        "app": SimpleNamespace(state=SimpleNamespace(providers=providers)), "state": {"request_id": "audit06-request"}})


def test_a09_audit_write_failure_does_not_revoke_existing_token():
    identity = InMemoryIdentityProvider(mode="test")
    token = identity.login(email="vet@example.com", password="password123", tenant_id="default", ip=None, user_agent=None)["session_token"]
    providers = Providers(settings=make_settings(), identity=identity, audit_sink=BrokenAudit())
    with pytest.raises(ApiError) as error:
        revoke_sessions(RevokeRequest(session_token=token, user_id="vet"), request(providers), actor())
    assert error.value.code == "provider_unavailable"
    assert identity.validate_token(token).authenticated


def test_a09_audit_write_failure_does_not_call_document_delete():
    class Deleter:
        def __init__(self):
            self.deleted = False
        def delete_document(self, document_id, **scope):
            self.deleted = True
            return {"document_id": document_id, "deleted": True}
        def upload(self, *args, **kwargs):
            raise AssertionError("not an upload test")
        def get_status(self, *args, **kwargs):
            return None
    service = Deleter()
    providers = Providers(settings=make_settings(), ingestion=service, audit_sink=BrokenAudit())
    with pytest.raises(ApiError):
        knowledge.delete_document("document", request(providers), actor())
    assert service.deleted is False


def test_failed_mandatory_audit_does_not_create_collection():
    store = InMemoryKnowledgeStore()
    providers = Providers(settings=make_settings(), knowledge=store, audit_sink=BrokenAudit())
    with pytest.raises(ApiError):
        knowledge.create_collection(knowledge.CollectionCreateRequest(collection_id="new", title="New"), request(providers), actor())
    assert store.get_collection("default", "new", tenant_id="default") is None


def test_update_collection_has_mandatory_audit_and_restores_on_failure():
    store = InMemoryKnowledgeStore()
    store.upsert_collection(Collection(tenant_id="default", workspace_id="default", collection_id="allowed", title="Original"))
    providers = Providers(settings=make_settings(), knowledge=store, audit_sink=BrokenAudit())
    with pytest.raises(ApiError):
        knowledge.update_collection("allowed", knowledge.CollectionUpdateRequest(title="Changed"), request(providers), actor())
    assert store.get_collection("default", "allowed", tenant_id="default").title == "Original"


def test_same_key_collection_create_replays_without_second_effect():
    store = InMemoryKnowledgeStore()
    providers = Providers(settings=make_settings(), knowledge=store, audit_sink=InMemoryAuditSink())
    payload = knowledge.CollectionCreateRequest(collection_id="new", title="New")
    first = knowledge.create_collection(payload, request(providers, "stable-create"), actor())
    second = knowledge.create_collection(payload, request(providers, "stable-create"), actor())
    assert first == second
    assert store.get_collection("default", "new", tenant_id="default").version == 1


def test_same_key_changed_collection_input_conflicts_without_mutation():
    store = InMemoryKnowledgeStore()
    store.upsert_collection(Collection(tenant_id="default", workspace_id="default", collection_id="allowed", title="Original"))
    providers = Providers(settings=make_settings(), knowledge=store, audit_sink=InMemoryAuditSink())
    knowledge.update_collection("allowed", knowledge.CollectionUpdateRequest(title="First"), request(providers, "stable-update"), actor())
    with pytest.raises(ApiError) as error:
        knowledge.update_collection("allowed", knowledge.CollectionUpdateRequest(title="Second"), request(providers, "stable-update"), actor())
    assert error.value.code == "conflict"
    assert store.get_collection("default", "allowed", tenant_id="default").title == "First"


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_atomic_completion_failure_rolls_back_collection_and_completion(tmp_path, kind):
    class FailCompletion(InMemoryAuditSink):
        def emit(self, event):
            return False if event.get("status") == "completed" else super().emit(event)
    sink = FailCompletion() if kind == "memory" else SQLiteAuditSink(tmp_path / "audit.db")
    if kind == "sqlite":
        sink._connection.execute("CREATE TRIGGER fail_complete BEFORE INSERT ON audit_events WHEN json_extract(NEW.event_json,'$.status')='completed' BEGIN SELECT RAISE(ABORT,'synthetic completion failure'); END")
    store = InMemoryKnowledgeStore()
    providers = Providers(settings=make_settings(), knowledge=store, audit_sink=sink)
    with pytest.raises(ApiError):
        knowledge.create_collection(knowledge.CollectionCreateRequest(collection_id="new", title="New"), request(providers, "fail-complete"), actor())
    assert store.get_collection("default", "new", tenant_id="default") is None
    assert all(event["status"] != "completed" for event in sink.events)
    assert [event["status"] for event in sink.events] == ["failed"]
    if kind == "sqlite":
        sink.close()


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_unknown_outcome_survives_failure_replays_without_callback_and_reconciles(tmp_path, kind):
    class FailCompletion(InMemoryAuditSink):
        def emit(self, event):
            return False if event.get("status") == "completed" else super().emit(event)
    sink = FailCompletion() if kind == "memory" else SQLiteAuditSink(tmp_path / "audit.db")
    if kind == "sqlite":
        sink._connection.execute("CREATE TRIGGER fail_complete BEFORE INSERT ON audit_events WHEN json_extract(NEW.event_json,'$.status')='completed' BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
    providers = Providers(settings=make_settings(), audit_sink=sink)
    calls = []
    def execute():
        return run_operation(request=request(providers, "unknown"), session=actor(), action="document.delete",
            target_id="doc", inputs={}, callback=lambda _: calls.append("effect") or {"deleted": True})
    first = execute()
    assert first.status_code == 202
    operation_id = __import__("json").loads(first.body)["audit_operation_id"]
    if kind == "sqlite":
        sink.close()
        providers.audit_sink = sink = SQLiteAuditSink(tmp_path / "audit.db")
    assert execute().status_code == 202
    assert calls == ["effect"]
    status = knowledge.audit_operation_status(operation_id, request(providers), actor())
    assert status["audit_status"] == "reconciliation_required"
    foreign = actor(); foreign.tenant_id = "foreign"
    with pytest.raises(ApiError) as missing:
        knowledge.audit_operation_status(operation_id, request(providers), foreign)
    assert missing.value.code == "not_found"
    payload = knowledge.AuditReconciliationRequest(resolution="effect_confirmed", evidence_ref="case-123")
    reconciled = knowledge.audit_operation_reconcile(operation_id, payload, request(providers), actor())
    assert reconciled["audit_status"] == "reconciled_effect_confirmed"
    assert knowledge.audit_operation_reconcile(operation_id, payload, request(providers), actor()) == reconciled
    assert execute().status_code == 202
    assert calls == ["effect"]
    if kind == "sqlite":
        sink.close()


def test_callback_exception_is_durable_unknown_outcome_and_is_not_repeated(tmp_path):
    sink = SQLiteAuditSink(tmp_path / "audit.db")
    providers = Providers(settings=make_settings(), audit_sink=sink)
    calls = []
    def callback(_):
        calls.append("partial-effect")
        raise ApiError("storage_unavailable")
    arguments = dict(request=request(providers, "exception"), session=actor(), action="document.delete",
        target_id="doc", inputs={}, callback=callback)
    with pytest.raises(ApiError) as error:
        run_operation(**arguments)
    assert error.value.code == "storage_unavailable"
    second = run_operation(**arguments)
    assert second.status_code == 202
    assert calls == ["partial-effect"]
    operation_id = __import__("json").loads(second.body)["audit_operation_id"]
    assert knowledge.audit_operation_status(operation_id, request(providers), actor())["error_code"] == "storage_unavailable"
    sink.close()


def test_concurrent_same_key_collection_update_runs_once():
    from concurrent.futures import ThreadPoolExecutor
    store = InMemoryKnowledgeStore()
    store.upsert_collection(Collection(tenant_id="default", workspace_id="default", collection_id="allowed", title="Original"))
    providers = Providers(settings=make_settings(), knowledge=store, audit_sink=InMemoryAuditSink())
    def execute(_):
        return knowledge.update_collection("allowed", knowledge.CollectionUpdateRequest(title="Changed"), request(providers, "parallel"), actor())
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(execute, range(8)))
    assert all(result == results[0] for result in results)
    assert store.get_collection("default", "allowed", tenant_id="default").version == 2


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_grant_failure_preserves_membership_authority(tmp_path, kind):
    identity = InMemoryIdentityProvider(mode="test")
    original = list(identity._users.get_by_id("vet")["authorized_collection_ids"])
    sink = BrokenAudit() if kind == "memory" else SQLiteAuditSink(tmp_path / "audit.db")
    if kind == "sqlite":
        sink._connection.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON audit_events BEGIN SELECT RAISE(ABORT,'synthetic audit failure'); END")
    providers = Providers(settings=make_settings(), identity=identity, knowledge=InMemoryKnowledgeStore(), audit_sink=sink)
    with pytest.raises(ApiError):
        knowledge.set_collection_grant("new", "vet", knowledge.CollectionGrantRequest(granted=True), request(providers), actor())
    assert identity._users.get_by_id("vet")["authorized_collection_ids"] == original
    assert identity._users.get_by_email("vet@example.com") is identity._users.get_by_id("vet")
    if kind == "sqlite":
        sink.close()


def test_sqlite_metadata_and_completion_are_one_real_owner_transaction(tmp_path):
    from rick_knowledge import SQLiteKnowledgeStore
    from services.audit_operations import collection_owner
    store = SQLiteKnowledgeStore(tmp_path / "knowledge.db")
    providers = Providers(settings=make_settings(), knowledge=store, audit_sink=BrokenAudit())
    ledger = OperationLedger(providers.audit_sink, sqlite_owner=collection_owner(store).audit_sqlite_owner)
    store._connection.execute("CREATE TRIGGER fail_complete BEFORE INSERT ON api_audit_completions WHEN json_extract(NEW.event_json,'$.status')='completed' BEGIN SELECT RAISE(ABORT,'synthetic mandatory outbox failure'); END")
    with pytest.raises(ApiError):
        knowledge.create_collection(knowledge.CollectionCreateRequest(collection_id="new", title="New"), request(providers, "owner-rollback"), actor())
    assert store.get_collection("default", "new", tenant_id="default") is None
    store._connection.execute("DROP TRIGGER fail_complete")
    first = knowledge.create_collection(knowledge.CollectionCreateRequest(collection_id="new", title="New"), request(providers, "owner-ok"), actor())
    assert first["collection_id"] == "new"
    assert store._connection.execute("SELECT COUNT(*) FROM api_audit_completions WHERE json_extract(event_json,'$.status')='completed'").fetchone()[0] == 1
    store.close()
    providers.knowledge = store = SQLiteKnowledgeStore(tmp_path / "knowledge.db")
    providers.audit_sink = InMemoryAuditSink()
    second = knowledge.create_collection(knowledge.CollectionCreateRequest(collection_id="new", title="New"), request(providers, "owner-ok"), actor())
    assert second == first
    record_id = store._connection.execute("SELECT operation_id FROM api_audit_operations WHERE json_extract(payload,'$.status')='completed'").fetchone()[0]
    assert knowledge.audit_operation_status(record_id, request(providers), actor())["audit_status"] == "completed"
    assert any(event["status"] == "completed" for event in providers.audit_sink.events)
    store.close()


def test_stream_digest_preserves_offset_and_does_not_persist_content():
    import io
    from services.audit_operations import source_digest
    stream = io.BytesIO(b"sensitive source" * 10000)
    stream.seek(20)
    assert len(source_digest(SimpleNamespace(file=stream))) == 64
    assert stream.tell() == 20


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_public_catalog_guard_precedes_owner_transaction_and_public_upsert(tmp_path, kind):
    from contextlib import contextmanager
    from rick_knowledge import SQLiteKnowledgeStore
    base = InMemoryKnowledgeStore if kind == "memory" else SQLiteKnowledgeStore
    class Observed(base):
        depth = 0
        outer_entries = 0
        writes = 0
        @contextmanager
        def collection_guard(self, **scope):
            if self.depth == 0:
                self.outer_entries += 1
                if kind == "sqlite":
                    assert not self._connection.in_transaction
            with super().collection_guard(**scope):
                self.depth += 1
                try:
                    yield
                finally:
                    self.depth -= 1
        def upsert_collection(self, collection):
            assert self.depth > 0
            if kind == "sqlite":
                assert self._connection.in_transaction
            self.writes += 1
            return super().upsert_collection(collection)
    store = Observed() if kind == "memory" else Observed(tmp_path / "knowledge.db")
    providers = Providers(settings=make_settings(), knowledge=store, audit_sink=InMemoryAuditSink())
    knowledge.create_collection(knowledge.CollectionCreateRequest(collection_id="new", title="New"), request(providers), actor())
    knowledge.archive_collection("new", request(providers), actor())
    assert store.outer_entries == store.writes == 2
    assert store.get_collection("default", "new", tenant_id="default").status == "archived"
    if kind == "sqlite":
        store.close()


def test_sqlite_catalog_owner_survives_unavailable_external_projection(tmp_path):
    from rick_knowledge import SQLiteKnowledgeStore
    from services.postgres_audit import PostgresAuditSink
    def unavailable():
        raise RuntimeError("synthetic offline delivery adapter")
    store = SQLiteKnowledgeStore(tmp_path / "knowledge.db")
    providers = Providers(settings=make_settings(), knowledge=store, audit_sink=PostgresAuditSink(unavailable))
    result = knowledge.create_collection(knowledge.CollectionCreateRequest(collection_id="new", title="New"), request(providers), actor())
    assert result["collection_id"] == "new"
    operation_id = store._connection.execute("SELECT operation_id FROM api_audit_operations").fetchone()[0]
    status = knowledge.audit_operation_status(operation_id, request(providers), actor())
    assert status["audit_status"] == "completed"
    assert status["delivery"]["status"] == "projection_pending"
    store.close()


@pytest.mark.parametrize("broken", [False, True])
def test_existing_custom_revoke_interface_uses_nonrepeating_tracked_workflow(broken):
    calls = []
    def revoke(**kwargs):
        calls.append(kwargs)
        return 1
    identity = SimpleNamespace(revoke=revoke)
    providers = Providers(settings=make_settings(), identity=identity, audit_sink=BrokenAudit() if broken else InMemoryAuditSink())
    payload = RevokeRequest(session_token="synthetic-session")
    if broken:
        with pytest.raises(ApiError):
            revoke_sessions(payload, request(providers, "legacy-port"), actor())
        assert calls == []
    else:
        assert revoke_sessions(payload, request(providers, "legacy-port"), actor()) == {"revoked": 1}
        assert revoke_sessions(payload, request(providers, "legacy-port"), actor()) == {"revoked": 1}
        assert len(calls) == 1
        assert "synthetic-session" not in __import__("json").dumps(providers.audit_sink._operation_records)


def test_reconciliation_permissions_and_changed_evidence_are_enforced():
    providers = Providers(settings=make_settings(), audit_sink=InMemoryAuditSink())
    effects = []
    def partial(_):
        effects.append("partial-effect")
        raise ApiError("storage_unavailable")
    arguments = dict(request=request(providers, "operator-proof"), session=actor(), action="document.delete",
        target_id="doc", inputs={}, callback=partial)
    with pytest.raises(ApiError):
        run_operation(**arguments)
    operation_id = __import__("json").loads(run_operation(**arguments).body)["audit_operation_id"]
    proof = knowledge.AuditReconciliationRequest(resolution="no_effect", evidence_ref="proof-1")
    with pytest.raises(ApiError) as denied:
        knowledge.audit_operation_reconcile(operation_id, proof, request(providers), actor("KNOWLEDGE_MANAGER", "km"))
    assert denied.value.code == "forbidden"
    with pytest.raises(ApiError) as unsafe:
        knowledge.audit_operation_reconcile(operation_id, proof, request(providers), actor())
    assert unsafe.value.code == "conflict"
    assert effects == ["partial-effect"]
    proof = knowledge.AuditReconciliationRequest(resolution="effect_confirmed", evidence_ref="proof-1")
    knowledge.audit_operation_reconcile(operation_id, proof, request(providers), actor())
    with pytest.raises(ApiError) as conflict:
        knowledge.audit_operation_reconcile(operation_id, knowledge.AuditReconciliationRequest(resolution="no_effect", evidence_ref="proof-2"), request(providers), actor())
    assert conflict.value.code == "conflict"
