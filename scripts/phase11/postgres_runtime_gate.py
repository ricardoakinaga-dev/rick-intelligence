#!/usr/bin/env python3
"""Run the real PostgreSQL migration and durable-queue runtime gate.

The gate is intentionally fail-closed.  It only accepts a loopback disposable
DSN by default, never discovers credentials, never uses a fake connection, and
returns ``BLOCKED_EXTERNAL`` when psycopg or the database is unavailable.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit
import uuid


ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "infrastructure/migrations"
DEFAULT_OUTPUT = ".runtime/phase-2/postgres-runtime-gate.json"
EXPECTED_MIGRATIONS = ("0001", "0002", "0003", "0004", "0005", "0006")
EXPECTED_CONSTRAINTS = {
    "rick_ingestion_jobs_contract_state_ck",
    "rick_ingestion_jobs_contract_payload_ck",
    "rick_ingestion_jobs_attempts_max_ck",
}
EXPECTED_INDEXES = {
    "rick_ingestion_jobs_idempotency_scope_idx",
    "rick_ingestion_jobs_contract_claim_idx",
    "rick_ingestion_jobs_contract_dead_idx",
}


@dataclass(frozen=True)
class GateResult:
    name: str
    result: str
    detail: str = ""

    def to_dict(self) -> dict[str, str]:
        payload = {"name": self.name, "result": self.result}
        if self.detail:
            payload["detail"] = self.detail
        return payload


def _safe_dsn(dsn: str, *, allow_nonlocal: bool) -> None:
    parsed = urlsplit(dsn)
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
        raise ValueError("database URL must be a PostgreSQL URL with a hostname")
    if not allow_nonlocal and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("refusing non-loopback database URL without explicit runtime authority")


def _run_migrations(dsn: str) -> GateResult:
    command = [
        sys.executable,
        str(ROOT / "infrastructure/scripts/migrate.py"),
        str(MIGRATIONS),
        "--apply",
        "--database-url",
        dsn,
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=180,
    )
    if completed.returncode != 0:
        return GateResult("migrations", "FAIL", "migration runner returned non-zero")
    return GateResult("migrations", "PASS")


def _query(cur: object, sql: str, params: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    cur.execute(sql, params)
    return list(cur.fetchall())


def _schema_checks(connection: object) -> list[GateResult]:
    results: list[GateResult] = []
    with connection.cursor() as cur:
        versions = [str(row[0]) for row in _query(
            cur,
            "SELECT version FROM rick_schema_migrations WHERE application=%s ORDER BY version",
            ("rick-intelligence",),
        )]
        results.append(
            GateResult(
                "migration-history",
                "PASS" if tuple(versions) == EXPECTED_MIGRATIONS else "FAIL",
                "six ordered migration records" if tuple(versions) == EXPECTED_MIGRATIONS else "migration history is incomplete or reordered",
            )
        )
        constraints = {
            str(row[0])
            for row in _query(
                cur,
                """
                SELECT conname
                FROM pg_constraint
                WHERE conrelid='rick_ingestion_jobs'::regclass
                """,
            )
        }
        missing_constraints = EXPECTED_CONSTRAINTS - constraints
        results.append(
            GateResult(
                "constraints",
                "PASS" if not missing_constraints else "FAIL",
                "all queue constraints present" if not missing_constraints else f"missing constraints: {sorted(missing_constraints)}",
            )
        )
        indexes = {
            str(row[0])
            for row in _query(
                cur,
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname='public' AND tablename='rick_ingestion_jobs'
                """,
            )
        }
        missing_indexes = EXPECTED_INDEXES - indexes
        results.append(
            GateResult(
                "indexes",
                "PASS" if not missing_indexes else "FAIL",
                "claim/idempotency/dead-letter indexes present" if not missing_indexes else f"missing indexes: {sorted(missing_indexes)}",
            )
        )
        try:
            _query(
                cur,
                """
                EXPLAIN (FORMAT JSON)
                SELECT job_id
                FROM rick_ingestion_jobs
                WHERE tenant_id=%s AND workspace_id=%s AND collection_id=%s
                  AND contract_state='QUEUED' AND available_at <= clock_timestamp()
                ORDER BY created_at, job_id
                LIMIT 1 FOR UPDATE SKIP LOCKED
                """,
                ("runtime-gate", "runtime-gate", "runtime-gate"),
            )
            plan_result = "PASS"
            plan_detail = "FOR UPDATE SKIP LOCKED query parsed and planned"
        except Exception:
            plan_result = "FAIL"
            plan_detail = "query plan for FOR UPDATE SKIP LOCKED failed"
        results.append(GateResult("query-plan-skip-locked", plan_result, plan_detail))
    return results


