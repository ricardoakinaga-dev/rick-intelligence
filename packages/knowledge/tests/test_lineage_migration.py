from pathlib import Path


MIGRATION = Path(__file__).parents[3] / "infrastructure" / "migrations" / "0006_document_lineage_contract.sql"


def test_lineage_migration_is_additive_and_scope_bound() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "ALTER TABLE rick_documents" in sql
    assert "ADD COLUMN IF NOT EXISTS ingestion_version TEXT NOT NULL DEFAULT ''" in sql
    assert "ADD COLUMN IF NOT EXISTS object_ref TEXT NOT NULL DEFAULT ''" in sql
    assert "ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ" in sql
    assert "SET ingestion_version = COALESCE(NULLIF(ingestion_version, ''), document_version)" in sql
    assert "object_ref = COALESCE(NULLIF(object_ref, ''), NULLIF(object_key, '')," in sql
    assert "rick_documents_lineage_scope_idx" in sql
    assert "tenant_id, workspace_id, collection_id, document_id" in sql
    assert "rick_documents_publication_scope_idx" in sql
    assert "DROP TABLE" not in sql
    assert "DROP COLUMN" not in sql
