-- Reference migration, pending application/schema review.
-- This is deployment bookkeeping and job-control state, not a claim that the
-- current SQLite knowledge schema has already been migrated to Postgres.

CREATE TABLE IF NOT EXISTS rick_schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    checksum TEXT NOT NULL,
    application TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rick_ingestion_job_control (
    job_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    collection_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued', 'leased', 'acked', 'dead', 'cancelled')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    lease_until TIMESTAMPTZ,
    lease_owner TEXT,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS rick_ingestion_job_claim_idx
    ON rick_ingestion_job_control (status, available_at, created_at);

-- Rollback is DROP only after an explicit backup and operator approval. The
-- migration runner must record the checksum before applying application code.
