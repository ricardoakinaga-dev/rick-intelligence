"""Replica gate identities must represent the same authenticated principal."""
from __future__ import annotations

from scripts.phase11 import redis_multi_replica_runtime_gate as gate


def test_api_fixture_uses_same_authenticated_principal_on_two_replicas():
    from services.identity_service import InMemoryIdentityProvider

    snapshots = []
    for _ in range(2):
        identity = InMemoryIdentityProvider(mode="test")
        gate._seed_runtime_users(identity, run_id="fixture-run-a", tenant_id="fixture-tenant-a")
        response = identity.login(email="runtime-chat-fixture-run-a@example.test", password="password123",
                                  tenant_id="fixture-tenant-a", ip="127.0.0.1", user_agent="owned-fixture")
        token = response.get("session_token") or response.get("token")
        snapshots.append(identity.validate_token(token))
    assert all(snapshot.authenticated for snapshot in snapshots)
    assert snapshots[0].user_id == snapshots[1].user_id
    assert snapshots[0].tenant_id == snapshots[1].tenant_id == "fixture-tenant-a"
    assert snapshots[0].workspace_id == snapshots[1].workspace_id == "default"
    assert snapshots[0].allowed_collection_ids == snapshots[1].allowed_collection_ids == []
