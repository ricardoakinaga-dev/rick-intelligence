#!/usr/bin/env python3
"""Read-only, aggregate scope checks before migration 0008; never apply SQL DDL."""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
SQL_PATH = ROOT / "docs/operations/0008-scope-preflight.sql"
MIGRATION_PATH = ROOT / "infrastructure/migrations/0008_composite_scope_constraints.sql"
CHECK_NAMES = frozenset({
    "chunks_document_scope", "jobs_document_scope",
    "conversations_collection_scope", "messages_conversation_scope",
})


def snapshot_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value):
        raise ValueError("snapshot identifier must be 1-128 letters, digits, dots, underscores, colons or hyphens")
    return value


def counts(rows) -> dict[str, int]:
    result = {}
    for row in rows:
        if (not isinstance(row, (tuple, list)) or len(row) != 2
                or not isinstance(row[0], str) or row[0] not in CHECK_NAMES
                or row[0] in result or type(row[1]) is not int or row[1] < 0):
            raise ValueError("invalid scope preflight result")
        result[row[0]] = row[1]
    if set(result) != CHECK_NAMES:
        raise ValueError("incomplete scope preflight result")
    return dict(sorted(result.items()))


def inspect_scope(dsn: str | None, snapshot_id: str) -> dict:
    snapshot_identifier(snapshot_id)
    if not isinstance(dsn, str) or not dsn.strip():
        raise ValueError("RICK_PREFLIGHT_DATABASE_DSN is required")
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("psycopg is required for scope preflight") from exc
    source = SQL_PATH.read_bytes()
    migration_digest = hashlib.sha256(MIGRATION_PATH.read_bytes()).hexdigest()
    try:
        with psycopg.connect(dsn, connect_timeout=5) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                cursor.execute("SET LOCAL statement_timeout = '15s'")
                cursor.execute("SET LOCAL lock_timeout = '5s'")
                cursor.execute("SELECT current_setting('transaction_read_only'), "
                               "current_setting('transaction_isolation')")
                if cursor.fetchone() != ("on", "repeatable read"):
                    raise RuntimeError("scope preflight transaction settings were not enforced")
                cursor.execute(source.decode("utf-8"))
                checks = counts(cursor.fetchall())
    except psycopg.Error as exc:
        # Driver diagnostics can contain credentials, SQL and row values.
        state = getattr(exc, "sqlstate", None)
        code = state if isinstance(state, str) and re.fullmatch(r"[A-Z0-9]{5}", state) else "unknown"
        raise RuntimeError(f"scope preflight database error (SQLSTATE {code})") from None
    return {
        "schema_version": 1,
        "snapshot_id": snapshot_id,
        "observed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "transaction": {"read_only": True, "isolation_level": "repeatable read"},
        "sql_sha256": hashlib.sha256(source).hexdigest(),
        "local_migration_sha256": migration_digest,
        "checks": checks,
        "status": "NO_CONFLICTS" if not any(checks.values()) else "BLOCKED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-id", required=True)
    args = parser.parse_args()
    try:
        result = inspect_scope(os.environ.get("RICK_PREFLIGHT_DATABASE_DSN"), args.snapshot_id)
    except (OSError, UnicodeError):
        print("scope preflight: cannot read local SQL inputs", file=sys.stderr)
        return 2
    except (ValueError, RuntimeError) as exc:
        print(f"scope preflight: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "NO_CONFLICTS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
