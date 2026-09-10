#!/usr/bin/env python3
"""Run the bounded Phase 3.9/3.10 observability runtime gate.

The gate has two deliberately different scopes:

* ``--mode local`` runs the real, dependency-light local contracts (the
  canonical redactor, API telemetry, SLO evaluator and the existing file
  backup/restore harness).  It is useful for fast feedback, but it always
  remains ``BLOCKED_EXTERNAL`` because no distributed runtime was observed.
* ``--mode external`` requires explicit OTLP/HTTP collector, trace backend,
  Prometheus-compatible metrics backend and an API pipeline probe.  It sends
  one bounded OTLP probe, exercises the configured API boundary with a W3C
  trace context, queries the configured backends, and checks the complete
  HTTP -> auth -> retrieval -> stores -> queue -> worker -> provider ->
  evidence -> decision trace.  Missing or unreachable runtime authority is
  never converted into a pass.

The script is intentionally dependency-light and safe to run from a clean
checkout.  It never prints configured URLs, headers, response bodies,
credentials, request payloads or backend exception text.  A successful run is
evidence for this exact bounded procedure only; it is not a promotion or
production approval.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import importlib.util
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import SplitResult, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import uuid


ROOT = Path(__file__).resolve().parents[2]

try:
    from scripts.state_of_art.json_boundary import load_json, loads_json
except ModuleNotFoundError:  # Direct execution from the scripts/phase11 directory.
    sys.path.insert(0, str(ROOT))
    from scripts.state_of_art.json_boundary import load_json, loads_json

DEFAULT_OUTPUT = ".runtime/phase-3/observability-runtime-gate.json"
RAW_MAX_BYTES = 512 * 1024
PROBE_MAX_BYTES = 64 * 1024
PROBE_MAX_HEADERS = 32
PROBE_MAX_HEADER_VALUE = 2 * 1024
PASS = "PASS"
FAIL = "FAIL"
BLOCKED_EXTERNAL = "BLOCKED_EXTERNAL"
NOT_RUN = "NOT_RUN"
NOT_AVAILABLE = "NOT_AVAILABLE"
PARTIAL = "PARTIAL"

REQUIRED_TRACE_STAGES = (
    "http",
    "auth",
    "retrieval",
    "stores",
    "queue",
    "worker",
    "provider",
    "evidence",
    "decision",
)

_TRACE_STAGE_ALIASES: dict[str, tuple[str, ...]] = {
    "http": ("http", "server", "request", "api"),
    "auth": ("auth", "authentication", "authorization", "identity", "session"),
    "retrieval": ("retrieval", "retrieve", "search", "rerank"),
    "stores": (
        "store", "storage", "object_store", "object-store", "s3", "postgres",
        "database", "db", "redis", "qdrant", "vector_store", "vector-store",
    ),
    "queue": ("queue", "enqueue", "dequeue", "job", "outbox"),
    "worker": ("worker", "ingestion", "parser", "chunk", "embedding"),
    "provider": ("provider", "llm", "model", "completion", "embedding"),
    "evidence": ("evidence", "citation", "grounding", "verify"),
    "decision": ("decision", "professor", "policy", "abstain", "answer"),
}

_METRIC_GROUPS: dict[str, tuple[str, ...]] = {
    "http_requests": ("rick_api_http_requests_total",),
    "http_errors": ("rick_api_http_errors_total",),
    "http_latency_p50": ("rick_api_http_latency_ms_p50",),
    "http_latency_p95": ("rick_api_http_latency_ms_p95",),
    "http_latency_p99": (
        "rick_api_http_latency_ms_p99",
        "rick_api_http_latency_ms{quantile=\"0.99\"}",
    ),
    "queue_depth": (
        "rick_queue_depth", "rick_worker_queue_depth", "rick_api_queue_depth",
    ),
    "worker_active": (
        "rick_worker_active", "rick_worker_active_total", "rick_worker_jobs_active",
    ),
    "worker_failures": (
        "rick_worker_failures_total", "rick_api_worker_failures_total",
        "rick_api_worker_jobs_total{status=\"failed\"}",
    ),
    "dead_letter": (
        "rick_worker_dead_letter_total", "rick_api_worker_dead_letter_total",
        "rick_api_worker_jobs_total{status=\"dead\"}",
    ),
    "redis_latency": (
        "rick_redis_latency_ms_p95", "rick_api_redis_latency_ms_p95",
        "rick_redis_operation_latency_ms_p95",
    ),
    "qdrant_latency": (
        "rick_qdrant_latency_ms_p95", "rick_api_qdrant_latency_ms_p95",
        "rick_vector_store_latency_ms_p95",
    ),
    "retrieval_latency": (
        "rick_api_retrieval_latency_ms_count", "rick_api_retrieval_latency_ms_p95",
        "rick_retrieval_latency_ms_p95",
    ),
    "provider_ttft": (
        "rick_api_chat_stream_ttft_ms_p95", "rick_provider_ttft_ms_p95",
        "rick_provider_time_to_first_token_ms_p95",
    ),
    "tokens_per_second": (
        "rick_provider_tokens_per_second", "rick_api_provider_tokens_per_second",
    ),
    "ingestion_time": (
        "rick_ingestion_duration_ms_p95", "rick_worker_ingestion_duration_ms_p95",
    ),
    "embedding_throughput": (
        "rick_embedding_throughput", "rick_worker_embedding_throughput",
    ),
    "citation_support": (
        "rick_citation_support", "rick_api_citation_support",
        "rick_citation_support_ratio",
    ),
    "abstention_rate": (
        "rick_abstention_rate", "rick_api_abstention_rate",
    ),
}

_REQUIRED_ALERTS = (
    "RickApiReadinessMissing",
    "RickWorkerDeadLetterGrowth",
    "RickApiErrorBudgetBurn",
    "RickRetrievalLatencyP95",
    "RickProviderFailureGrowth",
    "RickApiSloBreach",
    "RickApiSloNoData",
)

_SENSITIVE_TEXT = re.compile(
    r"(?<![A-Za-z0-9])(?:password|passphrase|secret|token|api[_-]?key|access[_-]?key|"
    r"private[_-]?key|authorization|cookie|credential|bearer)(?![A-Za-z0-9])"
    r"(?:\s*[:=]\s*|\s+)[^\s,;]+",
    re.IGNORECASE,
)
_SENSITIVE_KEY = re.compile(
    r"(?:(?<![A-Za-z0-9])(?:password|passphrase|secret|token|api[_-]?key|access[_-]?key|"
    r"private[_-]?key|authorization|cookie|credential|raw_response|request_body|"
    r"response_body)(?![A-Za-z0-9]))",
    re.IGNORECASE,
)
_URL_WITH_USERINFO_OR_QUERY_SECRET = re.compile(
    r"(?:[A-Za-z][A-Za-z0-9+.-]*://)[^\s/@]+:[^\s/@]+@|"
    r"[?&](?:token|password|secret|api[_-]?key|access[_-]?key|credential|authorization)=",
    re.IGNORECASE,
)
_HEX_TRACE_ID = re.compile(r"^[0-9a-f]{32}$", re.IGNORECASE)
_HEX_SPAN_ID = re.compile(r"^[0-9a-f]{16}$", re.IGNORECASE)
_HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")


class _BlockedExternalError(RuntimeError):
    """The requested external runtime is absent or not reachable."""


class _InvalidConfigurationError(RuntimeError):
    """The caller supplied a configuration that violates the gate contract."""


class _RuntimeAssertionError(RuntimeError):
    """A configured runtime responded but defeated a required assertion."""


@dataclass(frozen=True, slots=True)
class GateResult:
    """One typed check result; details are safe, stable and bounded."""

    name: str
    result: str
    detail: str = ""
    required: bool = True
    scope: str = "local-contract"

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "result": self.result,
            "detail": self.detail,
            "required": self.required,
            "scope": self.scope,
        }


@dataclass(frozen=True, slots=True)
class Endpoint:
    """Validated endpoint retained only in process memory."""

    raw: str
    parsed: SplitResult
    label: str

    @property
    def tls(self) -> bool:
        return self.parsed.scheme == "https"

    def report(self) -> dict[str, object]:
        try:
            port = self.parsed.port
        except ValueError:
            port = None
        return {
            "configured": True,
            "scheme": self.parsed.scheme,
            "host_scope": "loopback" if _is_loopback(self.parsed.hostname or "") else "nonloopback",
            "port_configured": port is not None,
            "path_configured": bool(self.parsed.path and self.parsed.path != "/"),
            "tls": self.tls,
        }


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class _NoRedirect(HTTPRedirectHandler):
    """Do not allow a configured service to redirect the probe elsewhere."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def _env_first(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def _is_loopback(hostname: str) -> bool:
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _safe_endpoint(
    value: str,
    *,
    label: str,
    allow_nonlocal: bool,
    require_tls: bool,
) -> Endpoint:
    if not isinstance(value, str) or not value.strip():
        raise _BlockedExternalError(f"{label}_missing")
    raw = value.strip().rstrip("/")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in raw):
        raise _InvalidConfigurationError(f"{label}_control_character")
    try:
        parsed = urlsplit(raw)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        del exc
        raise _InvalidConfigurationError(f"{label}_malformed") from None
    if parsed.scheme not in {"http", "https"} or not hostname or port == 0:
        raise _InvalidConfigurationError(f"{label}_http_url_required")
    if parsed.username is not None or parsed.password is not None:
        raise _InvalidConfigurationError(f"{label}_userinfo_forbidden")
    if parsed.fragment:
        raise _InvalidConfigurationError(f"{label}_fragment_forbidden")
    if parsed.query:
        # All query parameters used by this gate are added after validation.
        # Rejecting caller-provided queries prevents credentials from hiding in
        # a URL that later becomes evidence metadata.
        raise _InvalidConfigurationError(f"{label}_query_forbidden")
    if not allow_nonlocal and not _is_loopback(hostname):
        raise _BlockedExternalError(f"{label}_nonlocal_requires_authority")
    if require_tls and parsed.scheme != "https":
        raise _InvalidConfigurationError(f"{label}_tls_required")
    return Endpoint(raw=raw, parsed=parsed, label=label)


