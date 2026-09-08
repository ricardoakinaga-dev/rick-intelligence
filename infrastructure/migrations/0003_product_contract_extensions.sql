-- Additive compatibility columns used by the repository adapters.
-- Existing rows keep their safe defaults; no published document or session is
-- removed by this migration. Roll-forward is the supported recovery path.

ALTER TABLE rick_users
    ADD COLUMN IF NOT EXISTS password_hash TEXT;

ALTER TABLE rick_collections
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE rick_memberships
    ADD COLUMN IF NOT EXISTS authorized_collection_ids JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE rick_documents
    ADD COLUMN IF NOT EXISTS filename TEXT NOT NULL DEFAULT '';

ALTER TABLE rick_documents
    ADD COLUMN IF NOT EXISTS source_type TEXT NOT NULL DEFAULT '';

ALTER TABLE rick_documents
    ADD COLUMN IF NOT EXISTS language TEXT;

ALTER TABLE rick_documents
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE rick_chunks
    ADD COLUMN IF NOT EXISTS parent_chunk_id TEXT;

ALTER TABLE rick_chunks
    ADD COLUMN IF NOT EXISTS token_count INTEGER NOT NULL DEFAULT 0;

ALTER TABLE rick_chunks
    ADD COLUMN IF NOT EXISTS parser_version TEXT NOT NULL DEFAULT '';

ALTER TABLE rick_chunks
    ADD COLUMN IF NOT EXISTS chunker_version TEXT NOT NULL DEFAULT '';

ALTER TABLE rick_chunks
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE rick_ingestion_jobs
    ADD COLUMN IF NOT EXISTS payload JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS rick_users_email_idx
    ON rick_users (lower(email));
CREATE INDEX IF NOT EXISTS rick_memberships_user_scope_idx
    ON rick_memberships (tenant_id, user_id, status, workspace_id);

CREATE TABLE IF NOT EXISTS rick_password_reset_tokens (
    token_hash TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES rick_users(user_id),
    workspace_id TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (tenant_id, user_id, workspace_id)
      REFERENCES rick_memberships(tenant_id, user_id, workspace_id)
      DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX IF NOT EXISTS rick_password_reset_expiry_idx
    ON rick_password_reset_tokens (tenant_id, expires_at, consumed_at);
