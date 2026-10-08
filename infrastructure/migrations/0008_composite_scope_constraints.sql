-- Enforce that scoped child rows cannot point at an authority in another scope.
-- Existing rows are validated by PostgreSQL; no repair, merge, or backfill is
-- performed. Reconcile incompatible data explicitly before applying 0008.

-- rick_ingestion_jobs already received this composite relation in 0004. Keep
-- the contract explicit here so this migration's scope inventory is complete.
-- A same-name constraint only satisfies the prerequisite when its complete
-- catalog identity and FK behavior match the 0004 contract.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint c
        WHERE c.conrelid = 'rick_ingestion_jobs'::regclass
          AND c.conname = 'rick_ingestion_jobs_document_scope_fkey'
          AND c.contype = 'f'
          AND c.conkey = ARRAY[
              (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = 'rick_ingestion_jobs'::regclass AND a.attname = 'tenant_id' AND NOT a.attisdropped),
              (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = 'rick_ingestion_jobs'::regclass AND a.attname = 'workspace_id' AND NOT a.attisdropped),
              (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = 'rick_ingestion_jobs'::regclass AND a.attname = 'collection_id' AND NOT a.attisdropped),
              (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = 'rick_ingestion_jobs'::regclass AND a.attname = 'document_id' AND NOT a.attisdropped)
          ]::smallint[]
          AND c.confrelid = 'rick_documents'::regclass
          AND c.confkey = ARRAY[
              (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = 'rick_documents'::regclass AND a.attname = 'tenant_id' AND NOT a.attisdropped),
              (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = 'rick_documents'::regclass AND a.attname = 'workspace_id' AND NOT a.attisdropped),
              (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = 'rick_documents'::regclass AND a.attname = 'collection_id' AND NOT a.attisdropped),
              (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = 'rick_documents'::regclass AND a.attname = 'document_id' AND NOT a.attisdropped)
          ]::smallint[]
          AND c.confmatchtype = 's'
          AND c.confupdtype = 'a'
          AND c.confdeltype = 'a'
          AND NOT c.condeferrable
          AND NOT c.condeferred
          AND c.convalidated
    ) THEN
        RAISE EXCEPTION '0008 requires the exact validated rick_ingestion_jobs_document_scope_fkey from 0004';
    END IF;
END $$;

-- 0004 already owns the composite key. Require its exact validated unique
-- constraint; re-adding the same name can collide with its backing index.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint c
        WHERE c.conrelid = 'rick_documents'::regclass
          AND c.conname = 'rick_documents_scope_document_key'
          AND c.contype = 'u'
          AND c.conkey = ARRAY[
              (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = 'rick_documents'::regclass AND a.attname = 'tenant_id' AND NOT a.attisdropped),
              (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = 'rick_documents'::regclass AND a.attname = 'workspace_id' AND NOT a.attisdropped),
              (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = 'rick_documents'::regclass AND a.attname = 'collection_id' AND NOT a.attisdropped),
              (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = 'rick_documents'::regclass AND a.attname = 'document_id' AND NOT a.attisdropped)
          ]::smallint[]
          AND c.convalidated
          AND NOT c.condeferrable
          AND NOT c.condeferred
          AND pg_get_constraintdef(c.oid) = 'UNIQUE (tenant_id, workspace_id, collection_id, document_id)'
    ) THEN
        RAISE EXCEPTION '0008 requires the exact validated rick_documents_scope_document_key from 0004';
    END IF;
END $$;

