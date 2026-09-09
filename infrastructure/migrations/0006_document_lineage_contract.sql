-- Phase 2 lineage contract for durable document publication.
-- Additive and roll-forward compatible: legacy object_key/document_version
-- values remain readable while new knowledge writes persist explicit lineage.

ALTER TABLE rick_documents
    ADD COLUMN IF NOT EXISTS ingestion_version TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS object_ref TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ;

-- The legacy content version and object key are deterministic compatibility
-- aliases, not guesses about historical publication time.
UPDATE rick_documents
SET ingestion_version = COALESCE(NULLIF(ingestion_version, ''), document_version),
    object_ref = COALESCE(NULLIF(object_ref, ''), NULLIF(object_key, ''),
                          NULLIF(filename, ''), NULLIF(display_filename, ''), document_id)
WHERE ingestion_version = '' OR object_ref = '';

CREATE INDEX IF NOT EXISTS rick_documents_lineage_scope_idx
    ON rick_documents
       (tenant_id, workspace_id, collection_id, document_id,
        document_version, ingestion_version);

CREATE INDEX IF NOT EXISTS rick_documents_publication_scope_idx
    ON rick_documents
       (tenant_id, workspace_id, collection_id, status, published_at DESC, document_id);

-- Existing created_at is the durable creation boundary. Publication history is
-- intentionally NULL for legacy rows because the old schema did not record it.
