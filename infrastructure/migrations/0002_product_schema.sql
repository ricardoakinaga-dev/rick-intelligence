-- RICK product authority. This migration is additive and tenant-scoped.
-- Application queries must keep the tenant/workspace predicates even when a
-- caller has a platform role. Qdrant and object storage are projections of
-- this metadata, never authorities for membership or publication state.

CREATE TABLE IF NOT EXISTS rick_tenants (
    tenant_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'archived')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rick_users (
    user_id TEXT PRIMARY KEY,
    external_subject TEXT,
    email TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled', 'pending')),
    password_version INTEGER NOT NULL DEFAULT 1 CHECK (password_version > 0),
    role_version INTEGER NOT NULL DEFAULT 1 CHECK (role_version > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (external_subject),
    UNIQUE (email)
);

CREATE TABLE IF NOT EXISTS rick_memberships (
    tenant_id TEXT NOT NULL REFERENCES rick_tenants(tenant_id),
    user_id TEXT NOT NULL REFERENCES rick_users(user_id),
    workspace_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('PLATFORM_ADMIN', 'KNOWLEDGE_MANAGER', 'VETERINARIAN')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    permission_overrides JSONB NOT NULL DEFAULT '{"add": [], "remove": []}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, user_id, workspace_id)
);

CREATE TABLE IF NOT EXISTS rick_sessions (
    session_id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    authorization_snapshot JSONB NOT NULL,
    password_version INTEGER NOT NULL,
    role_version INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    revoke_reason TEXT,
    FOREIGN KEY (tenant_id, user_id, workspace_id)
      REFERENCES rick_memberships(tenant_id, user_id, workspace_id)
);
CREATE INDEX IF NOT EXISTS rick_sessions_scope_idx
    ON rick_sessions (tenant_id, user_id, revoked_at, expires_at);

CREATE TABLE IF NOT EXISTS rick_collections (
    tenant_id TEXT NOT NULL REFERENCES rick_tenants(tenant_id),
    workspace_id TEXT NOT NULL,
    collection_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_by TEXT NOT NULL REFERENCES rick_users(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, workspace_id, collection_id)
);

CREATE TABLE IF NOT EXISTS rick_collection_grants (
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    collection_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    granted_by TEXT NOT NULL REFERENCES rick_users(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, workspace_id, collection_id, user_id),
    FOREIGN KEY (tenant_id, workspace_id, collection_id)
      REFERENCES rick_collections(tenant_id, workspace_id, collection_id),
    FOREIGN KEY (tenant_id, user_id, workspace_id)
      REFERENCES rick_memberships(tenant_id, user_id, workspace_id)
);

CREATE TABLE IF NOT EXISTS rick_documents (
    document_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    collection_id TEXT NOT NULL,
    document_version TEXT NOT NULL,
    content_checksum TEXT NOT NULL,
    object_key TEXT NOT NULL,
    byte_size BIGINT NOT NULL CHECK (byte_size >= 0),
    title TEXT NOT NULL,
    display_filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('draft', 'processing', 'published', 'unpublished', 'deleted', 'partial', 'failed')),
    parser_version TEXT NOT NULL,
    chunker_version TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    embedding_version TEXT NOT NULL,
    created_by TEXT NOT NULL REFERENCES rick_users(user_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (tenant_id, workspace_id, collection_id)
      REFERENCES rick_collections(tenant_id, workspace_id, collection_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS rick_documents_version_idx
    ON rick_documents (tenant_id, workspace_id, collection_id, content_checksum, document_version);
CREATE INDEX IF NOT EXISTS rick_documents_scope_idx
    ON rick_documents (tenant_id, workspace_id, collection_id, status, document_id);

CREATE TABLE IF NOT EXISTS rick_chunks (
    chunk_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES rick_documents(document_id),
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    collection_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
    text TEXT NOT NULL,
    checksum TEXT NOT NULL,
    page_start INTEGER,
    page_end INTEGER,
    section TEXT,
    embedding_version TEXT NOT NULL,
    index_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (document_id, chunk_index),
    FOREIGN KEY (tenant_id, workspace_id, collection_id)
      REFERENCES rick_collections(tenant_id, workspace_id, collection_id)
);

CREATE TABLE IF NOT EXISTS rick_ingestion_jobs (
    job_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    collection_id TEXT NOT NULL,
    document_id TEXT,
    status TEXT NOT NULL CHECK (status IN ('queued', 'leased', 'processing', 'published', 'failed', 'cancelled', 'dead')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    lease_until TIMESTAMPTZ,
    lease_owner TEXT,
    last_error_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, idempotency_key),
    FOREIGN KEY (tenant_id, workspace_id, collection_id)
      REFERENCES rick_collections(tenant_id, workspace_id, collection_id),
    FOREIGN KEY (document_id) REFERENCES rick_documents(document_id)
);
CREATE INDEX IF NOT EXISTS rick_ingestion_jobs_claim_idx
    ON rick_ingestion_jobs (status, available_at, created_at);

CREATE TABLE IF NOT EXISTS rick_outbox (
    event_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    published_at TIMESTAMPTZ,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS rick_outbox_pending_idx
    ON rick_outbox (published_at, created_at);

CREATE TABLE IF NOT EXISTS rick_conversations (
    conversation_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    collection_id TEXT,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (tenant_id, user_id, workspace_id)
      REFERENCES rick_memberships(tenant_id, user_id, workspace_id)
);
CREATE INDEX IF NOT EXISTS rick_conversations_scope_idx
    ON rick_conversations (tenant_id, workspace_id, user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS rick_messages (
    message_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES rick_conversations(conversation_id),
    tenant_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    citations JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    idempotency_key TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, workspace_id, user_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS rick_audit_events (
    event_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    actor_user_id TEXT,
    action TEXT NOT NULL,
    target_type TEXT,
    target_id TEXT,
    workspace_id TEXT,
    request_id TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS rick_audit_scope_idx
    ON rick_audit_events (tenant_id, occurred_at DESC, event_id);

-- The runner records this migration only after the entire transaction commits.
