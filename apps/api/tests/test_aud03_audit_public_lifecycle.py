"""Mandatory audit admission on the real local API/ingestion composition."""

import pytest

from services.audit import InMemoryAuditSink
from test_phase16_root import _client, _login, _upload
from test_aud03_atomic_audit import BrokenAudit


@pytest.mark.parametrize("multipart", [False, True])
def test_real_local_upload_failure_has_no_staging_or_job_effect(multipart, monkeypatch):
    with _client() as client:
        _login(client, "km@example.com")
        providers = client.app.state.providers
        service = providers.ingestion
        calls = []
        submit = service.submit_upload
        def observed(*args, **kwargs):
            calls.append(True)
            return submit(*args, **kwargs)
        monkeypatch.setattr(service, "submit_upload", observed)
        providers.audit_sink = BrokenAudit()
        if multipart:
            result = client.post("/api/v1/documents/upload", files={"file": ("source.txt", b"synthetic source", "text/plain")}, data={"collection_id": "rag_phase0"})
        else:
            result = client.post("/api/v1/documents/upload", json={"filename": "source.txt", "collection_id": "rag_phase0", "content": "synthetic source"})
        assert result.status_code == 503, result.text
        assert calls == []
        assert service._jobs == {}
        assert service._staged_bytes == 0


@pytest.mark.parametrize("mutation", ["delete", "reindex"])
def test_real_published_document_survives_mandatory_audit_admission_failure(mutation, monkeypatch):
    with _client() as client:
        _login(client, "km@example.com")
        uploaded = _upload(client, filename="source.txt", content=b"Synthetic published source")
        document_id = uploaded["document_id"]
        providers = client.app.state.providers
        service = providers.ingestion
        method = service.delete_document if mutation == "delete" else service.reindex
        calls = []
        def observed(*args, **kwargs):
            calls.append(True)
            return method(*args, **kwargs)
        monkeypatch.setattr(service, "delete_document" if mutation == "delete" else "reindex", observed)
        providers.audit_sink = BrokenAudit()
        result = client.delete(f"/api/v1/documents/{document_id}") if mutation == "delete" else client.post("/api/v1/ingestion/reindex", json={"document_id": document_id, "content": "Replacement source"})
        assert result.status_code == 503, result.text
        assert calls == []
        assert providers.knowledge.get_document(document_id).status == "published"
        assert client.get(f"/api/v1/documents/{document_id}").status_code == 200


@pytest.mark.parametrize("mutation", ["retry", "cancel"])
def test_real_job_mutation_does_not_start_on_mandatory_audit_failure(mutation, monkeypatch):
    from copy import deepcopy
    from test_job_journal import _job
    with _client() as client:
        _login(client, "km@example.com")
        providers = client.app.state.providers
        service = providers.ingestion
        job = _job("audit06-job", status="failed")
        job.update(tenant_id="default", workspace_id="default", collection_id="rag_phase0")
        service._jobs["audit06-job"] = deepcopy(job)
        calls = []
        original = getattr(service, mutation)
        def observed(*args, **kwargs):
            calls.append(True)
            return original(*args, **kwargs)
        monkeypatch.setattr(service, mutation, observed)
        providers.audit_sink = BrokenAudit()
        result = client.post(f"/api/v1/ingestion/jobs/audit06-job/{mutation}",
            json={"filename": "retry.txt", "content": "Fresh synthetic source"} if mutation == "retry" else {})
        assert result.status_code == 503, result.text
        assert calls == []
        assert service._jobs["audit06-job"] == job


def test_public_upload_unknown_result_can_be_discovered_and_replayed_without_new_job():
    class FailCompletion(InMemoryAuditSink):
        def emit(self, event):
            return False if event.get("status") == "completed" else super().emit(event)
    with _client() as client:
        _login(client, "km@example.com")
        providers = client.app.state.providers
        providers.audit_sink = FailCompletion()
        body = {"filename": "source.txt", "collection_id": "rag_phase0", "content": "Synthetic source"}
        first = client.post("/api/v1/documents/upload", json=body, headers={"Idempotency-Key": "upload-result"})
        assert first.status_code == 202
        operation_id = first.json()["audit_operation_id"]
        second = client.post("/api/v1/documents/upload", json=body, headers={"Idempotency-Key": "upload-result"})
        assert second.status_code == 202
        assert second.json()["audit_operation_id"] == operation_id
        assert second.json()["job_id"] == first.json()["job_id"]
        assert len(providers.ingestion._jobs) == 1
        pending = client.get("/api/v1/audit/operations").json()
        assert pending["items"][0]["audit_operation_id"] == operation_id
        status = client.get(f"/api/v1/audit/operations/{operation_id}")
        assert status.json()["result"]["job_id"] == first.json()["job_id"]
