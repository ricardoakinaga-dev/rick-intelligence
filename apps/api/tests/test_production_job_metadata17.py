"""Public runtime metadata contract; no external adapters or credentials."""
from types import SimpleNamespace

import pytest

from services.ingestion_service import safe_job_json
from services.postgres_ingestion import PostgresIngestionApplicationService
from routes.knowledge import _job_envelope

DURABLE = {
    "execution": "external-worker", "durability": "postgres-s3",
    "restart_recovery": True, "storage": "object-store",
}
TEMPORARY = {
    "execution": "process-local", "durability": "process-local",
    "restart_recovery": False, "storage": "private-temporary",
}
JOURNALED = {
    "execution": "process-local", "durability": "local-sqlite",
    "restart_recovery": True, "storage": "private-staging",
}


def produced_job():
    service = PostgresIngestionApplicationService(
        queue=SimpleNamespace(enqueue=lambda **kw: None, get_by_idempotency=lambda **kw: None),
        object_store=SimpleNamespace(put=lambda *args: None),
    )
    return service._public_job({
        "job_id": "ing-metadata17", "status": "queued", "attempts": 1,
        "tenant_id": "tenant", "workspace_id": "workspace", "collection_id": "collection",
        "created_at": 100.0,
        "metadata": {**TEMPORARY, "secret": "caller-secret"},
        "payload": {"document_id": "doc-17", "metadata": TEMPORARY, "secret": "payload-secret"},
    })


@pytest.mark.parametrize("render", [safe_job_json, lambda job: _job_envelope(job)["job"]])
def test_public_producer_retains_durable_truth(render):
    job = produced_job()
    assert job["metadata"] == DURABLE
    result = render(job)
    assert result["metadata"] == DURABLE
    assert result["document_id"] == "doc-17"
    assert "caller-secret" not in str(result)
    assert "payload-secret" not in str(result)
    assert safe_job_json(result) == result


def test_durable_whitelist_drops_secret_fields_and_preserves_bounds():
    job = produced_job()
    job["metadata"].update(secret="secret-value", source_path="/private/input", heartbeat=["secret-value"])
    job.update(progress=7, attempt=999, job_id="x" * 129, created_at=float("inf"), source_path="/private/input")
    result = _job_envelope(job)["job"]
    assert result["metadata"] == DURABLE
    assert result["progress"] == 1.0 and result["attempt"] == 64
    assert result["job_id"] == "unknown-job" and result["created_at"] is None
    assert "secret-value" not in str(result) and "/private/input" not in str(result)


@pytest.mark.parametrize("metadata", [None, [], "postgres-s3", {}, TEMPORARY,
    {"execution": "external-worker"}, {"durability": "postgres-s3"},
    {**DURABLE, "restart_recovery": False}, {**DURABLE, "restart_recovery": 1},
    {**DURABLE, "execution": "unsupported"}, {**DURABLE, "storage": "private-staging"},
    {**DURABLE, "durability": "local-sqlite"},
    {key: value for key, value in DURABLE.items() if key != "storage"},
])
def test_partial_malformed_or_mixed_metadata_cannot_claim_external_runtime(metadata):
    result = safe_job_json({"job_id": "job", "metadata": metadata})
    assert result["metadata"]["execution"] == "process-local"
    assert result["metadata"]["durability"] != "postgres-s3"
    assert result["metadata"]["storage"] != "object-store"
    assert set(result["metadata"]) == set(TEMPORARY)


@pytest.mark.parametrize("fields", [
    {}, {"_journaled": False}, {"_journaled": True},
    {"metadata": {"durability": "local-sqlite"}},
    {"metadata": {"restart_recovery": True}}, {"metadata": JOURNALED},
])
def test_existing_local_staging_classification(fields):
    expected = TEMPORARY if not fields or fields == {"_journaled": False} else JOURNALED
    assert safe_job_json({"job_id": "job", **fields})["metadata"] == expected


def test_publication_outcome_remains_bounded():
    job = produced_job()
    job.update(status="verifying", stage="verifying")
    job["metadata"].update(publication_outcome_unknown=True, secret="private")
    assert safe_job_json(job)["metadata"] == {**DURABLE, "publication_outcome": "unknown"}
