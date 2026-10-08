"""Opt-in AUD03-06 API owner transactions against the Lead's disposable lab.

RICK_AUD03_AUDIT_POSTGRES_DSN must explicitly name an authorized disposable DB.
Tests use isolated random schemas and the actual canonical 0001-0008 migrations.
Never select a production DSN. The builder does not run these tests against a
shared database; the Lead runs them centrally after integration.
"""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import uuid

import pytest

from core.errors import ApiError
from dependencies.services import Providers
from routes import knowledge
from routes.sessions import RevokeRequest, revoke_sessions
from services.postgres_audit import PostgresAuditSink
from services.postgres_identity import PostgresIdentityProvider
from test_aud03_atomic_audit import actor, request
from conftest import make_settings
from rick_identity import hash_password
from rick_knowledge import PostgresKnowledgeStore


@pytest.fixture
def lab():
    dsn = os.environ.get("RICK_AUD03_AUDIT_POSTGRES_DSN")
    if not dsn:
        pytest.skip("NOT_RUN: Lead must supply the authorized private disposable PostgreSQL lab")
    import psycopg
    from psycopg import sql
    schema = "aud03_audit_" + uuid.uuid4().hex
    with psycopg.connect(dsn) as db:
        db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    def connect():
        return psycopg.connect(dsn, options=f"-c search_path={schema} -c statement_timeout=15000")
    try:
        root = Path(__file__).resolve().parents[3]
        with connect() as db:
            for migration in sorted((root / "infrastructure/migrations").glob("000[1-8]_*.sql")):
                db.execute(migration.read_text())
            db.execute("INSERT INTO rick_tenants(tenant_id,display_name) VALUES ('default','Synthetic audit lab')")
        yield connect
    finally:
        with psycopg.connect(dsn) as db:
            db.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def runtime(connect):
    identity = PostgresIdentityProvider(connect)
    password = hash_password("synthetic-password")
    for user_id, role, grants in (("admin", "PLATFORM_ADMIN", ["*"]), ("vet", "VETERINARIAN", ["allowed"])):
        identity._users.save(dict(user_id=user_id, email=f"{user_id}@example.test", status="active",
            membership_status="active", tenant_id="default", workspace_id="default", role=role,
            password_hash=password, password_version=1, role_version=1, authorized_collection_ids=grants))
    store = PostgresKnowledgeStore(connect, created_by="admin")
    return Providers(settings=make_settings(), identity=identity, knowledge=store, audit_sink=PostgresAuditSink(connect))


def fail_completed_outbox(connect):
    with connect() as db:
        db.execute("""CREATE FUNCTION reject_completion() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF NEW.event_type='admin.audit.completion' AND NEW.payload->>'status'='completed'
                THEN RAISE EXCEPTION 'synthetic mandatory audit failure'; END IF; RETURN NEW; END $$""")
        db.execute("CREATE TRIGGER reject_completion BEFORE INSERT ON rick_outbox FOR EACH ROW EXECUTE FUNCTION reject_completion()")


@pytest.mark.parametrize("mutation", ["collection", "grant", "revoke"])
def test_real_pg_completion_write_failure_rolls_back_api_owner(lab, mutation):
    providers = runtime(lab)
    token = providers.identity.login(email="vet@example.test", password="synthetic-password", tenant_id="default", ip=None, user_agent=None)["session_token"]
    fail_completed_outbox(lab)
    with pytest.raises(ApiError):
        if mutation == "collection":
            knowledge.create_collection(knowledge.CollectionCreateRequest(collection_id="new", title="New"), request(providers, "failure"), actor())
        elif mutation == "grant":
            knowledge.set_collection_grant("new", "vet", knowledge.CollectionGrantRequest(granted=True), request(providers, "failure"), actor())
        else:
            revoke_sessions(RevokeRequest(session_token=token, user_id="vet"), request(providers, "failure"), actor())
    assert providers.identity.validate_token(token).authenticated
    assert providers.identity._users.get_by_id_for_tenant("vet", "default")["authorized_collection_ids"] == ["allowed"]
    assert providers.knowledge.get_collection("default", "new", tenant_id="default") is None
    with lab() as db:
        assert db.execute("SELECT COUNT(*) FROM rick_outbox WHERE payload->>'status'='completed'").fetchone()[0] == 0


def test_real_pg_concurrent_collection_replay_and_projection_exactly_once(lab):
    from admin_audit_outbox import PostgresAdminAuditReconciler
    providers = runtime(lab)
    payload = knowledge.CollectionCreateRequest(collection_id="new", title="New")
    def execute(_):
        return knowledge.create_collection(payload, request(providers, "parallel"), actor())
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(execute, range(8)))
    assert all(result == results[0] for result in results)
    assert providers.knowledge.get_collection("default", "new", tenant_id="default").version == 1
    worker = PostgresAdminAuditReconciler(lab)
    assert worker.process_once() == 1
    assert worker.process_once() == 0
    with lab() as db:
        assert db.execute("SELECT COUNT(*) FROM rick_audit_events WHERE action='collection.create'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM rick_outbox WHERE event_type='api.audit.operation'").fetchone()[0] == 1


def test_real_pg_grant_and_revoke_replay_do_not_repeat_effects(lab):
    providers = runtime(lab)
    token = providers.identity.login(email="vet@example.test", password="synthetic-password", tenant_id="default", ip=None, user_agent=None)["session_token"]
    grant = knowledge.CollectionGrantRequest(granted=True)
    assert knowledge.set_collection_grant("new", "vet", grant, request(providers, "grant"), actor()) == knowledge.set_collection_grant("new", "vet", grant, request(providers, "grant"), actor())
    user = providers.identity._users.get_by_id_for_tenant("vet", "default")
    assert user["role_version"] == 2
    payload = RevokeRequest(session_token=token, user_id="vet")
    assert revoke_sessions(payload, request(providers, "revoke"), actor()) == {"revoked": 1}
    assert revoke_sessions(payload, request(providers, "revoke"), actor()) == {"revoked": 1}
    with lab() as db:
        assert db.execute("SELECT COUNT(*) FROM rick_outbox WHERE event_type='admin.audit.completion'").fetchone()[0] == 2


def test_real_pg_workflow_unknown_outcome_survives_restart_and_reconciles(lab):
    providers = runtime(lab)
    effects = []
    class Deleter:
        def upload(self, *args, **kwargs):
            raise AssertionError()
        def get_status(self, *args, **kwargs):
            return None
        def delete_document(self, document_id, **scope):
            effects.append(document_id)
            return {"document_id": document_id, "deleted": True}
    providers.ingestion = Deleter()
    fail_completed_outbox(lab)
    first = knowledge.delete_document("doc", request(providers, "delete"), actor())
    operation_id = json.loads(first.body)["audit_operation_id"]
    assert first.status_code == 202
    providers.identity = PostgresIdentityProvider(lab)
    providers.audit_sink = PostgresAuditSink(lab)
    assert knowledge.delete_document("doc", request(providers, "delete"), actor()).status_code == 202
    assert effects == ["doc"]
    status = knowledge.audit_operation_status(operation_id, request(providers), actor())
    assert status["audit_status"] == "reconciliation_required"
    assert knowledge.audit_pending_operations(request(providers), 100, actor())["items"][0]["audit_operation_id"] == operation_id
    resolution = knowledge.AuditReconciliationRequest(resolution="effect_confirmed", evidence_ref="synthetic-case-1")
    assert knowledge.audit_operation_reconcile(operation_id, resolution, request(providers), actor())["audit_status"] == "reconciled_effect_confirmed"
    assert effects == ["doc"]