-- Every same-name hit is checked before it is treated as an idempotent repeat.
-- This catches wrong-type, wrong-column/reference, changed-action and NOT VALID
-- constraints rather than allowing a duplicate_object handler to mask them.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint c
        WHERE c.conrelid = 'rick_chunks'::regclass
          AND c.conname = 'rick_chunks_document_scope_fkey'
    ) THEN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint c
            WHERE c.conrelid = 'rick_chunks'::regclass
              AND c.conname = 'rick_chunks_document_scope_fkey'
              AND c.contype = 'f'
              AND c.conkey = ARRAY[
                  (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = 'rick_chunks'::regclass AND a.attname = 'tenant_id' AND NOT a.attisdropped),
                  (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = 'rick_chunks'::regclass AND a.attname = 'workspace_id' AND NOT a.attisdropped),
                  (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = 'rick_chunks'::regclass AND a.attname = 'collection_id' AND NOT a.attisdropped),
                  (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = 'rick_chunks'::regclass AND a.attname = 'document_id' AND NOT a.attisdropped)
              ]::smallint[]
              AND c.confrelid = 'rick_documents'::regclass
              AND c.confkey = ARRAY[
                  (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = 'rick_documents'::regclass AND a.attname = 'tenant_id' AND NOT a.attisdropped),
                  (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = 'rick_documents'::regclass AND a.attname = 'workspace_id' AND NOT a.attisdropped),
                  (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = 'rick_documents'::regclass AND a.attname = 'collection_id' AND NOT a.attisdropped),
                  (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = 'rick_documents'::regclass AND a.attname = 'document_id' AND NOT a.attisdropped)
              ]::smallint[]
              AND c.confmatchtype = 's'
              AND c.confupdtype = 'a'
              AND c.confdeltype = 'a'
              AND NOT c.condeferrable
              AND NOT c.condeferred
              AND c.convalidated
        ) THEN
            RAISE EXCEPTION '0008 found incompatible rick_chunks_document_scope_fkey';
        END IF;
    ELSE
        ALTER TABLE rick_chunks
            ADD CONSTRAINT rick_chunks_document_scope_fkey
            FOREIGN KEY (tenant_id, workspace_id, collection_id, document_id)
            REFERENCES rick_documents (tenant_id, workspace_id, collection_id, document_id);
    END IF;
END $$;

