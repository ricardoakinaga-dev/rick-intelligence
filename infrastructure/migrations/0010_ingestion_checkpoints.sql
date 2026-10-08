-- Pre-intent phase outputs and request-only cancellation belong to the same
-- scoped canonical attempt, independently of document/vector publication.
CREATE TABLE IF NOT EXISTS rick_ingestion_checkpoints (
    tenant_id TEXT NOT NULL CHECK(length(btrim(tenant_id)) BETWEEN 1 AND 256),
    workspace_id TEXT NOT NULL CHECK(length(btrim(workspace_id)) BETWEEN 1 AND 256),
    collection_id TEXT NOT NULL CHECK(length(btrim(collection_id)) BETWEEN 1 AND 256),
    job_id TEXT NOT NULL CHECK(length(btrim(job_id)) BETWEEN 1 AND 256),
    record JSONB NOT NULL CHECK(jsonb_typeof(record) = 'object' AND octet_length(record::text) <= 67108864),
    PRIMARY KEY(tenant_id, workspace_id, collection_id, job_id)
);