def _replace_path(endpoint: Endpoint, path: str) -> str:
    parsed = endpoint.parsed
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _http_request(
    endpoint: str,
    *,
    method: str,
    timeout: float,
    body: bytes | None = None,
    headers: Mapping[str, str] | None = None,
) -> HttpResponse:
    if body is not None and len(body) > RAW_MAX_BYTES:
        raise _InvalidConfigurationError("request_body_too_large")
    request_headers = {str(key): str(value) for key, value in (headers or {}).items()}
    request = Request(endpoint, data=body, headers=request_headers, method=method)
    response: object | None = None
    opener = build_opener(_NoRedirect())
    try:
        try:
            response = opener.open(request, timeout=timeout)
        except HTTPError as error:
            response = error
        except (OSError, TimeoutError, URLError) as exc:
            del exc
            raise _BlockedExternalError("http_transport_unavailable") from None
        status = getattr(response, "status", None)
        if status is None:
            status = getattr(response, "code", None)
        if type(status) is not int:
            raise _RuntimeAssertionError("http_response_invalid")
        response_headers = getattr(response, "headers", None)
        items = getattr(response_headers, "items", None)
        reader = getattr(response, "read", None)
        if not callable(items) or not callable(reader):
            raise _RuntimeAssertionError("http_response_invalid")
        body_bytes = reader(RAW_MAX_BYTES + 1)
        if not isinstance(body_bytes, bytes):
            raise _RuntimeAssertionError("http_response_body_invalid")
        if len(body_bytes) > RAW_MAX_BYTES:
            raise _RuntimeAssertionError("http_response_body_too_large")
        return HttpResponse(
            status=status,
            headers={str(key).lower(): str(value) for key, value in items()},
            body=body_bytes,
        )
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass


def _json(response: HttpResponse, *, label: str) -> Mapping[str, object]:
    try:
        value = loads_json(response.body)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        del exc
        raise _RuntimeAssertionError(f"{label}_json_invalid") from None
    if not isinstance(value, Mapping):
        raise _RuntimeAssertionError(f"{label}_object_required")
    return value


def _new_trace_id() -> str:
    return uuid.uuid4().hex


def _new_span_id() -> str:
    return uuid.uuid4().hex[:16]


def _traceparent(trace_id: str, span_id: str) -> str:
    if not _HEX_TRACE_ID.fullmatch(trace_id) or not _HEX_SPAN_ID.fullmatch(span_id):
        raise ValueError("invalid generated trace context")
    return f"00-{trace_id}-{span_id}-01"


def _collector_trace_payload(trace_id: str, span_id: str) -> bytes:
    now = str(time.time_ns())
    payload = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "rick-observability-gate"}},
                        {"key": "deployment.environment", "value": {"stringValue": "phase3-gate"}},
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "rick.phase3.observability", "version": "1"},
                        "spans": [
                            {
                                "traceId": trace_id,
                                "spanId": span_id,
                                "name": "rick.gate.collector_probe",
                                "kind": 1,
                                "startTimeUnixNano": now,
                                "endTimeUnixNano": str(time.time_ns()),
                                "status": {"code": 1},
                            }
                        ],
                    }
                ],
            }
        ]
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _send_collector_probe(endpoint: Endpoint, *, timeout: float) -> str:
    trace_id = _new_trace_id()
    body = _collector_trace_payload(trace_id, _new_span_id())
    response = _http_request(
        endpoint.raw if endpoint.parsed.path not in {"", "/"} else _replace_path(endpoint, "/v1/traces"),
        method="POST",
        timeout=timeout,
        body=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    if response.status not in {200, 201, 202}:
        raise _RuntimeAssertionError("collector_rejected_otlp_probe")
    return trace_id


def _load_probe_body(args: argparse.Namespace) -> bytes | None:
    body_file = getattr(args, "probe_body_file", None)
    body_text = getattr(args, "probe_body", None)
    if body_file and body_text is not None:
        raise _InvalidConfigurationError("probe_body_sources_conflict")
    if body_file:
        try:
            body = Path(body_file).read_bytes()
        except (OSError, ValueError) as exc:
            del exc
            raise _InvalidConfigurationError("probe_body_file_unreadable") from None
    elif body_text is not None:
        if not isinstance(body_text, str):
            raise _InvalidConfigurationError("probe_body_invalid")
        body = body_text.encode("utf-8")
    else:
        return None
    if len(body) > PROBE_MAX_BYTES:
        raise _InvalidConfigurationError("probe_body_too_large")
    return body


def _probe_headers(args: argparse.Namespace, trace_id: str, span_id: str) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "traceparent": _traceparent(trace_id, span_id),
        "X-Request-ID": f"phase3-observability-{uuid.uuid4().hex[:16]}",
        "X-Correlation-ID": f"phase3-correlation-{uuid.uuid4().hex[:16]}",
    }
    raw_headers = tuple(getattr(args, "probe_header", ()) or ())
    if len(raw_headers) > PROBE_MAX_HEADERS:
        raise _InvalidConfigurationError("too_many_probe_headers")
    seen_names = {name.lower() for name in headers}
    for raw in raw_headers:
        if not isinstance(raw, str) or "=" not in raw:
            raise _InvalidConfigurationError("probe_header_invalid")
        name, value = raw.split("=", 1)
        if (
            not _HEADER_NAME.fullmatch(name)
            or not value
            or len(name) > 128
            or len(value) > PROBE_MAX_HEADER_VALUE
            or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value)
            or name.lower() in {"traceparent", "x-request-id", "x-correlation-id"}
            or name.lower() in seen_names
        ):
            raise _InvalidConfigurationError("probe_header_invalid")
        headers[name] = value
        seen_names.add(name.lower())
    return headers


def _probe_url(args: argparse.Namespace, api_endpoint: Endpoint | None) -> Endpoint:
    raw = getattr(args, "probe_url", None) or _env_first("RICK_OBSERVABILITY_PROBE_URL")
    if not raw and api_endpoint is not None:
        raw = _replace_path(api_endpoint, "/health/live")
    if not raw:
        raise _BlockedExternalError("pipeline_probe_missing")
    return _safe_endpoint(
        raw,
        label="probe",
        allow_nonlocal=bool(args.allow_nonlocal),
        require_tls=bool(args.require_tls),
    )


