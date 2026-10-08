"""Opt-in adapter proofs in private schemas; no shared tenant or catalog writes.

Set RICK_AUD03_DISPOSABLE_CONFIG to Lead's private disposable PG config file.
The DSN is read in-process and never placed in logs or command arguments.
"""
import importlib.util
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from rick_knowledge import PostgresKnowledgeStore


@pytest.fixture
def pg_store():
    config = os.environ.get("RICK_AUD03_DISPOSABLE_CONFIG")
    if not config:
        pytest.skip("Requires explicit disposable PostgreSQL config")
    import psycopg
    from psycopg import sql
    dsn = json.loads(Path(config).read_text())["database_dsn"]
    schema = "aud03_ingest_rework4_" + uuid4().hex
    with psycopg.connect(dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        for table in ("rick_collections", "rick_documents", "rick_chunks"):
            connection.execute(sql.SQL("CREATE TABLE {}.{} (LIKE public.{} INCLUDING ALL)").format(sql.Identifier(schema), sql.Identifier(table), sql.Identifier(table)))
        connection.execute(sql.SQL("ALTER TABLE {}.rick_documents ADD FOREIGN KEY (tenant_id,workspace_id,collection_id) REFERENCES {}.rick_collections(tenant_id,workspace_id,collection_id)").format(sql.Identifier(schema), sql.Identifier(schema)))
        connection.execute(sql.SQL("ALTER TABLE {}.rick_chunks ADD FOREIGN KEY (document_id) REFERENCES {}.rick_documents(document_id)").format(sql.Identifier(schema), sql.Identifier(schema)))
    def connect():
        connection = psycopg.connect(dsn, connect_timeout=5)
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        connection.commit()
        return connection
    print("OWNED_PG_SCHEMA", schema)
    try:
        yield PostgresKnowledgeStore(connect, created_by="aud03-rework4")
    finally:
        with psycopg.connect(dsn) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            assert connection.execute("SELECT 1 FROM pg_namespace WHERE nspname=%s", (schema,)).fetchone() is None
        print("CLEANUP_PG_SCHEMA", schema)


def probe(relative):
    path = Path(__file__).resolve().parents[3] / relative
    spec = importlib.util.spec_from_file_location("rework4_" + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("alias", ["cvg_master_rag", "rickvet_documents"])
@pytest.mark.parametrize("canonical_exists", [False, True])
def test_pg_historical_archive_denies_alias_family(pg_store, alias, canonical_exists):
    probe("packages/knowledge/tests/test_aud03_catalog_aliases.py").exercise_archived_alias(pg_store, dict(tenant_id="t", workspace_id="w"), alias, canonical_exists)


@pytest.mark.parametrize("alias", ["cvg_master_rag", "rickvet_documents"])
def test_pg_historical_active_retains_fk_parent_metadata(pg_store, alias):
    probe("packages/knowledge/tests/test_aud03_catalog_aliases.py").exercise_active_alias(pg_store, dict(tenant_id="t", workspace_id="w"), alias)


def test_pg_cancelled_restore_rolls_back_complete_tombstone(pg_store):
    probe("packages/knowledge/tests/test_aud03_cancel_transaction.py").exercise_cancelled_restore(pg_store, dict(tenant_id="t", workspace_id="w", collection_id="c"))


@pytest.mark.parametrize("caller", ["pipeline", "api", "worker"])
@pytest.mark.parametrize("operation", ["ingest", "duplicate", "reindex"])
def test_pg_cancelled_completion_public_callers(pg_store, tmp_path, caller, operation):
    probe("apps/api/tests/test_aud03_rework4.py").exercise_cancelled_completion(pg_store, tmp_path, dict(tenant_id="t", workspace_id="w", collection_id="c"), caller, operation)
