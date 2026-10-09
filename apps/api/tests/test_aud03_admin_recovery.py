import json
import pytest
from fastapi.testclient import TestClient
from app import create_app
from apps.api.tests.support import make_settings, login_as
from dependencies.services import Providers
from services.identity_service import InMemoryIdentityProvider
from services.audit import InMemoryAuditSink
from services.sqlite_audit import SQLiteAuditSink
from services.audit_operations import OperationLedger,input_digest

class BrokenAudit(InMemoryAuditSink):
    def emit(self,event): return False

@pytest.mark.parametrize('kind',['memory','sqlite'])
@pytest.mark.parametrize('target',['session_id','user_id'])
def test_admin_revocation_must_preserve_token_if_mandatory_audit_fails(tmp_path,kind,target):
    identity=InMemoryIdentityProvider(mode='test')
    p=Providers(settings=make_settings(environment='local'),identity=identity,audit_sink=InMemoryAuditSink())
    with TestClient(create_app(p.settings,p),raise_server_exceptions=False) as client:
        login_as(client,'admin@example.com')
        token=identity.login(email='vet@example.com',password='password123',tenant_id='default',ip=None,user_agent=None)['session_token']
        session_id=identity._sessions.get(token)['session_id']
        sink=BrokenAudit() if kind=='memory' else SQLiteAuditSink(tmp_path/'audit.db')
        if kind=='sqlite':
            sink._connection.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON audit_events BEGIN SELECT RAISE(ABORT,'synthetic mandatory audit failure'); END")
        client.app.state.providers.audit_sink=sink
        body={'session_id':session_id} if target=='session_id' else {'user_id':'vet','revoke_all':True}
        response=client.post('/api/v1/admin/sessions/revoke',json=body,headers={'Idempotency-Key':'admin-revoke'})
        authenticated=identity.validate_token(token).authenticated
        print(json.dumps({'kind':kind,'target':target,'http':response.status_code,'body':response.json(),'victim_authenticated':authenticated,'audit_events':sink.events,'pending':client.get('/api/v1/audit/operations').json()}))
        if kind=='sqlite': sink.close()
        assert response.status_code==503
        assert authenticated, 'mandatory audit failure committed revocation without an outcome trail'

def test_self_service_revocation_rollback_control():
    identity=InMemoryIdentityProvider(mode='test')
    p=Providers(settings=make_settings(environment='local'),identity=identity,audit_sink=InMemoryAuditSink())
    with TestClient(create_app(p.settings,p),raise_server_exceptions=False) as client:
        login_as(client,'admin@example.com')
        token=identity.login(email='vet@example.com',password='password123',tenant_id='default',ip=None,user_agent=None)['session_token']
        client.app.state.providers.audit_sink=BrokenAudit()
        response=client.post('/api/v1/auth/sessions/revoke',json={'session_token':token,'user_id':'vet'},headers={'Idempotency-Key':'self-revoke'})
        assert response.status_code==503
        assert identity.validate_token(token).authenticated

def test_admin_password_reset_replay_must_not_repeat_effect():
    identity=InMemoryIdentityProvider(mode='test')
    p=Providers(settings=make_settings(environment='local'),identity=identity,audit_sink=InMemoryAuditSink())
    with TestClient(create_app(p.settings,p),raise_server_exceptions=False) as client:
        login_as(client,'admin@example.com')
        versions=[identity._users.get_by_id('vet')['password_version']]
        for _ in range(2):
            response=client.post('/api/v1/admin/users/vet/reset-password',json={'password':'synthetic-new-pass'},headers={'Idempotency-Key':'reset-replay'})
            assert response.status_code==200,response.text
            versions.append(identity._users.get_by_id('vet')['password_version'])
        print(json.dumps({'password_versions':versions,'actions':[e.get('action') for e in p.audit_sink.events]}))
        assert versions[1]==versions[2], 'same key and input repeated credential mutation'

