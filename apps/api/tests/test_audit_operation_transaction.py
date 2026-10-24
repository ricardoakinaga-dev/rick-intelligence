from __future__ import annotations

from services.audit_operations_store import PostgresAuditOperationStore
from services.postgres_identity import PostgresIdentityProvider


class Cursor:
    def __init__(self):
        self.queries = []
        self.rowcount = 0
        self.description = None

    def execute(self, query, params=()):
        self.queries.append((query, params))
        self.rowcount = 1 if query.lstrip().upper().startswith("UPDATE") else 0

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def close(self):
        return None


class Connection:
    def __init__(self):
        self.cursor_instance = Cursor()
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def test_logout_writes_effect_and_operation_on_the_same_connection():
    connection = Connection()
    operations = PostgresAuditOperationStore(lambda: connection)
    provider = PostgresIdentityProvider(lambda: connection, audit_operations=operations)
    provider.logout("opaque-token", operation_id="op-1")
    queries = connection.cursor_instance.queries
    assert len(queries) == 2
    assert "UPDATE rick_sessions" in queries[0][0]
    assert "UPDATE rick_audit_operations" in queries[1][0]
    assert queries[1][1][-1] == "op-1"
    assert connection.commits == 1
    assert connection.rollbacks == 0
