#!/usr/bin/env python3
"""Fail-closed Postgres migration runner with offline checksum mode.

``--check`` never opens a database connection. Applying migrations requires an
explicit DSN and the optional psycopg driver; every file is applied in one
transaction under a PostgreSQL advisory lock. There is intentionally no
automatic destructive rollback.
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import sys


MIGRATION_NAME = re.compile(r"^(\d{4})_[a-z0-9][a-z0-9_-]*\.sql$")
APPLICATION = "rick-intelligence"


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
        rows.append((version, path, digest))
    if not rows:
        raise ValueError("no migration files found")
    return rows


def check(directory: Path) -> int:
    rows = migration_files(directory)
    for version, path, digest in rows:
        print(f"{version} {path.name} sha256:{digest}")
    print(f"migration checksums: PASS ({len(rows)} file(s)); execution: NOT_RUN")
    return 0


def apply(directory: Path, dsn: str) -> int:
    if not isinstance(dsn, str) or not dsn.strip():
        raise ValueError("--database-url is required for apply")
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("psycopg is required only for live migration execution") from exc
    rows = migration_files(directory)
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """CREATE TABLE IF NOT EXISTS rick_schema_migrations (
                   version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                   checksum TEXT NOT NULL, application TEXT NOT NULL)"""
            )
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("rick-intelligence:migrations",))
            cursor.execute(
                "SELECT version, checksum, application "
                "FROM rick_schema_migrations ORDER BY version"
            )
            applied_rows = cursor.fetchall()
            applied: dict[str, tuple[str, str]] = {}
            for applied_row in applied_rows:
                if len(applied_row) < 3:
                    raise RuntimeError("migration history row is malformed")
                applied_version, applied_checksum, application = applied_row[:3]
                if application != APPLICATION:
                    raise RuntimeError(
                        f"migration history application mismatch for {applied_version}"
                    )
                if applied_version in applied:
                    raise RuntimeError(f"duplicate migration history version {applied_version}")
                applied[applied_version] = (applied_checksum, application)
            local_versions = {version for version, _path, _digest in rows}
            unknown = sorted(set(applied) - local_versions)
            if unknown:
                raise RuntimeError(
                    "migration history contains unknown version(s): " + ", ".join(unknown)
                )
            ordered_versions = [version for version, _path, _digest in rows]
            if applied:
                highest_applied = max(applied)
                missing_prior = [
                    version
                    for version in ordered_versions
                    if version <= highest_applied and version not in applied
                ]
                if missing_prior:
                    raise RuntimeError(
                        "migration history has a gap before "
                        f"{highest_applied}: {', '.join(missing_prior)}"
                    )
            for version, path, digest in rows:
                current = applied.get(version)
                if current and current[0] != digest:
                    raise RuntimeError(f"checksum mismatch for migration {version}")
                if current:
                    print(f"{version} {path.name}: already applied")
                    continue
                cursor.execute(path.read_text(encoding="utf-8"))
                cursor.execute(
                    "INSERT INTO rick_schema_migrations (version, checksum, application) VALUES (%s, %s, %s)",
                    (version, digest, APPLICATION),
                )
                print(f"{version} {path.name}: applied")
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
