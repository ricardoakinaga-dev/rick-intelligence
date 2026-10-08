-- Publication receipts survive worker/API restarts and queue lease expiry.
-- No foreign key to jobs: local journals and the canonical queue share this seam.
CREATE TABLE IF NOT EXISTS rick_publication_receipts (
    tenant_id TEXT NOT NULL CHECK (length(btrim(tenant_id, U&'\0009\000a\000b\000c\000d\001c\001d\001e\001f\0020\0085\00a0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200a\2028\2029\202f\205f\3000')) > 0 AND length(tenant_id) <= 256),
    workspace_id TEXT NOT NULL CHECK (length(btrim(workspace_id, U&'\0009\000a\000b\000c\000d\001c\001d\001e\001f\0020\0085\00a0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200a\2028\2029\202f\205f\3000')) > 0 AND length(workspace_id) <= 256),
    collection_id TEXT NOT NULL CHECK (length(btrim(collection_id, U&'\0009\000a\000b\000c\000d\001c\001d\001e\001f\0020\0085\00a0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200a\2028\2029\202f\205f\3000')) > 0 AND length(collection_id) <= 256),
    job_id TEXT NOT NULL CHECK (length(btrim(job_id, U&'\0009\000a\000b\000c\000d\001c\001d\001e\001f\0020\0085\00a0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200a\2028\2029\202f\205f\3000')) > 0 AND length(job_id) <= 256),
    document_id TEXT NOT NULL CHECK (length(btrim(document_id, U&'\0009\000a\000b\000c\000d\001c\001d\001e\001f\0020\0085\00a0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200a\2028\2029\202f\205f\3000')) > 0 AND length(document_id) <= 256),
    attempt_id TEXT NOT NULL CHECK (length(btrim(attempt_id, U&'\0009\000a\000b\000c\000d\001c\001d\001e\001f\0020\0085\00a0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200a\2028\2029\202f\205f\3000')) > 0 AND length(attempt_id) <= 256),
    document_attempt TEXT NOT NULL CHECK (length(btrim(document_attempt, U&'\0009\000a\000b\000c\000d\001c\001d\001e\001f\0020\0085\00a0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200a\2028\2029\202f\205f\3000')) > 0 AND length(document_attempt) <= 256),
    outcome TEXT NOT NULL CHECK (outcome IN ('pending', 'committed', 'failed', 'cancelled')),
    cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
    ready_count INTEGER NOT NULL DEFAULT 0 CHECK (ready_count BETWEEN 0 AND 100000),
    job_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(job_snapshot) = 'object'),
    PRIMARY KEY (tenant_id, workspace_id, collection_id, job_id)
);
CREATE INDEX IF NOT EXISTS rick_publication_pending_document
    ON rick_publication_receipts(document_id) WHERE outcome = 'pending';

-- Recovery scheduling is independent of worker lease authority. Unknown
-- outcomes advance only this timestamp; they never renew the expired token.
ALTER TABLE rick_ingestion_jobs ADD COLUMN IF NOT EXISTS publication_recovery_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS rick_ingestion_publication_recovery_due
    ON rick_ingestion_jobs(tenant_id, workspace_id, collection_id, publication_recovery_at, created_at, job_id)
    WHERE contract_state = 'RUNNING';
