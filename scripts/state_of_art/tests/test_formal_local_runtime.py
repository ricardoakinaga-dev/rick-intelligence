import asyncio
import json
from types import SimpleNamespace

import pytest

from scripts.phase11.local_distributed_probe import inspect_graph
from scripts.phase11 import golden_runtime_gate as golden
from scripts.phase11.local_golden_runtime import StageTrace, Hooks, InjectedFailure
from scripts.phase11.local_product_probe import close_graph


def test_owned_graph_closes_stores_after_worker_and_continues_after_failure():
    calls = []
    class Resource:
        def __init__(self, name):
            self.name = name
        def close(self):
            calls.append(self.name)
            if self.name == "object":
                raise RuntimeError("synthetic-close-failure")
    worker, bridge, ingestion, objects, vectors, provider, redis = [Resource(name) for name in
        ("worker", "bridge", "ingestion", "object", "vector", "provider", "redis")]
    graph = SimpleNamespace(worker=worker, _embedding_adapter=bridge, ingestion=ingestion,
        object_store=objects, vector_store=vectors, provider=provider,
        rate_limiter=SimpleNamespace(redis_client=redis))
    with pytest.raises(RuntimeError, match="owned_resource_cleanup_failed"):
        asyncio.run(close_graph(graph))
    assert calls == ["worker", "bridge", "ingestion", "object", "vector", "provider", "redis"]


def trace_graph():
    trace = "a" * 32
    names = ["driver", "HTTP POST", "auth.authorization", "queue.enqueue", "worker.ingestion",
             "provider.embedding", "retrieval", "stores.retrieval", "evidence.validation", "decision.policy"]
    # Auth and retrieval are legitimate siblings in one request, not fake
    # recursively nested phases. The queue -> worker edge is mandatory.
    parents = [None, 0, 1, 1, 3, 4, 1, 6, 1, 1]
    spans = []
    for index, (name, parent) in enumerate(zip(names, parents)):
        span = {"traceID": trace, "spanID": f"{index + 1:016x}", "operationName": name,
                "processID": "worker" if index in (4, 5) else "api"}
        if parent is not None:
            span["references"] = [{"refType": "CHILD_OF", "traceID": trace, "spanID": f"{parent + 1:016x}"}]
        spans.append(span)
    return trace, {"data": [{"spans": spans, "processes": {
        "api": {"serviceName": "rick-formal-api"}, "worker": {"serviceName": "rick-formal-worker"}}}]}


def test_distributed_graph_accepts_connected_dag_with_queue_handoff():
    trace, payload = trace_graph()
    result = inspect_graph(payload, trace)
    assert result["stage_count"] == 9
    assert result["worker_descends_from_queue"]


@pytest.mark.parametrize("damage", ["sibling_worker", "wrong_trace", "missing_parent", "cycle", "duplicate", "one_service", "sensitive"])
def test_distributed_graph_rejects_unproven_causality_and_sensitive_data(damage):
    trace, payload = trace_graph()
    spans = payload["data"][0]["spans"]
    if damage == "sibling_worker":
        spans[4]["references"][0]["spanID"] = spans[1]["spanID"]
    elif damage == "wrong_trace":
        spans[-1]["traceID"] = "b" * 32
    elif damage == "missing_parent":
        spans[-1]["references"][0]["spanID"] = "f" * 16
    elif damage == "cycle":
        spans[1]["references"][0]["spanID"] = spans[2]["spanID"]
    elif damage == "duplicate":
        spans.append(dict(spans[-1]))
    elif damage == "one_service":
        payload["data"][0]["processes"].pop("worker")
    else:
        spans[-1]["authorization"] = "Bearer private-value"
    with pytest.raises(ValueError):
        inspect_graph(payload, trace)


def test_golden_invocation_does_not_bind_positional_parameter_twice():
    observed = []
    def target(document, collection, *, tenant):
        observed.append((document, collection, tenant))
        return 3
    assert asyncio.run(golden._invoke(target, "doc", "col", collection="col", tenant="tenant")) == 3
    assert observed == [("doc", "col", "tenant")]


def test_golden_invocation_does_not_retry_internal_type_error():
    calls = []
    def target(value):
        calls.append(value)
        raise TypeError("inside-port")
    with pytest.raises(TypeError, match="inside-port"):
        asyncio.run(golden._invoke(target, "value", value="duplicate"))
    assert calls == ["value"]


def test_stage_trace_records_actual_errors_and_fault_hook_requires_selected_point():
    trace = StageTrace()
    hooks = Hooks()
    hooks.hit("before_publish")
    assert hooks.hits == 0
    hooks.point = "before_publish"
    with pytest.raises(InjectedFailure):
        with trace.operation("publish"):
            hooks.hit("before_publish")
    assert hooks.hits == 1
    assert trace.snapshot()[0]["status"] == "FAIL"


