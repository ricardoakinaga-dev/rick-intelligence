#!/usr/bin/env python3
"""Thirteen bounded native chaos cases on owned workers/backends/proxies.

Redis and Qdrant are new private containers using already cached image IDs.
PostgreSQL/S3 outages affect only owned loopback proxies and a synthetic scope.
No shared container is killed. Each case needs a real fault, recovery, stable
baseline bytes/lineage and exactly one durable success for an actual upload.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import time
from urllib.parse import urlsplit, urlunsplit, quote
import uuid

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.phase11.formal_lab_resources import ROOT
from scripts.phase11.local_lab_environment import from_dev_compose, _inspect
from scripts.phase11.local_operational_harness import NativeLab, CONTENT, QUERY
from scripts.phase11.owned_lab_network import TCPProxy
from scripts.state_of_art.runtime_preflight import canonical_compose_project
from scripts.state_of_art.phase3_lane import CHAOS_FAULTS


LABEL = "rick.phase3.owned-run"


class OwnedBackends:
    def __init__(self, run_id):
        if os.environ.get("RICK_FORMAL_LAB_AUTHORIZED") != "1":
            raise ValueError("explicit_formal_lab_authority_required")
        self.run_id = run_id
        self.network = "rick-chaos-" + run_id
        self.names, self.proxies = {}, []
        self.network_created = False
        self.postgres = None

    def docker(self, *args, env=None):
        result = subprocess.run(["docker", *args], env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=40, check=False, text=True)
        if result.returncode:
            raise RuntimeError("owned_docker_operation_failed")
        return result.stdout.strip()

    def checked_name(self, service):
        name = self.names[service]
        item = json.loads(self.docker("inspect", name))[0]
        if item.get("Config", {}).get("Labels", {}).get(LABEL) != self.run_id:
            raise ValueError("refusing_nonowned_container")
        return name

    def change(self, service, action):
        if action not in {"kill", "start", "restart"}:
            raise ValueError("unsupported_owned_action")
        return self.docker(action, self.checked_name(service))

    async def start(self):
        import httpx
        import redis
        env = from_dev_compose(ROOT, provider_container=os.environ.get("RICK_LOCAL_PROVIDER_CONTAINER", "rick-dev-provider"))
        from scripts.phase11.owned_lab_postgres import OwnedPostgres
        self.postgres = OwnedPostgres(self.run_id)
        env["RICK_EXTERNAL_DATABASE_DSN"] = await asyncio.to_thread(self.postgres.start)
        project = canonical_compose_project(ROOT, "docker-compose.dev.yml")
        self.docker("network", "create", "--internal", "--label", LABEL + "=" + self.run_id, self.network)
        self.network_created = True
        password, api_key = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        for service in ("redis", "qdrant"):
            image_id = _inspect(f"{project}-{service}-1")["Image"]
            if not image_id.startswith("sha256:"):
                raise ValueError("cached_image_id_required")
            name = self.network + "-" + service
            child_env = {**os.environ, "RICK_CHAOS_REDIS_PASSWORD": password, "QDRANT__SERVICE__API_KEY": api_key}
            args = ["run", "-d", "--name", name, "--network", self.network, "--label", LABEL + "=" + self.run_id,
                    "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--log-driver", "none",
                    "--memory", "512m", "--cpus", "2", "--pids-limit", "128"]
            if service == "redis":
                args += ["--env", "RICK_CHAOS_REDIS_PASSWORD", image_id, "sh", "-c",
                         'exec redis-server --appendonly no --save "" --requirepass "$RICK_CHAOS_REDIS_PASSWORD"']
            else:
                args += ["--env", "QDRANT__SERVICE__API_KEY", image_id]
            # Remember the name before launch so a partially successful Docker
            # call cannot leave an untracked disposable container behind.
            self.names[service] = name
            self.docker(*args, env=child_env)
        addresses = {service: json.loads(self.docker("inspect", self.checked_name(service)))[0]
            ["NetworkSettings"]["Networks"][self.network]["IPAddress"] for service in self.names}
        redis_url = f"redis://default:{quote(password, safe='')}@{addresses['redis']}:6379/0"
        qdrant_url = f"http://{addresses['qdrant']}:6333"
        deadline = time.monotonic() + 40
        with redis.Redis.from_url(redis_url, socket_connect_timeout=1, socket_timeout=1) as client:
            while time.monotonic() < deadline:
                try:
                    if client.ping() and httpx.get(qdrant_url + "/healthz", headers={"api-key": api_key}, timeout=1).status_code == 200:
                        break
                except Exception:
                    pass
                await asyncio.sleep(.2)
            else:
                raise RuntimeError("owned_backends_readiness_timeout")
        from rick_retrieval.qdrant import QdrantHttpVectorStore
        collection = "chaos_" + self.run_id
        with QdrantHttpVectorStore(qdrant_url, collection, api_key=api_key) as vectors:
            if not vectors.create_collection(vector_dimensions=2, hybrid=True):
                raise RuntimeError("owned_index_bootstrap_failed")
        overrides = {"RICK_REDIS_URL": redis_url, "RICK_QDRANT_URL": qdrant_url,
                     "RICK_QDRANT_API_KEY": api_key, "RICK_QDRANT_COLLECTION": collection}
        for key in ("RICK_EXTERNAL_DATABASE_DSN", "RICK_OBJECT_STORE_ENDPOINT"):
            parsed = urlsplit(env[key])
            proxy = TCPProxy(parsed.hostname, parsed.port or (5432 if key.endswith("DSN") else 80))
            self.proxies.append(proxy)
            authority = parsed.netloc.rsplit("@", 1)[0] + "@" if "@" in parsed.netloc else ""
            overrides[key] = urlunsplit(parsed._replace(netloc=f"{authority}127.0.0.1:{proxy.port}"))
        self.pg, self.s3 = self.proxies
        return overrides

    def close(self):
        errors = []
        for proxy in self.proxies:
            try:
                proxy.close()
            except Exception:
                errors.append("owned_proxy")
        for service in self.names:
            try:
                self.docker("rm", "-f", "-v", self.checked_name(service))
            except Exception:
                errors.append("owned_container")
        if self.network_created:
            try:
                item = json.loads(self.docker("network", "inspect", self.network))[0]
                if item.get("Labels", {}).get(LABEL) != self.run_id:
                    raise ValueError("refusing_nonowned_network")
                self.docker("network", "rm", self.network)
            except Exception:
                errors.append("owned_network")
        if self.postgres:
            try:
                self.postgres.close()
            except Exception:
                errors.append("owned_postgres")
        if errors:
            raise RuntimeError("owned_chaos_cleanup_failed")


def baseline_snapshot(lab):
    from rick_storage import ObjectScope
    from rick_ingestion.pipeline import IngestionService
    job = lab.baseline
    document = lab.graph.knowledge.get_document(job.document_id,
        tenant_id=lab.scope["tenant_id"], workspace_id=lab.scope["workspace_id"])
    chunks = lab.graph.knowledge.get_chunks(job.document_id,
        tenant_id=lab.scope["tenant_id"], workspace_id=lab.scope["workspace_id"])
    points = lab.graph.vector_store.snapshot_document(job.document_id, lab.scope["collection_id"],
        tenant_id=lab.scope["tenant_id"], workspace_id=lab.scope["workspace_id"])
    body = lab.graph.object_store.get(ObjectScope(tenant_id=lab.scope["tenant_id"], workspace_id=lab.scope["workspace_id"],
        source_id=job.payload["object_source_id"]), job.payload["object_key"], max_bytes=16384)
    return {"status": document.status, "document_version": document.document_version,
            "checksum": document.content_checksum, "object_sha256": hashlib.sha256(body).hexdigest(),
            "chunk_facts": sorted((chunk.chunk_id, chunk.checksum, chunk.index_version) for chunk in chunks),
            "point_manifest": IngestionService._point_manifest(points), "point_count": len(points)}


def completion_facts(lab, job_id, content):
    import psycopg
    with psycopg.connect(lab.graph.settings.external_database_dsn, connect_timeout=5) as connection:
        attempt_count, successes, max_attempt = connection.execute(
            "SELECT count(*),count(*) FILTER (WHERE state='SUCCEEDED'),max(attempt_no) "
            "FROM rick_ingestion_job_attempts WHERE job_id=%s", (job_id,)).fetchone()
        row = connection.execute("SELECT document_id,attempts,max_attempts,contract_state FROM rick_ingestion_jobs "
            "WHERE job_id=%s AND tenant_id=%s AND workspace_id=%s", (job_id, lab.scope["tenant_id"], lab.scope["workspace_id"])).fetchone()
        publications = connection.execute("SELECT count(*) FROM rick_documents WHERE tenant_id=%s AND workspace_id=%s "
            "AND collection_id=%s AND status='published' AND content_checksum=%s",
            (*lab.scope.values(), hashlib.sha256(content.encode()).hexdigest())).fetchone()[0]
    if row is None:
        raise ValueError("completion_scope_missing")
    chunks = lab.graph.knowledge.get_chunks(row[0], tenant_id=lab.scope["tenant_id"], workspace_id=lab.scope["workspace_id"])
    points = lab.graph.vector_store.count_for_document(row[0], lab.scope["collection_id"],
        tenant_id=lab.scope["tenant_id"], workspace_id=lab.scope["workspace_id"])
    return {"attempt_count": attempt_count, "success_count": successes, "max_attempt": max_attempt,
            "recorded_attempts": row[1], "max_attempts": row[2], "terminal_state": row[3],
            "published_versions_for_checksum": publications, "chunks": len(chunks), "points": points}


async def eventually(operation, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = operation()
            if hasattr(result, "__await__"):
                result = await result
            if result:
                return result
        except Exception:
            pass
        await asyncio.sleep(.25)
    raise TimeoutError("owned_recovery_deadline")


async def provider_answer(lab, key):
    # Exercise the real typed provider/resilience boundary directly. Equal
    # synthetic vectors can make Professor abstain before provider I/O after
    # the earlier ingestion cases; abstention cannot prove a provider fault.
    # This result is only a transport recovery, never claim-support evidence.
    from rick_contracts.providers import ProviderMessage
    return await lab.graph.provider.chat_completion(messages=[ProviderMessage(role="user",
        content="Confirme a disponibilidade do provider local.")], correlation_id=key[:128])


async def inject(lab, backends, fault, client, run_id):
    observed = {"fault": fault}
    key = "chaos-" + run_id + "-" + fault
    fixture = lab.owner.server
    circuit_proved = False
    recovered_job = None
    if fault.startswith("provider-"):
        mode = {"provider-timeout": "timeout", "provider-429": "rate-limit", "provider-500": "server-error"}[fault]
        fixture.fault_mode, fixture.fault_counts = mode, {}
        failures = 0
        try:
            for index in range(lab.graph.provider.failure_threshold):
                try:
                    await provider_answer(lab, key + str(index))
                except Exception:
                    failures += 1
            open_seen = lab.graph.provider.is_open
            count = fixture.fault_counts.get(mode, 0)
            try:
                await provider_answer(lab, key + "-open")
            except Exception:
                pass
            held = fixture.fault_counts.get(mode, 0) == count
        finally:
            fixture.fault_mode = "normal"
        await eventually(lambda: not lab.graph.provider.is_open, timeout=40)
        answer = await provider_answer(lab, key + "-recovered")
        valid = bool(answer.content.strip()) and answer.finish_reason == "stop"
        circuit_proved = bool(open_seen and held and valid and not lab.graph.provider.is_open)
        observed.update(fault_observed=failures == lab.graph.provider.failure_threshold, provider_calls=count,
            provider_call_budget=lab.graph.provider.failure_threshold * lab.graph.settings.provider_max_attempts,
            circuit_open_observed=open_seen, circuit_suppressed_io=held, provider_recovered=valid,
            provider_recovery_scope="typed_transport_only_not_claim_support")
    elif fault.startswith("kill-worker"):
        # B is paused until A has demonstrably claimed this durable job.
        a, b = lab.workers
        os.killpg(b.pid, signal.SIGSTOP)
        fixture.embedding_delay = 2
        try:
            recovered_job = await lab.upload(client, key)
            async def claimed():
                import psycopg
                with psycopg.connect(lab.graph.settings.external_database_dsn, connect_timeout=5) as connection:
                    row = connection.execute("SELECT contract_state,lease_worker_id FROM rick_ingestion_jobs WHERE job_id=%s",
                                             (recovered_job,)).fetchone()
                return row if row and row[0] == "RUNNING" else None
            lease = await eventually(claimed, timeout=15)
            if lease[1] != a.owned_worker_id:
                raise ValueError("victim_did_not_own_claim")
            os.killpg(a.pid, signal.SIGKILL)
            await asyncio.to_thread(a.wait, timeout=5)
            observed.update(fault_observed=a.returncode == -signal.SIGKILL, victim_had_live_claim=lease[1] == a.owned_worker_id,
                            survivor_pid=b.pid, victim_pid=a.pid)
        finally:
            fixture.embedding_delay = 0
            os.killpg(b.pid, signal.SIGCONT)
        if fault == "kill-worker-a-only":
            survivor_job = await lab.upload(client, key + "-survivor")
            await lab.wait_job(survivor_job, timeout=90)
            observed["survivor_continued"] = b.poll() is None
        await lab.wait_job(recovered_job, timeout=90)
        replacement = lab.owner.start_worker(lab.scope, lab.user, continuous=True, duration_seconds=900, max_concurrency=1)
        lab.workers[0] = replacement
        lab.worker = replacement
        circuit_proved = not lab.graph.provider.is_open
    else:
        if "redis" in fault:
            probe = lab.graph.rate_limiter.health_check
            change = lambda: backends.change("redis", "restart" if fault == "restart-redis" else "kill")
            restore = lambda: backends.change("redis", "start") if fault == "kill-redis" else None
        elif "qdrant" in fault:
            probe = lab.graph.vector_store.health
            change = lambda: backends.change("qdrant", "restart" if fault == "restart-qdrant" else "kill")
            restore = lambda: backends.change("qdrant", "start") if fault == "kill-qdrant" else None
        elif fault in {"postgres-outage", "s3-outage"}:
            proxy = backends.pg if fault == "postgres-outage" else backends.s3
            probe = lab.graph.knowledge.health_check if fault == "postgres-outage" else lambda: baseline_snapshot(lab)["point_count"] > 0
            change, restore = proxy.pause, lambda: setattr(proxy, "paused", False)
        elif fault == "connection-reset":
            probe = lab.graph.knowledge.health_check
            change, restore = lambda: setattr(backends.pg, "reset_next", True), lambda: None
        elif fault == "network-delay":
            initial = time.perf_counter()
            if not lab.graph.knowledge.health_check():
                raise ValueError("delay_positive_control_failed")
            before = time.perf_counter() - initial
            backends.pg.delay_seconds = .1
            try:
                initial = time.perf_counter()
                valid = lab.graph.knowledge.health_check()
                after = time.perf_counter() - initial
            finally:
                backends.pg.delay_seconds = 0
            observed.update(fault_observed=bool(valid and after >= before + .075), before_ms=before * 1000,
                            delayed_ms=after * 1000, forwarded_bytes=backends.pg.forwarded_bytes)
            circuit_proved = not lab.graph.provider.is_open
            return observed, circuit_proved, recovered_job
        else:
            raise ValueError("unimplemented_chaos_fault")
        # Positive control before disruption is mandatory.
        await eventually(probe, timeout=10)
        service = "redis" if "redis" in fault else "qdrant" if "qdrant" in fault else None
        before_state = (json.loads(backends.docker("inspect", backends.checked_name(service)))[0]["State"]
                        if service else None)
        change()
        try:
            try:
                result = probe()
                if hasattr(result, "__await__"):
                    result = await result
                failed = result is False
            except Exception:
                failed = True
            # A fast restart can be healthy by the time Docker returns. The
            # actual PID/start timestamp change proves the restart, while a
            # successful post-restart probe proves recovery.
            if fault.startswith("restart-"):
                after_state = json.loads(backends.docker("inspect", backends.checked_name(service)))[0]["State"]
                restarted = (before_state["Pid"] > 0 and after_state["Pid"] > 0
                    and (before_state["Pid"] != after_state["Pid"] or before_state["StartedAt"] != after_state["StartedAt"]))
                observed.update(fault_observed=restarted, before_pid=before_state["Pid"], after_pid=after_state["Pid"],
                                start_timestamp_changed=before_state["StartedAt"] != after_state["StartedAt"])
            else:
                observed["fault_observed"] = failed
            observed["failure_response_observed"] = failed
        finally:
            restore()
        await eventually(probe)
        circuit_proved = not lab.graph.provider.is_open
    return observed, circuit_proved, recovered_job


async def run():
    import httpx
    run_id = uuid.uuid4().hex[:16]
    backends = OwnedBackends(run_id)
    lab = baseline = None
    results, reason, status, cleanup_errors = [], None, "FAIL", []
    output = ROOT / ".runtime/phase-3/chaos-local" / run_id
    output.mkdir(parents=True, exist_ok=True)
    try:
        overrides = await backends.start()
        os.environ.update(OPENAI_TIMEOUT_MS="1000", OPENAI_MAX_ATTEMPTS="2", OPENAI_RETRY_DELAY_MS="50")
        lab = NativeLab.__new__(NativeLab)
        lab.__init__(run_id, api_replicas=1, workers=2, environment_overrides=overrides)
        baseline = baseline_snapshot(lab)
        if baseline["status"] != "published" or baseline["point_count"] <= 0:
            raise ValueError("chaos_baseline_not_authoritative")
        async with httpx.AsyncClient(base_url=str(lab.session.base_url), cookies=lab.session.cookies,
            headers={lab.graph.settings.csrf_header_name: lab.session.headers[lab.graph.settings.csrf_header_name]}, timeout=15) as client:
            for fault in CHAOS_FAULTS:
                started = time.monotonic()
                try:
                    observations, circuit, job = await inject(lab, backends, fault, client, run_id)
                    key = "chaos-" + run_id + "-" + fault
                    if job is None:
                        job = await lab.upload(client, key)
                        await lab.wait_job(job, timeout=90)
                    facts = completion_facts(lab, job, CONTENT + " " + key)
                    same = baseline_snapshot(lab) == baseline
                    bounded = (facts["recorded_attempts"] <= facts["max_attempts"] and facts["attempt_count"] <= facts["max_attempts"]
                        and observations.get("provider_calls", 0) <= observations.get("provider_call_budget", 0))
                    observed = observations.get("fault_observed") is True
                    row = {"fault": fault, "no_silent_corruption": same and facts["points"] == facts["chunks"] > 0,
                        "no_duplicate_publish": facts["success_count"] == 1 and facts["published_versions_for_checksum"] == 1,
                        "bounded_retries": bounded, "circuit_breaker_correct": circuit,
                        "eventual_recovery": observed and facts["terminal_state"] == "SUCCEEDED",
                        "elapsed_seconds": time.monotonic() - started, "observations": observations, "completion": facts}
                    row["status"] = "PASS" if all(row[field] is True for field in (
                        "no_silent_corruption", "no_duplicate_publish", "bounded_retries", "circuit_breaker_correct", "eventual_recovery")) else "FAIL"
                except Exception as error:
                    import traceback
                    row = {"fault": fault, "status": "FAIL", "reason": type(error).__name__,
                           "failure_code": getattr(error, "code", None),
                           "failure_frames": [{"file": Path(frame.filename).name, "line": frame.lineno,
                                "function": frame.name} for frame in traceback.extract_tb(error.__traceback__)],
                           "elapsed_seconds": time.monotonic() - started}
                results.append(row)
                (output / "progress.json").write_text(json.dumps({"faults": results}, sort_keys=True, indent=2) + "\n")
        status = "PASS" if len(results) == len(CHAOS_FAULTS) and all(row["status"] == "PASS" for row in results) else "FAIL"
    except Exception as error:
        reason = type(error).__name__
    finally:
        if lab and getattr(lab, "owner", None):
            try:
                await lab.owner.close()
            except Exception:
                cleanup_errors.append("product_graph")
        try:
            await asyncio.to_thread(backends.close)
        except Exception:
            cleanup_errors.append("isolated_backends")
        if cleanup_errors:
            status = "FAIL"
    raw_path = output / "faults.json"
    raw_path.write_text(json.dumps({"faults": results, "reason": reason, "cleanup_errors": cleanup_errors,
        "baseline": baseline}, sort_keys=True, indent=2) + "\n")
    payload = {"schema_version": "rick-phase3-operational-observation.v1", "lane": "chaos", "status": status,
        "production_safe": False, "run_id": run_id, "runtime": {"disposable": True, "native_product": True,
            "postgres": getattr(backends.postgres, "profile", {"owned": False}),
            "fault_scope": "owned Redis/Qdrant containers, worker groups, PG/S3 proxies, synthetic provider"},
        "budgets": {"scope": "local diagnostics; no production approval", "max_attempts": 3, "recovery_seconds": 90,
            "provider_timeout_ms": 1000, "provider_max_attempts": 2, "circuit_cooldown_seconds": 30},
        "measurements": {"faults": results}, "checks": {"reason": reason, "cleanup_errors": cleanup_errors},
        "raw_artifacts": [{"path": str(raw_path.relative_to(ROOT)), "sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest()}],
        "limitations": ["Synthetic provider and fixture workload; real native stores, queue, parser and lease boundaries.",
            "PostgreSQL/S3 outages and network faults are scoped proxy disruptions; shared services remain running.",
            "Non-provider faults check that the provider circuit remains closed; provider cases prove open/suppressed-I/O/recovery."]}
    encoded = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    (output / "observation.json").write_text(encoded)
    (output.parent / "current.json").write_text(encoded)
    return payload


if __name__ == "__main__":
    report = asyncio.run(run())
    print(json.dumps(report, sort_keys=True))
    raise SystemExit(0 if report["status"] == "PASS" else 1)