def test_orphan_dispatched_operation_must_accept_operator_effect_evidence(tmp_path):
    # Synthetic post-crash persistent owner snapshot: effect happened, executor gone.
    identity=InMemoryIdentityProvider(mode='test')
    sink=SQLiteAuditSink(tmp_path/'orphan.db')
    p=Providers(settings=make_settings(environment='local'),identity=identity,audit_sink=sink)
    with TestClient(create_app(p.settings,p),raise_server_exceptions=False) as client:
        login_as(client,'admin@example.com')
        ledger=OperationLedger(sink)
        oid='auditop-'+input_digest(['default','default','admin','document.delete','orphan'])
        record={'operation_id':oid,'status':'in_progress','fingerprint':input_digest(['doc',{}]),'result':None,'execution':{'id':'dead-executor','phase':'dispatched'},'event':{'action':'document.delete','actor_user_id':'admin','tenant_id':'default','workspace_id':'default','target_id':'doc'}}
        with ledger.transaction() as db: ledger.save(db,record)
        with ledger.execution_guard(oid) as guard: assert guard is not None
        response=client.post('/api/v1/audit/operations/'+oid+'/reconcile',json={'resolution':'effect_confirmed','evidence_ref':'local-proof-1'})
        print(json.dumps({'http':response.status_code,'body':response.json(),'operation':client.get('/api/v1/audit/operations/'+oid).json()}))
        assert response.status_code==200, 'durable dispatched orphan cannot be reconciled even with operator evidence'
    sink.close()


def test_public_delete_outcome_write_outage_can_be_reconciled_after_recovery(monkeypatch):
    from test_phase16_root import _client,_login,_upload
    with _client() as client:
        _login(client,'admin@example.com')
        uploaded=_upload(client,filename='probe.txt',content=b'Synthetic local source for audit probe')
        document_id=uploaded['document_id']
        assert client.app.state.providers.knowledge.get_document(document_id).status=='published'
        save=OperationLedger.save
        def fail_outcome(self,connection,record):
            if record.get('status') in ('completed','reconciliation_required'):
                raise RuntimeError('synthetic owner outcome storage outage')
            return save(self,connection,record)
        monkeypatch.setattr(OperationLedger,'save',fail_outcome)
        first=client.delete('/api/v1/documents/'+document_id,headers={'Idempotency-Key':'delete-outage'})
        assert first.status_code==202,first.text
        assert client.app.state.providers.knowledge.get_document(document_id).status=='deleted'
        monkeypatch.setattr(OperationLedger,'save',save)
        oid=first.json()['audit_operation_id']
        replay=client.delete('/api/v1/documents/'+document_id,headers={'Idempotency-Key':'delete-outage'})
        status=client.get('/api/v1/audit/operations/'+oid)
        resolved=client.post('/api/v1/audit/operations/'+oid+'/reconcile',json={'resolution':'effect_confirmed','evidence_ref':'verified-local-tombstone'})
        print(json.dumps({'first':first.json(),'replay':replay.json(),'status':status.json(),'resolution_http':resolved.status_code,'resolution':resolved.json(),'document_status':client.app.state.providers.knowledge.get_document(document_id).status}))
        assert replay.status_code==202
        assert resolved.status_code==200,'storage recovered but actual public delete remains permanently in_progress'


@pytest.mark.parametrize("operation", ["revoke", "reset"])
@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_admin_completion_failure_rolls_back_effect_and_failed_replay(tmp_path, operation, kind):
    class FailCompletion(InMemoryAuditSink):
        def emit(self, event):
            return False if event.get("status") == "completed" else super().emit(event)

    identity = InMemoryIdentityProvider(mode="test")
    p = Providers(settings=make_settings(environment="local"), identity=identity, audit_sink=InMemoryAuditSink())
    with TestClient(create_app(p.settings, p), raise_server_exceptions=False) as client:
        login_as(client, "admin@example.com")
        token = identity.login(email="vet@example.com", password="password123", tenant_id="default", ip=None, user_agent=None)["session_token"]
        version = identity._users.get_by_id("vet")["password_version"]
        sink = FailCompletion() if kind == "memory" else SQLiteAuditSink(tmp_path / "completion.db")
        if kind == "sqlite":
            sink._connection.execute("CREATE TRIGGER fail_completion BEFORE INSERT ON audit_events WHEN json_extract(NEW.event_json,'$.status')='completed' BEGIN SELECT RAISE(ABORT,'synthetic completion outage'); END")
        client.app.state.providers.audit_sink = sink
        path = "/api/v1/admin/sessions/revoke" if operation == "revoke" else "/api/v1/admin/users/vet/reset-password"
        body = {"user_id": "vet", "revoke_all": True} if operation == "revoke" else {"password": "synthetic-password"}
        for _ in range(2):
            result = client.post(path, json=body, headers={"Idempotency-Key": "completion-failure"})
            assert result.status_code == 503, result.text
            assert identity.validate_token(token).authenticated
            assert identity._users.get_by_id("vet")["password_version"] == version
        assert [event["status"] for event in sink.events] == ["failed"]
        if kind == "sqlite":
            sink.close()


