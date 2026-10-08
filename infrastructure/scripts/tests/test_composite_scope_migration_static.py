import re
from pathlib import Path


MIGRATION = Path(__file__).parents[2] / "migrations" / "0008_composite_scope_constraints.sql"


def test_composite_scope_migration_covers_all_scoped_authority_edges() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    required_fragments = (
        "0008 requires the exact validated rick_ingestion_jobs_document_scope_fkey from 0004",
        "rick_ingestion_jobs_document_scope_fkey",
        "rick_chunks_document_scope_fkey",
        "FOREIGN KEY (tenant_id, workspace_id, collection_id, document_id)",
        "REFERENCES rick_documents (tenant_id, workspace_id, collection_id, document_id)",
        "rick_conversations_scope_key",
        "UNIQUE (tenant_id, workspace_id, user_id, conversation_id)",
        "rick_conversations_collection_scope_fkey",
        "REFERENCES rick_collections (tenant_id, workspace_id, collection_id)",
        "rick_messages_conversation_scope_fkey",
        "REFERENCES rick_conversations (tenant_id, workspace_id, user_id, conversation_id)",
    )
    for fragment in required_fragments:
        assert fragment in sql


def test_composite_scope_migration_is_non_destructive_and_validates_rows() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    sql_without_comments = re.sub(r"--[^\n]*", "", sql).upper()
    sql = sql.upper()
    assert "NO REPAIR, MERGE, OR BACKFILL" in sql
    assert "NOT VALID" not in sql_without_comments
    assert "DROP " not in sql
    assert "DELETE " not in sql
    assert "UPDATE " not in sql


def _catalog_guard(sql: str, name: str) -> str:
    blocks = re.findall(r"DO \$\$(.*?)END \$\$;", sql, flags=re.DOTALL)
    return next(block for block in blocks if f"conname = '{name}'" in block)


def test_same_name_constraints_require_exact_catalog_identity_and_fk_semantics() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    constraints = {
        "rick_ingestion_jobs_document_scope_fkey": (
            "rick_ingestion_jobs", "f",
            ["tenant_id", "workspace_id", "collection_id", "document_id"],
            "rick_documents", ["tenant_id", "workspace_id", "collection_id", "document_id"],
        ),
        "rick_documents_scope_document_key": (
            "rick_documents", "u",
            ["tenant_id", "workspace_id", "collection_id", "document_id"],
            None, [],
        ),
        "rick_chunks_document_scope_fkey": (
            "rick_chunks", "f",
            ["tenant_id", "workspace_id", "collection_id", "document_id"],
            "rick_documents", ["tenant_id", "workspace_id", "collection_id", "document_id"],
        ),
        "rick_conversations_scope_key": (
            "rick_conversations", "u",
            ["tenant_id", "workspace_id", "user_id", "conversation_id"],
            None, [],
        ),
        "rick_conversations_collection_scope_fkey": (
            "rick_conversations", "f",
            ["tenant_id", "workspace_id", "collection_id"],
            "rick_collections", ["tenant_id", "workspace_id", "collection_id"],
        ),
        "rick_messages_conversation_scope_fkey": (
            "rick_messages", "f",
            ["tenant_id", "workspace_id", "user_id", "conversation_id"],
            "rick_conversations", ["tenant_id", "workspace_id", "user_id", "conversation_id"],
        ),
    }

    for name, (relation, constraint_type, source_columns, referenced_relation, referenced_columns) in constraints.items():
        guard = _catalog_guard(sql, name)
        assert f"c.conrelid = '{relation}'::regclass" in guard
        assert f"c.conname = '{name}'" in guard
        assert f"c.contype = '{constraint_type}'" in guard
        assert "c.convalidated" in guard
        assert "c.conkey = ARRAY[" in guard
        expected_columns = source_columns + referenced_columns
        assert re.findall(r"a\.attname = '([^']+)'", guard) == expected_columns
        expected_relations = [relation] * len(source_columns)
        if referenced_relation is not None:
            assert f"c.confrelid = '{referenced_relation}'::regclass" in guard
            assert "c.confkey = ARRAY[" in guard
            expected_relations += [referenced_relation] * len(referenced_columns)
            for semantic_guard in (
                "c.confmatchtype = 's'",
                "c.confupdtype = 'a'",
                "c.confdeltype = 'a'",
                "NOT c.condeferrable",
                "NOT c.condeferred",
            ):
                assert semantic_guard in guard
        else:
            definition = f"UNIQUE ({', '.join(source_columns)})"
            assert f"pg_get_constraintdef(c.oid) = '{definition}'" in guard
            assert "NOT c.condeferrable" in guard
            assert "NOT c.condeferred" in guard
        assert re.findall(r"a\.attrelid = '([^']+)'::regclass", guard) == expected_relations


def test_new_constraint_guards_reject_known_bad_duplicate_object_shape() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    known_bad_shape = re.compile(
        r"EXCEPTION\s+WHEN\s+duplicate_object\s+THEN\s+NULL\s*;",
        flags=re.IGNORECASE,
    )

    assert known_bad_shape.search(sql) is None
    new_constraints = (
        "rick_chunks_document_scope_fkey",
        "rick_conversations_scope_key",
        "rick_conversations_collection_scope_fkey",
        "rick_messages_conversation_scope_fkey",
    )
    for name in new_constraints:
        guard = _catalog_guard(sql, name)
        assert "IF EXISTS (" in guard
        assert "IF NOT EXISTS (" in guard
        assert f"RAISE EXCEPTION '0008 found incompatible {name}'" in guard