def _seed_scope(connection: object, run_id: str) -> tuple[str, str, str]:
    tenant = f"runtime-tenant-{run_id}"
    user = f"runtime-user-{run_id}"
    workspace = f"runtime-workspace-{run_id}"
    collection = f"runtime-collection-{run_id}"
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO rick_tenants (tenant_id, display_name) VALUES (%s,%s)",
            (tenant, "Runtime gate tenant"),
        )
        cur.execute(
            "INSERT INTO rick_users (user_id, external_subject, email) VALUES (%s,%s,%s)",
            (user, f"runtime-subject-{run_id}", f"runtime-{run_id}@invalid.example"),
        )
        cur.execute(
            """
            INSERT INTO rick_memberships (tenant_id, user_id, workspace_id, role)
            VALUES (%s,%s,%s,'VETERINARIAN')
            """,
            (tenant, user, workspace),
        )
        cur.execute(
            """
            INSERT INTO rick_collections
                (tenant_id, workspace_id, collection_id, title, created_by)
            VALUES (%s,%s,%s,%s,%s)
            """,
            (tenant, workspace, collection, "Runtime gate collection", user),
        )
    connection.commit()
    return tenant, workspace, collection


def _cleanup_scope(connection: object, scope: tuple[str, str, str], user_id: str) -> None:
    tenant, workspace, collection = scope
    with connection.cursor() as cur:
        cur.execute(
            "DELETE FROM rick_ingestion_jobs WHERE tenant_id=%s AND workspace_id=%s AND collection_id=%s",
            scope,
        )
        cur.execute(
            "DELETE FROM rick_collection_grants WHERE tenant_id=%s AND workspace_id=%s AND collection_id=%s",
            scope,
        )
        cur.execute(
            "DELETE FROM rick_collections WHERE tenant_id=%s AND workspace_id=%s AND collection_id=%s",
            scope,
        )
        cur.execute(
            "DELETE FROM rick_memberships WHERE tenant_id=%s AND workspace_id=%s AND user_id=%s",
            (tenant, workspace, user_id),
        )
        cur.execute("DELETE FROM rick_users WHERE user_id=%s", (user_id,))
        cur.execute("DELETE FROM rick_tenants WHERE tenant_id=%s", (tenant,))
    connection.commit()