def _probe_api(endpoint: Endpoint, args: argparse.Namespace) -> tuple[str, str, str]:
    trace_id = _new_trace_id()
    span_id = _new_span_id()
    headers = _probe_headers(args, trace_id, span_id)
    body = _load_probe_body(args)
    if body is not None:
        headers.setdefault("Content-Type", "application/json")
    response = _http_request(
        endpoint.raw,
        method=str(getattr(args, "probe_method", "GET")),
        timeout=float(args.timeout),
        body=body,
        headers=headers,
    )
    if not 200 <= response.status < 400:
        raise _RuntimeAssertionError("pipeline_probe_rejected")
    if response.headers.get("x-request-id") != headers["X-Request-ID"]:
        raise _RuntimeAssertionError("request_id_not_echoed")
    if response.headers.get("x-correlation-id") != headers["X-Correlation-ID"]:
        raise _RuntimeAssertionError("correlation_id_not_echoed")
    return trace_id, headers["X-Request-ID"], span_id


def _trace_query_url(endpoint: Endpoint, trace_id: str) -> str:
    raw = endpoint.raw
    if "{trace_id}" in raw:
        return raw.replace("{trace_id}", trace_id)
    parsed = endpoint.parsed
    path = parsed.path.rstrip("/")
    if path.endswith("/api/traces") or path.endswith("/traces"):
        path = path + "/" + trace_id
        return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))
    query = urlencode({"trace_id": trace_id})
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", query, ""))


def _field(mapping: Mapping[str, object], *names: str) -> object:
    for name in names:
        if name in mapping:
            return mapping[name]
    return None


def _text_field(mapping: Mapping[str, object], *names: str) -> str | None:
    value = _field(mapping, *names)
    return value if isinstance(value, str) and value else None


def _attributes(value: object) -> dict[str, str]:
    result: dict[str, str] = {}
    if isinstance(value, Mapping):
        for key, raw in value.items():
            if not isinstance(key, str):
                continue
            if isinstance(raw, Mapping):
                candidate = _field(raw, "stringValue", "string_value", "value")
                if isinstance(candidate, str):
                    result[key] = candidate
            elif isinstance(raw, str):
                result[key] = raw
        return result
    if isinstance(value, list):
        for raw in value:
            if not isinstance(raw, Mapping):
                continue
            key = _text_field(raw, "key", "name")
            raw_value = raw.get("value")
            candidate = None
            if isinstance(raw_value, Mapping):
                candidate = _field(raw_value, "stringValue", "string_value", "value")
            elif isinstance(raw_value, str):
                candidate = raw_value
            if key and isinstance(candidate, str):
                result[key] = candidate
    return result


def _span_from_mapping(value: Mapping[str, object]) -> dict[str, object] | None:
    name = _text_field(value, "name", "operationName", "operation_name")
    if not name:
        return None
    trace_id = _text_field(value, "traceId", "traceID", "trace_id")
    span_id = _text_field(value, "spanId", "spanID", "span_id")
    parent_id = _text_field(value, "parentSpanId", "parentSpanID", "parent_span_id")
    references = value.get("references")
    if parent_id is None and isinstance(references, list):
        for reference in references:
            if isinstance(reference, Mapping):
                candidate = _text_field(reference, "spanID", "spanId", "span_id")
                if candidate:
                    parent_id = candidate
                    break
    # OTLP scope/resource objects also contain a ``name`` field.  A trace
    # record must expose at least one span identity; otherwise the recursive
    # extractor would mistake a scope name for a span and reject valid OTLP.
    if trace_id is None and span_id is None:
        return None
    attrs: dict[str, str] = {}
    for key in ("attributes", "tags", "fields"):
        attrs.update(_attributes(value.get(key)))
    return {
        "name": name,
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_id": parent_id,
        "attributes": attrs,
    }


def _extract_spans(value: object, *, limit: int = 512) -> list[dict[str, object]]:
    spans: list[dict[str, object]] = []
    seen: set[tuple[object, ...]] = set()

    def visit(node: object, depth: int = 0) -> None:
        if depth > 12 or len(spans) >= limit:
            return
        if isinstance(node, Mapping):
            candidate = _span_from_mapping(node)
            if candidate is not None:
                identity = (
                    candidate.get("trace_id"),
                    candidate.get("span_id"),
                    candidate.get("name"),
                )
                if identity not in seen:
                    seen.add(identity)
                    spans.append(candidate)
            for child in node.values():
                visit(child, depth + 1)
        elif isinstance(node, list):
            for child in node:
                visit(child, depth + 1)

    visit(value)
    return spans


def _trace_payload_is_redacted(value: object) -> bool:
    """Reject sensitive keys and obvious credential material in trace data."""

    def visit(node: object) -> bool:
        if isinstance(node, Mapping):
            for key, child in node.items():
                if isinstance(key, str) and _SENSITIVE_KEY.search(key):
                    return False
                if not visit(child):
                    return False
            return True
        if isinstance(node, list):
            return all(visit(child) for child in node)
        if isinstance(node, str):
            return _SENSITIVE_TEXT.search(node) is None and _URL_WITH_USERINFO_OR_QUERY_SECRET.search(node) is None
        return True

    return visit(value)


def _stage_for_name(name: str) -> tuple[str, ...]:
    normalized = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    stages: list[str] = []
    for stage, aliases in _TRACE_STAGE_ALIASES.items():
        if any(alias.replace("-", "_") in normalized for alias in aliases):
            stages.append(stage)
    return tuple(stages)


def _validate_trace(
    payload: Mapping[str, object],
    *,
    expected_trace_id: str,
    expected_remote_parent_id: str | None = None,
    collector_probe: bool = False,
) -> dict[str, object]:
    if not _trace_payload_is_redacted(payload):
        raise _RuntimeAssertionError("trace_redaction_failed")
    spans = _extract_spans(payload)
    if not spans:
        raise _RuntimeAssertionError("trace_backend_returned_no_spans")
    normalized_expected = expected_trace_id.lower()
    trace_ids: set[str] = set()
    span_ids: set[str] = set()
    for span in spans:
        trace_id = span.get("trace_id")
        if not isinstance(trace_id, str) or not _HEX_TRACE_ID.fullmatch(trace_id):
            raise _RuntimeAssertionError("trace_span_missing_trace_id")
        trace_ids.add(trace_id.lower())
        span_id = span.get("span_id")
        if not isinstance(span_id, str) or not _HEX_SPAN_ID.fullmatch(span_id):
            raise _RuntimeAssertionError("trace_span_missing_span_id")
        span_ids.add(span_id.lower())
    if trace_ids != {normalized_expected}:
        raise _RuntimeAssertionError("trace_context_not_propagated")
    if len(span_ids) != len(spans):
        raise _RuntimeAssertionError("trace_span_ids_not_unique")
    for span in spans:
        parent_id = span.get("parent_id")
        if parent_id is not None and (
            not isinstance(parent_id, str) or not _HEX_SPAN_ID.fullmatch(parent_id)
            or parent_id.lower() == str(span["span_id"]).lower()
            or (
                parent_id.lower() not in span_ids
                and parent_id.lower() != (expected_remote_parent_id or "").lower()
            )
        ):
            raise _RuntimeAssertionError("trace_parent_link_invalid")

    if collector_probe:
        return {
            "span_count": len(spans),
            "trace_ids": 1,
            "stages": [],
            "parent_links_checked": True,
        }

    stage_spans: dict[str, list[int]] = {stage: [] for stage in REQUIRED_TRACE_STAGES}
    for index, span in enumerate(spans):
        name = span.get("name")
        if isinstance(name, str):
            for stage in _stage_for_name(name):
                stage_spans[stage].append(index)
    missing = [stage for stage, indexes in stage_spans.items() if not indexes]
    if missing:
        raise _RuntimeAssertionError("trace_stages_missing:" + ",".join(missing))
    selected: list[int] = []
    for stage in REQUIRED_TRACE_STAGES:
        selected.append(stage_spans[stage][0])
    if len(set(selected)) != len(selected):
        raise _RuntimeAssertionError("trace_stages_not_distinct")
    if expected_remote_parent_id is not None:
        http_span = spans[selected[0]]
        parent_id = http_span.get("parent_id")
        if not isinstance(parent_id, str) or parent_id.lower() != expected_remote_parent_id.lower():
            raise _RuntimeAssertionError("http_remote_parent_not_propagated")

    # A trace ID shared by unrelated roots is not proof that context crossed
    # the requested pipeline.  Permit intermediate framework spans, but make
    # every required stage an ancestry descendant of the preceding stage.
    spans_by_id = {str(span["span_id"]).lower(): span for span in spans}
    selected_span_ids = [str(spans[index]["span_id"]).lower() for index in selected]
    for previous_id, current_index in zip(selected_span_ids, selected[1:]):
        ancestor = spans[current_index].get("parent_id")
        visited: set[str] = set()
        reached_previous = False
        while isinstance(ancestor, str):
            ancestor_id = ancestor.lower()
            if ancestor_id == previous_id:
                reached_previous = True
                break
            if ancestor_id in visited or ancestor_id == (expected_remote_parent_id or "").lower():
                break
            visited.add(ancestor_id)
            ancestor_span = spans_by_id.get(ancestor_id)
            if ancestor_span is None:
                break
            ancestor = ancestor_span.get("parent_id")
        if not reached_previous:
            raise _RuntimeAssertionError("trace_stage_chain_invalid")
    return {
        "span_count": len(spans),
        "trace_ids": len(trace_ids),
        "stages": list(REQUIRED_TRACE_STAGES),
        "parent_links_checked": True,
    }


