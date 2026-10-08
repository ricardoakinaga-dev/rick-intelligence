-- Durable completion audit events for identity mutations. Admin producers
-- commit these outbox rows with the user/session changes; a worker projects
-- them into rick_audit_events with stable event IDs.

ALTER TABLE rick_outbox
    ADD COLUMN available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ADD COLUMN last_error_code TEXT,
    ADD COLUMN dead_lettered_at TIMESTAMPTZ,
    ADD COLUMN manual_retry_count SMALLINT NOT NULL DEFAULT 0,
    ADD CONSTRAINT rick_outbox_manual_retry_count_check
        CHECK (manual_retry_count BETWEEN 0 AND 3),
    ADD CONSTRAINT rick_outbox_event_id_nonblank_check
        CHECK (event_id ~ '[^[:space:]]');

CREATE INDEX rick_outbox_admin_audit_pending_idx
    ON rick_outbox (available_at, created_at)
    WHERE event_type = 'admin.audit.completion'
      AND published_at IS NULL
      AND dead_lettered_at IS NULL;
