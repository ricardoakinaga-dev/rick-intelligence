"""Deletion during pending cancellation cannot discard durable vector cleanup."""
from copy import deepcopy
import pytest
from test_production_cancel_cleanup13 import rig, service, SCOPE

@pytest.mark.parametrize("receipt", [False, True])
def test_owned_tombstone_cleanup_stays_pending_and_preserves_deletion(rig, receipt):
    k, v, original, path, backend = rig
    if receipt:
        k.begin_publication(original, ready_count=1)
    k.delete_document(original.document_id)
    deleted = deepcopy(k.get_document(original.document_id))
    before = deepcopy(v.all_points())
    assert deleted.status == "deleted"
    waiting = service(k, v).recover_publication(original.job_id, **SCOPE)
    assert waiting.status == "verifying" and waiting.finished_at is None
    assert k.get_ingestion_checkpoint(original.job_id, **SCOPE)["state"] == "active"
    assert k.get_document(original.document_id) == deleted
    assert v.all_points() == before
    if backend == "sqlite":
        from rick_knowledge import SQLiteKnowledgeStore
        k.close()
        k = SQLiteKnowledgeStore(path)
    try:
        assert service(k, v).recover_publication(original.job_id, **SCOPE).status == "verifying"
        v.fault = None
        done = service(k, v).recover_publication(original.job_id, **SCOPE)
        assert done.status == "cancelled"
        assert k.get_ingestion_checkpoint(original.job_id, **SCOPE)["state"] == "cancelled"
        assert k.get_document(original.document_id) == deleted
        assert [p["point_id"] for p in v.all_points()] == ["foreign"]
    finally:
        if backend == "sqlite":
            k.close()
