"""Focused tests for the bounded Phase 3.9/3.10 observability gate."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading
from typing import Any
from urllib.parse import parse_qs, urlsplit
import uuid

import pytest


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.phase11 import observability_runtime_gate as gate


@dataclass
class _BackendState:
    incomplete_trace: bool = False
    traces: dict[str, list[dict[str, object]]] = field(default_factory=dict)


def _span(trace_id: str, span_id: str, name: str, parent_id: str | None) -> dict[str, object]:
    payload: dict[str, object] = {
        "traceID": trace_id,
        "spanID": span_id,
        "operationName": name,
        "tags": [{"key": "service.name", "value": "test-service"}],
    }
    if parent_id is not None:
        payload["references"] = [{"refType": "CHILD_OF", "spanID": parent_id}]
    return payload


def _full_trace(trace_id: str, *, incomplete: bool, initial_parent: str | None = None) -> list[dict[str, object]]:
    names = [
        "HTTP server",
        "auth.authenticate",
        "retrieval.search",
        "redis.store",
        "queue.enqueue",
        "worker.ingest",
        "provider.complete",
        "evidence.verify",
        "decision.answer",
    ]
    if incomplete:
        names = names[:1]
    spans: list[dict[str, object]] = []
    parent: str | None = initial_parent
    for name in names:
        span_id = uuid.uuid4().hex[:16]
        spans.append(_span(trace_id, span_id, name, parent))
        parent = span_id
    return spans


def _handler(state: _BackendState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, _format: str, *_args: object) -> None:
            return None

        def _send(self, status: int, body: bytes = b"{}", *, headers: dict[str, str] | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            if body:
                self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract.
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            if self.path == "/v1/traces":
                payload = json.loads(body.decode("utf-8"))
                trace_id = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["traceId"]
                span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
                state.traces[trace_id] = [{
                    "traceID": trace_id,
                    "spanID": span["spanId"],
                    "operationName": span["name"],
                }]
                self._send(200)
                return
            self._send(404)

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract.
            parsed = urlsplit(self.path)
            if parsed.path == "/pipeline":
                traceparent = self.headers.get("traceparent", "")
                trace_id = traceparent.split("-")[1]
                remote_parent = traceparent.split("-")[2]
                state.traces[trace_id] = _full_trace(
                    trace_id,
                    incomplete=state.incomplete_trace,
                    initial_parent=remote_parent,
                )
                self._send(
                    200,
                    headers={
                        "X-Request-ID": self.headers.get("X-Request-ID", ""),
                        "X-Correlation-ID": self.headers.get("X-Correlation-ID", ""),
                    },
                )
                return
            if parsed.path.startswith("/api/traces/"):
                trace_id = parsed.path.rsplit("/", 1)[-1]
                body = json.dumps({"data": [{"traceID": trace_id, "spans": state.traces.get(trace_id, [])}]}).encode()
                self._send(200, body)
                return
            if parsed.path == "/api/v1/query":
                query = parse_qs(parsed.query).get("query", [""])[0]
                metric_names = [aliases[0] for aliases in gate._METRIC_GROUPS.values()]
                if "rick_api_slo_status" in query:
                    result = [{"metric": {"__name__": "rick_api_slo_status", "status": "healthy"}, "value": ["1", "1"]}]
                elif "__name__=~" in query:
                    result = [{"metric": {"__name__": name}, "value": ["1", "1"]} for name in metric_names]
                else:
                    name = next((item for item in metric_names if item in query), metric_names[0])
                    result = [{"metric": {"__name__": name}, "value": ["1", "1"]}]
                body = json.dumps({"status": "success", "data": {"resultType": "vector", "result": result}}).encode()
                self._send(200, body)
                return
            if parsed.path == "/api/v1/rules":
                body = json.dumps({
                    "status": "success",
                    "data": {"groups": [{"name": "rick-runtime", "rules": [{"name": name} for name in gate._REQUIRED_ALERTS]}]},
                }).encode()
                self._send(200, body)
                return
            self._send(404)

    return Handler


@pytest.fixture()
def fake_runtime():
    state = _BackendState()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _output_path() -> Path:
    directory = ROOT / ".runtime/phase-3"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"test-observability-{uuid.uuid4().hex}.json"


def _read_and_remove(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    finally:
        path.unlink(missing_ok=True)


def test_external_gate_is_fail_closed_without_explicit_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "RICK_OBSERVABILITY_COLLECTOR_URL", "RICK_OTEL_COLLECTOR_URL", "RICK_OTEL_ENDPOINT",
        "RICK_OBSERVABILITY_BACKEND_URL", "RICK_OTEL_BACKEND_URL", "RICK_OBSERVABILITY_TRACE_BACKEND_URL",
        "RICK_OTEL_TRACE_BACKEND_URL", "RICK_JAEGER_QUERY_URL", "RICK_TEMPO_QUERY_URL",
        "RICK_OBSERVABILITY_METRICS_BACKEND_URL", "RICK_METRICS_BACKEND_URL", "RICK_PROMETHEUS_URL",
        "RICK_OBSERVABILITY_API_URL", "RICK_API_URL", "RICK_OBSERVABILITY_PROBE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    output = _output_path()
    code = gate.main(["--mode", "external", "--output", str(output)])
    payload = _read_and_remove(output)
    assert code == 2
    assert payload["status"] == gate.BLOCKED_EXTERNAL
    assert payload["runtime_claim"] is False
    assert any(item["name"] == "distributed-observability-runtime" and item["result"] == gate.BLOCKED_EXTERNAL for item in payload["results"])


def test_observability_json_boundary_rejects_duplicate_fields() -> None:
    response = gate.HttpResponse(
        status=200,
        headers={"content-type": "application/json"},
        body=b'{"status":"success","status":"forged"}',
    )
    with pytest.raises(gate._RuntimeAssertionError, match="trace_json_invalid"):
        gate._json(response, label="trace")


def test_local_mode_runs_real_contracts_but_does_not_claim_runtime() -> None:
    output = _output_path()
    code = gate.main(["--local", "--output", str(output)])
    payload = _read_and_remove(output)
    results = {item["name"]: item for item in payload["results"]}
    assert code == 2
    assert payload["status"] == gate.BLOCKED_EXTERNAL
    assert payload["runtime_claim"] is False
    assert results["adversarial-redaction"]["result"] == gate.PASS
    assert results["local-metrics-slo"]["result"] == gate.PASS
    assert results["backup-restore-contract"]["result"] == gate.PASS
    assert results["distributed-observability-runtime"]["result"] == gate.BLOCKED_EXTERNAL


def test_external_gate_validates_collector_trace_chain_metrics_and_alerts(fake_runtime) -> None:
    base, _state = fake_runtime
    output = _output_path()
    code = gate.main([
        "--mode", "external",
        "--collector-url", base + "/v1/traces",
        "--trace-backend-url", base + "/api/traces",
        "--metrics-backend-url", base,
        "--alerts-url", base,
        "--probe-url", base + "/pipeline",
        "--timeout", "1",
        "--poll-timeout", "1",
        "--poll-interval", ".01",
        "--output", str(output),
    ])
    payload = _read_and_remove(output)
    results = {item["name"]: item for item in payload["results"]}
    assert code == 0
    assert payload["status"] == gate.PASS
    assert payload["runtime_claim"] is True
    assert payload["production_safe"] is False
    assert results["collector-ingest"]["result"] == gate.PASS
    assert results["collector-backend-trace"]["result"] == gate.PASS
    assert results["distributed-trace-propagation"]["result"] == gate.PASS
    assert results["metrics-slo-backend"]["result"] == gate.PASS
    assert results["alerts-loaded"]["result"] == gate.PASS


def test_external_gate_rejects_trace_missing_a_required_stage(fake_runtime) -> None:
    base, state = fake_runtime
    state.incomplete_trace = True
    output = _output_path()
    code = gate.main([
        "--collector-url", base + "/v1/traces",
        "--trace-backend-url", base + "/api/traces",
        "--metrics-backend-url", base,
        "--alerts-url", base,
        "--probe-url", base + "/pipeline",
        "--timeout", "1",
        "--poll-timeout", ".2",
        "--poll-interval", ".01",
        "--output", str(output),
    ])
    payload = _read_and_remove(output)
    results = {item["name"]: item for item in payload["results"]}
    assert code == 1
    assert payload["status"] == gate.FAIL
    assert payload["runtime_claim"] is False
    assert results["distributed-trace-propagation"]["result"] == gate.FAIL


def test_endpoint_contract_rejects_credentials_and_nonlocal_without_authority() -> None:
    with pytest.raises(gate._InvalidConfigurationError):
        gate._safe_endpoint(
            "http://user:password@127.0.0.1:4318",
            label="collector",
            allow_nonlocal=False,
            require_tls=False,
        )
    with pytest.raises(gate._BlockedExternalError):
        gate._safe_endpoint(
            "http://example.test:4318",
            label="collector",
            allow_nonlocal=False,
            require_tls=False,
        )


def test_trace_requires_stage_ancestry_and_remote_http_parent() -> None:
    trace_id = "1" * 32
    remote_parent = "2" * 16
    spans = _full_trace(trace_id, incomplete=False, initial_parent=remote_parent)
    spans[2]["references"] = [{"refType": "CHILD_OF", "spanID": spans[0]["spanID"]}]
    with pytest.raises(gate._RuntimeAssertionError, match="trace_stage_chain_invalid"):
        gate._validate_trace(
            {"data": [{"traceID": trace_id, "spans": spans}]},
            expected_trace_id=trace_id,
            expected_remote_parent_id=remote_parent,
        )


def test_trace_redaction_allows_tokenizer_but_rejects_credential_material() -> None:
    assert gate._trace_payload_is_redacted({"name": "provider.tokenizer"}) is True
    assert gate._trace_payload_is_redacted({"authorization": "Bearer phase3-secret"}) is False


def test_prometheus_parser_reads_standard_nested_metric_labels() -> None:
    values = gate._prometheus_values({
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [{"metric": {"__name__": "rick_api_slo_status", "status": "healthy"}, "value": ["1", "1"]}],
        },
    })
    assert values == [({"__name__": "rick_api_slo_status", "status": "healthy"}, 1.0)]
