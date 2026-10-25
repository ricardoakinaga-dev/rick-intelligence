#!/usr/bin/env python3
"""Observe HTTP -> durable queue -> another worker process -> grounded chat.

Uses the running lab Collector/Jaeger and native product adapters. The trace
is a connected causal DAG, including multiple HTTP requests. It is not evidence
for production SLO ratification, all metrics, alerts or the canonical full gate.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from urllib.request import build_opener
import uuid

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.phase11.formal_lab_resources import LabResources
from scripts.phase11.local_lab_environment import _inspect
from scripts.phase11.local_product_probe import _NoRedirect
from scripts.state_of_art.runtime_preflight import canonical_compose_project
from scripts.phase11.observability_runtime_gate import _extract_spans, _stage_for_name, _trace_payload_is_redacted, REQUIRED_TRACE_STAGES


def inspect_graph(payload: dict, trace_id: str) -> dict:
    raw_spans = [span for record in payload.get("data", []) for span in record.get("spans", [])]
    if len({span.get("spanID") for span in raw_spans}) != len(raw_spans):
        raise ValueError("duplicate_raw_span_id")
    spans = _extract_spans(payload)
    by_id = {span.get("span_id"): span for span in spans}
    if not spans or len(by_id) != len(spans) or any(span.get("trace_id") != trace_id for span in spans):
        raise ValueError("trace_identity_invalid")
    if not _trace_payload_is_redacted(payload):
        raise ValueError("trace_redaction_failed")
    roots = [key for key, span in by_id.items() if not span.get("parent_id")]
    if len(roots) != 1:
        raise ValueError("trace_not_single_connected_journey")
    stages = set()
    worker_queue_link = False
    for key, span in by_id.items():
        stages.update(_stage_for_name(str(span.get("name", ""))))
        chain = set()
        ancestor = span.get("parent_id")
        while ancestor:
            if ancestor not in by_id or ancestor == key or ancestor in chain:
                raise ValueError("trace_parent_graph_invalid")
            chain.add(ancestor)
            ancestor = by_id[ancestor].get("parent_id")
        if "worker" in _stage_for_name(str(span.get("name", ""))):
            worker_queue_link |= any("queue" in _stage_for_name(str(by_id[parent].get("name", ""))) for parent in chain)
    if set(REQUIRED_TRACE_STAGES) - stages or not worker_queue_link:
        raise ValueError("trace_stages_or_queue_handoff_missing")
    services = {trace.get("processes", {}).get(span.get("processID"), {}).get("serviceName")
                for trace in payload.get("data", []) for span in trace.get("spans", [])}
    services.discard(None)
    if not {"rick-formal-api", "rick-formal-worker"}.issubset(services):
        raise ValueError("separate_service_exporters_missing")
    return {"span_count": len(spans), "stage_count": len(REQUIRED_TRACE_STAGES),
            "stages": sorted(stages), "service_names": sorted(services),
            "worker_descends_from_queue": True, "connected": True, "redacted": True}


def lab_endpoint(service: str, port: int) -> str:
    project = canonical_compose_project(ROOT, "docker-compose.dev.yml")
    item = _inspect(f"{project}-{service}-1")
    labels = item["Config"]["Labels"]
    if labels.get("com.docker.compose.project") != project:
        raise ValueError("wrong_lab_project")
    address = item["NetworkSettings"]["Networks"][f"{project}_private"]["IPAddress"]
    return f"http://{address}:{port}"


async def run(output: Path):
    owner = None
    telemetry = None
    results = []
    run_id = uuid.uuid4().hex[:16]
    status = "FAIL"
    trace_id = None
    raw_artifacts = []
    try:
        owner = LabResources(run_id)
        collector = lab_endpoint("otel-collector", 4317)
        backend = lab_endpoint("jaeger", 16686)
        os.environ.update(OTEL_EXPORTER_OTLP_ENDPOINT=collector, OTEL_EXPORTER_OTLP_PROTOCOL="grpc",
                          OTEL_TRACES_EXPORTER="otlp", OTEL_EXPORTER_OTLP_TIMEOUT="5", OTEL_SERVICE_NAME="rick-formal-api")
        from core.otel import configure_process_otel, stage_span, current_trace_context
        telemetry = configure_process_otel(service_name="rick-formal-driver")
        if telemetry.status != "CONFIGURED":
            raise ValueError("collector_exporter_not_configured")
        graph, scope, user = owner.graph()
        client = owner.serve_api(graph, scope, user)
        api_pid = owner.processes[-1].pid
        worker_proc = owner.start_worker(scope, user)
        with stage_span("lab.distributed_journey") as span:
            trace_id = format(span.get_span_context().trace_id, "032x")
            carrier = current_trace_context()
            content = "Segundo a fonte autorizada, o documento confirma o laboratório local. As citações no RICK usam fontes verificadas."
            uploaded = client.post("/api/v1/documents/upload", headers=carrier, json={
                "filename": "distributed.txt", "collection_id": scope["collection_id"], "content": content})
            if uploaded.status_code != 202:
                raise ValueError("http_upload_not_accepted")
            job_id = uploaded.json()["job_id"]
            deadline = time.monotonic() + 40
            final_job = {}
            while time.monotonic() < deadline:
                observed = client.get(f"/api/v1/ingestion/jobs/{job_id}", headers=carrier)
                if observed.status_code == 200:
                    final_job = observed.json()
                    if final_job.get("status") in {"published", "failed", "dead", "cancelled"}:
                        break
                await asyncio.sleep(.1)
            if final_job.get("status") != "published":
                raise ValueError("separate_worker_did_not_publish")
            answer = client.post("/api/v1/chat", headers=carrier,
                json={"message": "como funcionam as citacoes no rick", "conversation_id": "distributed-" + run_id})
            if answer.status_code != 200 or answer.json().get("metadata", {}).get("publication_validation") != "verified":
                raise ValueError("http_grounded_publication_not_verified")
        await asyncio.to_thread(worker_proc.wait, timeout=15)
        if worker_proc.returncode != 0 or api_pid == worker_proc.pid:
            raise ValueError("separate_worker_process_failed")
        telemetry.provider.force_flush(timeout_millis=7000)
        deadline = time.monotonic() + 20
        trace_result = None
        last_reason = "trace_not_observed"
        while time.monotonic() < deadline:
            try:
                with build_opener(_NoRedirect()).open(backend + "/api/traces/" + trace_id, timeout=3) as response:
                    payload = json.loads(response.read(512 * 1024 + 1))
                trace_result = inspect_graph(payload, trace_id)
                break
            except (OSError, ValueError) as error:
                last_reason = str(error) if isinstance(error, ValueError) else "trace_backend_unavailable"
            await asyncio.sleep(.25)
        if trace_result is None:
            raise ValueError(last_reason)
        raw_trace = ROOT / ".runtime/phase-3/formal-local" / run_id / "distributed-trace.json"
        raw_trace.parent.mkdir(parents=True, exist_ok=True)
        encoded_trace = json.dumps(payload, sort_keys=True, indent=2) + "\n"
        raw_trace.write_text(encoded_trace)
        raw_artifacts.append({"path": str(raw_trace.relative_to(ROOT)),
                              "sha256": hashlib.sha256(encoded_trace.encode()).hexdigest()})
        results.append({"status": "PASS", "name": "distributed_trace", **trace_result,
                        "api_pid": api_pid, "worker_pid": worker_proc.pid, "trace_id": trace_id})
        metrics = client.get("/api/v1/admin/metrics").json()
        results.append({"status": "PASS" if metrics.get("latency", {}).get("count", 0) > 0 else "FAIL",
            "name": "api_metrics_observed", "slo_status": metrics.get("slo", {}).get("status"),
            "samples": metrics.get("latency", {}).get("count")})
        status = "PASS" if all(row["status"] == "PASS" for row in results) else "FAIL"
    except Exception as error:
        results.append({"name": "journey", "status": "FAIL", "reason": str(error) if type(error) is ValueError else type(error).__name__})
    finally:
        if owner:
            try:
                await owner.close()
            except Exception:
                status = "FAIL"
                results.append({"name": "cleanup", "status": "FAIL"})
        if telemetry:
            telemetry.close()
    report = {"schema_version": "phase3-local-distributed-probe.v1", "status": status,
        "production_safe": False, "run_id": run_id, "results": results,
        "raw_artifacts": raw_artifacts,
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "limitations": ["Uses native product services and separate API/worker processes with a local provider fixture.",
            "Not the complete observability gate; does not ratify SLO/alerts or production safety."]}
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(report, sort_keys=True, indent=2) + "\n"
    output.with_name(f"distributed-{run_id}.json").write_text(encoded)
    output.write_text(encoded)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    report = asyncio.run(run(ROOT / ".runtime/phase-3/formal-local/distributed.json"))
    print(json.dumps({"status": report["status"], "production_safe": False}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