def _poll_trace(
    endpoint: Endpoint,
    trace_id: str,
    *,
    timeout: float,
    poll_interval: float,
    expected_remote_parent_id: str | None = None,
    collector_probe: bool = False,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while True:
        response = _http_request(
            _trace_query_url(endpoint, trace_id),
            method="GET",
            timeout=min(float(timeout), 5.0),
            headers={"Accept": "application/json"},
        )
        if response.status == 404:
            raise _RuntimeAssertionError("trace_backend_endpoint_not_found")
        if not 200 <= response.status < 300:
            raise _RuntimeAssertionError("trace_backend_query_rejected")
        payload = _json(response, label="trace_backend")
        try:
            return _validate_trace(
                payload,
                expected_trace_id=trace_id,
                expected_remote_parent_id=expected_remote_parent_id,
                collector_probe=collector_probe,
            )
        except _RuntimeAssertionError as exc:
            if str(exc) in {"trace_backend_returned_no_spans", "trace_context_not_propagated"} and time.monotonic() < deadline:
                time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))
                continue
            if str(exc) == "trace_backend_returned_no_spans" and time.monotonic() >= deadline:
                raise _RuntimeAssertionError("trace_backend_timeout") from None
            raise


def _metrics_query_url(endpoint: Endpoint, query: str) -> str:
    parsed = endpoint.parsed
    path = parsed.path.rstrip("/")
    if path.endswith("/api/v1/query"):
        query_path = path
    elif path.endswith("/api/v1"):
        query_path = path + "/query"
    else:
        query_path = (path or "") + "/api/v1/query"
    return urlunsplit((parsed.scheme, parsed.netloc, query_path, urlencode({"query": query}), ""))


def _prometheus_values(payload: Mapping[str, object]) -> list[tuple[dict[str, str], float]]:
    if payload.get("status") != "success":
        raise _RuntimeAssertionError("metrics_backend_query_failed")
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise _RuntimeAssertionError("metrics_backend_data_invalid")
    result = data.get("result")
    values: list[tuple[dict[str, str], float]] = []
    if data.get("resultType") == "scalar" and isinstance(result, list) and len(result) >= 2:
        try:
            number = float(result[1])
        except (TypeError, ValueError):
            raise _RuntimeAssertionError("metrics_backend_nonfinite_value") from None
        if not math.isfinite(number):
            raise _RuntimeAssertionError("metrics_backend_nonfinite_value")
        return [({}, number)]
    if isinstance(result, list):
        for item in result:
            if isinstance(item, Mapping) and isinstance(item.get("metric"), Mapping):
                labels = item["metric"]
            else:
                labels = item if isinstance(item, Mapping) else {}
            raw_value: object = None
            if isinstance(item, Mapping):
                if isinstance(item.get("value"), list) and len(item["value"]) >= 2:
                    raw_value = item["value"][1]
                elif isinstance(item.get("values"), list) and item["values"]:
                    last = item["values"][-1]
                    if isinstance(last, list) and len(last) >= 2:
                        raw_value = last[1]
            elif isinstance(item, list) and len(item) >= 2:
                raw_value = item[1]
            try:
                number = float(raw_value)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(number):
                raise _RuntimeAssertionError("metrics_backend_nonfinite_value")
            values.append(({str(key): str(value) for key, value in labels.items() if key not in {"value", "values"}}, number))
    elif isinstance(result, (int, float, str)):
        try:
            number = float(result)
        except (TypeError, ValueError):
            number = math.nan
        if not math.isfinite(number):
            raise _RuntimeAssertionError("metrics_backend_nonfinite_value")
        values.append(({}, number))
    return values


def _query_metrics(endpoint: Endpoint, *, timeout: float, poll_interval: float, poll_timeout: float) -> dict[str, object]:
    deadline = time.monotonic() + poll_timeout
    inventory: dict[str, float] = {}
    while True:
        try:
            response = _http_request(
                _metrics_query_url(endpoint, 'sum by (__name__) ({__name__=~"rick_.+"})'),
                method="GET",
                timeout=timeout,
                headers={"Accept": "application/json"},
            )
            if not 200 <= response.status < 300:
                raise _RuntimeAssertionError("metrics_backend_query_rejected")
            values = _prometheus_values(_json(response, label="metrics_backend"))
            inventory = {
                labels.get("__name__", ""): number
                for labels, number in values
                if labels.get("__name__")
            }
            if inventory:
                break
        except _RuntimeAssertionError:
            pass
        if time.monotonic() >= deadline:
            # Some restricted Prometheus-compatible APIs reject the metric
            # inventory selector while still supporting direct queries.  Do
            # not turn that protocol variation into a false external block;
            # the required direct queries below remain authoritative.
            break
        time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))

    observed: dict[str, dict[str, object]] = {}
    missing: list[str] = []
    for group, aliases in _METRIC_GROUPS.items():
        selected = next((alias for alias in aliases if alias in inventory), None)
        if selected is None:
            # An explicit query is useful for backends whose metadata query is
            # restricted.  It remains bounded and never changes the required
            # contract: an empty result is still a missing metric.
            for alias in aliases:
                query = alias if "{" in alias else f"sum({alias})"
                response = _http_request(
                    _metrics_query_url(endpoint, query),
                    method="GET",
                    timeout=timeout,
                    headers={"Accept": "application/json"},
                )
                if not 200 <= response.status < 300:
                    continue
                try:
                    values = _prometheus_values(_json(response, label="metrics_backend"))
                except _RuntimeAssertionError:
                    continue
                if values:
                    selected = alias
                    inventory.setdefault(alias.split("{", 1)[0], values[0][1])
                    break
        if selected is None:
            missing.append(group)
        else:
            observed[group] = {"metric": selected, "value": inventory.get(selected.split("{", 1)[0])}

    slo_response = _http_request(
        _metrics_query_url(endpoint, "rick_api_slo_status"),
        method="GET",
        timeout=timeout,
        headers={"Accept": "application/json"},
    )
    if not 200 <= slo_response.status < 300:
        raise _RuntimeAssertionError("slo_metric_query_rejected")
    slo_values = _prometheus_values(_json(slo_response, label="slo_metric"))
    healthy = any(labels.get("status") == "healthy" and value > 0 for labels, value in slo_values)
    unhealthy = [
        labels.get("status")
        for labels, value in slo_values
        if labels.get("status") in {"breach", "no_data"} and value > 0
    ]
    if not healthy or unhealthy:
        raise _RuntimeAssertionError("slo_not_healthy")
    if missing:
        raise _RuntimeAssertionError("metrics_missing:" + ",".join(missing))
    return {
        "metric_groups": observed,
        "metric_group_count": len(observed),
        "slo": {"healthy": True, "breach_or_no_data": False},
    }


def _static_file(path: Path, tokens: Sequence[str]) -> bool:
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return all(token in content for token in tokens)