def test_admin_reset_concurrent_replay_and_changed_input_conflict():
    from concurrent.futures import ThreadPoolExecutor
    identity = InMemoryIdentityProvider(mode="test")
    p = Providers(settings=make_settings(environment="local"), identity=identity, audit_sink=InMemoryAuditSink())
    with TestClient(create_app(p.settings, p), raise_server_exceptions=False) as client:
        login_as(client, "admin@example.com")
        path = "/api/v1/admin/users/vet/reset-password"
        def reset(_):
            return client.post(path, json={"password": "synthetic-password"}, headers={"Idempotency-Key": "concurrent-reset"})
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(reset, range(8)))
        assert all(response.status_code == 200 for response in responses)
        assert all(response.json() == responses[0].json() for response in responses)
        assert identity._users.get_by_id("vet")["password_version"] == 2
        changed = client.post(path, json={"password": "other-synthetic-password"}, headers={"Idempotency-Key": "concurrent-reset"})
        assert changed.status_code == 409
        assert identity._users.get_by_id("vet")["password_version"] == 2
        completed = [event for event in p.audit_sink.events if event.get("action") == "admin.user_access_reset" and event.get("status") == "completed"]
        assert len(completed) == 1
        assert "synthetic-password" not in json.dumps(p.audit_sink._operation_records)


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_public_reconcile_excludes_live_callback_and_dispatched_no_effect(tmp_path, kind):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from test_aud03_atomic_audit import actor, request
    from services.audit_operations import run_operation
    entered, release = Event(), Event()
    sink = InMemoryAuditSink() if kind == "memory" else SQLiteAuditSink(tmp_path / "live.db")
    p = Providers(settings=make_settings(environment="local"), identity=InMemoryIdentityProvider(mode="test"), audit_sink=sink)
    with TestClient(create_app(p.settings, p), raise_server_exceptions=False) as client:
        login_as(client, "admin@example.com")
        def partial(_):
            entered.set()
            assert release.wait(5)
            from core.errors import ApiError
            raise ApiError("provider_timeout")
        def execute():
            from core.errors import ApiError
            with pytest.raises(ApiError):
                run_operation(request=request(p, "live-callback"), session=actor(), action="document.delete", target_id="doc", inputs={}, callback=partial)
        oid = "auditop-" + input_digest(["default", "default", "admin", "document.delete", "live-callback"])
        path = "/api/v1/audit/operations/" + oid + "/reconcile"
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(execute)
            assert entered.wait(5)
            try:
                for resolution in ("no_effect", "effect_confirmed"):
                    result = client.post(path, json={"resolution": resolution, "evidence_ref": "local-evidence"})
                    assert result.status_code == 409
            finally:
                release.set()
            future.result(5)
        assert client.post(path, json={"resolution": "no_effect", "evidence_ref": "local-evidence"}).status_code == 409
        confirmed = client.post(path, json={"resolution": "effect_confirmed", "evidence_ref": "local-evidence"})
        assert confirmed.status_code == 200
    if kind == "sqlite":
        sink.close()


@pytest.mark.parametrize("failure", [False, True])
def test_postgres_admin_reset_borrows_owner_for_effect_and_completion(failure):
    from copy import deepcopy
    from core.errors import ApiError
    from services.postgres_identity import PostgresIdentityProvider
    from routes.admin import ResetPasswordRequest, reset_user_password
    from test_aud03_audit_postgres_contract import TransactionConnection
    from test_aud03_atomic_audit import actor, request
    db = TransactionConnection(fail_completion=failure)
    identity = PostgresIdentityProvider(lambda: db)
    p = Providers(settings=make_settings(environment="local"), identity=identity, audit_sink=InMemoryAuditSink())
    before = deepcopy(db.user)
    def execute():
        return reset_user_password("user-a", ResetPasswordRequest(password="synthetic-password"), request(p, "pg-reset"), actor())
    if failure:
        with pytest.raises(ApiError):
            execute()
        assert db.user == before
        assert db.session_revocations == 0
    else:
        assert execute() == execute()
        assert db.user["password_version"] == 2
        assert db.session_revocations == 2
        assert len(db.outbox) == 2
        assert sum(value.get("status") == "completed" for _, value in db.outbox) == 2