-- A conversation's identity is scoped by its membership and optional
-- collection. NULL collection_id remains valid for collection-less chats.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint c
        WHERE c.conrelid = 'rick_conversations'::regclass
          AND c.conname = 'rick_conversations_scope_key'
    ) THEN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint c
            WHERE c.conrelid = 'rick_conversations'::regclass
              AND c.conname = 'rick_conversations_scope_key'
              AND c.contype = 'u'
              AND c.conkey = ARRAY[
                  (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = 'rick_conversations'::regclass AND a.attname = 'tenant_id' AND NOT a.attisdropped),
                  (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = 'rick_conversations'::regclass AND a.attname = 'workspace_id' AND NOT a.attisdropped),
                  (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = 'rick_conversations'::regclass AND a.attname = 'user_id' AND NOT a.attisdropped),
                  (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = 'rick_conversations'::regclass AND a.attname = 'conversation_id' AND NOT a.attisdropped)
              ]::smallint[]
              AND c.convalidated
              AND NOT c.condeferrable
              AND NOT c.condeferred
              AND pg_get_constraintdef(c.oid) = 'UNIQUE (tenant_id, workspace_id, user_id, conversation_id)'
        ) THEN
            RAISE EXCEPTION '0008 found incompatible rick_conversations_scope_key';
        END IF;
    ELSE
        ALTER TABLE rick_conversations
            ADD CONSTRAINT rick_conversations_scope_key
            UNIQUE (tenant_id, workspace_id, user_id, conversation_id);
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint c
        WHERE c.conrelid = 'rick_conversations'::regclass
          AND c.conname = 'rick_conversations_collection_scope_fkey'
    ) THEN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint c
            WHERE c.conrelid = 'rick_conversations'::regclass
              AND c.conname = 'rick_conversations_collection_scope_fkey'
              AND c.contype = 'f'
              AND c.conkey = ARRAY[
                  (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = 'rick_conversations'::regclass AND a.attname = 'tenant_id' AND NOT a.attisdropped),
                  (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = 'rick_conversations'::regclass AND a.attname = 'workspace_id' AND NOT a.attisdropped),
                  (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = 'rick_conversations'::regclass AND a.attname = 'collection_id' AND NOT a.attisdropped)
              ]::smallint[]
              AND c.confrelid = 'rick_collections'::regclass
              AND c.confkey = ARRAY[
                  (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = 'rick_collections'::regclass AND a.attname = 'tenant_id' AND NOT a.attisdropped),
                  (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = 'rick_collections'::regclass AND a.attname = 'workspace_id' AND NOT a.attisdropped),
                  (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = 'rick_collections'::regclass AND a.attname = 'collection_id' AND NOT a.attisdropped)
              ]::smallint[]
              AND c.confmatchtype = 's'
              AND c.confupdtype = 'a'
              AND c.confdeltype = 'a'
              AND NOT c.condeferrable
              AND NOT c.condeferred
              AND c.convalidated
        ) THEN
            RAISE EXCEPTION '0008 found incompatible rick_conversations_collection_scope_fkey';
        END IF;
    ELSE
        ALTER TABLE rick_conversations
            ADD CONSTRAINT rick_conversations_collection_scope_fkey
            FOREIGN KEY (tenant_id, workspace_id, collection_id)
            REFERENCES rick_collections (tenant_id, workspace_id, collection_id);
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint c
        WHERE c.conrelid = 'rick_messages'::regclass
          AND c.conname = 'rick_messages_conversation_scope_fkey'
    ) THEN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint c
            WHERE c.conrelid = 'rick_messages'::regclass
              AND c.conname = 'rick_messages_conversation_scope_fkey'
              AND c.contype = 'f'
              AND c.conkey = ARRAY[
                  (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = 'rick_messages'::regclass AND a.attname = 'tenant_id' AND NOT a.attisdropped),
                  (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = 'rick_messages'::regclass AND a.attname = 'workspace_id' AND NOT a.attisdropped),
                  (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = 'rick_messages'::regclass AND a.attname = 'user_id' AND NOT a.attisdropped),
                  (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = 'rick_messages'::regclass AND a.attname = 'conversation_id' AND NOT a.attisdropped)
              ]::smallint[]
              AND c.confrelid = 'rick_conversations'::regclass
              AND c.confkey = ARRAY[
                  (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = 'rick_conversations'::regclass AND a.attname = 'tenant_id' AND NOT a.attisdropped),
                  (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = 'rick_conversations'::regclass AND a.attname = 'workspace_id' AND NOT a.attisdropped),
                  (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = 'rick_conversations'::regclass AND a.attname = 'user_id' AND NOT a.attisdropped),
                  (SELECT a.attnum FROM pg_attribute a WHERE a.attrelid = 'rick_conversations'::regclass AND a.attname = 'conversation_id' AND NOT a.attisdropped)
              ]::smallint[]
              AND c.confmatchtype = 's'
              AND c.confupdtype = 'a'
              AND c.confdeltype = 'a'
              AND NOT c.condeferrable
              AND NOT c.condeferred
              AND c.convalidated
        ) THEN
            RAISE EXCEPTION '0008 found incompatible rick_messages_conversation_scope_fkey';
        END IF;
    ELSE
        ALTER TABLE rick_messages
            ADD CONSTRAINT rick_messages_conversation_scope_fkey
            FOREIGN KEY (tenant_id, workspace_id, user_id, conversation_id)
            REFERENCES rick_conversations (tenant_id, workspace_id, user_id, conversation_id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS rick_chunks_scope_idx
    ON rick_chunks (tenant_id, workspace_id, collection_id, document_id, chunk_index);

CREATE INDEX IF NOT EXISTS rick_messages_conversation_scope_idx
    ON rick_messages (tenant_id, workspace_id, user_id, conversation_id, created_at);