def _source_contract() -> GateResult:
    requirements = {
        ROOT / "packages/observability/src/rick_observability/redaction.py": ("def redact", "def safe_event"),
        ROOT / "packages/observability/src/rick_observability/events.py": ("class BoundedEventBuffer", "def emit_safely"),
        ROOT / "packages/observability/src/rick_observability/metrics.py": ("class CounterRegistry", "class Histogram"),
        ROOT / "packages/observability/src/rick_observability/slo.py": ("def evaluate_slo", "class AlertRule"),
        ROOT / "packages/observability/src/rick_observability/tracing.py": ("class CorrelationContext", "def should_sample"),
        ROOT / "apps/api/src/core/telemetry.py": ("class ApiTelemetry", "def prometheus_text", "record_retrieval", "record_provider_failure"),
        ROOT / "infrastructure/compose/otel-collector-config.yaml": ("receivers:", "traces:", "metrics:", "memory_limiter", "batch"),
        ROOT / "infrastructure/compose/prometheus.yml": ("scrape_configs:", "otel-collector"),
        ROOT / "infrastructure/compose/alerts.yml": ("RickApiSloBreach", "RickApiSloNoData"),
        ROOT / "infrastructure/monitoring/prometheus.rules.yml": ("RickApiReadinessMissing", "RickApiErrorBudgetBurn", "RickRetrievalLatencyP95"),
    }
    missing = [path.relative_to(ROOT).as_posix() for path, tokens in requirements.items() if not _static_file(path, tokens)]
    if missing:
        return GateResult("observability-source-contract", FAIL, "required observability source contract is incomplete:" + ",".join(missing))
    return GateResult(
        "observability-source-contract",
        PASS,
        "bounded redaction, event, metric, trace, SLO, collector and alert seams are present",
    )


def _alert_contract() -> GateResult:
    content = ""
    for path in (
        ROOT / "infrastructure/compose/alerts.yml",
        ROOT / "infrastructure/monitoring/prometheus.rules.yml",
    ):
        try:
            content += path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return GateResult("alert-configuration-contract", FAIL, "alert configuration could not be read")
    missing = [name for name in _REQUIRED_ALERTS if name not in content]
    required_fragments = ("status=\"no_data\"", "absent(", "histogram_quantile", "rate(")
    absent_fragments = [fragment for fragment in required_fragments if fragment not in content]
    if missing or absent_fragments:
        detail = "alert contract incomplete"
        if missing:
            detail += ":missing=" + ",".join(missing)
        if absent_fragments:
            detail += ":fragments=" + ",".join(absent_fragments)
        return GateResult("alert-configuration-contract", FAIL, detail)
    return GateResult("alert-configuration-contract", PASS, "required SLO, readiness, latency, error and provider alerts are declared")


def _audit_snapshot() -> dict[str, object]:
    """Capture facts about the current canonical telemetry wiring.

    This is an audit projection, not a promotion verdict.  In particular, the
    current API intentionally reports ``NOT_CONFIGURED`` until an external
    exporter/backend is supplied; the runtime gate must therefore prove that
    boundary rather than infer it from the Compose files.
    """

    telemetry_path = ROOT / "apps/api/src/core/telemetry.py"
    try:
        telemetry_source = telemetry_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        telemetry_source = ""
    canonical_sources: list[str] = []
    for directory in (ROOT / "apps/api/src", ROOT / "packages/observability/src"):
        if not directory.is_dir():
            continue
        for path in directory.rglob("*.py"):
            try:
                canonical_sources.append(path.read_text(encoding="utf-8").lower())
            except (OSError, UnicodeDecodeError):
                continue
    telemetry_lower = telemetry_source.lower()
    api_metric_markers = {
        "http_latency_p50": "rick_api_http_latency_ms_p50",
        "http_latency_p95": "rick_api_http_latency_ms_p95",
        "http_latency_p99": "rick_api_http_latency_ms_p99",
        "retrieval_histogram": "rick_api_retrieval_latency_ms_bucket",
        "provider_ttft": "rick_api_chat_stream_ttft_ms_p95",
        "tokens_per_second": "tokens_per_second",
    }
    return {
        "local_api_telemetry": "PRESENT" if "class apitelemetry" in telemetry_lower else "MISSING",
        "api_export_status": "NOT_CONFIGURED" if "not_configured" in telemetry_lower else "UNKNOWN",
        "canonical_otel_sdk": "PRESENT" if any("opentelemetry" in source for source in canonical_sources) else "NOT_PRESENT",
        "api_metric_coverage": {
            name: "PRESENT" if marker in telemetry_lower else "MISSING"
            for name, marker in api_metric_markers.items()
        },
        "collector_config": "PRESENT" if _static_file(ROOT / "infrastructure/compose/otel-collector-config.yaml", ("receivers:", "pipelines:")) else "MISSING",
        "prometheus_config": "PRESENT" if _static_file(ROOT / "infrastructure/compose/prometheus.yml", ("scrape_configs:",)) else "MISSING",
        "alert_config": "PRESENT" if _static_file(ROOT / "infrastructure/compose/alerts.yml", ("RickApiSloNoData",)) else "MISSING",
        "runtime_observation": NOT_RUN,
    }


def _walk_nodes(value: object) -> int:
    count = 1
    if isinstance(value, Mapping):
        for key, child in value.items():
            count += _walk_nodes(key) + _walk_nodes(child)
    elif isinstance(value, list):
        for child in value:
            count += _walk_nodes(child)
    return count


def _redaction_contract() -> GateResult:
    try:
        sys.path[:0] = [
            str(ROOT / "packages/observability/src"),
            str(ROOT / "apps/api/src"),
        ]
        from rick_observability import safe_event
        from rick_observability.redaction import MAX_EVENT_BYTES, MAX_EVENT_NODES
        from core.telemetry import ApiTelemetry
    except (ImportError, OSError, ValueError):
        return GateResult("adversarial-redaction", FAIL, "canonical observability modules could not be imported")

    markers = (
        "phase3-secret-canary",
        "phase3-password-canary",
        "phase3-token-canary",
        "phase3-api-key-canary",
    )
    event = safe_event(
        {
            "authorization": "Bearer phase3-secret-canary",
            "nested": {
                "password": "phase3-password-canary",
                "credentials": {"api_key": "phase3-api-key-canary"},
                "escaped": "\\u0070hase3-token-canary",
            },
            "url": "redis://user:phase3-password-canary@example.test:6379/0?token=phase3-token-canary#fragment",
            "items": [{"secret": "phase3-secret-canary"} for _ in range(1000)],
        },
        event_name="phase3.redaction.probe",
    )
    serialized = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    if any(marker in serialized for marker in markers):
        return GateResult("adversarial-redaction", FAIL, "sensitive marker survived structured redaction")
    if len(serialized.encode("utf-8")) > MAX_EVENT_BYTES or _walk_nodes(event) > MAX_EVENT_NODES:
        return GateResult("adversarial-redaction", FAIL, "redaction budget was exceeded")

    telemetry = ApiTelemetry()
    telemetry.record_request(
        method="POST",
        path="/api/v1/chat?token=phase3-token-canary",
        status=200,
        duration_ms=12.0,
        request_id="phase3-request-canary",
        correlation_id="phase3-correlation-canary",
    )
    telemetry.emit({
        "event": "worker.ingestion.published",
        "fields": {
            "job_ref": "phase3-secret-canary",
            "worker_ref": "phase3-worker-canary",
            "request_ref": "phase3-request-canary",
            "correlation_ref": "phase3-correlation-canary",
            "status": "published",
            "stage": "published",
            "source_path": "/private/phase3-secret-canary.txt",
            "tenant_id": "phase3-secret-canary",
            "error": "phase3-secret-canary-exception",
        },
    })
    snapshot = telemetry.snapshot()
    exposition = telemetry.prometheus_text()
    combined = json.dumps(snapshot, ensure_ascii=False) + exposition
    if any(marker in combined for marker in markers) or "?token=" in combined or "/private/phase3-secret-canary" in combined:
        return GateResult("adversarial-redaction", FAIL, "API telemetry exposed an adversarial marker")
    if len(snapshot.get("events", [])) != 2:
        return GateResult("adversarial-redaction", FAIL, "expected bounded request and worker observations")
    return GateResult(
        "adversarial-redaction",
        PASS,
        "nested credentials, URL userinfo/query, escaped sensitive values and private worker fields were withheld",
    )


