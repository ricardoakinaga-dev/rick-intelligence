#!/usr/bin/env python3
"""Run the real two-process worker fencing and crash-recovery gate.

The gate uses the canonical PostgreSQL queue against an explicitly supplied
database. It never substitutes an in-memory queue or a fake driver: missing
runtime authority is reported as ``BLOCKED_EXTERNAL``.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import multiprocessing as multiprocessing_module
import os
from pathlib import Path
import sys
import time
from typing import Any
import uuid

try:
    from scripts.phase11 import postgres_runtime_gate
except ImportError:  # pragma: no cover - direct script execution fallback.
    import postgres_runtime_gate


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ".runtime/phase-3/multi-worker-runtime-gate.json"
LEASE_SECONDS = 0.75
WORKER_WAIT_SECONDS = 30
PROCESS_JOIN_SECONDS = 10
CRASH_POINTS = (
    "after_claim", "after_heartbeat", "during_handler", "before_result",
    "in_transaction", "after_commit", "before_publish", "after_publish",
)
# The full matrix is executable through explicit runtime and canonical queue
# fault seams. ``production_safe`` still requires every point to finish with a
# real external database run; local tests never promote that claim.
SUPPORTED_CRASH_POINTS = CRASH_POINTS


@dataclass(frozen=True)
class GateResult:
    name: str
    result: str
    detail: str = ""

    def to_dict(self) -> dict[str, str]:
        value = {"name": self.name, "result": self.result}
        if self.detail:
            value["detail"] = self.detail
        return value


def _runtime_dependencies() -> tuple[Any, ...] | None:
    try:
        import psycopg
    except ImportError:
        return None
    sys.path[:0] = [
        str(ROOT / "apps/worker"),
        str(ROOT / "packages/jobs/src"),
        str(ROOT / "packages/observability/src"),
    ]
    try:
        from postgres_jobs import PostgresJobLeaseError, PostgresJobQueue
        from rick_jobs import Job, JobId, JobLease, JobResult, JobScope, LeaseToken, WorkerId
        from runtime import RealWorkerRuntime  # Verify the real execution dependency too.
    except ImportError:
        return None
    return (
        psycopg,
        PostgresJobLeaseError,
        PostgresJobQueue,
        Job,
        JobId,
        JobLease,
        JobResult,
        JobScope,
        LeaseToken,
        WorkerId,
    )


def _queue_for(
    dsn: str,
    dependencies: tuple[Any, ...],
    *,
    fault_injector: Any | None = None,
) -> Any:
    psycopg, _lease_error, queue_type = dependencies[:3]
    return queue_type(
        lambda: psycopg.connect(dsn),
        lease_seconds=LEASE_SECONDS,
        backoff_seconds=0.0,
        fault_injector=fault_injector,
    )


def _send(channel: Any, value: dict[str, object]) -> None:
    try:
        channel.send(value)
    except (BrokenPipeError, EOFError, OSError):
        pass


def _run_runtime_cycle(queue: Any, scope: Any, job_id: str, worker_id: str, result_type: Any) -> dict[str, object]:
    """Execute a real handler, requiring a runtime-owned heartbeat before ACK.

    The handler publishes only a metadata result. PostgreSQL remains the
    authority for lease ownership and the transactional acknowledgement.
    """

    from runtime import RealWorkerRuntime

    def handler(job: Any, _lease: Any, *, cancelled: Any) -> Any:
        if str(job.job_id) != job_id:
            raise RuntimeError("worker claimed an unexpected fixture")
        deadline = time.monotonic() + WORKER_WAIT_SECONDS / 2
        while runtime.metrics().heartbeats < 1:
            cancelled.checkpoint()
            if time.monotonic() >= deadline:
                raise RuntimeError("runtime heartbeat was not observed")
            time.sleep(0.01)
        return result_type(
            output_refs={"publication_ref": f"runtime-publication:{job_id}"},
            completed_at=time.time(),
        )

    runtime = RealWorkerRuntime(
        queue,
        worker_id=worker_id,
        scope=scope,
        handlers={"runtime_multi_worker": handler},
        max_concurrency=1,
        heartbeat_interval_seconds=LEASE_SECONDS / 3,
        poll_interval_seconds=0.01,
        handler_timeout_seconds=WORKER_WAIT_SECONDS / 2,
        shutdown_timeout_seconds=2.0,
    )
    try:
        runtime.start()
        result = runtime.run_once(wait=True)
        metrics = runtime.metrics()
        if result.queue_errors or result.failed or result.lease_lost or result.timed_out:
            raise RuntimeError("canonical worker execution failed")
        return {
            "kind": "completed",
            "worker_id": worker_id,
            "pid": os.getpid(),
            "claimed": result.claimed == 1,
            "heartbeat": metrics.heartbeats > 0,
            "acked": result.succeeded == 1,
            "runtime": "RealWorkerRuntime",
        }
    finally:
        stopped = runtime.shutdown(timeout=2.0)
        if not stopped.drained:
            raise RuntimeError("canonical worker did not drain")


def _claim_and_ack_worker(
    dsn: str,
    scope_values: tuple[str, str, str],
    job_id: str,
    worker_id: str,
    ready: Any,
    channel: Any,
) -> None:
    """Run the canonical claim/handler/heartbeat/ACK cycle in one process."""

    try:
        dependencies = _runtime_dependencies()
        if dependencies is None:
            _send(channel, {"kind": "error", "error": "runtime_driver_unavailable"})
            return
        _psycopg, _lease_error, _queue_type, _job_type, _job_id_type, _lease_type, result_type, scope_type, _token_type, worker_type = dependencies
        if not ready.wait(WORKER_WAIT_SECONDS):
            _send(channel, {"kind": "error", "error": "worker_start_barrier_timeout"})
            return
        queue = _queue_for(dsn, dependencies)
        scope = scope_type(*scope_values)
        _send(channel, _run_runtime_cycle(queue, scope, job_id, worker_id, result_type))
    except Exception as exc:  # pragma: no cover - exercised by a live dependency.
        _send(channel, {"kind": "error", "error": type(exc).__name__})
    finally:
        try:
            channel.close()
        except (AttributeError, OSError):
            pass


class _ObservedHeartbeatQueue:
    """Observe the real renewed lease without replacing any queue operation."""

    def __init__(self, queue: Any) -> None:
        self.queue = queue
        self.renewed_lease: Any = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self.queue, name)

    def heartbeat(self, *args: Any, **kwargs: Any) -> Any:
        renewed = self.queue.heartbeat(*args, **kwargs)
        self.renewed_lease = renewed
        return renewed


def _run_crash_cycle(
    queue: Any,
    scope: Any,
    worker_id: str,
    channel: Any,
    crash_point: str,
    result_type: Any | None = None,
) -> None:
    """Terminate a real runtime at one explicit matrix boundary.

    Handler boundaries are injected by ``RealWorkerRuntime`` and transaction
    boundaries by ``PostgresJobQueue``. The callback is only supplied by this
    gate process; normal workers have no enabled crash injector.
    """

    from runtime import RealWorkerRuntime
    if result_type is None:
        from rick_jobs import JobResult as result_type

    if crash_point not in SUPPORTED_CRASH_POINTS:
        raise ValueError("unsupported crash point")
    observed = _ObservedHeartbeatQueue(queue)
    claim: dict[str, Any] = {"job": None, "lease": None}
    sent = False

    def send_claim(job: Any, lease: Any) -> None:
        nonlocal sent
        if sent:
            return
        sent = True
        claim["job"] = job
        claim["lease"] = lease
        # Lease credentials cross only the private parent pipe for the stale
        # mutation negative. They are never included in the evidence artifact.
        _send(channel, {
            "kind": "claimed", "pid": os.getpid(), "worker_id": worker_id,
            "job_id": str(job.job_id), "version": job.version,
            "token": str(lease.token), "acquired_at": lease.acquired_at,
            "expires_at": lease.expires_at, "heartbeat_at": lease.heartbeat_at,
            "runtime": "RealWorkerRuntime", "crash_point": crash_point,
        })

    def terminate() -> None:
        if claim["job"] is not None and claim["lease"] is not None:
            send_claim(claim["job"], claim["lease"])
        try:
            channel.close()
        except (AttributeError, OSError):
            pass
        os._exit(0)

    def runtime_fault(point: str, job: Any, lease: Any) -> None:
        if point == crash_point:
            send_claim(job, lease)
            terminate()

    def handler(job: Any, lease: Any, *, cancelled: Any) -> Any:
        claim["job"] = job
        claim["lease"] = lease
        if crash_point == "after_heartbeat":
            deadline = time.monotonic() + WORKER_WAIT_SECONDS / 2
            while runtime.metrics().heartbeats < 1:
                cancelled.checkpoint()
                if time.monotonic() >= deadline:
                    raise RuntimeError("runtime heartbeat was not observed")
                time.sleep(0.01)
            lease = observed.renewed_lease
            claim["lease"] = lease
        if crash_point in {"after_claim", "after_heartbeat"}:
            send_claim(job, lease)
            terminate()
        # Publish the private observation before result finalization. For
        # transaction points the queue callback terminates after this handler
        # returns, while ``before_result`` terminates in the runtime itself.
        send_claim(job, lease)
        return result_type(
            output_refs={"publication_ref": f"runtime-publication:{job.job_id}"},
            completed_at=time.time(),
        )

    runtime = RealWorkerRuntime(
        observed, worker_id=worker_id, scope=scope,
        handlers={"runtime_multi_worker": handler}, max_concurrency=1,
        heartbeat_interval_seconds=LEASE_SECONDS / 3,
        poll_interval_seconds=0.01, handler_timeout_seconds=WORKER_WAIT_SECONDS / 2,
        shutdown_timeout_seconds=2.0, fault_injector=runtime_fault,
    )
    try:
        runtime.start()
        runtime.run_once(wait=True)
        raise RuntimeError("crash worker did not terminate at the requested point")
    finally:
        # Reached only when setup fails or a hermetic test replaces os._exit.
        runtime.shutdown(timeout=2.0)


def _crash_after_claim_worker(
    dsn: str,
    scope_values: tuple[str, str, str],
    worker_id: str,
    ready: Any,
    channel: Any,
    crash_point: str = "after_claim",
) -> None:
    """Launch a real runtime and terminate before ACK at the requested point."""

    try:
        dependencies = _runtime_dependencies()
        if dependencies is None:
            _send(channel, {"kind": "error", "error": "runtime_driver_unavailable"})
            os._exit(1)
        _psycopg, _lease_error, _queue_type, _job_type, _job_id_type, _lease_type, _result_type, scope_type, _token_type, worker_type = dependencies
        if not ready.wait(WORKER_WAIT_SECONDS):
            _send(channel, {"kind": "error", "error": "worker_start_barrier_timeout"})
            os._exit(1)
        def queue_fault(point: str) -> None:
            if point != crash_point:
                return
            # The handler has sent the private lease observation before any
            # result transaction is entered. Abrupt exit forces PostgreSQL to
            # roll back all uncommitted writes for the three pre-commit points.
            try:
                channel.close()
            except (AttributeError, OSError):
                pass
            os._exit(0)

        queue = _queue_for(dsn, dependencies, fault_injector=queue_fault)
        scope = scope_type(*scope_values)
        _run_crash_cycle(queue, scope, worker_id, channel, crash_point, _result_type)
    except Exception as exc:  # pragma: no cover - exercised by a live dependency.
        _send(channel, {"kind": "error", "error": type(exc).__name__})
        os._exit(1)


def _receive(channel: Any, timeout: float) -> dict[str, object]:
    if not channel.poll(timeout):
        return {"kind": "error", "error": "worker_result_timeout"}
    try:
        value = channel.recv()
    except (EOFError, OSError):
        return {"kind": "error", "error": "worker_result_unreadable"}
    return value if isinstance(value, dict) else {"kind": "error", "error": "worker_result_invalid"}


def _finish_process(process: Any) -> None:
    process.join(PROCESS_JOIN_SECONDS)
    if process.is_alive():
        process.terminate()
        process.join(5)


def _new_job(dependencies: tuple[Any, ...], scope: tuple[str, str, str], job_id: str, run_id: str) -> Any:
    now = time.time()
    return dependencies[3].create(
        job_id=job_id,
        tenant_id=scope[0],
        workspace_id=scope[1],
        collection_id=scope[2],
        operation="runtime_multi_worker",
        idempotency_key=f"runtime-multi-worker:{run_id}:{job_id}",
        payload={"source_ref": f"runtime:{run_id}:{job_id}"},
        now=now,
        max_attempts=2,
    )


def _run_concurrent_claim(
    dsn: str,
    dependencies: tuple[Any, ...],
    scope: tuple[str, str, str],
    run_id: str,
) -> list[GateResult]:
    queue = _queue_for(dsn, dependencies)
    job_id = f"runtime-concurrent-{run_id}"
    queue.enqueue(_new_job(dependencies, scope, job_id, run_id), expected_version=0)
    context = multiprocessing_module.get_context("spawn")
    ready = context.Event()
    workers: list[Any] = []
    channels: list[Any] = []
    for worker_id in ("worker-a", "worker-b"):
        parent, child = context.Pipe(duplex=False)
        process = context.Process(
            target=_claim_and_ack_worker,
            args=(dsn, scope, job_id, worker_id, ready, child),
            name=f"rick-runtime-{worker_id}",
        )
        workers.append(process)
        channels.append(parent)
        process.start()
        child.close()
    ready.set()
    try:
        observations = [_receive(channel, WORKER_WAIT_SECONDS) for channel in channels]
    finally:
        for channel in channels:
            channel.close()
        for process in workers:
            _finish_process(process)
    if any(item.get("kind") == "error" for item in observations):
        raise RuntimeError("isolated worker process failed during concurrent claim")
    if any(item.get("runtime") != "RealWorkerRuntime" for item in observations):
        raise RuntimeError("isolated processes did not execute the canonical runtime")
    claimed = [item for item in observations if item.get("claimed") is True]
    if len(claimed) != 1 or sum(item.get("acked") is True for item in claimed) != 1:
        raise RuntimeError("two isolated workers did not produce exactly one owner and publication")
    if len({item.get("pid") for item in observations}) != 2:
        raise RuntimeError("worker observations did not come from two distinct processes")
    if claimed[0].get("heartbeat") is not True:
        raise RuntimeError("winning worker did not renew its lease")
    outbox_connection = dependencies[0].connect(dsn)
    try:
        with outbox_connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM rick_outbox "
                "WHERE aggregate_id=%s AND event_type='jobs.acknowledged'",
                (job_id,),
            )
            row = cursor.fetchone()
    finally:
        outbox_connection.close()
    if not row or int(row[0]) != 1:
        raise RuntimeError("concurrent claim produced more than one durable publication event")
    return [
        GateResult("PROCESS_ISOLATION", "PASS", "two distinct RealWorkerRuntime processes used independent database sessions"),
        GateResult("ONE_OWNER_CLAIM", "PASS", "exactly one worker claimed the queued job"),
        GateResult("HEARTBEAT_FENCING", "PASS", "the winning worker renewed its durable lease"),
        GateResult("SINGLE_PUBLICATION", "PASS", "the durable outbox contains exactly one publication event"),
        GateResult("PUBLICATION_OUTBOX_FENCE", "PASS", "the durable outbox contains one idempotent publication event"),
    ]


def _run_crash_recovery(
    dsn: str,
    dependencies: tuple[Any, ...],
    scope: tuple[str, str, str],
    run_id: str,
    crash_point: str = "after_claim",
) -> list[GateResult]:
    queue = _queue_for(dsn, dependencies)
    job_id = f"runtime-crash-{crash_point}-{run_id}"
    queue.enqueue(_new_job(dependencies, scope, job_id, run_id), expected_version=0)
    context = multiprocessing_module.get_context("spawn")
    ready = context.Event()
    parent, child = context.Pipe(duplex=False)
    crashed = context.Process(
        target=_crash_after_claim_worker,
        args=(dsn, scope, "worker-crash", ready, child, crash_point),
        name="rick-runtime-worker-crash",
    )
    crashed.start()
    child.close()
    ready.set()
    claim = _receive(parent, WORKER_WAIT_SECONDS)
    parent.close()
    _finish_process(crashed)
    if claim.get("kind") != "claimed" or crashed.exitcode != 0:
        raise RuntimeError("crash worker did not claim and terminate cleanly")
    if claim.get("runtime") != "RealWorkerRuntime" or claim.get("crash_point") != crash_point:
        raise RuntimeError("crash observation did not come from the requested runtime point")
    if crash_point == "after_heartbeat" and float(claim["heartbeat_at"]) <= float(claim["acquired_at"]):
        raise RuntimeError("crash worker did not observe a renewed lease")

    expires_at = float(claim["expires_at"])
    committed_result = crash_point == "after_commit"
    reclaimed: dict[str, object] | None = None
    if not committed_result:
        time.sleep(max(0.0, expires_at - time.time() + 0.25))
        reclaim_ready = context.Event()
        reclaim_parent, reclaim_child = context.Pipe(duplex=False)
        reclaimer = context.Process(
            target=_claim_and_ack_worker,
            args=(dsn, scope, job_id, "worker-reclaimer", reclaim_ready, reclaim_child),
            name="rick-runtime-worker-reclaimer",
        )
        reclaimer.start()
        reclaim_child.close()
        reclaim_ready.set()
        reclaimed = _receive(reclaim_parent, WORKER_WAIT_SECONDS)
        reclaim_parent.close()
        _finish_process(reclaimer)
        if reclaimed.get("kind") == "error" or reclaimed.get("claimed") is not True or reclaimed.get("acked") is not True:
            raise RuntimeError("a second worker did not reclaim and acknowledge the crashed job")

    psycopg, lease_error_type, _queue_type, _job_type, job_id_type, lease_type, result_type, scope_type, token_type, worker_type = dependencies
    stale_lease = lease_type(
        job_id=job_id_type(job_id),
        scope=scope_type(*scope),
        worker_id=worker_type("worker-crash"),
        token=token_type(str(claim["token"])),
        acquired_at=float(claim["acquired_at"]),
        expires_at=expires_at,
        heartbeat_at=float(claim["heartbeat_at"]),
    )
    try:
        queue.acknowledge(
            stale_lease,
            result_type(output_refs={"publication_ref": f"runtime-publication:{job_id}"}, completed_at=time.time()),
            now=time.time(),
            expected_version=int(claim["version"]),
        )
    except lease_error_type:
        stale_rejected = True
    else:
        stale_rejected = False
    if not stale_rejected:
        raise RuntimeError("stale crashed-worker ACK was accepted")

    final_job = queue.get(
        job_id_type(job_id),
        tenant_id=scope[0],
        workspace_id=scope[1],
        collection_id=scope[2],
    )
    if final_job is None or final_job.state.value != "SUCCEEDED":
        raise RuntimeError("crashed job did not finish successfully")
    expected_attempts = 1 if committed_result else 2
    if final_job.attempt_count != expected_attempts:
        raise RuntimeError("crash recovery produced an unexpected attempt count")
    if not final_job.attempts or final_job.attempts[-1].state.value != "SUCCEEDED":
        raise RuntimeError("crash recovery produced no successful final attempt")
    if committed_result:
        if final_job.attempts[0].state.value != "SUCCEEDED":
            raise RuntimeError("after-commit crash did not retain the committed attempt")
    elif (
        final_job.attempts[0].state.value != "FAILED"
        or final_job.attempts[0].failure is None
        or final_job.attempts[0].failure.code != "lease_expired"
    ):
        raise RuntimeError("reclaimed crash did not record the expired first attempt")
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM rick_ingestion_job_events "
                "WHERE job_id=%s AND event_type='acknowledged'",
                (job_id,),
            )
            lifecycle_row = cursor.fetchone()
            cursor.execute(
                "SELECT COUNT(*) FROM rick_outbox "
                "WHERE aggregate_id=%s AND event_type='jobs.acknowledged'",
                (job_id,),
            )
            outbox_row = cursor.fetchone()
            cursor.execute(
                "SELECT COUNT(*) FROM rick_audit_events "
                "WHERE target_id=%s AND action='jobs.acknowledged'",
                (job_id,),
            )
            audit_row = cursor.fetchone()
            cursor.execute(
                "SELECT lease_owner, lease_until FROM rick_ingestion_jobs WHERE job_id=%s",
                (job_id,),
            )
            lease_row = cursor.fetchone()
    if not lifecycle_row or int(lifecycle_row[0]) != 1:
        raise RuntimeError("crash recovery produced an unexpected lifecycle publication count")
    if not outbox_row or int(outbox_row[0]) != 1:
        raise RuntimeError("crash recovery produced an unexpected durable publication count")
    if not audit_row or int(audit_row[0]) != 1:
        raise RuntimeError("crash recovery produced an unexpected audit count")
    if not lease_row or lease_row[0] is not None or lease_row[1] is not None:
        raise RuntimeError("successful crash recovery retained a durable lease")
    recovery_detail = (
        "real worker terminated after the result transaction committed; durable state, attempt, audit and outbox were retained"
        if committed_result
        else "real worker terminated before result commit; lease expiry reclaimed the job with one durable publication"
    )
    return [
        GateResult(f"CRASH_{crash_point.upper()}", "PASS", recovery_detail),
        GateResult(
            "LEASE_RECLAIM_AFTER_EXPIRY",
            "PASS",
            "a second process reclaimed the expired durable lease"
            if not committed_result
            else "no reclaim was required because the result transaction was already durable",
        ),
        GateResult("STALE_WORKER_ACK_REJECTED", "PASS", "the crashed worker's stale lease could not acknowledge after the terminal mutation"),
        GateResult("STALE_WORKER_PUBLISH_REJECTED", "PASS", "the stale worker attempt left the durable outbox publication count unchanged"),
        GateResult("CRASH_RECOVERY_SUCCEEDS", "PASS", "state, lease, attempt, audit and outbox invariants held after recovery"),
        GateResult("DUPLICATE_PUBLICATION_REJECTED", "PASS", "crash recovery retained exactly one durable publication event"),
    ]


def run_gate(dsn: str, *, allow_nonlocal: bool = False) -> tuple[str, list[GateResult]]:
    postgres_runtime_gate._safe_dsn(dsn, allow_nonlocal=allow_nonlocal)
    dependencies = _runtime_dependencies()
    if dependencies is None:
        return "BLOCKED_EXTERNAL", [GateResult("driver", "BLOCKED_EXTERNAL", "psycopg and canonical worker packages are required")]

    migration = postgres_runtime_gate._run_migrations(dsn)
    results = [GateResult("migrations", migration.result, migration.detail)]
    if migration.result != "PASS":
        return "FAIL", results

    psycopg = dependencies[0]
    connection: Any | None = None
    scope: tuple[str, str, str] | None = None
    run_id = uuid.uuid4().hex[:12]
    try:
        connection = psycopg.connect(dsn)
        scope = postgres_runtime_gate._seed_scope(connection, run_id)
        results.extend(_run_concurrent_claim(dsn, dependencies, scope, run_id))
        for crash_point in SUPPORTED_CRASH_POINTS:
            case_results = _run_crash_recovery(dsn, dependencies, scope, run_id, crash_point)
            # Keep common case names once, while preserving separate point
            # evidence; every invocation must succeed before either is accepted.
            existing = {result.name for result in results}
            results.extend(result for result in case_results if result.name not in existing)
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            if cursor.fetchone() != (1,):
                raise RuntimeError("PostgreSQL health query returned an unexpected result")
        results.append(GateResult("health", "PASS"))
    except Exception:
        results.append(GateResult("runtime", "FAIL", "two-process worker fencing assertion failed"))
    finally:
        if connection is not None and scope is not None:
            try:
                postgres_runtime_gate._cleanup_scope(connection, scope, f"runtime-user-{run_id}")
            except Exception:
                results.append(GateResult("cleanup", "FAIL", "runtime fixture cleanup failed"))
        if connection is not None:
            connection.close()
    status = "PASS" if all(item.result == "PASS" for item in results) else "FAIL"
    return status, results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.environ.get("RICK_TEST_DATABASE_DSN", ""))
    parser.add_argument("--allow-nonlocal", action="store_true")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if not args.database_url.strip():
        status = "BLOCKED_EXTERNAL"
        results = [GateResult("database", status, "RICK_TEST_DATABASE_DSN or --database-url is required")]
    else:
        try:
            status, results = run_gate(args.database_url, allow_nonlocal=args.allow_nonlocal)
        except ValueError as exc:
            status = "FAIL"
            results = [GateResult("configuration", status, str(exc))]
    crash_matrix = {
        point: "PASS" if any(result.name == f"CRASH_{point.upper()}" and result.result == "PASS" for result in results)
        else "NOT_RUN" if point in SUPPORTED_CRASH_POINTS else "NOT_IMPLEMENTED"
        for point in CRASH_POINTS
    }
    payload = {
        "schema_version": "phase3-multi-worker-runtime-gate.v1",
        "status": status,
        "results": [item.to_dict() for item in results],
        "runtime_claim": status == "PASS",
        "production_safe": status == "PASS" and all(value == "PASS" for value in crash_matrix.values()),
        "crash_matrix": crash_matrix,
        "crash_matrix_complete": all(value == "PASS" for value in crash_matrix.values()),
    }
    output = (ROOT / args.output).resolve()
    output.relative_to(ROOT.resolve())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": args.output, "status": status}, sort_keys=True))
    return 0 if status == "PASS" else (2 if status == "BLOCKED_EXTERNAL" else 1)


if __name__ == "__main__":
    raise SystemExit(main())
