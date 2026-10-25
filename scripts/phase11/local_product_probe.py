#!/usr/bin/env python3
"""Observe the real disposable product graph without claiming Phase 3 promotion.

Requires explicit local authorization and a local provider fixture. All data is
scoped to a fresh tenant. No installed schema or shared service is destroyed.
The complete golden crash matrix and HTTP/OIDC adversarial matrix remain the
responsibility of their formal gates, not this bounded integration probe.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit
import uuid
from urllib.request import HTTPRedirectHandler, build_opener

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.phase13.pyenv import source_paths

for source_path in reversed(source_paths()):
    sys.path.insert(0, str(source_path))

from scripts.state_of_art.release_integrity import capture_checkout


class ProbeBlocked(RuntimeError):
    """A stable reason code, with no endpoint or credential in its message."""


def local_target(raw: str, *, allow_private: bool = False) -> bool:
    """Accept literal loopback; private container IPs need explicit consent."""
    try:
        target = urlsplit(raw)
        if target.scheme not in {"http", "https", "redis", "rediss", "postgres", "postgresql"}:
            return False
        host = target.hostname or ""
        if host == "localhost":
            return True
        address = ipaddress.ip_address(host)
        return address.is_loopback or (
            allow_private and address.is_private
            and not address.is_unspecified and not address.is_link_local
            and not address.is_multicast
        )
    except ValueError:
        return False


def check_authority(settings) -> None:
    if os.environ.get("RICK_LOCAL_PROBES_AUTHORIZED") != "1":
        raise ProbeBlocked("local_probe_authority_missing")
    if settings.environment not in {"local", "dev", "test"}:
        raise ProbeBlocked("local_probe_refuses_production")
    if os.environ.get("RICK_LOCAL_PROVIDER_FIXTURE") != "1":
        raise ProbeBlocked("local_provider_fixture_required")
    private = os.environ.get("RICK_LOCAL_PROBE_ALLOW_PRIVATE") == "1"
    targets = [settings.external_database_dsn, settings.redis_url,
               settings.qdrant_url, settings.object_store_endpoint,
               settings.provider_base_url]
    if settings.embedding_base_url:
        targets.append(settings.embedding_base_url)
    if not all(local_target(target, allow_private=private) for target in targets):
        raise ProbeBlocked("explicit_local_service_targets_required")


def create_graph(run_id: str, *, scope: dict | None = None):
    from core.config import ApiSettings
    import psycopg
    from psycopg.types.json import Jsonb

    settings = ApiSettings.from_env()
    fixture_url = os.environ.get("RICK_LOCAL_MANAGED_FIXTURE_URL")
    if fixture_url:
        settings = replace(settings, provider_base_url=fixture_url,
                           external_chat_api_key="local-fixture", embedding_base_url="",
                           embedding_api_key="", embedding_provider_kind="",
                           provider_embedding_dimensions=2)
    check_authority(settings)
    scope = scope or {"tenant_id": f"ph3-{run_id}", "workspace_id": f"ws-{run_id}",
                      "collection_id": f"col-{run_id}"}
    user_id = f"probe-{run_id}"
    # Values are parameters, never interpolated SQL. These are disposable
    # product rows, not a shadow probe schema or an installed migration.
    with psycopg.connect(settings.external_database_dsn, connect_timeout=5) as connection:
        connection.execute("INSERT INTO rick_tenants(tenant_id,display_name) VALUES (%s,%s)",
                           (scope["tenant_id"], "Phase 3 synthetic probe"))
        connection.execute("INSERT INTO rick_users(user_id) VALUES (%s)", (user_id,))
        connection.execute(
            "INSERT INTO rick_memberships(tenant_id,user_id,workspace_id,role,authorized_collection_ids) "
            "VALUES (%s,%s,%s,'KNOWLEDGE_MANAGER',%s)",
            (scope["tenant_id"], user_id, scope["workspace_id"], Jsonb([scope["collection_id"]])))
        connection.execute(
            "INSERT INTO rick_collections(tenant_id,workspace_id,collection_id,title,created_by) "
            "VALUES (%s,%s,%s,%s,%s)",
            (*scope.values(), "Synthetic runtime fixture", user_id))
    graph = build_graph(settings, scope, user_id)
    return graph, scope, user_id


def build_graph(settings, scope: dict, user_id: str, *, identity=None, worker_id: str | None = None,
                worker_max_concurrency: int | None = None):
    """Reopen an already seeded disposable scope in another owned process."""
    from scripts.phase11.local_lab_composition import build
    from services.external_composition import build_external_providers

    check_authority(settings)
    inputs = replace(build(settings), created_by=user_id,
                     worker_scope=tuple(scope.values()), worker_id=worker_id or user_id,
                     worker_temp_root=str(ROOT / ".runtime/tmp" / user_id))
    # A fixture's login IP bucket must not consume the shared dev namespace.
    # Replicas of this synthetic tenant still share the actual Redis limiter
    # and leases; only unrelated diagnostic runs receive separate prefixes.
    from rick_locking import RedisNamespace, RedisRateLimiter, RedisLeaseClient
    namespace = RedisNamespace.global_scope(environment=settings.environment,
        prefix="rick-lab-" + hashlib.sha256(scope["tenant_id"].encode()).hexdigest()[:16])
    inputs = replace(inputs, rate_limit_namespace=namespace,
        rate_limiter=RedisRateLimiter(inputs.redis_client, namespace=namespace),
        lease=RedisLeaseClient(inputs.redis_client, namespace=namespace))
    if identity is not None:
        inputs = replace(inputs, identity=identity,
                         authorization_revalidator=identity.refresh_authorization_context)
    if worker_max_concurrency is not None:
        if type(worker_max_concurrency) is not int or not 1 <= worker_max_concurrency <= 4:
            raise ValueError("invalid_owned_worker_concurrency")
        inputs = replace(inputs, worker_max_concurrency=worker_max_concurrency)
    return build_external_providers(settings, inputs)


async def close_graph(graph) -> None:
    """Close each owned resource once; never stop a shared lab service."""
    errors = []
    seen = set()
    for resource in (graph.worker, graph._embedding_adapter, graph.ingestion,
                     getattr(graph, "object_store", None), getattr(graph, "vector_store", None),
                     graph.provider, graph.rate_limiter.redis_client):
        if resource is None:
            continue
        if id(resource) in seen:
            continue
        seen.add(id(resource))
        close = getattr(resource, "aclose", None) or getattr(resource, "close", None)
        if close:
            try:
                import inspect
                result = close()
                if inspect.isawaitable(result):
                    await result
            except Exception:
                errors.append("owned_resource_cleanup_failed")
    if errors:
        raise RuntimeError("owned_resource_cleanup_failed")


def candidate_dict(candidate) -> dict:
    if hasattr(candidate, "model_dump"):
        return candidate.model_dump()
    return dict(candidate)


def evidence_checks(graph, scope: dict, candidate: dict) -> list[dict]:
    from rick_evidence import EvidenceValidator, EvidenceValidationError
    from services.professor_backend import EvidenceDecisionGate

    validator = EvidenceValidator(authority=EvidenceDecisionGate._KnowledgeAuthority(graph.knowledge),
                                  require_authority=True)
    evidence = validator.issue(candidate, scope=scope)
    results = [{"name": "evidence.authoritative_positive", "status": "PASS"}]
    # An exception alone is insufficient: a valid positive control above must
    # resolve the very same row through PostgreSQL before any negative passes.
    mutations = {
        "cross-tenant-document": {"tenant_id": "other-tenant"},
        "unauthorized-collection": {"collection_id": "other-collection"},
        "stale-document-version": {"document_version": "stale-version"},
        "wrong-checksum": {"checksum": "sha256:" + "0" * 64},
        "unknown-chunk": {"chunk_id": "unknown-chunk"},
    }
    for name, mutation in mutations.items():
        try:
            issued = validator.issue({**candidate, **mutation}, scope=scope,
                        document_version=mutation.get("document_version"))
        except EvidenceValidationError:
            rejected = True
            disposition = "rejected"
        else:
            # The existing authority contract intentionally replaces an
            # untrusted checksum with the canonical checksum. Observe that
            # behavior explicitly, without calling normalization rejection.
            rejected = (name == "wrong-checksum" and issued.checksum == evidence.checksum
                        and issued.checksum != mutation["checksum"])
            disposition = "canonicalized" if rejected else "accepted"
        results.append({"name": name, "status": "PASS" if rejected else "FAIL",
                        "disposition": disposition})
    forged = evidence.model_copy(update={"evidence_id": "ev-forged-runtime"})
    rejected = not validator.validate_evidence(forged, expected_scope=scope).valid
    results.append({"name": "forged-evidence-id", "status": "PASS" if rejected else "FAIL"})
    return results


def _assert(name: str, condition: bool, **observed) -> dict:
    return {"name": name, "status": "PASS" if condition else "FAIL", **observed}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def trace_observation(payload: dict, trace_id: str) -> dict:
    """Count only spans actually read from the backend for this trace."""
    records = payload.get("data", [])
    spans = [span for record in records if isinstance(record, dict)
             for span in record.get("spans", []) if isinstance(span, dict)
             and span.get("traceID") == trace_id]
    names = sorted({span.get("operationName") for span in spans
                    if isinstance(span.get("operationName"), str)})
    ids = {span.get("spanID") for span in spans}
    linked = sum(any(ref.get("traceID") == trace_id and ref.get("spanID") in ids
                     for ref in span.get("references", []) if isinstance(ref, dict)) for span in spans)
    return _assert("collector_trace_delivery", bool(spans) and linked > 0,
                   trace_id=trace_id, spans=len(spans), linked_spans=linked, operations=names)


async def observe_trace(runtime, trace_id: str, backend: str) -> dict:
    runtime.provider.force_flush(timeout_millis=10000)
    deadline = time.monotonic() + 15
    observation = _assert("collector_trace_delivery", False, spans=0, linked_spans=0)
    while time.monotonic() < deadline:
        try:
            with build_opener(_NoRedirect()).open(backend.rstrip("/") + "/api/traces/" + trace_id, timeout=3) as response:
                payload = json.loads(response.read(512 * 1024 + 1))
            observation = trace_observation(payload, trace_id)
            if observation["status"] == "PASS":
                return observation
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        await asyncio.sleep(.25)
    return observation


async def exercise_graph(graph, scope: dict, user_id: str, run_id: str,
                         results: list[dict] | None = None) -> list[dict]:
    from rick_storage import ObjectScope

    fixture = (f"RICK synthetic runtime probe {run_id}. Segundo a fonte autorizada, "
               "o documento confirma o laboratório local. Publicação verificada preserva "
               "a linhagem do documento. Isolamento protege as evidências de cada tenant.\n").encode()
    checksum = "sha256:" + hashlib.sha256(fixture).hexdigest()
    key = f"probe-{run_id}"
    kwargs = {**scope, "filename": f"probe-{run_id}.txt", "idempotency_key": key}
    uploaded = graph.ingestion.submit_upload(fixture, **kwargs)
    replay = graph.ingestion.submit_upload(fixture, **kwargs)
    job = graph.queue.get_by_idempotency(**scope, idempotency_key=key)
    if results is None:
        results = []
    results.append(_assert("upload_and_replay", bool(job) and
                       uploaded["job_id"] == replay["job_id"] == job.job_id))
    if job is None:
        return results
    payload = dict(job.payload)
    object_scope = ObjectScope(tenant_id=scope["tenant_id"], workspace_id=scope["workspace_id"],
                               source_id=payload["object_source_id"])
    body = graph.object_store.get(object_scope, payload["object_key"], max_bytes=16384)
    results.append(_assert("object_integrity", body == fixture and payload["checksum"] == checksum))
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        graph.worker.run_once(wait=True)
        job = graph.queue.get_by_idempotency(**scope, idempotency_key=key)
        if job is not None and job.status in {"published", "failed", "cancelled", "dead"}:
            break
        await asyncio.sleep(.05)
    published = job is not None and job.status == "published"
    results.append(_assert("worker_publication", published,
                           state=getattr(job, "status", None),
                           error_code=getattr(job, "last_error", None)))
    if not published:
        return results
    public = graph.ingestion.get_status(job.job_id, tenant_id=scope["tenant_id"],
                                        workspace_id=scope["workspace_id"],
                                        allowed_collection_ids=[scope["collection_id"]])
    document_id = public["document_id"]
    document = graph.knowledge.get_document(document_id, tenant_id=scope["tenant_id"],
                                             workspace_id=scope["workspace_id"])
    chunks = graph.knowledge.get_chunks(document_id, tenant_id=scope["tenant_id"],
                                         workspace_id=scope["workspace_id"])
    results.append(_assert("postgres_lineage", document is not None and
        document.status == "published" and document.content_checksum.removeprefix("sha256:")
        == checksum.removeprefix("sha256:") and bool(chunks)
        and all(getattr(document, name) for name in (
            "document_version", "ingestion_version", "parser_version", "chunker_version",
            "embedding_model", "embedding_version", "object_ref", "created_at", "published_at"))))
    count = graph.vector_store.count_for_document(document_id, scope["collection_id"],
                      tenant_id=scope["tenant_id"], workspace_id=scope["workspace_id"])
    results.append(_assert("qdrant_projection", count == len(chunks), points=count, chunks=len(chunks)))
    foreign = graph.knowledge.get_document(document_id, tenant_id=f"foreign-{run_id}",
                                             workspace_id=scope["workspace_id"])
    foreign_chunks = graph.knowledge.get_chunks(document_id, tenant_id=f"foreign-{run_id}",
                                                  workspace_id=scope["workspace_id"])
    results.append(_assert("postgres_cross_tenant_read", foreign is None and not foreign_chunks))
    context = {"tenant_id": scope["tenant_id"], "workspace_id": scope["workspace_id"],
               "allowed_collection_ids": [scope["collection_id"]], "user_id": user_id,
               "permissions": ["sources.read", "chat.query", "history.read"]}
    query = "como funcionam as citacoes no rick"
    retrieved = graph.retrieval.retrieve(query=query, context=context, top_k=3)
    candidates = [candidate_dict(item) for item in retrieved.evidence]
    matching = next((item for item in candidates if item["document_id"] == document_id), None)
    results.append(_assert("retrieval_published_version", matching is not None))
    denied = graph.retrieval.retrieve(query=query,
             context={**context, "tenant_id": f"foreign-{run_id}"}, top_k=3)
    results.append(_assert("qdrant_cross_tenant_retrieval", not denied.evidence))
    if matching:
        results.extend(evidence_checks(graph, scope, matching))
    answer = await graph.chat_backend.generate(message=query, context=context,
                         conversation_id=f"probe-{run_id}", history=[])
    metadata = answer.get("metadata", {}) if isinstance(answer, dict) else getattr(answer, "metadata", {})
    # Publication revalidation is measured from the real Professor output;
    # fixture generation only proves the provider HTTP/citation contract.
    results.append(_assert("grounded_response_publication", metadata.get("publication_validation") == "verified",
                          evidence_status=metadata.get("evidence_status"),
                          decision_action=metadata.get("decision_action"),
                          decision_reason=metadata.get("decision_reason"),
                          publication_validation=metadata.get("publication_validation")))
    return results


async def run_probe(output: Path) -> dict:
    started = datetime.now(timezone.utc).isoformat()
    checkout = capture_checkout(ROOT)
    run_id = uuid.uuid4().hex[:16]
    graph = None
    telemetry = None
    results = []
    status = "FAIL"
    try:
        graph, scope, user_id = create_graph(run_id)
        collector = os.environ.get("RICK_LOCAL_TRACE_COLLECTOR", "")
        backend = os.environ.get("RICK_LOCAL_TRACE_BACKEND", "")
        if collector or backend:
            if not all(local_target(value, allow_private=os.environ.get("RICK_LOCAL_PROBE_ALLOW_PRIVATE") == "1")
                       for value in (collector, backend)):
                raise ProbeBlocked("local_trace_targets_required")
            from core.otel import configure_process_otel, stage_span
            os.environ.update(OTEL_TRACES_EXPORTER="otlp", OTEL_EXPORTER_OTLP_ENDPOINT=collector,
                              OTEL_EXPORTER_OTLP_PROTOCOL="grpc", OTEL_EXPORTER_OTLP_TIMEOUT="5")
            telemetry = configure_process_otel(service_name="rick-local-product-probe")
            if telemetry.status != "CONFIGURED":
                raise ProbeBlocked("local_trace_exporter_unavailable")
            with stage_span("lab.product_probe") as span:
                if span is None:
                    raise ProbeBlocked("local_trace_context_unavailable")
                trace_id = format(span.get_span_context().trace_id, "032x")
                await exercise_graph(graph, scope, user_id, run_id, results)
            results.append(await observe_trace(telemetry, trace_id, backend))
        else:
            await exercise_graph(graph, scope, user_id, run_id, results)
        status = "PASS" if results and all(item["status"] == "PASS" for item in results) else "FAIL"
    except ProbeBlocked as exc:
        status = "BLOCKED_EXTERNAL"
        results.append({"name": "configuration", "status": status, "reason": str(exc)})
    except Exception as exc:
        results.append({"name": "runtime", "status": "FAIL", "reason": type(exc).__name__})
    finally:
        if graph is not None:
            try:
                await close_graph(graph)
            except Exception:
                status = "FAIL"
                results.append({"name": "cleanup", "status": "FAIL"})
        if telemetry is not None:
            telemetry.close()
    after = capture_checkout(ROOT)
    if any(checkout.get(field) != after.get(field) for field in ("head", "fingerprint")):
        status = "FAIL"
        results.append({"name": "checkout_changed_during_probe", "status": "FAIL"})
    report = {
        "schema_version": "phase3-local-product-probe.v1", "run_id": run_id,
        "status": status, "production_safe": False, "promotable": False,
        "scope": "disposable-product-graph-integration", "results": results,
        "started_at": started, "finished_at": datetime.now(timezone.utc).isoformat(),
        "checkout": {key: after.get(key) for key in ("head", "tree", "status", "fingerprint")},
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "limitations": [
            "Uses real PostgreSQL/S3/Qdrant/Redis with a local HTTP provider fixture.",
            "Not a commit-bound formal golden or tenant runtime envelope.",
            "Does not prove the eleven golden fault points, HTTP/OIDC enumeration/timing isolation, or production quality.",
            "Wrong-checksum projection is canonicalized by the existing authority contract, not rejected by issuance.",
            "Optional trace delivery observes this graph and its worker thread, not an HTTP/OIDC request across separate API/worker processes.",
            "Synthetic tenant rows and artifacts are retained for inspection in the disposable lab.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(report, sort_keys=True, indent=2) + "\n"
    archive = output.with_name(f"{output.stem}-{run_id}{output.suffix}")
    archive.write_text(encoded, encoding="utf-8")
    output.write_text(encoded, encoding="utf-8")
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=".runtime/phase-3/local-closure/product-probe.json")
    parser.add_argument("--from-dev-compose", action="store_true")
    parser.add_argument("--provider-container")
    parser.add_argument("--local-provider-fixture", action="store_true")
    parser.add_argument("--managed-provider-fixture", action="store_true",
                        help="start the checked-in citation/embedding fixture on an owned loopback port")
    parser.add_argument("--allow-private-containers", action="store_true")
    parser.add_argument("--trace-collector-url")
    parser.add_argument("--trace-backend-url")
    args = parser.parse_args(argv)
    if args.from_dev_compose:
        if not (args.local_provider_fixture or args.managed_provider_fixture) or not args.provider_container:
            parser.error("--from-dev-compose requires --local-provider-fixture and --provider-container")
        from scripts.phase11.local_lab_environment import from_dev_compose
        try:
            os.environ.update(from_dev_compose(ROOT, provider_container=args.provider_container))
        except (ValueError, OSError, subprocess.TimeoutExpired):
            parser.error("canonical disposable lab configuration unavailable")
        os.environ["RICK_LOCAL_PROBES_AUTHORIZED"] = "1"
    if args.local_provider_fixture or args.managed_provider_fixture:
        os.environ["RICK_LOCAL_PROVIDER_FIXTURE"] = "1"
    if args.allow_private_containers:
        os.environ["RICK_LOCAL_PROBE_ALLOW_PRIVATE"] = "1"
    if args.trace_collector_url or args.trace_backend_url:
        os.environ["RICK_LOCAL_TRACE_COLLECTOR"] = args.trace_collector_url or ""
        os.environ["RICK_LOCAL_TRACE_BACKEND"] = args.trace_backend_url or ""
    from scripts.state_of_art.prepare_phase3_handoff import safe_file
    try:
        output = safe_file(ROOT, args.output)
    except (ValueError, TypeError):
        parser.error("unsafe local probe output")
    if not output.is_relative_to(ROOT / ".runtime/phase-3/local-closure") or output.name != "product-probe.json":
        parser.error("output must be named product-probe.json under .runtime/phase-3/local-closure")
    fixture_server = fixture_thread = None
    if args.managed_provider_fixture:
        from http.server import ThreadingHTTPServer
        from threading import Thread
        from scripts.phase11.local_citation_provider import Handler
        fixture_server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        fixture_thread = Thread(target=fixture_server.serve_forever, daemon=True)
        fixture_thread.start()
        os.environ["RICK_LOCAL_MANAGED_FIXTURE_URL"] = f"http://127.0.0.1:{fixture_server.server_port}/v1"
    try:
        report = asyncio.run(run_probe(output))
    finally:
        if fixture_server:
            fixture_server.shutdown()
            fixture_server.server_close()
            fixture_thread.join(timeout=5)
            os.environ.pop("RICK_LOCAL_MANAGED_FIXTURE_URL", None)
    print(json.dumps({"status": report["status"], "checks": len(report["results"]),
                      "output": args.output, "production_safe": False}))
    return {"PASS": 0, "FAIL": 1, "BLOCKED_EXTERNAL": 2}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