def _queue_checks(psycopg: object, dsn: str, scope: tuple[str, str, str], run_id: str) -> list[GateResult]:
    sys.path[:0] = [
        str(ROOT / "apps/worker"),
        str(ROOT / "packages/jobs/src"),
        str(ROOT / "packages/observability/src"),
    ]
    from postgres_jobs import (
        PostgresJobLeaseError,
        PostgresJobQueue,
    )
    from rick_jobs import Job, JobFailure, JobResult, JobScope, WorkerId

    tenant, workspace, collection = scope
    job_scope = JobScope(tenant, workspace, collection)

    def factory() -> object:
        return psycopg.connect(dsn)

    queue_a = PostgresJobQueue(factory, lease_seconds=1.0, backoff_seconds=0.0)
    queue_b = PostgresJobQueue(factory, lease_seconds=1.0, backoff_seconds=0.0)
    now = time.time()

    def new_job(suffix: str) -> object:
        return Job.create(
            job_id=f"runtime-job-{suffix}-{run_id}",
            tenant_id=tenant,
            workspace_id=workspace,
            collection_id=collection,
            operation="runtime_gate",
            idempotency_key=f"runtime-key-{suffix}-{run_id}",
            payload={"source_ref": f"runtime:{run_id}:{suffix}"},
            now=now,
            max_attempts=3,
        )

    concurrent_jobs = (new_job("concurrent-a"), new_job("concurrent-b"))
    for concurrent_job in concurrent_jobs:
        queue_a.enqueue(concurrent_job, expected_version=0)

    def claim_one(queue: object, worker: str) -> tuple[object, object]:
        claimed = queue.claim(
            worker_id=WorkerId(worker),
            scope=job_scope,
            expected_versions={},
            limit=1,
            now=time.time(),
        )
        if len(claimed) != 1:
            raise RuntimeError("concurrent worker did not claim exactly one job")
        return claimed[0]

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(claim_one, queue_a, "worker-a")
        second = executor.submit(claim_one, queue_b, "worker-b")
        concurrent_claims = (first.result(), second.result())
    concurrent_ids = {str(item[0].job_id) for item in concurrent_claims}
    if len(concurrent_ids) != 2:
        raise RuntimeError("two workers claimed the same job")
    for queue, (_job, lease) in zip((queue_a, queue_b), concurrent_claims):
        queue.ack(
            lease,
            JobResult(output_refs={"runtime_ref": run_id}, completed_at=time.time()),
            now=time.time(),
            expected_version=_job.version,
        )
    results = [GateResult("multi-worker-concurrent-claim", "PASS")]

    job = new_job("stale")
    queued = queue_a.enqueue(job, expected_version=0)
    replay = queue_a.enqueue(job, expected_version=0)
    results.append(
        GateResult(
            "enqueue-idempotency",
            "PASS" if queued.job_id == replay.job_id and queued.state.value == "QUEUED" else "FAIL",
        )
    )
    claimed_a = queue_a.claim(worker_id=WorkerId("worker-a"), scope=job_scope, expected_versions={}, limit=1, now=time.time())
    if len(claimed_a) != 1:
        raise RuntimeError("worker A did not claim the fencing fixture")
    job_a, lease_a = claimed_a[0]
    results.append(GateResult("multi-worker-claim", "PASS"))

    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cur:
            cur.execute(
                "UPDATE rick_ingestion_jobs SET lease_until=clock_timestamp()-INTERVAL '1 second' WHERE job_id=%s",
                (str(job_a.job_id),),
            )
        connection.commit()
    reclaimed = queue_b.claim(worker_id=WorkerId("worker-b"), scope=job_scope, expected_versions={}, limit=1, now=time.time())
    if len(reclaimed) != 1:
        raise RuntimeError("expired lease was not reclaimed by worker B")
    job_b, lease_b = reclaimed[0]
    try:
        queue_a.ack(
            lease_a,
            JobResult(output_refs={"runtime_ref": run_id}, completed_at=time.time()),
            now=time.time(),
            expected_version=job_a.version,
        )
    except PostgresJobLeaseError:
        results.append(GateResult("stale-worker-ack", "PASS"))
    else:
        results.append(GateResult("stale-worker-ack", "FAIL", "stale worker acknowledged after lease fencing"))

    dead_failure = JobFailure(
        code="runtime_gate_failure",
        message="intentional runtime gate dead-letter fixture",
        retryable=False,
        attempt=job_b.attempt_count,
        occurred_at=time.time(),
    )
    dead = queue_b.fail(lease_b, dead_failure, now=time.time(), expected_version=job_b.version)
    results.append(GateResult("dead-letter", "PASS" if dead.state.value == "DEAD_LETTER" else "FAIL"))
    replayed = queue_b.replay_dead_letter(
        dead.job_id,
        tenant_id=tenant,
        workspace_id=workspace,
        collection_id=collection,
        replay_job_id=f"runtime-replay-{run_id}",
        replay_idempotency_key=f"runtime-replay-key-{run_id}",
        now=time.time(),
        expected_version=dead.version,
    )
    results.append(GateResult("dead-letter-replay", "PASS" if replayed.state.value == "QUEUED" else "FAIL"))
    replay_claim = queue_a.claim(worker_id=WorkerId("worker-a"), scope=job_scope, expected_versions={}, limit=1, now=time.time())
    if len(replay_claim) != 1:
        raise RuntimeError("replayed job was not claimable")
    replay_job, replay_lease = replay_claim[0]
    completed = queue_a.ack(
        replay_lease,
        JobResult(output_refs={"runtime_ref": run_id}, completed_at=time.time()),
        now=time.time(),
        expected_version=replay_job.version,
    )
    results.append(GateResult("ack-transaction", "PASS" if completed.state.value == "SUCCEEDED" else "FAIL"))
    removed = queue_a.prune_terminal(scope=job_scope, older_than=time.time() + 60, limit=100)
    results.append(GateResult("retention", "PASS" if removed >= 2 else "FAIL", f"removed={removed}"))
    return results


