from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "infrastructure" / "migrations" / "0005_rewrite_legacy_jobs.sql"


def test_legacy_rewrite_is_fail_closed_and_materializes_attempt_history() -> None:
    sql = MIGRATION.read_text()
    assert "unknown status" in sql
    assert "already have attempt rows" in sql
    assert "timestamps outside the canonical lifetime" in sql
    assert "INSERT INTO rick_ingestion_job_attempts" in sql
    assert "contract_state IS NULL" in sql
    assert "target_state := 'RUNNING'" in sql
    assert "target_state := 'DEAD_LETTER'" in sql
    assert "Phase 2.3 legacy job rewrite left NULL contract rows" in sql
    assert "INSERT INTO rick_ingestion_job_events" in sql
    assert "INSERT INTO rick_outbox" in sql
    assert "INSERT INTO rick_audit_events" in sql
    assert "rick-intelligence:jobs-canonical-rewrite" in sql
    assert "filename_ref" in sql
    assert "jsonb_each_text(target_payload)" in sql
    assert "result violates the completed result contract" in sql
    assert "result references violate the bounded metadata contract" in sql
    assert "document_id = canonical_document_id" in sql
    assert "'byte_size'" in sql
    assert "result_item.key NOT IN" in sql
    assert "jsonb_typeof((target_result -> 'output_refs') -> result_item.key) <> 'string'" in sql
    assert "canonical_document_id" in sql
    assert "result document reference conflicts" in sql
    assert "identifier or scope outside the canonical contract" in sql
    assert "operation outside the canonical contract" in sql
    assert "operation !~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$'" in sql
    assert "jsonb_typeof(target_result -> 'document_id') = 'null'" in sql
    assert "bearer|basic" in sql
    assert "DROP TABLE" not in sql.upper()


def test_legacy_rewrite_keeps_running_rows_owner_bound() -> None:
    sql = MIGRATION.read_text()
    assert "lease_owner IS NOT NULL" in sql
    assert "lease_until > COALESCE(job_row.lease_acquired_at, job_row.created_at)" in sql
    assert "lease_worker_id = lease_worker" in sql
    assert "lease_owner = CASE WHEN target_state = 'RUNNING'" in sql
