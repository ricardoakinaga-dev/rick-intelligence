#!/usr/bin/env python3
"""Fail-closed Postgres migration runner with offline checksum mode.

``--check`` never opens a database connection. Applying migrations requires an
explicit DSN and the optional psycopg driver; the entire pending batch is applied
in one transaction under a PostgreSQL advisory lock. There is intentionally no
automatic destructive rollback.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys


MIGRATION_NAME = re.compile(r"^(\d{4})_[a-z0-9][a-z0-9_-]*\.sql$")
FUNCTION_SOURCE = re.compile(
    r"CREATE\s+OR\s+REPLACE\s+FUNCTION\s+([A-Za-z_][A-Za-z0-9_]*)\s*"
    r"\([^)]*\)\s*RETURNS\b.*?\bAS\s+\$\$(.*?)\$\$;",
    re.IGNORECASE | re.DOTALL,
)
APPLICATION = "rick-intelligence"
REQUIRED_JOB_FUNCTIONS = frozenset({
    "rick_guard_job_attempt_update",
    "rick_guard_job_attempt_delete",
    "rick_check_job_attempt_count",
    "rick_require_canonical_job_write",
})

# Q24-07: the sole historical 0005 blob in Git (commit
# 1c6fe4dc7da98386e2c09263d8d87df40e06ac6f) has two PostgreSQL-incompatible
# expressions, each used twice. The corrected SQL preserves its contract.
# 0004 also has an earlier length-only constraint from a42a1eb9ee30fef0f1317b114679993f3ca862c9;
# it needs a separately recorded additive repair. These are exact source/target
# compatibility pairs, NOT checksum resets.
# See docs/operations/migration-upgrade-2026-09-24.md before changing it.
LEGACY_REWRITE_NAME = "0005_rewrite_legacy_jobs.sql"
LEGACY_REWRITE_ORIGINAL = "d577b70fb1af2790851c0f42d50d2269e80da412405cff2dfde53d63bb873a03"
LEGACY_REWRITE_CURRENT = "58878320223f9f30d42aea840c7e58795eb5c448daf90a0877adedc781cc9774"
JOBS_CONTRACT_NAME = "0004_durable_jobs_contract.sql"
JOBS_CONTRACT_ORIGINAL = "9ddcde2578d7c829a4efcba6db33fd37c7781b753f3676198a653f133436db8d"
JOBS_CONTRACT_CURRENT = "0621c726c6eaae17fba0a72a209452964eb6320c38f2ebc60966b1d562731274"
OPERATION_REPAIR_NAME = "0004_operation_guard.sql.inc"
OPERATION_REPAIR_SHA256 = "9691a200e4746e0cc69b035c7a81ac1ede8cab3053ab24b354294d9725afa1e2"
OPERATION_REPAIR_ID = "0004_operation_contract_v1"

COMPATIBLE_ARTIFACTS = {
    "0004": (JOBS_CONTRACT_NAME, JOBS_CONTRACT_CURRENT, JOBS_CONTRACT_ORIGINAL),
    "0005": (LEGACY_REWRITE_NAME, LEGACY_REWRITE_CURRENT, LEGACY_REWRITE_ORIGINAL),
}


def compatible_checksum(version: str, path: Path, digest: str, recorded: str) -> bool:
    return COMPATIBLE_ARTIFACTS.get(version) == (path.name, digest, recorded)


def operation_repair_source(directory: Path) -> str:
    content = (directory / OPERATION_REPAIR_NAME).read_bytes()
    if hashlib.sha256(content).hexdigest() != OPERATION_REPAIR_SHA256:
        raise ValueError("unrecognized operation repair checksum")
    return content.decode("utf-8")


def expected_job_function_sources(statements: dict[str, str]) -> dict[str, str]:
    """Extract the function bodies whose exact bindings enforce job history."""
    result: dict[str, str] = {}
    for version in ("0004", "0005"):
        source = statements.get(version, "")
        for name, body in FUNCTION_SOURCE.findall(source):
            if name in REQUIRED_JOB_FUNCTIONS:
                result[name] = body
    if set(result) != REQUIRED_JOB_FUNCTIONS:
        missing = sorted(REQUIRED_JOB_FUNCTIONS - set(result))
        raise RuntimeError("job migration is missing required trigger function(s): " + ", ".join(missing))
    return result


def _normalise_function_source(source: str) -> str:
    # Catalog bodies must match the reviewed source. Removing whitespace or
    # comments can change literals and token boundaries while hiding drift.
    # Only padding outside the complete body is safe to disregard.
    return source.strip()


def migration_files(directory: Path) -> list[tuple[str, Path, str]]:
    if not directory.is_dir():
        raise ValueError("migration directory is invalid")
    rows: list[tuple[str, Path, str]] = []
    seen: set[str] = set()
    for path in sorted(directory.glob("*.sql")):
        match = MIGRATION_NAME.fullmatch(path.name)
        if match is None:
            raise ValueError(f"invalid migration filename: {path.name}")
        version = match.group(1)
        if version in seen:
            raise ValueError(f"duplicate migration version: {version}")
        seen.add(version)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        pinned = COMPATIBLE_ARTIFACTS.get(version)
        if pinned is not None and (path.name, digest) != pinned[:2]:
            raise ValueError(f"unrecognized local artifact/checksum for migration {version}")
        rows.append((version, path, digest))
    if not rows:
        raise ValueError("no migration files found")
    if [int(version) for version, _path, _digest in rows] != list(range(1, len(rows) + 1)):
        raise ValueError("migration files must form a contiguous sequence starting at 0001")
    if "0004" in seen:
        operation_repair_source(directory)
    return rows


def validate_history(
    rows: list[tuple[str, Path, str]], applied_rows: list[tuple[str, str, str]]
) -> dict[str, str]:
    """Validate the complete history before executing any pending migration."""
    applied: dict[str, str] = {}
    for row in applied_rows:
        if len(row) != 3 or not all(isinstance(value, str) for value in row):
            raise RuntimeError("migration history row is malformed")
        version, checksum, application = row
        if not re.fullmatch(r"\d{4}", version):
            raise RuntimeError("migration history version is malformed")
        if application != APPLICATION:
            raise RuntimeError(f"migration history application mismatch for {version}")
        if version in applied:
            raise RuntimeError(f"duplicate migration history version {version}")
        applied[version] = checksum
    local_versions = [version for version, _path, _digest in rows]
    unknown = sorted(set(applied) - set(local_versions))
    if unknown:
        raise RuntimeError("migration history contains unknown version(s): " + ", ".join(unknown))
    if sorted(applied) != local_versions[:len(applied)]:
        raise RuntimeError("migration history has a gap; expected a contiguous applied prefix")
    for version, path, digest in rows:
        recorded = applied.get(version)
        if recorded is not None and recorded != digest:
            if not compatible_checksum(version, path, digest, recorded):
                raise RuntimeError(f"checksum mismatch for migration {version}")
    return applied


def repair_historical_operation_guard(cursor, source: str) -> str:
    """Expand the real old-0004 constraint, recording only SQL actually run.

    This is a separately checksummed repair, never a fabricated numbered
    migration or an update of the old migration's digest. It commits with
    the pending migrations or rolls back with them.
    """
    cursor.execute("""CREATE TABLE IF NOT EXISTS rick_schema_migration_repairs (
        repair_id TEXT PRIMARY KEY, source_version TEXT NOT NULL,
        source_checksum TEXT NOT NULL, repair_checksum TEXT NOT NULL,
        application TEXT NOT NULL, applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""")
    cursor.execute("""SELECT repair_id, source_version, source_checksum,
        repair_checksum, application FROM rick_schema_migration_repairs ORDER BY repair_id""")
    recorded = cursor.fetchall()
    expected = (OPERATION_REPAIR_ID, "0004", JOBS_CONTRACT_ORIGINAL, OPERATION_REPAIR_SHA256, APPLICATION)
    if recorded and recorded != [expected]:
        raise RuntimeError("unknown or mismatched migration repair history")
    if not recorded:
        # ADD CONSTRAINT validates every existing row, including canonical rows
        # that migration 0005 intentionally skips. The old constraint remains.
        cursor.execute(source)
        cursor.execute("""INSERT INTO rick_schema_migration_repairs
            (repair_id, source_version, source_checksum, repair_checksum, application)
            VALUES (%s, %s, %s, %s, %s)""", expected)
    cursor.execute("""SELECT pg_get_constraintdef(oid), convalidated
        FROM pg_constraint WHERE conrelid='rick_ingestion_jobs'::regclass
        AND conname='rick_ingestion_jobs_operation_v2_ck' AND contype='c'""")
    required = "CHECK ((operation ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$'::text))"
    if cursor.fetchall() != [(required, True)]:
        raise RuntimeError("recorded operation repair has a missing or mismatched validated constraint")
    return f"{OPERATION_REPAIR_ID}: {'already applied' if recorded else 'applied'} (original 0004 checksum retained)"


def verify_jobs_rewrite(cursor, expected_functions: dict[str, str]) -> None:
    """Check the persisted 0005 boundary without replaying or repairing it.

    A recognized checksum does not authorize accepting a partially applied
    rewrite or disabling the canonical/append-only guards.
    """
    cursor.execute("""DO $q24_verify$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM rick_ingestion_jobs
            WHERE contract_state IS NULL
               OR contract_version IS DISTINCT FROM 'jobs-contract-v1'
        ) THEN
            RAISE EXCEPTION 'recorded 0005 has incomplete canonical jobs';
        END IF;
        IF EXISTS (
            SELECT 1 FROM rick_ingestion_jobs j
            LEFT JOIN rick_ingestion_job_attempts a ON a.job_id = j.job_id
            GROUP BY j.job_id, j.attempts
            HAVING j.attempts <> count(a.attempt_no)
               OR (count(a.attempt_no) > 0 AND
                   (min(a.attempt_no) <> 1 OR max(a.attempt_no) <> count(a.attempt_no)))
        ) THEN
            RAISE EXCEPTION 'recorded 0005 has incomplete attempt history';
        END IF;
        IF (
            SELECT count(*) FROM pg_trigger t
            WHERE NOT t.tgisinternal AND t.tgenabled IN ('O', 'A')
              AND (
                  (t.tgrelid = 'rick_ingestion_jobs'::regclass
                   AND t.tgname = 'rick_require_canonical_job_write_trg'
                   AND t.tgfoid = 'rick_require_canonical_job_write()'::regprocedure
                   AND t.tgtype = 23 AND NOT t.tgdeferrable)
                  OR (t.tgrelid = 'rick_ingestion_jobs'::regclass
                   AND t.tgname = 'rick_job_attempt_count_jobs_trg'
                   AND t.tgfoid = 'rick_check_job_attempt_count()'::regprocedure
                   AND t.tgtype = 21 AND t.tgdeferrable AND t.tginitdeferred)
                  OR (t.tgrelid = 'rick_ingestion_job_attempts'::regclass
                   AND t.tgname = 'rick_job_attempt_immutable_trg'
                   AND t.tgfoid = 'rick_guard_job_attempt_update()'::regprocedure
                   AND t.tgtype = 19 AND NOT t.tgdeferrable)
                  OR (t.tgrelid = 'rick_ingestion_job_attempts'::regclass
                   AND t.tgname = 'rick_job_attempt_delete_guard_trg'
                   AND t.tgfoid = 'rick_guard_job_attempt_delete()'::regprocedure
                   AND t.tgtype = 11 AND NOT t.tgdeferrable)
                  OR (t.tgrelid = 'rick_ingestion_job_attempts'::regclass
                   AND t.tgname = 'rick_job_attempt_count_attempts_trg'
                   AND t.tgfoid = 'rick_check_job_attempt_count()'::regprocedure
                   AND t.tgtype = 29 AND t.tgdeferrable AND t.tginitdeferred)
              )
        ) <> 5 THEN
            RAISE EXCEPTION 'recorded 0005 is missing enabled canonical job guards';
        END IF;
    END $q24_verify$;""")
    names = sorted(expected_functions)
    placeholders = ",".join(["%s"] * len(names))
    cursor.execute(
        f"""SELECT p.proname, p.prosrc, p.prorettype='trigger'::regtype, l.lanname
            FROM pg_proc p
            JOIN pg_namespace n ON n.oid=p.pronamespace
            JOIN pg_language l ON l.oid=p.prolang
            WHERE n.nspname=current_schema() AND p.proname IN ({placeholders})""",
        tuple(names),
    )
    rows = cursor.fetchall()
    actual = {row[0]: row for row in rows}
    if set(actual) != REQUIRED_JOB_FUNCTIONS:
        raise RuntimeError("recorded 0005 trigger function set changed")
    for name in names:
        _function_name, body, is_trigger, language = actual[name]
        if (
            is_trigger is not True
            or language != "plpgsql"
            or _normalise_function_source(str(body))
            != _normalise_function_source(expected_functions[name])
        ):
            raise RuntimeError(f"recorded 0005 trigger function body changed: {name}")


def check(directory: Path) -> int:
    rows = migration_files(directory)
    for version, path, digest in rows:
        print(f"{version} {path.name} sha256:{digest}")
    if any(version == "0004" for version, _path, _digest in rows):
        print(f"repair {OPERATION_REPAIR_NAME} sha256:{OPERATION_REPAIR_SHA256}")
    print(f"migration checksums: PASS ({len(rows)} file(s)); execution: NOT_RUN")
    return 0


# Relation identities, rather than just EMPTY/EXISTING, are part of production
# authorization. This catalog read never creates the history table.
AUTHORIZATION_RELATIONS_SQL = """/* migration_authorization_relations */
SELECT n.nspname, c.relname, c.relkind::text FROM pg_class c
JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname NOT IN ('pg_catalog','information_schema')
AND n.nspname NOT LIKE 'pg_toast%' AND c.relkind IN ('r','p','v','m','S','f')
ORDER BY n.nspname, c.relname, c.relkind"""


def reviewed_authorization(data: bytes) -> dict:
    """Immutable guard handoff; local callers may omit it, never relax it."""
    if not isinstance(data, bytes):
        raise RuntimeError("immutable reviewed migration authorization required")
    try:
        plan = json.loads(data)
    except (ValueError, TypeError) as exc:
        raise RuntimeError("invalid reviewed migration authorization") from exc
    required = {'schema','authorization','observed','maintenance_window','verified_backup_id','backward_compatible'}
    if (not isinstance(plan,dict) or set(plan) != required
        or plan['schema'] != 'rick.vps.migration-plan/v1'
        or plan['authorization'] != 'APPLY_REVIEWED_SQL'
        or plan['backward_compatible'] is not True
        or type(plan['maintenance_window']) is not bool
        or not isinstance(plan['verified_backup_id'],str)
        or plan['verified_backup_id'] != plan['verified_backup_id'].strip()
        or any(ord(c)<32 for c in plan['verified_backup_id'])):
        raise RuntimeError('reviewed maintenance, backup and compatibility authorization required')
    observed = plan['observed']
    if (not isinstance(observed,dict)
        or set(observed) != {'schema','read_only','database_state','relation_count','relations','history','pending'}
        or observed['schema'] != 'rick.vps.preflight/v1' or observed['read_only'] is not True
        or type(observed['relation_count']) is not int):
        raise RuntimeError('complete reviewed database observation required')
    if observed['database_state'] == 'EMPTY':
        valid = not observed['history'] and plan['maintenance_window'] is False and plan['verified_backup_id'] == ''
    elif observed['database_state'] == 'EXISTING':
        history = observed['history']
        valid = (isinstance(history,list) and bool(history)
                 and isinstance(history[-1],dict)
                 and isinstance(history[-1].get('version'),str)
                 and history[-1]['version'] >= '0007'
                 and plan['maintenance_window'] is True and bool(plan['verified_backup_id']))
    else:
        valid = False
    if not valid:
        raise RuntimeError('reviewed database maintenance and backup assumptions required')
    return plan


def locked_observation(cursor, rows):
    cursor.execute('SELECT current_schema()')
    if cursor.fetchone() != ('public',):
        raise RuntimeError('reviewed public schema search path required')
    cursor.execute(AUTHORIZATION_RELATIONS_SQL)
    relations = [list(row) for row in cursor.fetchall()]
    cursor.execute("SELECT to_regclass('rick_schema_migrations') IS NOT NULL")
    has_history = cursor.fetchone()[0]
    history = []
    if has_history:
        cursor.execute('SELECT version, checksum, application FROM rick_schema_migrations ORDER BY version')
        history = cursor.fetchall()
    applied = validate_history(rows, history)
    if any(applied.get(v, h) != h for v, _, h in rows):
        raise RuntimeError('historical migration requires separate reviewed repair')
    return {'schema':'rick.vps.preflight/v1', 'read_only':True,
            'database_state':'EXISTING' if relations else 'EMPTY',
            'relation_count':len(relations), 'relations':relations,
            'history':[{'version':v,'sha256':h} for v,h,_ in history],
            'pending':[{'version':v,'sha256':h} for v,_,h in rows if v not in applied]}


def apply(directory: Path, dsn: str, *, authorization: bytes | None = None) -> int:
    if not isinstance(dsn, str) or not dsn.strip():
        raise ValueError("--database-url is required for apply")
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("psycopg is required only for live migration execution") from exc
    approved = reviewed_authorization(authorization) if authorization is not None else None
    rows = migration_files(directory)
    # Execute exactly the bytes that were checked, even if the checkout changes
    # while waiting for the database lock.
    statements: dict[str, str] = {}
    for version, path, digest in rows:
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != digest:
            raise RuntimeError(f"migration {version} changed during checksum validation")
        statements[version] = content.decode("utf-8")
    repair_source = operation_repair_source(directory) if "0004" in statements else None
    messages: list[str] = []
    jobs_rewrite = any(path.name == LEGACY_REWRITE_NAME for _version, path, _digest in rows)
    job_function_sources = expected_job_function_sources(statements) if jobs_rewrite else {}
    try:
        with psycopg.connect(dsn) as connection:
            with connection.cursor() as cursor:
                if approved is not None:
                    # Do not inherit a repeatable-read default: a snapshot taken
                    # while waiting for the lock would miss its holder's commit.
                    cursor.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
                # The lock must precede even the bookkeeping DDL: two first
                # installations must not race to create the history table.
                cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("rick-intelligence:migrations",))
                if approved is not None:
                    # Lock acquisition uses READ COMMITTED: the catalog/history
                    # read after waiting sees the preceding lock holder's commit.
                    # Refusal exits the connection transaction before any DDL,
                    # historical repair, or pending SQL is allowed.
                    current = locked_observation(cursor, rows)
                    if current != approved['observed']:
                        raise RuntimeError('database inventory changed under migration lock')
                    if migration_files(directory) != rows:
                        raise RuntimeError('migration SQL inventory changed under migration lock')
                cursor.execute(
                    """CREATE TABLE IF NOT EXISTS rick_schema_migrations (
                       version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                       checksum TEXT NOT NULL, application TEXT NOT NULL)"""
                )
                cursor.execute(
                    "SELECT version, checksum, application "
                    "FROM rick_schema_migrations ORDER BY version"
                )
                applied = validate_history(rows, cursor.fetchall())
                if not applied:
                    cursor.execute("""DO $q24_history$
                    BEGIN
                        IF EXISTS (
                            SELECT 1 FROM pg_class c
                            JOIN pg_namespace n ON n.oid = c.relnamespace
                            WHERE n.nspname = current_schema()
                              AND c.relname LIKE 'rick\\_%' ESCAPE '\\'
                              AND c.relname <> 'rick_schema_migrations'
                              AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
                        ) THEN
                            RAISE EXCEPTION 'RICK objects exist without migration history; inventory or restore is required';
                        END IF;
                    END $q24_history$;""")
                if applied.get("0004") == JOBS_CONTRACT_ORIGINAL:
                    assert repair_source is not None
                    messages.append(repair_historical_operation_guard(cursor, repair_source))
                else:
                    cursor.execute("""DO $q24_repairs$
                    BEGIN
                        IF to_regclass('rick_schema_migration_repairs') IS NOT NULL THEN
                            RAISE EXCEPTION 'migration repair history exists without its recognized source migration';
                        END IF;
                    END $q24_repairs$;""")
                if jobs_rewrite and "0005" in applied:
                    verify_jobs_rewrite(cursor, job_function_sources)
                for version, path, digest in rows:
                    if version in applied:
                        suffix = "already applied"
                        if compatible_checksum(version, path, digest, applied[version]):
                            suffix += " (recognized historical checksum retained)"
                        messages.append(f"{version} {path.name}: {suffix}")
                        continue
                    cursor.execute(statements[version])
                    if path.name == LEGACY_REWRITE_NAME:
                        # 0005 reconstructs jobs and their attempt rows together.
                        # Drain its two deferred integrity guards before later
                        # migrations ALTER the jobs table (PostgreSQL 55006).
                        # Keep the entire batch transactional and restore these
                        # guards' INITIALLY DEFERRED behavior for subsequent SQL.
                        guards = (
                            "rick_job_attempt_count_jobs_trg, "
                            "rick_job_attempt_count_attempts_trg"
                        )
                        cursor.execute(f"SET CONSTRAINTS {guards} IMMEDIATE")
                        cursor.execute(f"SET CONSTRAINTS {guards} DEFERRED")
                    cursor.execute(
                        "INSERT INTO rick_schema_migrations (version, checksum, application) VALUES (%s, %s, %s)",
                        (version, digest, APPLICATION),
                    )
                    messages.append(f"{version} {path.name}: applied")
                if jobs_rewrite and "0005" not in applied:
                    verify_jobs_rewrite(cursor, job_function_sources)
    except psycopg.Error as exc:
        # Driver diagnostics can include DSNs, SQL, payloads and identifiers.
        # SQLSTATE is sufficient to correlate the failure with protected DB logs.
        raise RuntimeError(
            f"database migration failed (SQLSTATE {exc.sqlstate or 'unavailable'}); "
            "no success confirmed; inspect history before retry"
        ) from None
    for message in messages:
        print(message)
    print("migration execution: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--database-url", default=os.environ.get("RICK_EXTERNAL_DATABASE_DSN"))
    args = parser.parse_args()
    if args.check == args.apply:
        parser.error("choose exactly one of --check or --apply")
    try:
        return check(args.directory) if args.check else apply(args.directory, args.database_url)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"migration: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