def test_postgres_owner_registry_detects_callback_even_without_db_session_lock():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from services.audit_operations import run_operation
    from test_aud03_atomic_audit import actor, request
    entered, release = Event(), Event()
    sink = InMemoryAuditSink()
    p = Providers(settings=make_settings(), audit_sink=sink)
    def callback(_):
        entered.set()
        assert release.wait(5)
        return {"deleted": True}
    def execute():
        return run_operation(request=request(p, "owner-registry"), session=actor(), action="document.delete", target_id="doc", inputs={}, callback=callback)
    # This check must not consult the DB session: that session may already be
    # terminated. It observes the actual callback's registered Python owner.
    pg_ledger = OperationLedger(sink, factory=lambda: pytest.fail("unexpected database connection"))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(execute)
        assert entered.wait(5)
        try:
            record = next(iter(sink._operation_records.values()))
            assert record["execution"]["phase"] == "dispatched"
            assert pg_ledger.executor_absent(record) is False
        finally:
            release.set()
        future.result(5)
    assert pg_ledger.executor_absent(record) is True
    from copy import deepcopy
    foreign = deepcopy(record)
    foreign["execution"]["process_owner"] = "other-process"
    assert pg_ledger.executor_absent(foreign) is False
    del foreign["execution"]["process_owner"]
    assert pg_ledger.executor_absent(foreign) is False

@pytest.mark.parametrize('kind', ['memory', 'sqlite', 'postgres_fixture'])
def test_admin_patch_replay_preserves_later_role_change(tmp_path, kind):
    from core.errors import ApiError
    from routes.admin import update_user, UpdateUserRequest
    from services.postgres_identity import PostgresIdentityProvider
    from test_aud03_audit_postgres_contract import TransactionConnection
    from test_aud03_atomic_audit import actor, request
    sink = InMemoryAuditSink() if kind != 'sqlite' else SQLiteAuditSink(tmp_path / 'audit.db')
    connection = TransactionConnection() if kind == 'postgres_fixture' else None
    identity = PostgresIdentityProvider(lambda: connection) if connection else InMemoryIdentityProvider(mode='test')
    p = Providers(settings=make_settings(environment='local'), identity=identity, audit_sink=sink)
    user_id = 'user-a' if connection else 'vet'
    def change(key, role):
        return update_user(user_id, UpdateUserRequest(role=role), request(p, key), actor())
    first = change('original', 'KNOWLEDGE_MANAGER')
    change('later', 'VETERINARIAN')
    replay = change('original', 'KNOWLEDGE_MANAGER')
    assert (json.loads(replay.body) if hasattr(replay, 'body') else replay) == (json.loads(first.body) if hasattr(first, 'body') else first)
    user = connection.user if connection else identity._users.get_by_id(user_id)
    assert user['role'] == 'VETERINARIAN'
    assert user['role_version'] == 3
    with pytest.raises(ApiError) as error:
        change('original', 'PLATFORM_ADMIN')
    assert error.value.code == 'conflict'
    assert user['role_version'] == 3
    completions = [value for event_id, value in connection.outbox if event_id.endswith('-completed')] if connection else [event for event in sink.events if event.get('status') == 'completed']
    assert len(completions) == 2
    if kind == 'sqlite':
        sink.close()


@pytest.mark.parametrize('kind', ['memory', 'sqlite', 'postgres_fixture'])
def test_admin_patch_completion_failure_rolls_back_and_replays_failed_outcome(tmp_path, kind):
    from copy import deepcopy
    from core.errors import ApiError
    from routes.admin import update_user, UpdateUserRequest
    from services.postgres_identity import PostgresIdentityProvider
    from test_aud03_audit_postgres_contract import TransactionConnection
    from test_aud03_atomic_audit import actor, request
    class FailCompletion(InMemoryAuditSink):
        def emit(self, event):
            return False if event.get('status') == 'completed' else super().emit(event)
    path = tmp_path / 'audit.db'
    sink = SQLiteAuditSink(path) if kind == 'sqlite' else FailCompletion()
    if kind == 'sqlite':
        sink._connection.execute("CREATE TRIGGER reject_completed BEFORE INSERT ON audit_events WHEN json_extract(NEW.event_json,'$.status')='completed' BEGIN SELECT RAISE(ABORT,'synthetic completion failure'); END")
    connection = TransactionConnection(fail_completion=True) if kind == 'postgres_fixture' else None
    identity = PostgresIdentityProvider(lambda: connection) if connection else InMemoryIdentityProvider(mode='test')
    p = Providers(settings=make_settings(environment='local'), identity=identity, audit_sink=sink)
    user_id = 'user-a' if connection else 'vet'
    before = deepcopy(connection.user if connection else identity._users.get_by_id(user_id))
    def execute():
        return update_user(user_id, UpdateUserRequest(role='KNOWLEDGE_MANAGER'), request(p, 'failed-patch'), actor())
    with pytest.raises(ApiError) as error:
        execute()
    assert error.value.code == 'provider_unavailable'
    assert (connection.user if connection else identity._users.get_by_id(user_id)) == before
    if kind == 'sqlite':
        sink.close()
        p.audit_sink = sink = SQLiteAuditSink(path)
    with pytest.raises(ApiError) as replay:
        execute()
    assert replay.value.code == 'provider_unavailable'
    assert (connection.user if connection else identity._users.get_by_id(user_id)) == before
    ledger = OperationLedger(sink, identity.audit_connection_factory if connection else None)
    operation_id = 'auditop-' + input_digest(['default', 'default', 'admin', 'admin.user_updated', 'failed-patch'])
    with ledger.transaction() as owner:
        record = ledger.get(owner, operation_id)
    assert record['status'] == 'failed' and record['execution']['phase'] == 'rolled_back'
    if kind == 'sqlite':
        sink.close()

