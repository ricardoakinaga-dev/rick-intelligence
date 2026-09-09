-- Phase 2.2: canonical durable jobs storage.
-- rick_ingestion_jobs is the single durable queue authority. The legacy
-- status columns remain for the compatibility facade, while contract_state,
-- version, attempts and the event tables are used by rick_jobs adapters.

ALTER TABLE rick_ingestion_jobs
    ADD COLUMN IF NOT EXISTS contract_state TEXT,
    ADD COLUMN IF NOT EXISTS operation TEXT NOT NULL DEFAULT 'ingest',
    ADD COLUMN IF NOT EXISTS contract_version TEXT NOT NULL DEFAULT 'jobs-contract-v1',
    ADD COLUMN IF NOT EXISTS max_attempts INTEGER NOT NULL DEFAULT 3,
    ADD COLUMN IF NOT EXISTS version BIGINT NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS result JSONB,
    ADD COLUMN IF NOT EXISTS failure JSONB,
    ADD COLUMN IF NOT EXISTS lease_worker_id TEXT,
    ADD COLUMN IF NOT EXISTS lease_acquired_at TIMESTAMPTZ;

DO $$
BEGIN
    ALTER TABLE rick_ingestion_jobs
        ADD CONSTRAINT rick_ingestion_jobs_max_attempts_ck
        CHECK (max_attempts BETWEEN 1 AND 64);
EXCEPTION WHEN duplicate_object THEN
    NULL;
END $$;

