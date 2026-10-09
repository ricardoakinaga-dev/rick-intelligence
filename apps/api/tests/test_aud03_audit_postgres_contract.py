"""DB-API rollback fixtures for the public PostgreSQL mutation adapters.

These fixtures model transactions; real PostgreSQL evidence is separately opt-in.
"""

from copy import deepcopy
import json

import pytest

from core.errors import ApiError
from dependencies.services import Providers
from routes import knowledge
from routes.sessions import RevokeRequest, revoke_sessions
from services.audit import InMemoryAuditSink
from services.postgres_identity import PostgresIdentityProvider
from test_postgres_admin_mutations import _Connection, _Cursor
from test_aud03_atomic_audit import actor, request
from apps.api.tests.support import make_settings
from rick_knowledge import InMemoryKnowledgeStore


class TransactionConnection(_Connection):
    def __init__(self, *, fail_completion=False):
        super().__init__()
        self.user.update(tenant_id="default", workspace_id="default")
        self.fail_completion = fail_completion
        self._snapshot = (deepcopy(self.user), [], 0)

    def cursor(self):
        return TransactionCursor(self)


class TransactionCursor(_Cursor):
    def execute(self, query, params=()):
        compact = " ".join(query.lower().split())
        if compact.startswith("select payload from rick_outbox"):
            self.connection.trace.append(compact)
            row = next((payload for event_id, payload in self.connection.outbox if event_id == params[0]
                        and "operation_id" in payload), None)
            self.rows = [{"payload": deepcopy(row)}] if row else []
            return
        if compact.startswith("insert into rick_outbox"):
            self.connection.trace.append(compact)
            payload = json.loads(params[-1])
            if "admin.audit.completion" in compact and payload.get("status") == "completed" and self.connection.fail_completion:
                raise RuntimeError("synthetic completion write failure")
            self.connection.outbox = [(event_id, value) for event_id, value in self.connection.outbox if event_id != params[0]]
            self.connection.outbox.append((params[0], payload))
            self.rowcount = 1
            return
        super().execute(query, params)


@pytest.mark.parametrize("failure", [False, True])
def test_public_revoke_user_shares_transaction_with_mandatory_completion(failure):
    connection = TransactionConnection(fail_completion=failure)
    calls = []
    def factory():
        calls.append(connection)
        return connection
    identity = PostgresIdentityProvider(factory)
    providers = Providers(settings=make_settings(), identity=identity, audit_sink=InMemoryAuditSink())
    payload = RevokeRequest(user_id="user-a", revoke_all=True)
    if failure:
        with pytest.raises(ApiError):
            revoke_sessions(payload, request(providers, "revoke"), actor())
        assert connection.rollbacks == 1
        assert connection.session_revocations == 0
        assert all(value.get("status") != "completed" for _, value in connection.outbox)
    else:
        first = revoke_sessions(payload, request(providers, "revoke"), actor())
        second = revoke_sessions(payload, request(providers, "revoke"), actor())
        assert first == second == {"revoked": 2}
        assert connection.session_revocations == 2
        assert len(calls) == 2  # One owner connection per call; no hidden store connection.
        assert len(connection.outbox) == 2  # Replay record and exactly one completion.
    assert any(query.startswith("update rick_sessions") for query in connection.trace)


@pytest.mark.parametrize("failure", [False, True])
def test_public_grant_uses_scoped_row_lock_owner_save_and_completion(failure):
    connection = TransactionConnection(fail_completion=failure)
    identity = PostgresIdentityProvider(lambda: connection)
    providers = Providers(settings=make_settings(), identity=identity,
        knowledge=InMemoryKnowledgeStore(), audit_sink=InMemoryAuditSink())
    def execute():
        return knowledge.set_collection_grant("allowed", "user-a", knowledge.CollectionGrantRequest(granted=True),
            request(providers, "grant"), actor())
    if failure:
        with pytest.raises(ApiError):
            execute()
        assert connection.user["authorized_collection_ids"] == []
        assert connection.user["role_version"] == 1
        assert connection.rollbacks == 1
    else:
        assert execute() == execute() == {"user_id": "user-a", "collection_id": "allowed", "granted": True}
        assert connection.user["authorized_collection_ids"] == ["allowed"]
        assert connection.user["role_version"] == 2
        assert len(connection.outbox) == 2
    assert any("for update of m" in query for query in connection.trace)