@pytest.mark.parametrize('kind', ['memory', 'sqlite', 'postgres_fixture'])
@pytest.mark.parametrize('operation', ['create', 'deactivate'])
@pytest.mark.parametrize('failure', [False, True])
def test_admin_create_deactivate_owner_replay_and_completion_rollback(tmp_path, kind, operation, failure):
    from copy import deepcopy
    from core.errors import ApiError
    from routes.admin import create_user, deactivate_user, CreateUserRequest
    from services.postgres_identity import PostgresIdentityProvider
    from test_aud03_audit_postgres_contract import TransactionConnection
    from test_aud03_atomic_audit import actor, request
    class Sink(InMemoryAuditSink):
        def emit(self, event):
            return False if failure and event.get('status') == 'completed' else super().emit(event)
    path = tmp_path / 'audit.db'
    sink = SQLiteAuditSink(path) if kind == 'sqlite' else Sink()
    if failure and kind == 'sqlite':
        sink._connection.execute("CREATE TRIGGER reject_completion BEFORE INSERT ON audit_events WHEN json_extract(NEW.event_json,'$.status')='completed' BEGIN SELECT RAISE(ABORT,'synthetic completion rejection'); END")
    connection = TransactionConnection(fail_completion=failure) if kind == 'postgres_fixture' else None
    if connection and operation == 'create':
        connection.user = None
        connection._snapshot = (None, [], 0)
    identity = PostgresIdentityProvider(lambda: connection) if connection else InMemoryIdentityProvider(mode='test')
    p = Providers(settings=make_settings(environment='local'), identity=identity, audit_sink=sink)
    before = deepcopy(connection.user if connection else identity._users._by_id)
    def execute():
        if operation == 'create':
            return create_user(CreateUserRequest(email='new@example.test', role='VETERINARIAN', tenant_id='default', password='private-password'), request(p, 'stable'), actor())
        return deactivate_user('user-a' if connection else 'vet', request(p, 'stable'), actor())
    if failure:
        with pytest.raises(ApiError) as error:
            execute()
        assert error.value.code == 'provider_unavailable'
        assert (connection.user if connection else identity._users._by_id) == before
        if kind == 'sqlite':
            sink.close()
            p.audit_sink = sink = SQLiteAuditSink(path)
        with pytest.raises(ApiError) as replay:
            execute()
        assert replay.value.code == 'provider_unavailable'
        assert (connection.user if connection else identity._users._by_id) == before
    else:
        first = execute()
        snapshot = deepcopy(connection.user if connection else identity._users._by_id)
        replay = execute()
        assert (json.loads(first.body) if hasattr(first, 'body') else first) == (json.loads(replay.body) if hasattr(replay, 'body') else replay)
        assert (connection.user if connection else identity._users._by_id) == snapshot
        if connection:
            assert first.status_code == 202
            assert len(connection.outbox) == 2
    if kind == 'sqlite':
        sink.close()