DO $$
BEGIN
    ALTER TABLE rick_ingestion_jobs
        ADD CONSTRAINT rick_ingestion_jobs_operation_ck
        CHECK (operation ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$');
EXCEPTION WHEN duplicate_object THEN
    NULL;
END $$;

DO $$
BEGIN
    ALTER TABLE rick_ingestion_jobs
        ADD CONSTRAINT rick_ingestion_jobs_version_ck
        CHECK (version > 0);
EXCEPTION WHEN duplicate_object THEN
    NULL;
END $$;

DO $$
BEGIN
    ALTER TABLE rick_ingestion_jobs
        ADD CONSTRAINT rick_ingestion_jobs_attempts_limit_ck
        CHECK (attempts BETWEEN 0 AND 64);
EXCEPTION WHEN duplicate_object THEN
    NULL;
END $$;

DO $$
BEGIN
    ALTER TABLE rick_ingestion_jobs
        ADD CONSTRAINT rick_ingestion_jobs_contract_state_ck
        CHECK (
            contract_state IN (
                'PENDING', 'QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED',
                'CANCELLED', 'RETRYING', 'DEAD_LETTER'
            )
        );
EXCEPTION WHEN duplicate_object THEN
    NULL;
END $$;

-- Replace the old tenant-wide idempotency key with the complete authorization
-- and destination scope. Existing duplicate data must fail the migration so
-- it can be reconciled explicitly rather than silently merged.
ALTER TABLE rick_ingestion_jobs
    DROP CONSTRAINT IF EXISTS rick_ingestion_jobs_tenant_id_idempotency_key_key;
CREATE UNIQUE INDEX IF NOT EXISTS rick_ingestion_jobs_idempotency_scope_idx
    ON rick_ingestion_jobs (tenant_id, workspace_id, collection_id, idempotency_key);

-- Make the job -> document relation reject a cross-scope binding.
DO $$
BEGIN
    ALTER TABLE rick_documents
        ADD CONSTRAINT rick_documents_scope_document_key
        UNIQUE (tenant_id, workspace_id, collection_id, document_id);
EXCEPTION WHEN duplicate_object THEN
    NULL;
END $$;

ALTER TABLE rick_ingestion_jobs
    DROP CONSTRAINT IF EXISTS rick_ingestion_jobs_document_id_fkey;

DO $$
BEGIN
    ALTER TABLE rick_ingestion_jobs
        ADD CONSTRAINT rick_ingestion_jobs_document_scope_fkey
        FOREIGN KEY (tenant_id, workspace_id, collection_id, document_id)
        REFERENCES rick_documents (tenant_id, workspace_id, collection_id, document_id);
EXCEPTION WHEN duplicate_object THEN
    NULL;
END $$;

CREATE INDEX IF NOT EXISTS rick_ingestion_jobs_contract_claim_idx
    ON rick_ingestion_jobs
       (tenant_id, workspace_id, collection_id, contract_state,
        available_at, created_at, job_id);

CREATE INDEX IF NOT EXISTS rick_ingestion_jobs_contract_dead_idx
    ON rick_ingestion_jobs
       (tenant_id, workspace_id, collection_id, contract_state, updated_at, job_id)
    WHERE contract_state = 'DEAD_LETTER';

CREATE TABLE IF NOT EXISTS rick_ingestion_job_attempts (
    job_id TEXT NOT NULL REFERENCES rick_ingestion_jobs(job_id) ON DELETE CASCADE,
    attempt_no INTEGER NOT NULL CHECK (attempt_no BETWEEN 1 AND 64),
    worker_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')),
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    failure JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (job_id, attempt_no),
    CHECK (finished_at IS NULL OR finished_at >= started_at),
    CHECK ((state = 'RUNNING' AND finished_at IS NULL AND failure IS NULL)
        OR (state = 'SUCCEEDED' AND finished_at IS NOT NULL AND failure IS NULL)
        OR (state = 'CANCELLED' AND finished_at IS NOT NULL AND failure IS NULL)
        OR (state = 'FAILED' AND finished_at IS NOT NULL AND failure IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS rick_ingestion_job_attempts_scope_idx
    ON rick_ingestion_job_attempts (job_id, attempt_no);

CREATE TABLE IF NOT EXISTS rick_ingestion_job_events (
    event_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES rick_ingestion_jobs(job_id) ON DELETE CASCADE,
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    collection_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    from_state TEXT,
    to_state TEXT NOT NULL,
    version BIGINT NOT NULL CHECK (version > 0),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- event_id is the idempotency key. A lease heartbeat or retention action may
-- share the job version with the preceding state transition.
ALTER TABLE rick_ingestion_job_events
    DROP CONSTRAINT IF EXISTS rick_ingestion_job_events_job_id_version_key;

CREATE INDEX IF NOT EXISTS rick_ingestion_job_events_scope_idx
    ON rick_ingestion_job_events
       (tenant_id, workspace_id, collection_id, created_at, event_id);

-- Migration 0001 created a separate queue authority. The current runtime has
-- never used it, so archive the empty table instead of leaving two writable
-- authorities. Existing rows stop this migration and require an explicit
-- operator reconciliation before the archive can be renamed.
DO $$
BEGIN
    IF to_regclass('public.rick_ingestion_job_control') IS NOT NULL THEN
        IF EXISTS (SELECT 1 FROM rick_ingestion_job_control) THEN
            RAISE EXCEPTION
                'legacy rick_ingestion_job_control contains rows; reconcile before Phase 2.2 migration';
        END IF;
        ALTER TABLE rick_ingestion_job_control
            RENAME TO rick_ingestion_job_control_legacy;
    END IF;
END $$;

-- Existing rows were written by the legacy facade. Keep their canonical
-- projection NULL so the old writer remains a separate compatibility lane;
-- canonical claims and mutations are limited to rows explicitly created by
-- the new adapter. Phase 2.3 will rewrite these rows deliberately, with a
-- replayable attempt-history migration and a caller switch.

-- If a prior partial deployment already contains canonical rows, make their
-- retry scalar compatible before installing the canonical-only constraint.
UPDATE rick_ingestion_jobs
SET max_attempts = GREATEST(max_attempts, attempts)
WHERE contract_state IS NOT NULL
  AND attempts > max_attempts;

DO $$
BEGIN
    ALTER TABLE rick_ingestion_jobs
        ADD CONSTRAINT rick_ingestion_jobs_contract_payload_ck
        CHECK (
            (contract_state <> 'RUNNING'
             OR (lease_worker_id IS NOT NULL AND lease_owner IS NOT NULL
                 AND lease_acquired_at IS NOT NULL AND lease_until IS NOT NULL
                 AND lease_until > lease_acquired_at))
            AND (contract_state <> 'SUCCEEDED' OR result IS NOT NULL)
            AND (contract_state NOT IN ('FAILED', 'RETRYING', 'DEAD_LETTER')
                 OR failure IS NOT NULL)
            AND (contract_state NOT IN ('PENDING', 'QUEUED', 'RETRYING')
                 OR result IS NULL)
        );
EXCEPTION WHEN duplicate_object THEN
    NULL;
END $$;

DO $$
BEGIN
    ALTER TABLE rick_ingestion_jobs
        ADD CONSTRAINT rick_ingestion_jobs_attempts_max_ck
        CHECK (contract_state IS NULL OR attempts <= max_attempts);
EXCEPTION WHEN duplicate_object THEN
    NULL;
END $$;

ALTER TABLE rick_ingestion_jobs
    ALTER COLUMN operation SET NOT NULL;

-- The adapter only appends an attempt and then finishes that same running
-- attempt. A finished attempt is immutable even for direct SQL callers.
CREATE OR REPLACE FUNCTION rick_guard_job_attempt_update()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.job_id IS DISTINCT FROM NEW.job_id
       OR OLD.attempt_no IS DISTINCT FROM NEW.attempt_no
       OR OLD.worker_id IS DISTINCT FROM NEW.worker_id
       OR OLD.started_at IS DISTINCT FROM NEW.started_at
       OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
        RAISE EXCEPTION 'job attempt identity is immutable';
    END IF;
    IF OLD.state <> 'RUNNING'
       AND (OLD.state IS DISTINCT FROM NEW.state
            OR OLD.finished_at IS DISTINCT FROM NEW.finished_at
            OR OLD.failure IS DISTINCT FROM NEW.failure) THEN
        RAISE EXCEPTION 'finished job attempts are immutable';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION rick_guard_job_attempt_delete()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    -- Deleting a whole retained job aggregate is allowed to cascade. A direct
    -- child delete would otherwise create gaps while preserving the scalar.
    IF pg_trigger_depth() > 1 THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'job attempt history is append-only';
END;
$$;

DROP TRIGGER IF EXISTS rick_job_attempt_immutable_trg ON rick_ingestion_job_attempts;
CREATE TRIGGER rick_job_attempt_immutable_trg
BEFORE UPDATE ON rick_ingestion_job_attempts
FOR EACH ROW EXECUTE FUNCTION rick_guard_job_attempt_update();

DROP TRIGGER IF EXISTS rick_job_attempt_delete_guard_trg ON rick_ingestion_job_attempts;
CREATE TRIGGER rick_job_attempt_delete_guard_trg
BEFORE DELETE ON rick_ingestion_job_attempts
FOR EACH ROW EXECUTE FUNCTION rick_guard_job_attempt_delete();

-- Keep the denormalized job.attempts scalar equal to the append-only history.
-- Compatibility rows with a NULL contract_state are deliberately outside this
-- invariant until the legacy facade is retired by Phase 2.3.
CREATE OR REPLACE FUNCTION rick_check_job_attempt_count()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    observed_job_id TEXT;
    expected_count INTEGER;
    canonical_state TEXT;
    actual_count INTEGER;
    minimum_attempt INTEGER;
    maximum_attempt INTEGER;
BEGIN
    IF TG_OP = 'DELETE' THEN
        observed_job_id := OLD.job_id;
    ELSE
        observed_job_id := NEW.job_id;
    END IF;
    SELECT attempts, contract_state
      INTO expected_count, canonical_state
      FROM rick_ingestion_jobs
     WHERE job_id = observed_job_id;
    IF NOT FOUND OR canonical_state IS NULL THEN
        RETURN NULL;
    END IF;
    SELECT COUNT(*)::INTEGER,
           COALESCE(MIN(attempt_no), 0),
           COALESCE(MAX(attempt_no), 0)
      INTO actual_count, minimum_attempt, maximum_attempt
      FROM rick_ingestion_job_attempts
     WHERE job_id = observed_job_id;
    IF expected_count IS DISTINCT FROM actual_count
       OR (actual_count > 0 AND (minimum_attempt <> 1 OR maximum_attempt <> actual_count)) THEN
        RAISE EXCEPTION
            'job % attempt history is not contiguous or count mismatches',
            observed_job_id;
    END IF;
    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS rick_job_attempt_count_jobs_trg ON rick_ingestion_jobs;
CREATE CONSTRAINT TRIGGER rick_job_attempt_count_jobs_trg
AFTER INSERT OR UPDATE ON rick_ingestion_jobs
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION rick_check_job_attempt_count();

DROP TRIGGER IF EXISTS rick_job_attempt_count_attempts_trg ON rick_ingestion_job_attempts;
CREATE CONSTRAINT TRIGGER rick_job_attempt_count_attempts_trg
AFTER INSERT OR UPDATE OR DELETE ON rick_ingestion_job_attempts
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION rick_check_job_attempt_count();

-- contract_state intentionally remains nullable for pre-existing rows and for
-- rows written by the legacy PostgresIngestionQueue. Those compatibility rows
-- keep the legacy status vocabulary and are excluded from canonical claims
-- and mutations until the Phase 2.3 worker migration rewrites them with
-- attempt history.

-- Application mutations must insert the job row, attempt row, lifecycle event
-- and audit record in one transaction. The migration runner only records this
-- migration after the complete DDL/data transaction commits.
