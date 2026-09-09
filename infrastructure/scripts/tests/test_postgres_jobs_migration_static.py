from pathlib import Path


MIGRATION = Path(__file__).parents[2] / "migrations" / "0004_durable_jobs_contract.sql"


def test_canonical_jobs_migration_has_scope_cas_attempt_and_outbox_guards() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    required_fragments = (
        "contract_state",
        "ADD COLUMN IF NOT EXISTS operation TEXT",
        "operation ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$'",
        "contract_version",
        "max_attempts",
        "version BIGINT",
        "rick_ingestion_job_attempts",
        "rick_ingestion_job_events",
        "rick_ingestion_jobs_idempotency_scope_idx",
        "rick_ingestion_jobs_document_scope_fkey",
        "FOREIGN KEY (tenant_id, workspace_id, collection_id, document_id)",
        "rick_ingestion_jobs_contract_claim_idx",
        "rick_ingestion_jobs_contract_dead_idx",
        "rick_ingestion_jobs_contract_payload_ck",
        "rick_ingestion_jobs_attempts_max_ck",
        "rick_ingestion_job_control_legacy",
        "rick_guard_job_attempt_update",
        "rick_guard_job_attempt_delete",
        "rick_job_attempt_immutable_trg",
        "rick_job_attempt_delete_guard_trg",
        "rick_check_job_attempt_count",
        "DEFERRABLE INITIALLY DEFERRED",
        "GREATEST(max_attempts, attempts)",
        "contract_state intentionally remains nullable",
    )
    for fragment in required_fragments:
        assert fragment in sql
