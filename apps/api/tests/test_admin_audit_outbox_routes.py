import json
from copy import deepcopy
from routes.admin import create_user, CreateUserRequest
from services.postgres_identity import PostgresIdentityProvider
from services.audit import InMemoryAuditSink
from dependencies.services import Providers
from apps.api.tests.support import make_settings
from test_aud03_atomic_audit import actor, request
from test_aud03_audit_postgres_contract import TransactionConnection


def test_admin_mutation_returns_durable_audit_event_reference():
    connection = TransactionConnection()
    connection.user = None
    connection._snapshot = (None, [], 0)
    identity = PostgresIdentityProvider(lambda: connection)
    providers = Providers(settings=make_settings(), identity=identity, audit_sink=InMemoryAuditSink())
    payload = CreateUserRequest(email='created@example.test', role='VETERINARIAN', tenant_id='default', password='private-password')
    first = create_user(payload, request(providers, 'native-pg-create'), actor())
    user = deepcopy(connection.user)
    replay = create_user(payload, request(providers, 'native-pg-create'), actor())
    assert first.status_code == replay.status_code == 202
    body = json.loads(first.body)
    assert json.loads(replay.body) == body
    assert body['audit_status'] == 'pending'
    assert body['reconciliation_required'] is True
    assert body['user']['user_id'] == user['user_id']
    assert connection.user == user
    assert 'password' not in first.body.decode()
    assert len(connection.outbox) == 2
    assert [value for event_id, value in connection.outbox if event_id == body['audit_event_id']][0]['status'] == 'completed'