def _metrics_slo_local_contract() -> GateResult:
    try:
        sys.path[:0] = [str(ROOT / "packages/observability/src"), str(ROOT / "apps/api/src")]
        from rick_observability import AlertRule, evaluate_slo
        from core.telemetry import ApiTelemetry
    except (ImportError, OSError, ValueError):
        return GateResult("local-metrics-slo", FAIL, "canonical metric and SLO modules could not be imported")
    try:
        if evaluate_slo(total=0, errors=0, latency_p95=None, max_error_rate=.05).status != "no_data":
            raise ValueError("no_data contract")
        if evaluate_slo(total=100, errors=6, latency_p95=1, max_error_rate=.05).status != "breach":
            raise ValueError("error budget contract")
        if AlertRule("phase3", .05, 2_000).evaluate(total=20, errors=0, latency_p95=10).status != "healthy":
            raise ValueError("healthy SLO contract")
        telemetry = ApiTelemetry()
        for index in range(20):
            telemetry.record_request(
                method="GET",
                path="/api/v1/chat",
                status=200 if index else 500,
                duration_ms=float(index + 1),
                request_id=f"phase3-{index}",
                correlation_id=f"phase3-correlation-{index}",
            )
        telemetry.record_readiness(status="ready", check_count=4)
        telemetry.record_retrieval(duration_ms=20, outcome="success")
        telemetry.record_provider_failure(provider="qdrant", reason="timeout")
        telemetry.record_stream(outcome="complete", ttft_ms=5, duration_ms=25)
        snapshot = telemetry.snapshot()
        exposition = telemetry.prometheus_text()
    except (TypeError, ValueError, KeyError, AttributeError):
        return GateResult("local-metrics-slo", FAIL, "bounded metrics/SLO contract failed")
    slo = snapshot.get("slo")
    latency = snapshot.get("latency")
    if not isinstance(slo, Mapping) or slo.get("status") != "healthy":
        return GateResult("local-metrics-slo", FAIL, "local SLO did not remain healthy for the bounded sample")
    if not isinstance(latency, Mapping) or latency.get("p50") is None or latency.get("p95") is None:
        return GateResult("local-metrics-slo", FAIL, "local p50/p95 latency observation is missing")
    required_names = (
        "rick_api_http_requests_total",
        "rick_api_http_errors_total",
        "rick_api_retrieval_latency_ms_count",
        "rick_api_slo_status",
    )
    if any(name not in exposition for name in required_names):
        return GateResult("local-metrics-slo", FAIL, "local Prometheus exposition is missing a required metric")
    if _SENSITIVE_TEXT.search(exposition):
        return GateResult("local-metrics-slo", FAIL, "local Prometheus exposition contains sensitive syntax")
    return GateResult(
        "local-metrics-slo",
        PASS,
        "bounded counters, latency, retrieval, provider, stream and healthy/no-data/breach SLO semantics verified locally",
    )


def _load_backup_module() -> Any | None:
    path = ROOT / "infrastructure/scripts/backup_restore.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("rick_phase3_backup_restore", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        return None
    return module


def _backup_restore_contract() -> GateResult:
    module = _load_backup_module()
    if module is None:
        return GateResult("backup-restore-contract", NOT_AVAILABLE, "existing backup/restore harness is unavailable", required=False)
    try:
        with tempfile.TemporaryDirectory(prefix="rick-phase3-observability-") as temporary:
            root = Path(temporary)
            sources = {
                "postgres": root / "postgres",
                "object_store": root / "object-store",
                "audit": root / "audit",
                "evidence": root / "evidence",
            }
            contents = {
                "postgres": b"job-state:queued\n",
                "object_store": b"sha256:object\n",
                "audit": b"audit-event:published\n",
                "evidence": b"evidence-lineage:v1\n",
            }
            for name, source in sources.items():
                source.mkdir()
                (source / "export.bin").write_bytes(contents[name])
            backup_root = root / "backups"
            backup = module.create_backup(
                sources,
                backup_root,
                backup_id="phase3-observability-contract",
                operator="phase3-gate",
                restore_target="disposable-target",
            )
            backup_path = backup_root / str(backup["backup_id"])
            verified = module.verify_backup(backup_path)
            if verified.get("status") != "PASS":
                raise RuntimeError("backup verification")
            restored = root / "restored"
            report = module.restore_backup(backup_path, restored)
            if report.get("status") != "PASS":
                raise RuntimeError("restore")
            for name, payload in contents.items():
                if (restored / name / "export.bin").read_bytes() != payload:
                    raise RuntimeError("restored payload mismatch")
            nonempty = root / "nonempty"
            nonempty.mkdir()
            (nonempty / "sentinel").write_bytes(b"sentinel")
            try:
                module.restore_backup(backup_path, nonempty)
            except Exception:
                pass
            else:
                raise RuntimeError("nonempty restore target accepted")
            tampered = backup_path / "payload" / "audit" / "export.bin"
            tampered.write_bytes(b"tampered")
            try:
                module.verify_backup(backup_path)
            except Exception:
                pass
            else:
                raise RuntimeError("tampered backup accepted")
    except Exception:
        return GateResult("backup-restore-contract", FAIL, "existing backup/restore harness rejected its bounded contract", required=False)
    return GateResult(
        "backup-restore-contract",
        PASS,
        "existing checksum-verified backup, restore, non-empty-target and tamper negatives executed",
        required=False,
    )


