#!/usr/bin/env python3
"""Bounded native lab performance/soak observations; never production approval.

Every latency is measured around actual HTTP or durable job completion. The
provider is the explicit local citation fixture. Local budgets and short soak
windows are disclosed; no production workload or SLO authority is inferred.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import secrets
import signal
import sys
from threading import Event, Thread
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.phase11.formal_lab_resources import LabResources, publish
from scripts.state_of_art.phase3_lane import PERFORMANCE_CONCURRENCY_LEVELS, PERFORMANCE_WORKLOADS

QUERY = "como funcionam as citacoes no rick"
CONTENT = "Segundo a fonte autorizada, o documento confirma o laboratório local. As citações no RICK preservam fontes verificadas."


def percentile(values, quantile):
    if not values or not 0 <= quantile <= 1 or any(not math.isfinite(x) or x < 0 for x in values):
        raise ValueError("invalid_latency_samples")
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def process_sample(pids):
    """Sample only owned processes and their current descendants, never the host."""
    pending, seen = list(pids), set()
    totals = dict(memory_bytes=0, threads=0, processes=0, connections=0, file_descriptors=0, cpu_seconds=0.)
    while pending:
        pid = pending.pop()
        if pid in seen:
            continue
        seen.add(pid)
        base = Path("/proc") / str(pid)
        try:
            # comm can contain spaces; fields following the final ')' start
            # with state (field 3), hence utime/stime are offsets 11/12.
            stat = (base / "stat").read_text().rsplit(")", 1)[1].split()
            status = dict(line.split(":", 1) for line in (base / "status").read_text().splitlines() if ":" in line)
            fds = list((base / "fd").iterdir())
            sockets = 0
            for fd in fds:
                try:
                    sockets += os.readlink(fd).startswith("socket:")
                except OSError:
                    pass
            for task in (base / "task").iterdir():
                try:
                    pending.extend(int(value) for value in (task / "children").read_text().split())
                except OSError:
                    pass
            totals["memory_bytes"] += int(status.get("VmRSS", "0 kB").split()[0]) * 1024
            totals["threads"] += int(status.get("Threads", "0"))
            totals["processes"] += 1
            totals["connections"] += sockets
            totals["file_descriptors"] += len(fds)
            totals["cpu_seconds"] += sum(int(stat[index]) for index in (11, 12, 13, 14)) / os.sysconf("SC_CLK_TCK")
        except (OSError, ValueError, IndexError):
            continue
    if totals["processes"] == 0:
        raise ValueError("owned_process_measurements_unavailable")
    return totals


class Sampler:
    def __init__(self, pids):
        self.pids, self.samples = pids, []
        self.stopped = Event()

    def __enter__(self):
        self.started = time.monotonic()
        self.initial = process_sample(self.pids)
        self.samples.append(self.initial)
        def collect():
            while not self.stopped.wait(.05):
                try:
                    self.samples.append(process_sample(self.pids))
                except ValueError:
                    pass
        self.thread = Thread(target=collect, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.stopped.set()
        self.thread.join(2)
        self.elapsed = time.monotonic() - self.started
        self.final = process_sample(self.pids)
        self.samples.append(self.final)

    def metrics(self):
        return {"cpu_percent": max(0., (self.final["cpu_seconds"] - self.initial["cpu_seconds"]) / max(.001, self.elapsed) * 100),
                "ram_bytes": max(sample["memory_bytes"] for sample in self.samples),
                "resource_sample_count": len(self.samples)}


class NativeLab:
    def __init__(self, run_id, *, api_replicas=8, workers=4, web_origin=None, environment_overrides=None):
        self.owner = LabResources(run_id, environment_overrides=environment_overrides,
            isolated_postgres=not environment_overrides or "RICK_EXTERNAL_DATABASE_DSN" not in environment_overrides)
        # Explicit capacity fixture configuration, scoped to owned children.
        # Admission/rate limits in the shared dev stack are not changed.
        os.environ.update(CHAT_RATE_LIMIT_PER_MIN="100000", SEARCH_TENANT_RATE_LIMIT_PER_MIN="100000",
                          INGESTION_MAX_PENDING_JOBS="1024")
        if web_origin:
            from scripts.phase11.local_product_probe import local_target
            if not local_target(web_origin):
                raise ValueError("owned_web_requires_loopback_origin")
            os.environ["CORS_ALLOWED_ORIGINS"] = web_origin
        self.graph, self.scope, self.user = self.owner.graph()
        self.baseline = publish(self.graph, self.scope, key="operational-baseline", content=CONTENT.encode())
        if self.baseline.status != "published":
            raise ValueError("native_positive_control_not_published")
        password = secrets.token_urlsafe(24)
        self.login_password = password
        self.sessions, self.api_pids = [], []
        for index in range(api_replicas):
            self.sessions.append(self.owner.serve_api(self.graph, self.scope, self.user,
                password=password, provision=index == 0))
            self.api_pids.append(self.owner.processes[-1].pid)
        self.session = self.sessions[0]
        self.readiness_observations = []
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            response = self.session.get("/health/ready")
            self.readiness_observations.append({"status_code": response.status_code, "body": response.json()})
            if response.status_code == 200:
                break
            time.sleep(.1)
        else:
            raise ValueError("native_owned_api_not_ready")
        self.workers = [self.owner.start_worker(self.scope, self.user, continuous=True, duration_seconds=1800, max_concurrency=1)
                        for _ in range(workers)]
        self.worker = self.workers[0]

    @property
    def pids(self):
        return [os.getpid(), *self.api_pids, *(worker.pid for worker in self.workers)]

    def queue_facts(self):
        import psycopg
        with psycopg.connect(self.graph.settings.external_database_dsn, connect_timeout=5) as connection:
            rows = connection.execute("SELECT job_id,contract_state,attempts,document_id FROM rick_ingestion_jobs "
                "WHERE tenant_id=%s AND workspace_id=%s AND collection_id=%s", tuple(self.scope.values())).fetchall()
        return {str(row[0]): {"state": row[1], "attempts": row[2], "document_id": row[3]} for row in rows}

    def queue_depth(self):
        return sum(value["state"] in {"PENDING", "QUEUED", "RUNNING", "RETRYING"} for value in self.queue_facts().values())

    @contextmanager
    def paused_worker(self):
        if any(worker.poll() is not None for worker in self.workers):
            raise ValueError("owned_worker_not_running")
        stopped = []
        try:
            for worker in self.workers:
                os.killpg(worker.pid, signal.SIGSTOP)
                stopped.append(worker)
            yield
        finally:
            for worker in stopped:
                os.killpg(worker.pid, signal.SIGCONT)

    async def wait_job(self, job_id, *, timeout=120):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            # Coalesce diagnostic polling. One SQL snapshot per interval is
            # enough for every actor; opening a connection per waiting job
            # otherwise makes the observer itself exhaust PostgreSQL.
            if not hasattr(self, "_queue_snapshot_lock"):
                self._queue_snapshot_lock = asyncio.Lock()
                self._queue_snapshot_at = 0.
                self._queue_snapshot = {}
            async with self._queue_snapshot_lock:
                if time.monotonic() - self._queue_snapshot_at >= .15:
                    self._queue_snapshot = await asyncio.to_thread(self.queue_facts)
                    self._queue_snapshot_at = time.monotonic()
                facts = self._queue_snapshot
            row = facts.get(job_id)
            if row and row["state"] in {"SUCCEEDED", "FAILED", "CANCELLED", "DEAD_LETTER"}:
                if row["state"] != "SUCCEEDED" or not row["document_id"]:
                    raise ValueError("durable_job_not_successful")
                return row
            await asyncio.sleep(.15)
        raise TimeoutError("native_job_deadline")

    async def upload(self, client, key):
        response = await client.post("/api/v1/documents/upload", json={"filename": key + ".txt",
            "collection_id": self.scope["collection_id"], "content": CONTENT + " " + key,
            }, headers={"Idempotency-Key": key})
        if response.status_code != 202:
            try:
                code = response.json().get("error", {}).get("code", "invalid_response")
            except (ValueError, AttributeError):
                code = "invalid_response"
            code = re.sub("[^A-Za-z0-9_.-]", "_", str(code))[:64]
            raise ObservationFailure(f"upload_http_{response.status_code}_{code}")
        return response.json()["job_id"]

    async def operation(self, client, workload, key):
        if workload == "api-only":
            response = await client.get("/health/live")
            valid = response.status_code == 200
        elif workload == "retrieval":
            response = await client.post("/api/v1/search", json={"query": QUERY, **{
                name: value for name, value in self.scope.items() if name != "tenant_id"}})
            valid = response.status_code == 200 and response.json().get("total", 0) > 0
        elif workload == "chat":
            response = await client.post("/api/v1/chat", json={"message": QUERY, "conversation_id": key})
            body = response.json() if response.status_code == 200 else {}
            valid = (response.status_code == 200 and body.get("metadata", {}).get("publication_validation") == "verified"
                and body.get("metadata", {}).get("decision_action") == "ANSWER" and bool(body.get("citations")))
            if valid:
                response = await client.get("/api/v1/conversations/" + key)
                valid = response.status_code == 200 and response.json().get("total", 0) > 0
        else:
            job_id = await self.upload(client, key)
            return await self.wait_job(job_id)
        if not valid:
            try:
                error = response.json().get("error", {}).get("code", "unverified")
            except (ValueError, AttributeError):
                error = "invalid_json"
            code = re.sub("[^A-Za-z0-9_.-]", "_", str(error))[:64]
            raise ObservationFailure(f"http_{response.status_code}_{code}")

    async def retire_fixture(self, client, row):
        if row["document_id"] == self.baseline.document_id:
            raise ValueError("refusing_baseline_retirement")
        response = await client.delete("/api/v1/documents/" + row["document_id"])
        if response.status_code != 200:
            raise ObservationFailure(f"fixture_retirement_http_{response.status_code}")


class ObservationFailure(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


async def performance(lab, clients, run_id):
    client = clients[0]
    results, raw = [], []
    for workload in PERFORMANCE_WORKLOADS:
        for concurrency in PERFORMANCE_CONCURRENCY_LEVELS:
            # Two requests per configured concurrent actor. This is a bounded
            # fixture matrix, explicitly not a statistically mature benchmark.
            count = concurrency * 2
            latencies, errors = [], Counter()
            jobs = []
            if workload == "worker-throughput":
                with lab.paused_worker():
                    for index in range(count):
                        jobs.append(await lab.upload(client, f"queued-{run_id}-{concurrency}-{index}"))
                    initial_depth = await asyncio.to_thread(lab.queue_depth)
                    if initial_depth != count:
                        raise ValueError("worker_batch_not_fully_pending")
            else:
                initial_depth = await asyncio.to_thread(lab.queue_depth)
            semaphore = asyncio.Semaphore(concurrency)
            async def attempt(index):
                async with semaphore:
                    started = time.perf_counter()
                    try:
                        if workload == "worker-throughput":
                            await lab.wait_job(jobs[index])
                        else:
                            await lab.operation(clients[index % len(clients)], workload, f"{run_id}-{workload}-{concurrency}-{index}")
                    except Exception as error:
                        errors[getattr(error, "code", type(error).__name__)] += 1
                    finally:
                        latencies.append((time.perf_counter() - started) * 1000)
            with Sampler(lab.pids) as sampler:
                await asyncio.gather(*(attempt(index) for index in range(count)))
            depth = await asyncio.to_thread(lab.queue_depth)
            row = dict(workload=workload, concurrency=concurrency, samples=count,
                p50_ms=percentile(latencies, .50), p95_ms=percentile(latencies, .95), p99_ms=percentile(latencies, .99),
                throughput=(count - sum(errors.values())) / sampler.elapsed, error_rate=sum(errors.values()) / count,
                queue_depth=depth, initial_queue_depth=initial_depth, **sampler.metrics())
            results.append(row)
            raw.append({**row, "latencies_ms": latencies, "errors": dict(errors)})
            progress = ROOT / ".runtime/phase-3/operational-local" / run_id / "progress.json"
            progress.parent.mkdir(parents=True, exist_ok=True)
            progress.write_text(json.dumps({"observations": raw, "measurements": {"results": results}}, indent=2) + "\n")
    return {"results": results}, raw


async def soak(lab, client, run_id, durations):
    profiles, raw = [], []
    # Warm provider, worker, connection pools and parser before the baseline.
    await lab.operation(client, "chat", "warm-" + run_id)
    warm = await lab.operation(client, "ingestion", "warm-ingest-" + run_id)
    await lab.retire_fixture(client, warm)
    await asyncio.sleep(1)
    for profile, duration in zip(("short", "extended"), durations):
        before = process_sample(lab.pids)
        initial_depth = await asyncio.to_thread(lab.queue_depth)
        initial_facts = await asyncio.to_thread(lab.queue_facts)
        latencies, failures, cycles = [], [], 0
        started = time.monotonic()
        with Sampler(lab.pids) as sampler:
            while time.monotonic() - started < duration:
                tick = time.perf_counter()
                try:
                    await lab.operation(client, "chat", f"soak-{run_id}-{profile}-{cycles}")
                    if cycles % 3 == 0:
                        published = await lab.operation(client, "ingestion", f"soak-ingest-{run_id}-{profile}-{cycles}")
                        await lab.retire_fixture(client, published)
                except Exception as error:
                    failures.append(type(error).__name__)
                latencies.append((time.perf_counter() - tick) * 1000)
                cycles += 1
                await asyncio.sleep(.25)
        # Allow completed native parser processes/socket cleanup to settle.
        await asyncio.sleep(1)
        after = process_sample(lab.pids)
        facts = await asyncio.to_thread(lab.queue_facts)
        new = [value for key, value in facts.items() if key not in initial_facts]
        quarter = max(1, len(latencies) // 4)
        row = {"profile": profile, "duration_seconds": time.monotonic() - started,
            "requested_duration_seconds": duration, "cycles": cycles, "memory_bytes": after["memory_bytes"],
            "threads": after["threads"], "processes": after["processes"], "connections": after["connections"],
            "queue_growth": await asyncio.to_thread(lab.queue_depth) - initial_depth,
            "latency_drift_ms": percentile(latencies[-quarter:], .50) - percentile(latencies[:quarter], .50),
            "retry_storms": any(value["attempts"] > 1 for value in new),
            "worker_starvation": not new or any(value["state"] != "SUCCEEDED" for value in new),
            "file_descriptor_leaks": after["file_descriptors"] > before["file_descriptors"] + 2,
            "memory_growth_bytes": after["memory_bytes"] - before["memory_bytes"],
            "thread_growth": after["threads"] - before["threads"],
            "process_growth": after["processes"] - before["processes"],
            "connection_growth": after["connections"] - before["connections"],
            "error_count": len(failures), **sampler.metrics()}
        profiles.append(row)
        raw.append({**row, "latencies_ms": latencies, "errors": failures,
                    "initial_resources": before, "final_resources": after, "resource_samples": sampler.samples})
    return {"profiles": profiles}, raw


async def run(lane, durations, *, api_replicas=8, workers=4):
    import httpx
    run_id = uuid.uuid4().hex[:16]
    owner = lab = None
    worker_failures = []
    failure_frames = []
    rows, measurements, reason, status = [], {}, None, "FAIL"
    try:
        # Retain ownership even if graph/positive-control setup raises.
        lab = NativeLab.__new__(NativeLab)
        try:
            lab.__init__(run_id, api_replicas=api_replicas, workers=workers)
        finally:
            owner = getattr(lab, "owner", None)
        from contextlib import AsyncExitStack
        async with AsyncExitStack() as stack:
            clients = [await stack.enter_async_context(httpx.AsyncClient(base_url=str(session.base_url), cookies=session.cookies,
                headers={lab.graph.settings.csrf_header_name: session.headers[lab.graph.settings.csrf_header_name]},
                timeout=150, limits=httpx.Limits(max_connections=110, max_keepalive_connections=110))) for session in lab.sessions]
            measurements, rows = await (performance(lab, clients, run_id) if lane == "performance"
                                       else soak(lab, clients[0], run_id, durations))
        if lane == "performance":
            complete = {(row["workload"], row["concurrency"]) for row in rows} == {
                (workload, concurrency) for workload in PERFORMANCE_WORKLOADS for concurrency in PERFORMANCE_CONCURRENCY_LEVELS}
            status = "PASS" if complete and all(row["error_rate"] == 0 and row["queue_depth"] == 0 for row in rows) else "FAIL"
        else:
            status = "PASS" if len(rows) == 2 and all(row["cycles"] > 0 and row["error_count"] == 0 and row["queue_growth"] == 0
                and not any(row[name] for name in ("retry_storms", "worker_starvation", "file_descriptor_leaks"))
                and row["memory_growth_bytes"] <= 64 * 1024 * 1024
                and row["thread_growth"] <= 4 and row["process_growth"] <= 0
                and row["connection_growth"] <= 2 and row["latency_drift_ms"] <= 1000 for row in rows) else "FAIL"
    except Exception as error:
        reason = type(error).__name__
        import traceback
        failure_frames = [{"file": Path(frame.filename).name, "line": frame.lineno,
                           "function": frame.name} for frame in traceback.extract_tb(error.__traceback__)]
        progress = ROOT / ".runtime/phase-3/operational-local" / run_id / "progress.json"
        if progress.is_file():
            partial = json.loads(progress.read_text())
            rows, measurements = partial["observations"], partial["measurements"]
    finally:
        for worker in getattr(lab, "workers", []):
            if worker.poll() not in {None, 0}:
                detail = {"pid": worker.pid, "exit_code": worker.returncode}
                if worker.stdout:
                    try:
                        detail["diagnostic"] = json.loads(worker.stdout.read(16384))
                    except (ValueError, OSError):
                        detail["diagnostic"] = "unavailable"
                worker_failures.append(detail)
        if owner:
            try:
                await owner.close()
            except Exception:
                status, reason = "FAIL", "owned_cleanup_failed"
    base = ROOT / ".runtime/phase-3/operational-local" / run_id
    base.mkdir(parents=True, exist_ok=True)
    raw = {"lane": lane, "run_id": run_id, "observations": rows, "reason": reason}
    encoded = json.dumps(raw, sort_keys=True, indent=2) + "\n"
    raw_path = base / "samples.json"
    raw_path.write_text(encoded)
    payload = {"schema_version": "rick-phase3-operational-observation.v1", "lane": lane, "status": status,
        "production_safe": False, "run_id": run_id,
        "runtime": {"disposable": True, "native_product": True, "provider_fixture": True,
            "baseline": {"hardware": {"logical_cpus": os.cpu_count(), "machine": platform.machine()},
                "container_limits": {"backends": "Qdrant/S3/Redis shared dev; PostgreSQL owned; host CPU unreserved", "api_replicas": api_replicas,
                    "worker_processes": workers, "concurrency_per_worker": 1},
                "postgres": getattr(getattr(owner, "postgres", None), "profile", {"owned": False}),
                "dataset": "unique synthetic tenant; bounded text fixture per operation", "provider": "local-citation-fixture",
                "workload_definitions": {"chat": "HTTP generation with verified publication followed by durable conversation reload"},
                "model": "chat-test/dimensions-2", "versions": {"python": platform.python_version()}}},
        "budgets": {"scope": "local diagnostic only; no production ratification", "max_error_rate": 0,
            "max_queue_growth": 0, "max_memory_growth_bytes": 64 * 1024 * 1024,
            "max_thread_growth": 4, "max_process_growth": 0, "max_connection_growth": 2, "max_latency_drift_ms": 1000,
            "max_fd_growth": 2, "soak_seconds": list(durations), "max_job_seconds": 120},
        "measurements": measurements, "checks": {"owned_cleanup": owner is not None and owner.closed, "reason": reason},
        "failure_frames": failure_frames, "worker_failures": worker_failures,
        "readiness_observations": getattr(lab, "readiness_observations", []),
        "raw_artifacts": [{"path": str(raw_path.relative_to(ROOT)), "sha256": hashlib.sha256(encoded.encode()).hexdigest()}],
        "limitations": ["Complete configured matrix on a small synthetic fixture; not production capacity or a representative model benchmark.",
            "CPU sampling includes live descendants and reaped-child CPU counters; it is sampled process CPU, not reserved hardware capacity.",
            "Socket/FD/process samples are /proc observations; soak windows are explicitly local and bounded."]}
    target = base.parent / (lane + "-current.json")
    target.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
    (base / "observation.json").write_bytes(target.read_bytes())
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", choices=("performance", "soak"), required=True)
    parser.add_argument("--short-seconds", type=int, default=30)
    parser.add_argument("--extended-seconds", type=int, default=120)
    parser.add_argument("--api-replicas", type=int, default=8)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if not 10 <= args.short_seconds < args.extended_seconds <= 600:
        parser.error("local soak windows require 10 <= short < extended <= 600 seconds")
    if not 1 <= args.api_replicas <= 8 or not 1 <= args.workers <= 4:
        parser.error("owned API replicas must be 1..8 and workers 1..4")
    payload = asyncio.run(run(args.lane, (args.short_seconds, args.extended_seconds),
                              api_replicas=args.api_replicas, workers=args.workers))
    print(json.dumps(payload, sort_keys=True))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
