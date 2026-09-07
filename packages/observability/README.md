# `packages/observability`

This package contains dependency-light, bounded primitives for structured
events, request/correlation IDs, deterministic trace sampling, counters,
histograms and explicit SLO/alert evaluation. `BoundedEventBuffer` provides a
thread-safe 256-entry local ring, while `emit_safely` redacts before invoking
an injected sink and isolates callback failures. `opaque_ref` creates stable
short references for opaque worker identifiers. `safe_event`/`redact` remove
tokens, credentials, prompts, document/content fields, stack traces and
userinfo/query/fragment components from hierarchical URLs before serialization.

These are composition seams, not a telemetry backend. No exporter, global
logger, trace collector, metrics server or production integration is created
by importing the package; live telemetry evidence remains `NOT_RUN`.

The API composes these primitives in `apps/api/src/core/telemetry.py` and
exposes its per-process snapshot through the authenticated
`GET /api/v1/admin/metrics` route (`observability.read`). Counters are
cumulative, while error-rate and latency SLO observations share the last
10,000 requests. A separate 256-entry ring retains only redacted request and
transport outcome metadata for local correlation. Latency measures
response-header availability, not completion of streamed bodies. Early
middleware rejections are counted. Labels and event fields contain finite
route families and status/method classes; request contents and query strings
are excluded. Export remains explicitly `NOT_CONFIGURED`.

The root API composes the same sink contract into its local ingestion
executor. `ApiTelemetry.emit` applies an application-level worker allowlist in
addition to package redaction, so only bounded lifecycle fields and opaque
references reach the admin snapshot. This remains a process-local observation
of the actual root executor, not a broker, collector or multi-instance
delivery guarantee.