@pytest.mark.parametrize('failure', [None, 'callback', 'completion'])
def test_custom_admin_patch_uses_real_callable_without_claiming_atomicity(failure):
    from core.errors import ApiError
    from routes.admin import update_user, UpdateUserRequest
    from test_aud03_atomic_audit import actor, request
    class CustomIdentity:
        mode = 'test'
        durable_admin_mutations = False
        production_safe = False
        def __init__(self):
            self.calls = 0
            self.role = 'VETERINARIAN'
        def admin_target_in_scope(self, **scope):
            return scope == dict(user_id='vet', tenant_id='default', workspace_id='default')
        def audit_transaction(self, actor):
            raise AssertionError('custom owner must not be treated as native atomic')
        def update_user(self, *, actor, user_id, role):
            self.calls += 1
            self.role = role
            if failure == 'callback':
                raise ApiError('storage_unavailable')
            return dict(user_id=user_id, role=role, tenant_id=actor.tenant_id, workspace_id=actor.workspace_id)
    class Sink(InMemoryAuditSink):
        def emit(self, event):
            return False if failure == 'completion' and event.get('status')=='completed' else super().emit(event)
    identity = CustomIdentity()
    p = Providers(settings=make_settings(environment='local'), identity=identity, audit_sink=Sink())
    def execute():
        return update_user('vet', UpdateUserRequest(role='KNOWLEDGE_MANAGER'), request(p,'custom-patch'), actor())
    if failure == 'callback':
        with pytest.raises(ApiError) as error:
            execute()
        assert error.value.code == 'storage_unavailable'
    else:
        first = execute()
    replay = execute()
    assert identity.calls == 1 and identity.role == 'KNOWLEDGE_MANAGER'
    if failure:
        assert replay.status_code == 202
        assert json.loads(replay.body)['audit_status'] == 'reconciliation_required'
    else:
        assert replay == first
    ledger = OperationLedger(p.audit_sink)
    operation_id = 'auditop-' + input_digest(['default','default','admin','admin.user_updated','custom-patch'])
    with ledger.transaction() as connection:
        record = ledger.get(connection, operation_id)
    assert record['execution']['phase'] != 'atomic'
    assert record['status'] == ('reconciliation_required' if failure else 'completed')


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_custom_revoke_completion_failure_preserves_recoverable_outcome(tmp_path, kind):
    native = InMemoryIdentityProvider(mode="test")
    sink = InMemoryAuditSink() if kind == "memory" else SQLiteAuditSink(tmp_path / "custom-revoke.db")
    providers = Providers(settings=make_settings(environment="local"), identity=native, audit_sink=sink)
    with TestClient(create_app(providers.settings, providers), raise_server_exceptions=False) as client:
        login_as(client, "admin@example.com")
        token = native.login(email="vet@example.com", password="password123", tenant_id="default", ip=None, user_agent=None)["session_token"]
        class CustomIdentity:
            calls = 0
            def __getattr__(self, name):
                return getattr(native, name)
            def audit_transaction(self, actor):
                raise AssertionError("custom transaction cannot prove native rollback")
            def revoke_in_transaction(self, **kwargs):
                self.calls += 1
                return native.revoke_in_transaction(**kwargs)
        custom = CustomIdentity()
        client.app.state.providers.identity = custom
        emit = sink.emit
        if kind == "sqlite":
            sink._connection.execute("CREATE TRIGGER deny_custom_completion BEFORE INSERT ON audit_events WHEN json_extract(NEW.event_json,'$.status')='completed' BEGIN SELECT RAISE(ABORT,'synthetic completion failure'); END")
        else:
            sink.emit = lambda event: False if event.get("status") == "completed" else emit(event)
        def execute():
            return client.post("/api/v1/admin/sessions/revoke", json={"user_id": "vet", "revoke_all": True},
                               headers={"Idempotency-Key": "custom-owner"})
        first = execute()
        assert first.status_code == 202 and first.json()["reconciliation_required"] is True
        assert not native.validate_token(token).authenticated
        operation_id = first.json()["audit_operation_id"]
        status = client.get("/api/v1/audit/operations/" + operation_id).json()
        assert status["audit_status"] == "reconciliation_required"
        assert status["execution"]["phase"] != "rolled_back"
        assert execute().json() == first.json() and custom.calls == 1
        assert any(row["audit_operation_id"] == operation_id
                   for row in client.get("/api/v1/audit/operations").json()["items"])
        proof = client.post("/api/v1/audit/operations/" + operation_id + "/reconcile",
                            json={"resolution": "effect_confirmed", "evidence_ref": "synthetic-token-inactive"})
        assert proof.status_code == 200 and custom.calls == 1
    if kind == "sqlite":
        sink.close()
