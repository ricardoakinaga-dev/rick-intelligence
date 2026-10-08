# Bounded process-local telemetry sink delivery

**Decision:** OBS-SINK-2026-09-25-01. **Status:** local implementation with verified worker process shutdown; API process ownership and external delivery remain open.

## Problem and invariant

Diagnostic sink callbacks are injected into API and worker code. They may block,
raise, or be saturated. Telemetry must not change the result or hold an
operational caller indefinitely. A reported successful delivery must mean the
callback returned successfully before the caller's wait budget elapsed.

Current evidence shows that the canonical API image includes
`packages/observability` on `PYTHONPATH`. Standalone API mode also retains a
local fallback. Both paths therefore need the same bounded contract. No
external exporter or distributed delivery guarantee is currently configured.

## Selected design

Use a process-local fixed pool of two daemon workers and a queue capped at 1,024
waiting events. The default caller wait is 250 ms; `timeout=None` is a
compatibility spelling for that same finite wait. A full queue drops the new
best-effort event. Sink method discovery avoids running descriptors on the
caller thread; lookup and invocation happen on a worker. Callback exceptions
increment the failure counter and return a failed observation.

A timeout returns `False` without cancelling work already queued or active,
so the callback may complete later. `False` means there was no successful
completion observation inside the caller's budget. It does not mean the event
was definitely not delivered. Durable audit and business effects remain on
their own synchronous or transactional paths.

Fixed-cardinality worker, queue and delivery outcome metrics are available in
the authenticated API metrics JSON and Prometheus routes. Reading the snapshot
does not initialize the lane. The standalone API fallback keeps a matching
bounded lane and metrics shape when the package import is unavailable.

### Root ingestion lifecycle events

The API producer offers `worker.ingestion.enqueued` before opening the worker
start gate and `worker.ingestion.started` before processing when a scheduled
attempt proceeds. The worker then offers `worker.ingestion.published`,
`worker.ingestion.failed`, or `worker.ingestion.cancelled` after the terminal
state and any configured root retrieval refresh. Shutdown may also offer a
separate `cancelled` notification for outstanding jobs. The producer waits for
each sink callback to finish or reach its 250 ms budget before it advances.
Delivery uses the best-effort lane above: a timeout may leave a callback
running, and saturation may drop an event, so callback arrival order is
guaranteed only when each callback finishes within its budget. These events are
diagnostic telemetry; the job record remains the source of lifecycle state.
Tests wait for the published callback before inspecting the event list, because
the terminal job state can become visible before the asynchronous sink records
its event.

## Alternatives and trade-offs

- Calling the sink on the caller thread is rejected because a blocked callback
  or `emit` property can hold a worker or request beyond its deadline.
- Creating one thread per event is rejected because concurrency and thread
  creation are then driven by event volume; both the package lane and API
  fallback also used to report callback exceptions as completed.
- A process-local fixed pool is selected as the smallest existing design that
  bounds concurrent callbacks and queued memory while preserving best-effort
  isolation. It adds two worker threads and a finite queue per process.

## Failure, security and lifecycle

The event is redacted before enqueue. Metrics contain only fixed outcome names
and numeric gauges; event payloads and sink exceptions are not added to those
metrics. Queue saturation increments `dropped`; callback exceptions increment
`failed`; caller wait expiry increments `timeout`; an incomplete drain
increments `shutdown_timeout`.

`shutdown_sink_delivery(timeout=2.0)` closes an existing process-global lane,
waits up to the supplied bound, discards queued events at the deadline and
returns `False` if a callback remains active. In the package implementation an
unused lane returns `True` without allocating delivery threads; this no-op does
not prevent a later producer from creating a lane. Call it after stopping the
event producers. The standalone API fallback retains its existing behavior.

The actual worker entrypoint now owns a `finally` drain around `main()`. After
worker shutdown it gives the already-loaded observability package two seconds
to finish diagnostics, including events queued by cleanup. It runs on normal
completion, health-check exit and startup/run failure. An incomplete drain or
unexpected cleanup exception emits a fixed stderr message and preserves the
worker's operational exit status. Unused optional telemetry is not imported on
exit. This budget is additional to the existing worker shutdown budget.

Imported `main()` does not own this hook. The current per-app FastAPI lifespan
also does not call it: the lane may be shared by more than one app instance in
tests or embedded use. API process-owner integration remains open. A permanently
blocked daemon callback can outlive the drain deadline and be terminated with
the worker process; this is best-effort diagnostics, not durable audit delivery.

## Verification and limits

The package and API focused tests cover callback failure, `timeout=None`, a
blocking `emit` descriptor, fixed worker/queue bounds, overload counters,
bounded shutdown and the API JSON/Prometheus signal shape. The new worker
subprocess tests use the actual entrypoint and actual package with synthetic
callbacks. They verify SIGTERM/SIGINT, final cleanup events, normal/health-check
exit, startup/run failures, a permanently blocked callback and continued use
after an embedded `main()` call. The original focused launcher/process/package
run passed 34 tests; after adding the exact two-second budget regression, the
combined Docker-test and observability-package run passes 46 tests. The added
test preserves success, failure and configuration-exit outcomes when the drain
succeeds, times out or raises. Its pre-fix run failed all seven original process
scenarios. The separate worker/API health/telemetry regression passes 129 tests.

These establish local process behavior only. Representative throughput/tail
latency, an external collector, distributed runtime and API process-owner
integration remain unverified. Evidence and the frozen scoped criteria are in
`docs/reports/evidence/implementation-q24-2026-09-24/verification-q24-08-worker-shutdown-20260925/`.
Q17-23.A remains `VERIFY`; this note does not close the broader observability
gate or authorize release.
