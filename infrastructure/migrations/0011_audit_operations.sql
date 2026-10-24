-- Durable audit-operation outcomes for security effects (ADR-024).
-- One row per operation, keyed by (action, request_id). The row is written in
-- the same transaction as the effect and projected to rick_audit_events by the
-- API/reconciler; it is the authority for "effect applied / acknowledged".
CREATE TABLE IF NOT EXISTS rick_audit_operations (
    operation_id TEXT PRIMARY KEY,
    action TEXT NOT NULL CHECK(length(btrim(action)) BETWEEN 1 AND 256),
    request_id TEXT NOT NULL CHECK(length(btrim(request_id)) BETWEEN 1 AND 256),
    tenant_id TEXT CHECK(tenant_id IS NULL OR length(btrim(tenant_id)) BETWEEN 1 AND 256),
    actor_user_id TEXT CHECK(actor_user_id IS NULL OR length(btrim(actor_user_id)) BETWEEN 1 AND 256),
    workspace_id TEXT CHECK(workspace_id IS NULL OR length(btrim(workspace_id)) BETWEEN 1 AND 256),
    state TEXT NOT NULL CHECK(state IN ('requested','effect_applied','acknowledged','indeterminate','failed')),
    payload JSONB NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(payload) = 'object' AND octet_length(payload::text) <= 65536),
    effect_at TIMESTAMPTZ,
    acknowledged_at TIMESTAMPTZ,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
    last_error_code TEXT CHECK(last_error_code IS NULL OR length(last_error_code) <= 128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (action, request_id)
);
CREATE INDEX IF NOT EXISTS rick_audit_operations_pending_idx
    ON rick_audit_operations (state, updated_at);