def test_golden_closes_injected_runtime_after_preflight_failure(tmp_path):
    calls = []
    loops = []
    async def preflight():
        loops.append(asyncio.get_running_loop())
        return False
    async def cleanup():
        assert asyncio.get_running_loop() is loops[0]
        calls.append("closed")
    report = golden.run_gate(root=tmp_path, output="gate.json", dependencies=golden.GoldenRuntime(
        authorized=True, external=True, preflight=preflight, cleanup=cleanup))
    assert report["status"] != "PASS"
    assert calls == ["closed"]
    assert any(row["name"] == "runtime_cleanup" and row["result"] == "PASS" for row in report["results"])


def test_golden_accepts_evidence_builder_that_also_exposes_required_validation():
    from rick_evidence import EvidenceValidator
    scope = {"tenant_id": "tenant", "workspace_id": "workspace", "collection_id": "collection"}
    candidate = {**scope, "document_id": "document", "document_version": "version",
                 "chunk_id": "chunk", "checksum": "sha256:fixture", "text": "Verified source content.",
                 "source": "fixture.txt", "retrieval_score": .9}
    runtime = golden.GoldenRuntime(
        evidence=EvidenceValidator(), retrieval=SimpleNamespace(retrieve=lambda **kwargs: {"evidence": [candidate]}))
    results, bundle, candidates = asyncio.run(golden._retrieve_evidence(
        runtime, golden.SyntheticFixture(), scope=scope, document=SimpleNamespace(document_id="document"),
        chunks=[SimpleNamespace(chunk_id="chunk", checksum="sha256:fixture")],
        document_version="version", checksum="sha256:fixture", timeout=1))
    assert bundle is not None
    assert candidates == [candidate]
    assert all(result.result == golden.PASS for result in results)


@pytest.mark.parametrize("damage", [None, "receipt", "duplicates", "projection", "retirement", "uncommitted", "boolean_count"])
def test_after_commit_fault_requires_durable_success_and_exactly_one_replay(damage):
    baseline = {"document_version": "old", "checksum": "sha256:old"}
    precommit = {"status": "PASS", "injected": True, "failed": True, "last_verified_preserved": True,
                 "published_version": "old", "published_checksum": "sha256:old", "replay_verified": True}
    committed = {"status": "PASS", "publication_outcome": "committed", "injected": True,
        "failed": False, "replay_verified": True, "receipt_bound_to_job": True,
        "projection_consistent": True, "previous_version_retired": True, "new_version_published": True,
        "point_count": 1, "chunk_count": 1, "succeeded_attempts": 1,
        "committed_document_id": "new-document", "committed_version": "new", "committed_checksum": "sha256:new"}
    if damage == "receipt":
        committed["receipt_bound_to_job"] = False
    elif damage == "duplicates":
        committed["succeeded_attempts"] = 2
    elif damage == "projection":
        committed["projection_consistent"] = False
    elif damage == "retirement":
        committed["previous_version_retired"] = False
    elif damage == "uncommitted":
        committed["publication_outcome"] = "pending"
    elif damage == "boolean_count":
        committed["chunk_count"] = True
    matrix = {point: dict(precommit) for point in golden.FAILURE_POINTS}
    matrix["after_publish"] = committed
    rows, all_pass = golden.evaluate_failure_matrix(matrix, baseline)
    assert all_pass is (damage is None)
    assert rows["after_publish"].result == (golden.PASS if damage is None else golden.FAIL)


def test_pending_publication_recovery_must_prove_original_baseline_survived():
    baseline = {"document_version": "old", "checksum": "sha256:old"}
    row = {"status": "PASS", "injected": True, "failed": True, "last_verified_preserved": True,
           "published_version": "old", "published_checksum": "sha256:old", "replay_verified": True}
    matrix = {point: dict(row) for point in golden.FAILURE_POINTS}
    recovered = {**row, "publication_outcome": "committed", "failed": False, "new_version_published": True,
        "receipt_bound_to_job": True, "projection_consistent": True, "previous_version_retired": True,
        "point_count": 1, "chunk_count": 1, "succeeded_attempts": 1,
        "committed_document_id": "new-document", "committed_version": "new", "committed_checksum": "sha256:new",
        "recovered_from_pending": True, "baseline_preserved_while_pending": True}
    matrix["before_publish"] = recovered
    assert golden.evaluate_failure_matrix(matrix, baseline)[1] is True
    recovered["baseline_preserved_while_pending"] = False
    assert golden.evaluate_failure_matrix(matrix, baseline)[1] is False