def _phase3_lane_contracts(*, run: bool, timeout: float) -> list[GateResult]:
    """Project the existing phase3 operational harness without writing repo files."""

    harness = ROOT / "scripts/state_of_art/phase3_lane.py"
    lanes = ("performance", "chaos", "soak")
    if not harness.is_file():
        return [
            GateResult(
                f"{lane}-contract",
                NOT_AVAILABLE,
                "existing Phase 3 operational harness is unavailable",
                required=False,
            )
            for lane in lanes
        ]
    if not run:
        return [
            GateResult(
                f"{lane}-contract",
                NOT_RUN,
                "existing Phase 3 operational harness was not requested",
                required=False,
            )
            for lane in lanes
        ]

    bounded_timeout = max(1, min(30, int(math.ceil(timeout))))
    results: list[GateResult] = []
    for lane in lanes:
        name = f"{lane}-contract"
        try:
            with tempfile.TemporaryDirectory(prefix=f"rick-phase3-{lane}-") as temporary:
                artifact_path = Path(temporary) / f"{lane}.json"
                process = subprocess.Popen(
                    [
                        sys.executable,
                        str(harness),
                        "--lane",
                        lane,
                        "--strict",
                        "--timeout-seconds",
                        str(bounded_timeout),
                        "--output",
                        str(artifact_path),
                    ],
                    cwd=ROOT,
                    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                try:
                    process.communicate(timeout=bounded_timeout + 2)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except OSError:
                        pass
                    try:
                        process.communicate(timeout=2)
                    except subprocess.TimeoutExpired:
                        pass
                    results.append(GateResult(name, FAIL, "existing operational harness exceeded its bound", required=False))
                    continue
                try:
                    payload = load_json(artifact_path)
                except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
                    results.append(GateResult(name, FAIL, "existing operational harness emitted no valid observation", required=False))
                    continue
        except OSError:
            results.append(GateResult(name, FAIL, "existing operational harness could not be started", required=False))
            continue

        status = payload.get("status") if isinstance(payload, Mapping) else None
        return_code = process.returncode
        if status == PASS and return_code == 0:
            result = PASS
            detail = "existing bounded operational observation completed"
        elif status == BLOCKED_EXTERNAL and return_code == 2:
            result = BLOCKED_EXTERNAL
            detail = "existing operational harness is present but its approved runtime is unavailable"
        else:
            result = FAIL
            detail = "existing operational harness did not emit a consistent passing observation"
        results.append(GateResult(name, result, detail, required=False))
    return results


def _optional_harness_contracts(*, run: bool, timeout: float) -> list[GateResult]:
    # The canonical Phase 3 lane is the only operational harness invoked here.
    # The older phase15/phase16 benchmarks write documentation artifacts and
    # are therefore intentionally not executed by this three-file gate.
    return _phase3_lane_contracts(run=run, timeout=timeout)


def _rule_names(value: object) -> set[str]:
    names: set[str] = set()

    def visit(node: object) -> None:
        if isinstance(node, Mapping):
            for key, child in node.items():
                if key in {"name", "alert", "alertname"} and isinstance(child, str):
                    names.add(child)
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    return names


def _local_results(args: argparse.Namespace) -> list[GateResult]:
    results = [
        _source_contract(),
        _alert_contract(),
        _redaction_contract(),
        _metrics_slo_local_contract(),
        _backup_restore_contract(),
    ]
    results.extend(_optional_harness_contracts(run=bool(args.run_harness_contracts), timeout=float(args.timeout)))
    results.append(
        GateResult(
            "distributed-observability-runtime",
            BLOCKED_EXTERNAL,
            "explicit collector, trace backend, metrics backend and full pipeline probe are required",
            required=True,
            scope="external-runtime",
        )
    )
    return results


def _configured_endpoint(
    value: str,
    *,
    label: str,
    args: argparse.Namespace,
) -> tuple[Endpoint | None, GateResult | None]:
    try:
        return (
            _safe_endpoint(
                value,
                label=label,
                allow_nonlocal=bool(args.allow_nonlocal),
                require_tls=bool(args.require_tls),
            ),
            None,
        )
    except _BlockedExternalError as exc:
        del exc
        return None, GateResult(label, BLOCKED_EXTERNAL, f"{label} is not explicitly configured", scope="external-runtime")
    except _InvalidConfigurationError as exc:
        del exc
        return None, GateResult(label, FAIL, f"{label} configuration violates the bounded URL contract", scope="external-runtime")


def _external_results(args: argparse.Namespace) -> tuple[list[GateResult], dict[str, object]]:
    results = [
        _source_contract(),
        _alert_contract(),
        _redaction_contract(),
        _metrics_slo_local_contract(),
        _backup_restore_contract(),
    ]
    results.extend(_optional_harness_contracts(run=bool(args.run_harness_contracts), timeout=float(args.timeout)))

    collector_raw = args.collector_url or _env_first("RICK_OBSERVABILITY_COLLECTOR_URL", "RICK_OTEL_COLLECTOR_URL", "RICK_OTEL_ENDPOINT")
    backend_raw = args.backend_url or _env_first("RICK_OBSERVABILITY_BACKEND_URL", "RICK_OTEL_BACKEND_URL")
    trace_raw = args.trace_backend_url or _env_first("RICK_OBSERVABILITY_TRACE_BACKEND_URL", "RICK_OTEL_TRACE_BACKEND_URL", "RICK_JAEGER_QUERY_URL", "RICK_TEMPO_QUERY_URL") or backend_raw
    metrics_raw = args.metrics_backend_url or _env_first("RICK_OBSERVABILITY_METRICS_BACKEND_URL", "RICK_METRICS_BACKEND_URL", "RICK_PROMETHEUS_URL") or backend_raw
    api_raw = args.api_url or _env_first("RICK_OBSERVABILITY_API_URL", "RICK_API_URL")

    collector, collector_error = _configured_endpoint(collector_raw, label="collector", args=args)
    trace_backend, trace_error = _configured_endpoint(trace_raw, label="trace-backend", args=args)
    metrics_backend, metrics_error = _configured_endpoint(metrics_raw, label="metrics-backend", args=args)
    if collector_error:
        results.append(collector_error)
    if trace_error:
        results.append(trace_error)
    if metrics_error:
        results.append(metrics_error)

    api_endpoint: Endpoint | None = None
    if api_raw:
        api_endpoint, api_error = _configured_endpoint(api_raw, label="api", args=args)
        if api_error:
            results.append(api_error)
    try:
        probe_endpoint = _probe_url(args, api_endpoint)
    except _BlockedExternalError:
        probe_endpoint = None
        results.append(GateResult("pipeline-probe", BLOCKED_EXTERNAL, "full pipeline probe is not explicitly configured", scope="external-runtime"))
    except _InvalidConfigurationError:
        probe_endpoint = None
        results.append(GateResult("pipeline-probe", FAIL, "pipeline probe configuration violates the bounded URL contract", scope="external-runtime"))

    configuration = {
        "collector": collector.report() if collector else {"configured": False},
        "trace_backend": trace_backend.report() if trace_backend else {"configured": False},
        "metrics_backend": metrics_backend.report() if metrics_backend else {"configured": False},
        "api": api_endpoint.report() if api_endpoint else {"configured": False},
        "probe": probe_endpoint.report() if probe_endpoint else {"configured": False},
    }
    if not all((collector, trace_backend, metrics_backend, probe_endpoint)):
        # Keep one explicit gate result even when several configuration pieces
        # are absent, so a consumer can distinguish a missing runtime from a
        # local contract failure without parsing prose.
        results.append(
            GateResult(
                "distributed-observability-runtime",
                BLOCKED_EXTERNAL,
                "collector, trace backend, metrics backend and pipeline probe are all required",
                scope="external-runtime",
            )
        )
        return results, configuration

    collector_trace_id: str | None = None
    try:
        collector_trace_id = _send_collector_probe(collector, timeout=float(args.timeout))
        results.append(GateResult("collector-ingest", PASS, "collector accepted one bounded OTLP/HTTP trace probe", scope="external-runtime"))
    except _BlockedExternalError:
        results.append(GateResult("collector-ingest", BLOCKED_EXTERNAL, "collector transport is unavailable", scope="external-runtime"))
    except (_InvalidConfigurationError, _RuntimeAssertionError):
        results.append(GateResult("collector-ingest", FAIL, "collector rejected the bounded OTLP/HTTP probe", scope="external-runtime"))

    if collector_trace_id is not None:
        try:
            observation = _poll_trace(
                trace_backend,
                collector_trace_id,
                timeout=float(args.poll_timeout),
                poll_interval=float(args.poll_interval),
                collector_probe=True,
            )
            results.append(GateResult("collector-backend-trace", PASS, f"trace backend returned the collector probe ({observation['span_count']} span)", scope="external-runtime"))
        except _BlockedExternalError:
            results.append(GateResult("collector-backend-trace", BLOCKED_EXTERNAL, "trace backend transport is unavailable", scope="external-runtime"))
        except (_InvalidConfigurationError, _RuntimeAssertionError):
            results.append(GateResult("collector-backend-trace", FAIL, "trace backend did not return the collector probe", scope="external-runtime"))

    api_trace_id: str | None = None
    api_remote_parent_id: str | None = None
    try:
        api_trace_id, _request_id, api_remote_parent_id = _probe_api(probe_endpoint, args)
        del _request_id
        results.append(GateResult("http-pipeline-probe", PASS, "configured API boundary accepted the W3C trace context", scope="external-runtime"))
    except _BlockedExternalError:
        results.append(GateResult("http-pipeline-probe", BLOCKED_EXTERNAL, "configured API boundary is unavailable", scope="external-runtime"))
    except (_InvalidConfigurationError, _RuntimeAssertionError):
        results.append(GateResult("http-pipeline-probe", FAIL, "configured API boundary rejected the bounded trace probe", scope="external-runtime"))

    if api_trace_id is not None:
        try:
            observation = _poll_trace(
                trace_backend,
                api_trace_id,
                timeout=float(args.poll_timeout),
                poll_interval=float(args.poll_interval),
                expected_remote_parent_id=api_remote_parent_id,
            )
            results.append(
                GateResult(
                    "distributed-trace-propagation",
                    PASS,
                    f"one trace carried all {len(REQUIRED_TRACE_STAGES)} required stages ({observation['span_count']} spans)",
                    scope="external-runtime",
                )
            )
        except _BlockedExternalError:
            results.append(GateResult("distributed-trace-propagation", BLOCKED_EXTERNAL, "trace backend transport is unavailable", scope="external-runtime"))
        except (_InvalidConfigurationError, _RuntimeAssertionError):
            results.append(GateResult("distributed-trace-propagation", FAIL, "trace context or required stage propagation failed", scope="external-runtime"))

    try:
        metrics = _query_metrics(
            metrics_backend,
            timeout=float(args.timeout),
            poll_interval=float(args.poll_interval),
            poll_timeout=float(args.poll_timeout),
        )
        results.append(GateResult("metrics-slo-backend", PASS, f"Prometheus backend exposed {metrics['metric_group_count']} bounded metric groups and a healthy SLO", scope="external-runtime"))
    except _BlockedExternalError:
        results.append(GateResult("metrics-slo-backend", BLOCKED_EXTERNAL, "metrics backend transport is unavailable", scope="external-runtime"))
    except (_InvalidConfigurationError, _RuntimeAssertionError):
        results.append(GateResult("metrics-slo-backend", FAIL, "metrics inventory or SLO query did not satisfy the contract", scope="external-runtime"))

    alerts_raw = args.alerts_url or _env_first("RICK_OBSERVABILITY_ALERTS_URL", "RICK_PROMETHEUS_RULES_URL")
    if alerts_raw:
        alerts_endpoint, alerts_error = _configured_endpoint(alerts_raw, label="alerts", args=args)
    else:
        alerts_endpoint, alerts_error = metrics_backend, None
    configuration["alerts"] = alerts_endpoint.report() if alerts_endpoint else {"configured": False}
    if alerts_error:
        results.append(alerts_error)
    if alerts_endpoint is not None:
        parsed = alerts_endpoint.parsed
        path = parsed.path.rstrip("/")
        if path.endswith("/api/v1/rules"):
            alerts_url = alerts_endpoint.raw
        elif path.endswith("/api/v1/query"):
            alerts_url = urlunsplit((parsed.scheme, parsed.netloc, path[:-len("/query")] + "/rules", "", ""))
        else:
            alerts_url = urlunsplit((parsed.scheme, parsed.netloc, (path or "") + "/api/v1/rules", "", ""))
        try:
            response = _http_request(alerts_url, method="GET", timeout=float(args.timeout), headers={"Accept": "application/json"})
            if not 200 <= response.status < 300:
                raise _RuntimeAssertionError("alerts_backend_query_rejected")
            payload = _json(response, label="alerts_backend")
            missing = [name for name in _REQUIRED_ALERTS if name not in _rule_names(payload)]
            if missing:
                raise _RuntimeAssertionError("alerts_missing")
            results.append(GateResult("alerts-loaded", PASS, "configured alert backend returned all required rule names", scope="external-runtime"))
        except _BlockedExternalError:
            results.append(GateResult("alerts-loaded", BLOCKED_EXTERNAL, "alerts backend transport is unavailable", scope="external-runtime"))
        except (_InvalidConfigurationError, _RuntimeAssertionError):
            results.append(GateResult("alerts-loaded", FAIL, "configured alert backend did not expose the required rules", scope="external-runtime"))
    else:
        results.append(GateResult("alerts-loaded", BLOCKED_EXTERNAL, "alert backend is not explicitly configured or derivable", scope="external-runtime"))
    return results, configuration


def _aggregate(results: Sequence[GateResult]) -> str:
    required = [item.result for item in results if item.required]
    if any(result == FAIL for result in required):
        return FAIL
    if any(result in {BLOCKED_EXTERNAL, NOT_RUN, NOT_AVAILABLE, PARTIAL} for result in required):
        return BLOCKED_EXTERNAL
    return PASS if required and all(result == PASS for result in required) else BLOCKED_EXTERNAL


def _safe_output(raw: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise _InvalidConfigurationError("output_missing")
    path = (ROOT / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError:
        raise _InvalidConfigurationError("output_must_be_inside_repository") from None
    return path


def _write_payload(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("local", "external"), default="external")
    parser.add_argument("--local", action="store_true", help="alias for --mode local")
    parser.add_argument("--collector-url", default="")
    parser.add_argument("--backend-url", default="", help="use one explicit backend for both trace and metrics queries")
    parser.add_argument("--trace-backend-url", default="")
    parser.add_argument("--metrics-backend-url", default="")
    parser.add_argument("--alerts-url", default="")
    parser.add_argument("--api-url", default="")
    parser.add_argument("--probe-url", default="")
    parser.add_argument("--probe-method", choices=("GET", "POST", "PUT", "PATCH"), default="GET")
    parser.add_argument("--probe-body")
    parser.add_argument("--probe-body-file")
    parser.add_argument("--probe-header", action="append", default=[])
    parser.add_argument("--allow-nonlocal", action="store_true")
    parser.add_argument("--require-tls", action="store_true")
    parser.add_argument("--run-harness-contracts", action="store_true")
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--poll-timeout", type=float, default=15.0)
    parser.add_argument("--poll-interval", type=float, default=0.25)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    args = parser.parse_args(list(argv))
    if args.local:
        args.mode = "local"
    if not 0.1 <= args.timeout <= 30.0:
        parser.error("--timeout must be between 0.1 and 30 seconds")
    if not 0.1 <= args.poll_timeout <= 60.0:
        parser.error("--poll-timeout must be between 0.1 and 60 seconds")
    if not 0.01 <= args.poll_interval <= 5.0:
        parser.error("--poll-interval must be between 0.01 and 5 seconds")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    started = datetime.now(timezone.utc)
    configuration: dict[str, object] = {"mode": args.mode}
    audit = _audit_snapshot()
    try:
        if args.mode == "local":
            results = _local_results(args)
        else:
            results, external_configuration = _external_results(args)
            configuration.update(external_configuration)
        status = _aggregate(results)
    except _BlockedExternalError:
        results = [GateResult("gate", BLOCKED_EXTERNAL, "required runtime authority is unavailable", scope="external-runtime")]
        status = BLOCKED_EXTERNAL
    except _InvalidConfigurationError:
        results = [GateResult("gate", FAIL, "gate configuration violates its bounded contract", scope="external-runtime")]
        status = FAIL
    except Exception:
        # No implementation exception is allowed to masquerade as a runtime
        # result, and no exception text is safe evidence.
        results = [GateResult("gate", FAIL, "gate execution failed before a valid result was produced", scope="external-runtime")]
        status = FAIL

    audit["runtime_observation"] = status if args.mode == "external" else NOT_RUN

    endpoint_reports = [
        value for value in configuration.values()
        if isinstance(value, Mapping) and value.get("configured") is True
    ]
    production_safe = bool(
        status == PASS
        and args.mode == "external"
        and args.require_tls
        and endpoint_reports
        and all(report.get("tls") is True for report in endpoint_reports)
    )
    observed_at = started.isoformat()
    payload = {
        "schema_version": "phase3-observability-runtime-gate.v1",
        "status": status,
        "runtime_claim": status == PASS,
        "production_safe": production_safe,
        "observed_at": observed_at,
        "mode": args.mode,
        "environment": "phase3-observability-local-contract" if args.mode == "local" else "phase3-observability-external-disposable",
        "audit": audit,
        "configuration": configuration,
        "trace_contract": {
            "required_stages": list(REQUIRED_TRACE_STAGES),
            "propagation": "single W3C trace context with bounded parent-link validation",
        },
        "metric_contract": {
            "required_groups": list(_METRIC_GROUPS),
            "slo_metric": "rick_api_slo_status",
            "missing_data_is": BLOCKED_EXTERNAL if args.mode == "external" else NOT_RUN,
        },
        "alert_contract": {"required_rules": list(_REQUIRED_ALERTS)},
        "results": [item.to_dict() for item in results],
        "limitations": (
            [
                "No distributed collector/backend/pipeline runtime was configured; local contracts do not create runtime evidence.",
                "Backup/restore and optional harness contracts are file-level or hermetic and do not prove service DR, chaos, soak or production SLOs.",
            ]
            if status == BLOCKED_EXTERNAL
            else [
                "This PASS is limited to the explicitly configured endpoints, synthetic probe and bounded observation window.",
                "It is not an independent review, production approval or full Triple AAA promotion decision.",
            ]
        ),
        "next_action": (
            "Provide an approved disposable collector, trace backend, metrics/alert backend and full pipeline endpoint, then rerun on a clean checkout."
            if status == BLOCKED_EXTERNAL
            else "Bind this current runtime artifact to the Phase 3 evidence ledger and obtain independent review."
        ),
    }
    try:
        output = _safe_output(args.output)
        _write_payload(output, payload)
        output_label = str(output.relative_to(ROOT))
    except Exception:
        output_label = "unwritten"
        if status == PASS:
            status = FAIL
            payload["status"] = status
            payload["runtime_claim"] = False
    print(json.dumps({"output": output_label, "status": status, "runtime_claim": payload["runtime_claim"], "production_safe": production_safe}, sort_keys=True))
    if status == PASS:
        return 0
    if status == BLOCKED_EXTERNAL:
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
