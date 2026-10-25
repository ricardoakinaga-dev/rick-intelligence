#!/usr/bin/env python3
"""Native causal trace, scoped metrics, Prometheus and local alert delivery.

Unknown semantic claim support is deliberately absent, not replaced with a
passing number. The canonical full gate must retain that missing group until
an approved evaluator supplies an actual observation. Local alert timers are
shortened only in separate diagnostic rules, never in production rule files.
"""
from __future__ import annotations

import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from threading import Lock, Thread
import time
from urllib.parse import urlencode
import uuid

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.phase11.local_operational_harness import NativeLab, percentile, CONTENT, QUERY
from scripts.phase11.local_distributed_probe import lab_endpoint
from scripts.phase11.local_lab_environment import _inspect
from scripts.phase11 import observability_runtime_gate as gate
from scripts.phase11.frontend_supply_runtime_gate import _free_port
from scripts.state_of_art.runtime_preflight import canonical_compose_project


class Runtime:
    def __init__(self, run_id):
        self.run_id = run_id
        self.output = ROOT / ".runtime/phase-3/observability-local" / run_id
        self.output.mkdir(parents=True)
        self.secret = secrets.token_urlsafe(32)
        self.containers, self.servers, self.threads = [], [], []
        self.samples, self.notifications, self.journeys, self.answers = [], [], [], []
        self.redis_latencies, self.qdrant_latencies = [], []
        self.telemetry = self.lab = self.redis = None
        self.metrics_unavailable = False
        self.lock = Lock()

    def docker(self, *args):
        result = subprocess.run(["docker", *args], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=40, check=False, text=True)
        if result.returncode:
            raise RuntimeError("owned_monitoring_container_failed")
        return result.stdout.strip()

    def start_container(self, service, name, argv, mounts):
        project = canonical_compose_project(ROOT, "docker-compose.dev.yml")
        image = _inspect(f"{project}-{service}-1")["Image"]
        args = ["run", "-d", "--name", name, "--network", "host", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges", "--memory", "512m", "--cpus", "1",
                "--log-driver", "none", "--label", "rick.phase3.owned-run=" + self.run_id]
        for source, target in mounts:
            args += ["--mount", f"type=bind,src={source},dst={target},readonly"]
        self.containers.append(name)
        self.docker(*args, image, *argv)

    def serve(self, handler):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        self.servers.append(server)
        self.threads.append(thread)
        thread.start()
        return server

    def initialize(self):
        import redis
        from core.otel import configure_process_otel
        collector = lab_endpoint("otel-collector", 4317)
        self.trace_backend = lab_endpoint("jaeger", 16686)
        self.http_collector = lab_endpoint("otel-collector", 4318)
        os.environ.update(OTEL_EXPORTER_OTLP_ENDPOINT=collector, OTEL_EXPORTER_OTLP_PROTOCOL="grpc",
            OTEL_TRACES_EXPORTER="otlp", OTEL_EXPORTER_OTLP_TIMEOUT="5", OTEL_SERVICE_NAME="rick-formal-api")
        self.telemetry = configure_process_otel(service_name="rick-observability-driver")
        if self.telemetry.status != "CONFIGURED":
            raise RuntimeError("native_collector_not_configured")
        self.lab = NativeLab.__new__(NativeLab)
        self.lab.__init__(self.run_id, api_replicas=1, workers=1)
        self.redis = redis.Redis.from_url(self.lab.graph.settings.redis_url, socket_timeout=2, socket_connect_timeout=2)
        self.lab.owner.server.provider_observations = []
        self.lab.owner.server.embedding_observations = []
        runtime = self
        class Handler(BaseHTTPRequestHandler):
            def send(self, status, body, content_type="application/json"):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                for name in ("X-Request-ID", "X-Correlation-ID"):
                    if self.headers.get(name):
                        self.send_header(name, self.headers[name])
                self.end_headers()
                try:
                    self.wfile.write(body)
                except OSError:
                    pass
            def do_GET(self):
                if self.path != "/metrics":
                    self.send(404, b"{}")
                    return
                if runtime.metrics_unavailable:
                    self.send(503, b"unavailable", "text/plain")
                    return
                try:
                    body = runtime.exposition().encode()
                    self.send(200, body, "text/plain; version=0.0.4")
                except Exception:
                    self.send(503, b"unavailable", "text/plain")
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 <= length <= 65536:
                    self.send(413, b"{}")
                    return
                body = self.rfile.read(length)
                if self.path == "/alerts":
                    try:
                        value = json.loads(body)
                        alerts = [{"name": alert.get("labels", {}).get("alertname"), "status": alert.get("status")}
                                  for alert in value.get("alerts", [])]
                        with runtime.lock:
                            runtime.notifications.extend(alerts)
                        self.send(200, b"{}")
                    except Exception:
                        self.send(400, b"{}")
                    return
                if self.path != "/journey" or not hmac.compare_digest(
                    self.headers.get("Authorization", ""), "Bearer " + runtime.secret):
                    self.send(403, b"{}")
                    return
                try:
                    result = asyncio.run(runtime.journey({name.lower(): value for name, value in self.headers.items()}))
                    self.send(200, json.dumps(result).encode())
                except Exception as error:
                    runtime.journeys.append({"status": "FAIL", "reason": type(error).__name__})
                    self.send(500, b'{"status":"failed"}')
            def log_message(self, *_args):
                pass
        self.server = self.serve(Handler)
        self.origin = f"http://127.0.0.1:{self.server.server_port}"
        self.prom_port, self.alert_port = _free_port(), _free_port()
        self.prom = f"http://127.0.0.1:{self.prom_port}"
        rules = self.output / "lab-rules.json"
        rules.write_text(json.dumps({"groups": [{"name": "owned-local-diagnostics", "rules": [
            {"alert": "RickLabSloBreach", "expr": 'rick_api_slo_status{status="breach"} == 1', "for": "2s"},
            {"alert": "RickLabTelemetryMissing", "expr": 'up{job="rick-api"} == 0', "for": "2s"}]}]}))
        alert_config = self.output / "alertmanager.json"
        alert_config.write_text(json.dumps({"route": {"receiver": "owned-loopback", "group_wait": "0s", "group_interval": "1s",
            "repeat_interval": "1h", "group_by": ["alertname"]}, "receivers": [{"name": "owned-loopback",
            "webhook_configs": [{"url": self.origin + "/alerts", "send_resolved": True}]}]}))
        config = self.output / "prometheus.json"
        config.write_text(json.dumps({"global": {"scrape_interval": "1s", "evaluation_interval": "1s"},
            "rule_files": ["/rules/runtime.yml", "/rules/slo.yml", "/rules/lab.json"],
            "alerting": {"alertmanagers": [{"static_configs": [{"targets": [f"127.0.0.1:{self.alert_port}"]}]}]},
            "scrape_configs": [{"job_name": "rick-api", "static_configs": [{"targets": [f"127.0.0.1:{self.server.server_port}"]}]}]}))
        self.start_container("alertmanager", "rick-observe-alert-" + self.run_id,
            ["--config.file=/config.json", f"--web.listen-address=127.0.0.1:{self.alert_port}", "--cluster.listen-address=", "--storage.path=/tmp/alertmanager"],
            [(alert_config, "/config.json")])
        self.start_container("metrics", "rick-observe-prom-" + self.run_id,
            ["--config.file=/config.json", f"--web.listen-address=127.0.0.1:{self.prom_port}", "--storage.tsdb.path=/tmp/prometheus"],
            [(config, "/config.json"), (rules, "/rules/lab.json"),
             (ROOT / "infrastructure/monitoring/prometheus.rules.yml", "/rules/runtime.yml"),
             (ROOT / "infrastructure/compose/alerts.yml", "/rules/slo.yml")])

    def exposition(self):
        native = self.lab.session.get("/api/v1/admin/metrics/prometheus")
        if native.status_code != 200:
            raise ValueError("native_metrics_not_available")
        facts = self.lab.queue_facts()
        import psycopg
        with psycopg.connect(self.lab.graph.settings.external_database_dsn, connect_timeout=5) as connection:
            failures = connection.execute("SELECT count(*) FROM rick_ingestion_job_attempts a JOIN rick_ingestion_jobs j USING(job_id) "
                "WHERE j.tenant_id=%s AND j.workspace_id=%s AND a.state='FAILED'", (self.lab.scope["tenant_id"], self.lab.scope["workspace_id"])).fetchone()[0]
            durations = connection.execute("SELECT EXTRACT(EPOCH FROM (a.finished_at-j.created_at))*1000 "
                "FROM rick_ingestion_job_attempts a JOIN rick_ingestion_jobs j USING(job_id) "
                "WHERE j.tenant_id=%s AND j.workspace_id=%s AND a.state='SUCCEEDED'",
                (self.lab.scope["tenant_id"], self.lab.scope["workspace_id"])).fetchall()
        started = time.perf_counter()
        if not self.redis.ping():
            raise ValueError("redis_probe_not_successful")
        self.redis_latencies.append((time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        if not self.lab.graph.vector_store.health():
            raise ValueError("qdrant_probe_not_successful")
        self.qdrant_latencies.append((time.perf_counter() - started) * 1000)
        del self.redis_latencies[:-256]
        del self.qdrant_latencies[:-256]
        values = {
            "rick_queue_depth": sum(row["state"] in {"QUEUED", "RUNNING", "RETRYING", "PENDING"} for row in facts.values()),
            "rick_worker_active": sum(row["state"] == "RUNNING" for row in facts.values()),
            "rick_worker_failures_total": failures,
            "rick_worker_dead_letter_total": sum(row["state"] == "DEAD_LETTER" for row in facts.values()),
            "rick_redis_latency_ms_p95": percentile(self.redis_latencies, .95),
            "rick_qdrant_latency_ms_p95": percentile(self.qdrant_latencies, .95),
        }
        if durations:
            values["rick_ingestion_duration_ms_p95"] = percentile([float(row[0]) for row in durations], .95)
        observations = self.lab.owner.server.provider_observations[:]
        if observations:
            elapsed = sum(row["duration_seconds"] for row in observations)
            values["rick_provider_tokens_per_second"] = sum(row["completion_tokens"] for row in observations) / elapsed
        embeddings = self.lab.owner.server.embedding_observations[:]
        if embeddings:
            elapsed = sum(row["duration_seconds"] for row in embeddings)
            values["rick_embedding_throughput"] = sum(row["vectors"] for row in embeddings) / elapsed
        with self.lock:
            answers = self.answers[:]
        if answers:
            values["rick_abstention_rate"] = sum(row["action"] in {"ABSTAIN", "ESCALATE"} for row in answers) / len(answers)
            # Structural validation is measured and named honestly. It is not
            # exported under the canonical semantic claim-support aliases.
            values["rick_citation_registry_validity_ratio"] = sum(row["verified"] for row in answers) / len(answers)
        text = native.text
        if "rick_api_http_errors_total" not in text:
            # The native lifetime registry creates an error counter only on
            # its first 5xx. Absence in this complete native snapshot is an
            # observed zero count, not a missing dependency inference.
            snapshot = self.lab.session.get("/api/v1/admin/metrics").json()
            total = sum(row.get("total", row.get("value", 0)) for row in snapshot.get("counters", []) if row.get("name") == "api.http.errors")
            values["rick_api_http_errors_total"] = total
        lines = [text.rstrip(), "# Semantic claim support NOT_EVALUATED: approved evaluator/corpus missing.",
                 "# Provider throughput uses the explicit synthetic provider-reported usage."]
        lines.extend(f"{name} {value:.9g}" for name, value in values.items())
        with self.lock:
            self.samples.append({"observed_at": time.time(), **values})
            del self.samples[:-512]
        return "\n".join(lines) + "\n"

    async def journey(self, headers):
        import httpx
        from core.otel import attach_trace_context, stage_span, current_trace_context
        with attach_trace_context(headers), stage_span("lab.observability_journey") as span:
            trace_id = format(span.get_span_context().trace_id, "032x")
            carrier = current_trace_context()
            async with httpx.AsyncClient(base_url=str(self.lab.session.base_url), cookies=self.lab.session.cookies,
                headers={self.lab.graph.settings.csrf_header_name: self.lab.session.headers[self.lab.graph.settings.csrf_header_name]}, timeout=20) as client:
                uploaded = await client.post("/api/v1/documents/upload", headers=carrier, json={"filename": "observability.txt",
                    "collection_id": self.lab.scope["collection_id"], "content": CONTENT + " " + trace_id})
                if uploaded.status_code != 202:
                    raise ValueError("observability_upload_not_accepted")
                published = await self.lab.wait_job(uploaded.json()["job_id"], timeout=20)
                # Keep a single authorized source for the model/stream stage.
                # The equal synthetic vectors otherwise exercise Professor's
                # ambiguity policy instead of the provider boundary. The real
                # upload/worker publication remains in the causal trace.
                retired = await client.delete("/api/v1/documents/" + published["document_id"], headers=carrier)
                if retired.status_code != 200:
                    raise ValueError("observability_fixture_retirement_failed")
                search = await client.post("/api/v1/search", headers=carrier, json={"query": QUERY})
                if search.status_code != 200 or search.json().get("total", 0) <= 0:
                    raise ValueError("observability_search_not_grounded")
                final = None
                async with client.stream("POST", "/api/v1/chat", headers=carrier,
                    json={"message": QUERY, "stream": True, "conversation_id": "observe-" + self.run_id}) as response:
                    if response.status_code != 200:
                        raise ValueError("observability_stream_not_accepted")
                    async for line in response.aiter_lines():
                        if line.startswith("data: ") and line[6:] != "[DONE]":
                            event = json.loads(line[6:])
                            if event.get("type") == "completion":
                                final = event
                if final is None or final.get("metadata", {}).get("publication_validation") != "verified":
                    raise ValueError("observability_completion_not_authoritative")
                with self.lock:
                    self.answers.append({"action": final["metadata"].get("decision_action"), "verified": bool(final.get("citations"))})
        self.telemetry.provider.force_flush(timeout_millis=5000)
        row = {"status": "PASS", "trace_id": trace_id, "api_pid": self.lab.api_pids[0], "worker_pid": self.lab.worker.pid,
               "published_fixture_retired_before_chat": True}
        self.journeys.append(row)
        return {"status": "complete"}

    def query(self, path):
        import httpx
        response = httpx.get(self.prom + path, timeout=5)
        response.raise_for_status()
        return response.json()

    async def await_notification(self, name, status, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.lock:
                if any(row == {"name": name, "status": status} for row in self.notifications):
                    return True
            await asyncio.sleep(.25)
        return False

    async def alert_tests(self):
        # Actual native 5xx, not an injected metric value. Production rules
        # stay byte-identical; a separate lab-only 2s rule uses the same SLO.
        self.lab.owner.server.fault_mode = "unavailable"
        try:
            response = await asyncio.to_thread(self.lab.session.post, "/api/v1/chat", json={
                "message": QUERY, "conversation_id": "fault-" + self.run_id})
        finally:
            self.lab.owner.server.fault_mode = "normal"
        fault_slo = self.lab.session.get("/api/v1/admin/metrics").json()["slo"]
        breach = fault_slo["status"]
        delivered = await self.await_notification("RickLabSloBreach", "firing")
        # Replace the bounded SLO window with actual successful business GETs.
        for _ in range(260):
            good = await asyncio.to_thread(self.lab.session.get, "/api/v1/collections")
            if good.status_code != 200:
                raise ValueError("slo_recovery_http_failure")
            await asyncio.sleep(.01)
        recovery_slo = self.lab.session.get("/api/v1/admin/metrics").json()["slo"]
        recovered = recovery_slo["status"]
        resolved = await self.await_notification("RickLabSloBreach", "resolved")
        self.metrics_unavailable = True
        try:
            missing_delivered = await self.await_notification("RickLabTelemetryMissing", "firing")
        finally:
            self.metrics_unavailable = False
        missing_resolved = await self.await_notification("RickLabTelemetryMissing", "resolved")
        return {"native_fault_status": response.status_code, "slo_after_fault": breach, "slo_after_recovery": recovered,
                "fault_slo_snapshot": fault_slo, "recovery_slo_snapshot": recovery_slo,
                "breach_delivered": delivered, "breach_resolved": resolved,
                "missing_delivered": missing_delivered, "missing_resolved": missing_resolved,
                "status": "PASS" if response.status_code == 503 and breach == "breach" and recovered == "healthy"
                    and all((delivered, resolved, missing_delivered, missing_resolved)) else "FAIL"}

    async def close(self):
        errors = []
        for name in self.containers:
            try:
                value = json.loads(self.docker("inspect", name))[0]
                if value["Config"]["Labels"].get("rick.phase3.owned-run") != self.run_id:
                    raise ValueError("refusing_nonowned_monitoring_cleanup")
                self.docker("rm", "-f", name)
            except Exception:
                errors.append("owned_monitoring_container")
        for server in self.servers:
            await asyncio.to_thread(server.shutdown)
            server.server_close()
        for thread in self.threads:
            thread.join(5)
        if self.redis:
            self.redis.close()
        if self.lab and getattr(self.lab, "owner", None):
            try:
                await self.lab.owner.close()
            except Exception:
                errors.append("native_graph")
        if self.telemetry:
            self.telemetry.close()
        if errors:
            raise RuntimeError("observability_owned_cleanup_failed")


async def run():
    import httpx
    run_id = uuid.uuid4().hex[:16]
    runtime = Runtime(run_id)
    report = {"status": "FAIL", "production_safe": False, "run_id": run_id}
    try:
        await asyncio.to_thread(runtime.initialize)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                if httpx.get(runtime.prom + "/-/ready", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            await asyncio.sleep(.25)
        else:
            raise RuntimeError("owned_prometheus_not_ready")
        output = runtime.output / "canonical-gate.json"
        await asyncio.to_thread(gate.main, ["--mode", "external", "--collector-url", runtime.http_collector,
            "--trace-backend-url", runtime.trace_backend + "/api/traces", "--metrics-backend-url", runtime.prom,
            "--api-url", str(runtime.lab.session.base_url), "--probe-url", runtime.origin + "/journey", "--probe-method", "POST",
            "--probe-body", "{}", "--probe-header", "Authorization=Bearer " + runtime.secret,
            "--allow-nonlocal", "--timeout", "30", "--poll-timeout", "30", "--output", str(output.relative_to(ROOT))])
        canonical = json.loads(output.read_text())
        deadline = time.monotonic() + 30
        while True:
            inventory = runtime.query("/api/v1/query?" + urlencode({"query": 'sum by (__name__) ({__name__=~"rick_.+"})'}))
            names = {row["metric"].get("__name__") for row in inventory["data"]["result"]}
            missing = [group for group, aliases in gate._METRIC_GROUPS.items() if not any(alias.split("{", 1)[0] in names for alias in aliases)]
            if not set(missing) - {"citation_support"} or time.monotonic() >= deadline:
                break
            await asyncio.sleep(.25)
        alerts = await runtime.alert_tests()
        report.update(canonical_status=canonical["status"], canonical_results=canonical["results"],
            metric_group_count=len(gate._METRIC_GROUPS) - len(missing), required_metric_groups=len(gate._METRIC_GROUPS),
            missing_metric_groups=missing, alert_delivery=alerts, journeys=runtime.journeys,
            status="PASS" if canonical["status"] == "PASS" and alerts["status"] == "PASS" else "PARTIAL")
        (runtime.output / "metric-inventory.json").write_text(json.dumps(inventory, sort_keys=True, indent=2) + "\n")
        for row in runtime.journeys:
            if row.get("trace_id"):
                trace = httpx.get(runtime.trace_backend + "/api/traces/" + row["trace_id"], timeout=5).json()
                if not gate._trace_payload_is_redacted(trace):
                    raise ValueError("raw_trace_redaction_failed")
                (runtime.output / "distributed-trace.json").write_text(json.dumps(trace, sort_keys=True, indent=2) + "\n")
    except Exception as error:
        report["reason"] = type(error).__name__
        import traceback
        report["failure_frames"] = [{"file": Path(frame.filename).name, "line": frame.lineno,
                                     "function": frame.name} for frame in traceback.extract_tb(error.__traceback__)]
    finally:
        try:
            await runtime.close()
            report["cleanup_status"] = "PASS"
        except Exception:
            report.update(status="FAIL", cleanup_status="FAIL")
        (runtime.output / "samples.json").write_text(json.dumps({"metrics": runtime.samples,
            "notifications": runtime.notifications, "journeys": runtime.journeys}, sort_keys=True, indent=2) + "\n")
    report["raw_artifacts"] = [{"path": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in runtime.output.glob("*.json") if path.name != "observation.json"]
    report["limitations"] = ["Semantic claim support is NOT_EVALUATED; structural registry validity is a separately named metric.",
        "Real native graph, Collector/Jaeger and owned Prometheus/Alertmanager; all notification traffic stays on loopback.",
        "Separate diagnostic alert rules use 2s windows; original production rules/timers are unchanged and no production SLO is ratified.",
        "Token/vector throughput uses the explicit fixture provider, not a real-model capacity claim."]
    encoded = json.dumps(report, sort_keys=True, indent=2) + "\n"
    (runtime.output / "observation.json").write_text(encoded)
    (runtime.output.parent / "current.json").write_text(encoded)
    return report


if __name__ == "__main__":
    report = asyncio.run(run())
    print(json.dumps({"status": report["status"], "production_safe": False, "run_id": report["run_id"]}))
    raise SystemExit(0 if report["status"] == "PASS" else 1)
