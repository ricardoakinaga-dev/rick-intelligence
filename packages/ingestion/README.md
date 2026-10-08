# `packages/ingestion`

Reserved for the validated acquire → validate → parse → normalize → structure
→ chunk → enrich → embed → index → validate → publish pipeline. The current
CVG ingestion implementation remains unmoved.

The local compatibility path uses `InProcessParserRunner`. The external worker
composition uses `ProcessParserRunner` (the backwards-compatible parser name
for `ProcessIsolatedExecutor`), which runs each parser in a fresh `spawn`
child with a wall-clock deadline, advisory resource limits and process-group
termination. Parser stdout and stderr are redirected to a sink before parser
code runs, so untrusted/native diagnostics have a zero-byte external bound;
structured parser results use the bounded JSON-only versioned wire schema and
hard serialized-result ceiling. The parent never unpickles child data.
Oversized or malformed custom-runner output fails closed. The local default
remains in-process for compatibility; external composition opts into the
isolated runner explicitly. PDF and DOCX support is packaged in the API and
worker images with pinned `pdfplumber` and `python-docx` dependencies.

Publication ownership is stored per execution, independently of the queue job
ID. Every document/chunk/vector write and compensation holds the knowledge
store's shared mutation guard and verifies that token. A successor takes over
under the same guard and retires any partial vectors before indexing its own
publication. An obsolete execution cannot send a later batch or remove the
successor's effects. Replacement retirement and rollback hold both document
guards in stable order; lease loss after publication defers retirement.

The lease guard checks entry and immediately before commit. A successful
document commit and terminal job transition define publication. A guard-exit
failure records `publication_guard_error_after_commit` and preserves the real
published outcome and data. A cancel request during exit cannot relabel that
terminal job. Failure before commit compensates only the current attempt.

Completion notifications run after commit. An exception from that callback
records `completion_notification_error_after_commit` and returns the actual
published job through package, API, and worker callers. It does not retry the
callback, whose delivery may already have happened, or compensate published data.
The marker is outcome evidence, not a claim of durable notification delivery.

This outcome rule also covers typed exceptions from subsequent reindex lease
callbacks. A failed guard exit or retirement check returns the committed job,
records deferred retirement, and preserves both versions' data. Explicit failed
retirement compensation still reports its actual failed outcome. Publication
and duplicate decisions share the knowledge collection guard with catalog writers;
their lock order is collection, document, then job state. Late deduplication drops
its claim's document guard before entering that publication boundary.

The AUD03 PostgreSQL regressions are opt-in:
`RICK_AUD03_TEST_DATABASE_URL=<disposable migrated lab> python -m pytest -q packages/knowledge/tests/test_aud03_postgres_live.py`.
Set `PYTHONPATH` to the current repository's `packages/*/src`, `apps/worker`, and
`apps/api/src` directories; the complete knowledge suite's publication gate
probe also uses `apps/api/tests`. They
seed unique fixture scopes and delete only those rows; they do not run migrations
or claim Qdrant/process-death validation.


When publication commits but its acknowledgement is lost, recovery reads the
owned document under its effect fence. Recovery tries at most three reads. If
all fail, the job stays `verifying` with an explicit unknown-outcome marker;
cancellation remains a request and data/source are retained. No failed read
proves rollback. `IngestionService.reconcile_publication(job_id)` can retry
that process-local outcome without starting another attempt. API service callers
use `IngestionApplicationService.reconcile_publication` with tenant/workspace
and collection authorization to finish source registration, journal outcome,
filename ownership and derived refresh. Repeated published registration is
idempotent. This seam has no HTTP route, background scheduler or restart recovery
guarantee; successful local journal updates do not prove recovery during a
journal outage.
