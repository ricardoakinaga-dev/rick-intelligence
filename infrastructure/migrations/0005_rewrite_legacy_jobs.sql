-- Phase 2.3: move the last legacy job rows into the canonical contract.
--
-- Migration 0004 deliberately left pre-existing rows in a NULL
-- contract_state lane. This migration is the one-time, replayable caller
-- switch: it creates a bounded attempt history before exposing each row to
-- canonical claims. It fails closed for unknown states, impossible attempt
-- counts, or an already populated canonical attempt table.

DO $$
DECLARE
    job_row RECORD;
    observed_attempts INTEGER;
    effective_max_attempts INTEGER;
    attempt_no INTEGER;
    attempt_started TIMESTAMPTZ;
    attempt_finished TIMESTAMPTZ;
    attempt_state TEXT;
    attempt_failure JSONB;
    target_state TEXT;
    target_status TEXT;
    target_payload JSONB;
    target_result JSONB;
    target_failure JSONB;
    lease_worker TEXT;
    lease_acquired TIMESTAMPTZ;
    lease_expires TIMESTAMPTZ;
    retryable_failure BOOLEAN;
    canonical_document_id TEXT;
    rewrite_event_id TEXT;
    rewrite_metadata JSONB;
BEGIN
    -- Legacy writers take the same transaction advisory lock before their
    -- enqueue. This closes the scan-to-trigger window during the caller switch.
    PERFORM pg_advisory_xact_lock(hashtext('rick-intelligence:jobs-canonical-rewrite'));

    IF EXISTS (
        SELECT 1
        FROM rick_ingestion_jobs j
        JOIN rick_ingestion_job_attempts a ON a.job_id = j.job_id
        WHERE j.contract_state IS NULL
    ) THEN
        RAISE EXCEPTION
            'legacy jobs already have attempt rows; reconcile before Phase 2.3 rewrite';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM rick_ingestion_jobs
        WHERE contract_state IS NULL
          AND status NOT IN ('queued', 'leased', 'processing', 'published',
                             'acked', 'failed', 'dead', 'cancelled')
    ) THEN
        RAISE EXCEPTION 'legacy jobs contain an unknown status';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM rick_ingestion_jobs
        WHERE contract_state IS NULL
          AND (attempts < 0 OR attempts > 64)
    ) THEN
        RAISE EXCEPTION 'legacy jobs contain an attempt count outside 0..64';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM rick_ingestion_jobs
        WHERE contract_state IS NULL
          AND (updated_at < created_at OR available_at < created_at)
    ) THEN
        RAISE EXCEPTION 'legacy jobs contain timestamps outside the canonical lifetime';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM rick_ingestion_jobs
        WHERE contract_state IS NULL
          AND (
              job_id !~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'
              OR tenant_id !~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'
              OR workspace_id !~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'
              OR collection_id !~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'
              OR idempotency_key !~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'
          )
    ) THEN
        RAISE EXCEPTION 'legacy jobs contain an identifier or scope outside the canonical contract';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM rick_ingestion_jobs
        WHERE contract_state IS NULL
          AND (
              operation IS NULL
              OR length(operation) = 0
              OR length(operation) > 64
              OR operation ~ '[[:cntrl:]]'
              OR operation !~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$'
          )
    ) THEN
        RAISE EXCEPTION 'legacy jobs contain an operation outside the canonical contract';
    END IF;

    FOR job_row IN
        SELECT *
        FROM rick_ingestion_jobs
        WHERE contract_state IS NULL
        ORDER BY created_at, job_id
        FOR UPDATE
    LOOP
        effective_max_attempts := GREATEST(1, COALESCE(job_row.max_attempts, 3));
        observed_attempts := GREATEST(0, COALESCE(job_row.attempts, 0));
        IF observed_attempts > effective_max_attempts THEN
            effective_max_attempts := observed_attempts;
        END IF;

        target_state := 'QUEUED';
        target_status := 'queued';
        target_payload := COALESCE(job_row.payload, '{}'::jsonb);
        target_result := NULL;
        target_failure := NULL;
        canonical_document_id := NULLIF(job_row.document_id, '');
        lease_worker := NULL;
        lease_acquired := NULL;
        lease_expires := NULL;
        retryable_failure := TRUE;

        IF jsonb_typeof(target_payload) <> 'object' THEN
            RAISE EXCEPTION 'legacy job % payload is not a JSON object', job_row.job_id;
        END IF;
        IF target_payload ? 'display_filename' THEN
            IF target_payload ? 'filename_ref' THEN
                RAISE EXCEPTION 'legacy job % has conflicting filename references', job_row.job_id;
            END IF;
            IF jsonb_typeof(target_payload -> 'display_filename') <> 'string' THEN
                RAISE EXCEPTION 'legacy job % display filename is not text', job_row.job_id;
            END IF;
            target_payload := (target_payload - 'display_filename') || jsonb_build_object(
                'filename_ref', replace(
                    replace(encode(convert_to(target_payload ->> 'display_filename', 'UTF8'), 'base64'), E'\n', ''),
                    E'\r', ''
                )
            );
        END IF;
        IF target_payload ->> 'document_id' = '' THEN
            target_payload := target_payload - 'document_id';
        END IF;
        IF jsonb_object_length(target_payload) > 32
           OR EXISTS (
               SELECT 1
               FROM jsonb_each_text(target_payload) AS payload_item(key, value)
               WHERE jsonb_typeof(target_payload -> payload_item.key) <> 'string'
                  OR length(payload_item.key) = 0
                  OR length(payload_item.key) > 64
                  OR payload_item.key !~ '^[a-z][a-z0-9_.:-]{0,63}$'
                  OR payload_item.key ~* '(api[_-]?key|authorization|bearer|credential|password|pem|prompt|private|provider[_-]?(response|result)|raw[_-]?content|response|secret|token)'
                  OR (
                      payload_item.key NOT IN (
                          'attempt_id', 'byte_size', 'bytes', 'checksum', 'chunk_id',
                          'collection_id', 'document_id', 'etag', 'filename', 'hash',
                          'index_version', 'job_id', 'lease_id', 'mime_type', 'model_id',
                          'object_key', 'operation', 'page', 'provider_id', 'schema_version',
                          'section', 'size', 'source_key', 'stage', 'state', 'status',
                          'tenant_id', 'trace_id', 'uri', 'url', 'version', 'vector_id',
                          'workspace_id'
                      )
                      AND payload_item.key !~ '(_id|_key|_ref|_version|_hash|_checksum|_uri|_url)$'
                  )
                  OR length(payload_item.value) = 0
                  OR length(payload_item.value) > 512
                  OR payload_item.value !~ '^[A-Za-z0-9][A-Za-z0-9_.:/@?=&%+~,\-]{0,511}$'
                  OR payload_item.value ~* '(^|[^a-z0-9])(sk|pk|rk|ghp|glpat|xox[baprs])_[a-z0-9_-]*($|[^a-z0-9])'
                  OR payload_item.value ~* '(bearer|basic)[[:space:]]+[a-z0-9._~+/=-]{8,}'
                  OR payload_item.value ~* '(api[_-]?key|authorization|password|secret|token|private[_[:space:]-]?key)[[:space:]]*[:=]'
                  OR payload_item.value ~* '(raw[-_.[:space:]]?(document[-_.[:space:]]?)?(content|body|text))'
                  OR payload_item.value ~* '((full[-_.[:space:]]?)?document[-_.[:space:]]?(content|body|text))'
                  OR payload_item.value ~* '(provider[-_.[:space:]]?(response|result))'
                  OR payload_item.value ~* '-----begin[-_[:space:]]*(private|secret)?[-_[:space:]]*key-----'
           ) THEN
            RAISE EXCEPTION 'legacy job % payload violates the bounded jobs contract', job_row.job_id;
        END IF;

        IF job_row.status IN ('published', 'acked') THEN
            target_state := 'SUCCEEDED';
            target_status := 'published';
            observed_attempts := GREATEST(1, observed_attempts);
            target_result := COALESCE(
                job_row.result,
                jsonb_build_object(
                    'output_refs', '{}'::jsonb,
                    'document_id', NULLIF(job_row.document_id, ''),
                    'completed_at', EXTRACT(EPOCH FROM job_row.updated_at)
                )
            );
            IF jsonb_typeof(target_result) <> 'object'
               OR (target_result ? 'output_refs'
                   AND jsonb_typeof(target_result -> 'output_refs') <> 'object')
               OR NOT (target_result ? 'completed_at')
               OR jsonb_typeof(target_result -> 'completed_at') <> 'number'
               OR (target_result ->> 'completed_at')::DOUBLE PRECISION
                    < EXTRACT(EPOCH FROM job_row.created_at)
               OR (target_result ->> 'completed_at')::DOUBLE PRECISION
                    > EXTRACT(EPOCH FROM job_row.updated_at) THEN
                RAISE EXCEPTION 'legacy job % result violates the completed result contract', job_row.job_id;
            END IF;
            IF target_result ? 'document_id' THEN
                IF jsonb_typeof(target_result -> 'document_id') NOT IN ('string', 'null')
                   OR (jsonb_typeof(target_result -> 'document_id') = 'string'
                       AND target_result ->> 'document_id' <> ''
                       AND target_result ->> 'document_id'
                           !~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$') THEN
                    RAISE EXCEPTION 'legacy job % result document reference is invalid', job_row.job_id;
                END IF;
                IF jsonb_typeof(target_result -> 'document_id') = 'null'
                   OR target_result ->> 'document_id' = '' THEN
                    target_result := target_result - 'document_id';
                ELSE
                    IF canonical_document_id IS NOT NULL
                       AND canonical_document_id <> (target_result ->> 'document_id') THEN
                        RAISE EXCEPTION 'legacy job % result document reference conflicts with the job document', job_row.job_id;
                    END IF;
                    canonical_document_id := target_result ->> 'document_id';
                END IF;
            END IF;
            IF target_result ? 'output_refs'
               AND (
                   jsonb_object_length(target_result -> 'output_refs') > 32
                   OR EXISTS (
                       SELECT 1
                       FROM jsonb_each_text(target_result -> 'output_refs') AS result_item(key, value)
                       WHERE jsonb_typeof((target_result -> 'output_refs') -> result_item.key) <> 'string'
                          OR length(result_item.key) = 0
                          OR length(result_item.key) > 64
                          OR result_item.key !~ '^[a-z][a-z0-9_.:-]{0,63}$'
                          OR result_item.key ~* '(api[_-]?key|authorization|bearer|credential|password|pem|prompt|private|provider[_-]?(response|result)|raw[_-]?content|response|secret|token)'
                          OR (
                              result_item.key NOT IN (
                                  'attempt_id', 'byte_size', 'bytes', 'checksum', 'chunk_id',
                                  'collection_id', 'document_id', 'etag', 'filename', 'hash',
                                  'index_version', 'job_id', 'lease_id', 'mime_type', 'model_id',
                                  'object_key', 'operation', 'page', 'provider_id', 'schema_version',
                                  'section', 'size', 'source_key', 'stage', 'state', 'status',
                                  'tenant_id', 'trace_id', 'uri', 'url', 'version', 'vector_id',
                                  'workspace_id'
                              )
                              AND result_item.key !~ '(_id|_key|_ref|_version|_hash|_checksum|_uri|_url)$'
                          )
                          OR length(result_item.value) = 0
                          OR length(result_item.value) > 512
                          OR result_item.value !~ '^[A-Za-z0-9][A-Za-z0-9_.:/@?=&%+~,\-]{0,511}$'
                          OR result_item.value ~* '(^|[^a-z0-9])(sk|pk|rk|ghp|glpat|xox[baprs])_[a-z0-9_-]*($|[^a-z0-9])'
                          OR result_item.value ~* '(bearer|basic)[[:space:]]+[a-z0-9._~+/=-]{8,}'
                          OR result_item.value ~* '(api[_-]?key|authorization|password|secret|token|private[_[:space:]-]?key)[[:space:]]*[:=]'
                          OR result_item.value ~* '(raw[-_.[:space:]]?(document[-_.[:space:]]?)?(content|body|text))'
                          OR result_item.value ~* '((full[-_.[:space:]]?)?document[-_.[:space:]]?(content|body|text))'
                          OR result_item.value ~* '(provider[-_.[:space:]]?(response|result))'
                          OR result_item.value ~* '-----begin[-_[:space:]]*(private|secret)?[-_[:space:]]*key-----'
                   )
               ) THEN
                RAISE EXCEPTION 'legacy job % result references violate the bounded metadata contract', job_row.job_id;
            END IF;
        ELSIF job_row.status = 'cancelled' THEN
            target_state := 'CANCELLED';
            target_status := 'cancelled';
        ELSIF job_row.status = 'dead' THEN
            target_state := 'DEAD_LETTER';
            target_status := 'dead';
            observed_attempts := GREATEST(1, observed_attempts);
            retryable_failure := FALSE;
        ELSIF job_row.status IN ('leased', 'processing')
              AND job_row.lease_owner IS NOT NULL
              AND job_row.lease_until IS NOT NULL
              AND job_row.lease_until > COALESCE(job_row.lease_acquired_at, job_row.created_at)
              AND job_row.lease_until > clock_timestamp() THEN
            target_state := 'RUNNING';
            target_status := 'processing';
            observed_attempts := GREATEST(1, observed_attempts);
            lease_worker := COALESCE(
                job_row.lease_worker_id,
                split_part(job_row.lease_owner, ':', 1),
                'legacy-migration'
            );
            lease_acquired := COALESCE(
                job_row.lease_acquired_at,
                job_row.created_at
            );
            lease_expires := job_row.lease_until;
        ELSIF job_row.status IN ('failed', 'dead')
              AND observed_attempts >= effective_max_attempts THEN
            target_state := 'DEAD_LETTER';
            target_status := 'dead';
            observed_attempts := GREATEST(1, observed_attempts);
            retryable_failure := FALSE;
        ELSIF job_row.status IN ('queued', 'leased', 'processing')
              AND observed_attempts >= effective_max_attempts
              AND observed_attempts > 0 THEN
            target_state := 'DEAD_LETTER';
            target_status := 'dead';
            retryable_failure := FALSE;
        ELSIF job_row.status IN ('failed', 'leased', 'processing') THEN
            -- Expired or failed legacy work is made claimable after a
            -- synthetic finished attempt. The canonical queue will apply its
            -- normal retry policy from this point onward.
            target_state := 'QUEUED';
            target_status := 'queued';
            observed_attempts := GREATEST(1, observed_attempts);
        END IF;

        IF target_state = 'RUNNING' THEN
            -- The active attempt is materialized below with a NULL finish.
            NULL;
        END IF;

        FOR attempt_no IN 1..observed_attempts LOOP
            attempt_started := job_row.created_at
                + ((job_row.updated_at - job_row.created_at)
                   * ((attempt_no - 1)::DOUBLE PRECISION / observed_attempts));
            IF target_state = 'RUNNING' AND attempt_no = observed_attempts THEN
                attempt_state := 'RUNNING';
                attempt_finished := NULL;
                attempt_failure := NULL;
            ELSIF target_state = 'SUCCEEDED' AND attempt_no = observed_attempts THEN
                attempt_state := 'SUCCEEDED';
                attempt_finished := GREATEST(attempt_started, job_row.updated_at);
                attempt_failure := NULL;
            ELSIF target_state = 'CANCELLED' AND attempt_no = observed_attempts THEN
                attempt_state := 'CANCELLED';
                attempt_finished := GREATEST(attempt_started, job_row.updated_at);
                attempt_failure := NULL;
            ELSE
                attempt_state := 'FAILED';
                attempt_finished := GREATEST(
                    attempt_started,
                    job_row.created_at
                        + ((job_row.updated_at - job_row.created_at)
                           * (attempt_no::DOUBLE PRECISION / observed_attempts))
                );
                attempt_failure := jsonb_build_object(
                    'code', CASE
                        WHEN job_row.last_error_code IN (
                            'provider_timeout', 'provider_unavailable',
                            'storage_unavailable', 'lock_unavailable',
                            'validation_error', 'ingestion_failed',
                            'cancelled', 'recovery_required'
                        ) THEN job_row.last_error_code
                        ELSE 'legacy_failure'
                    END,
                    'message', CASE
                        WHEN target_state = 'DEAD_LETTER'
                            THEN 'legacy job exhausted its bounded retry history'
                        WHEN attempt_no = observed_attempts AND retryable_failure
                            THEN 'legacy job requires a bounded retry'
                        ELSE 'legacy failure reconstructed during canonical migration'
                    END,
                    'retryable', retryable_failure,
                    'attempt', attempt_no,
                    'occurred_at', EXTRACT(EPOCH FROM attempt_finished)
                );
            END IF;

            INSERT INTO rick_ingestion_job_attempts
                (job_id, attempt_no, worker_id, state, started_at,
                 finished_at, failure)
            VALUES (
                job_row.job_id,
                attempt_no,
                COALESCE(lease_worker, 'legacy-migration'),
                attempt_state,
                attempt_started,
                attempt_finished,
                attempt_failure
            );
        END LOOP;

        IF target_state IN ('DEAD_LETTER', 'QUEUED') THEN
            target_failure := CASE
                WHEN target_state = 'DEAD_LETTER' THEN jsonb_build_object(
                    'code', CASE
                        WHEN job_row.last_error_code IN (
                            'provider_timeout', 'provider_unavailable',
                            'storage_unavailable', 'lock_unavailable',
                            'validation_error', 'ingestion_failed',
                            'cancelled', 'recovery_required'
                        ) THEN job_row.last_error_code
                        ELSE 'legacy_failure'
                    END,
                    'message', 'legacy job exhausted its bounded retry history',
                    'retryable', FALSE,
                    'attempt', observed_attempts,
                    'occurred_at', EXTRACT(EPOCH FROM job_row.updated_at)
                )
                ELSE NULL
            END;
        END IF;

        UPDATE rick_ingestion_jobs
        SET contract_state = target_state,
            contract_version = 'jobs-contract-v1',
            document_id = canonical_document_id,
            payload = target_payload,
            max_attempts = effective_max_attempts,
            attempts = observed_attempts,
            status = target_status,
            result = target_result,
            failure = target_failure,
            lease_worker_id = lease_worker,
            lease_acquired_at = lease_acquired,
            lease_until = lease_expires,
            lease_owner = CASE WHEN target_state = 'RUNNING' THEN job_row.lease_owner ELSE NULL END,
            updated_at = GREATEST(job_row.updated_at, job_row.created_at)
        WHERE job_id = job_row.job_id;

        -- Preserve the same durable projection contract used by canonical
        -- mutations. The migration itself is observable and replay-safe: one
        -- stable event id fans out to lifecycle, outbox, and audit records.
        rewrite_event_id := format('job:%s:legacy-rewritten', job_row.job_id);
        rewrite_metadata := jsonb_build_object(
            'contract_version', 'jobs-contract-v1',
            'migration', '0005_rewrite_legacy_jobs',
            'legacy_status', job_row.status,
            'state', target_state,
            'attempt_count', observed_attempts,
            'max_attempts', effective_max_attempts
        );
        INSERT INTO rick_ingestion_job_events
            (event_id, job_id, tenant_id, workspace_id, collection_id,
             event_type, from_state, to_state, version, metadata)
        VALUES (
            rewrite_event_id,
            job_row.job_id,
            job_row.tenant_id,
            job_row.workspace_id,
            job_row.collection_id,
            'legacy_rewritten',
            NULL,
            target_state,
            job_row.version,
            rewrite_metadata
        )
        ON CONFLICT (event_id) DO NOTHING;
        INSERT INTO rick_outbox
            (event_id, tenant_id, aggregate_type, aggregate_id, event_type, payload)
        VALUES (
            rewrite_event_id,
            job_row.tenant_id,
            'job',
            job_row.job_id,
            'jobs.legacy_rewritten',
            rewrite_metadata
        )
        ON CONFLICT (event_id) DO NOTHING;
        INSERT INTO rick_audit_events
            (event_id, tenant_id, actor_user_id, action, target_type,
             target_id, workspace_id, metadata)
        VALUES (
            rewrite_event_id,
            job_row.tenant_id,
            NULL,
            'jobs.legacy_rewritten',
            'job',
            job_row.job_id,
            job_row.workspace_id,
            rewrite_metadata
        )
        ON CONFLICT (event_id) DO NOTHING;
    END LOOP;
END $$;

-- Every row is canonical after this point. A follow-up deployment must not
-- reintroduce the legacy writer; the compatibility facade is read-only until
-- all callers have moved to rick_jobs.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM rick_ingestion_jobs WHERE contract_state IS NULL) THEN
        RAISE EXCEPTION 'Phase 2.3 legacy job rewrite left NULL contract rows';
    END IF;
END $$;

-- The old facade remains importable for rollback/read compatibility, but it
-- must not recreate a second writable authority after this migration.
CREATE OR REPLACE FUNCTION rick_require_canonical_job_write()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.contract_state IS NULL THEN
        RAISE EXCEPTION
            'legacy job writes are disabled after Phase 2.3 canonical rewrite';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS rick_require_canonical_job_write_trg ON rick_ingestion_jobs;
CREATE TRIGGER rick_require_canonical_job_write_trg
BEFORE INSERT OR UPDATE ON rick_ingestion_jobs
FOR EACH ROW EXECUTE FUNCTION rick_require_canonical_job_write();
