#!/usr/bin/env python3
"""Real crash-before/after-commit harness for the PostgreSQL runtime gate.

The parent seeds a disposable scope and spawns two child processes that insert
one queue row and terminate with os._exit:
- before-commit: the row must not survive the severed connection;
- after-commit: the committed row must survive and be visible.

This is intentionally a process crash, not a mocked rollback. The parent emits
the JSON keys expected by RICK_POSTGRES_CRASH_HARNESS.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "phase11"))


def _connect(dsn: str):
    import psycopg
    return psycopg.connect(dsn)


def _insert(connection, *, scope: tuple[str, str, str], job_id: str, run_id: str) -> None:
    tenant, workspace, collection = scope
    with connection.cursor() as cur:
        cur.execute(
            """
            INSERT INTO rick_ingestion_jobs
                (job_id, idempotency_key, tenant_id, workspace_id, collection_id,
                 status, contract_state, operation)
            VALUES (%s, %s, %s, %s, %s, 'queued', 'QUEUED', 'runtime_crash')
            """,
            (job_id, f"crash-key-{job_id}", tenant, workspace, collection),
        )


def _count(dsn: str, job_id: str) -> int:
    connection = _connect(dsn)
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM rick_ingestion_jobs WHERE job_id=%s", (job_id,))
            row = cur.fetchone()
            return int(row[0]) if row else 0
    finally:
        connection.close()


def _child(args: argparse.Namespace) -> int:
    connection = _connect(args.dsn)
    scope = (args.tenant, args.workspace, args.collection)
    _insert(connection, scope=scope, job_id=args.job_id, run_id=args.run_id)
    if args.case == "after-commit":
        connection.commit()
    # Sever the process without cleanup; the server must roll back an
    # uncommitted transaction and retain a committed one.
    os._exit(17)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--case", choices=("before-commit", "after-commit"))
    parser.add_argument("--dsn")
    parser.add_argument("--tenant")
    parser.add_argument("--workspace")
    parser.add_argument("--collection")
    parser.add_argument("--job-id")
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    if args.child:
        return _child(args)

    dsn = os.environ.get("RICK_POSTGRES_DSN", "").strip()
    run_id = os.environ.get("RICK_POSTGRES_RUN_ID", "crashtest").strip() or "crashtest"
    if not dsn:
        print(json.dumps({"error": "RICK_POSTGRES_DSN is required"}))
        return 2
    from postgres_runtime_gate import _cleanup_scope, _seed_scope

    scope_run_id = f"{run_id}-crash"
    connection = _connect(dsn)
    try:
        scope = _seed_scope(connection, scope_run_id)
    finally:
        connection.close()
    tenant, workspace, collection = scope
    results: dict[str, str] = {}
    for case in ("before-commit", "after-commit"):
        job_id = f"crash-{case}-{run_id}"
        child = subprocess.run(
            [
                sys.executable, str(Path(__file__).resolve()), "--child",
                "--case", case, "--dsn", dsn,
                "--tenant", tenant, "--workspace", workspace, "--collection", collection,
                "--job-id", job_id, "--run-id", run_id,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        present = _count(dsn, job_id) > 0
        expected = case == "after-commit"
        results[f"crash-{case}"] = "PASS" if child.returncode == 17 and present == expected else "FAIL"
        debug_path = os.environ.get("RICK_CRASH_DEBUG", "").strip()
        if debug_path:
            try:
                with open(debug_path, "a", encoding="utf-8") as handle:
                    handle.write(f"{case} rc={child.returncode} present={present} expected={expected} stderr={child.stderr[-300:]!r}\n")
            except OSError:
                pass
    # Cleanup the fixture rows; the surrounding gate removes the scope.
    connection = _connect(dsn)
    try:
        with connection.cursor() as cur:
            cur.execute("DELETE FROM rick_ingestion_jobs WHERE job_id LIKE %s", (f"crash-%-{run_id}",))
        connection.commit()
        _cleanup_scope(connection, scope, f"runtime-user-{scope_run_id}")
    finally:
        connection.close()
    print(json.dumps(results, sort_keys=True))
    return 0 if all(value == "PASS" for value in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