def run_gate(dsn: str, *, allow_nonlocal: bool = False) -> tuple[str, list[GateResult]]:
    _safe_dsn(dsn, allow_nonlocal=allow_nonlocal)
    try:
        import psycopg
    except ImportError:
        return "BLOCKED_EXTERNAL", [GateResult("driver", "BLOCKED_EXTERNAL", "psycopg is not installed")]

    migration = _run_migrations(dsn)
    if migration.result != "PASS":
        return "FAIL", [migration]
    connection = None
    scope: tuple[str, str, str] | None = None
    user_id: str | None = None
    run_id = uuid.uuid4().hex[:12]
    results: list[GateResult] = [migration]
    try:
        connection = psycopg.connect(dsn)
        results.extend(_schema_checks(connection))
        scope = _seed_scope(connection, run_id)
        user_id = f"runtime-user-{run_id}"
        results.extend(_queue_checks(psycopg, dsn, scope, run_id))
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
            if cur.fetchone() != (1,):
                raise RuntimeError("PostgreSQL health query returned an unexpected result")
        results.append(GateResult("health", "PASS"))
    except Exception:
        results.append(GateResult("runtime", "FAIL", "live PostgreSQL runtime assertion failed"))
    finally:
        if connection is not None and scope is not None and user_id is not None:
            try:
                _cleanup_scope(connection, scope, user_id)
            except Exception:
                results.append(GateResult("cleanup", "FAIL", "runtime fixture cleanup failed"))
        if connection is not None:
            connection.close()
    status = "PASS" if all(item.result == "PASS" for item in results) else "FAIL"
    return status, results


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.environ.get("RICK_TEST_DATABASE_DSN", ""))
    parser.add_argument("--allow-nonlocal", action="store_true", help="require explicit authority for a non-loopback DSN")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    if not args.database_url.strip():
        status = "BLOCKED_EXTERNAL"
        results = [GateResult("database", status, "RICK_TEST_DATABASE_DSN or --database-url is required")]
    else:
        try:
            status, results = run_gate(args.database_url, allow_nonlocal=args.allow_nonlocal)
        except ValueError as exc:
            status = "FAIL"
            results = [GateResult("configuration", status, str(exc))]
    payload = {
        "schema_version": "phase-2-postgres-runtime-gate.v1",
        "status": status,
        "results": [item.to_dict() for item in results],
        "runtime_claim": status == "PASS",
    }
    output = (ROOT / args.output).resolve()
    output.relative_to(ROOT.resolve())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": args.output, "status": status}, sort_keys=True))
    return 0 if status == "PASS" else (2 if status == "BLOCKED_EXTERNAL" else 1)


if __name__ == "__main__":
    raise SystemExit(main())
