# Ingestion lifecycle (Phase 1.6)

Phase 1.6 connects the root API to the existing canonical ingestion pipeline
with a bounded application facade. The facade owns HTTP input handling and
safe job representation; `packages/ingestion` remains the owner of document
identity, parsing, chunking, embedding, indexing, verification, publication,
and failure state transitions.

## Public surface

| Route | Permission | Behavior |
| --- | --- | --- |
| `POST /api/v1/documents/upload` | `documents.upload` | Multipart `file` + `collection_id`; returns `202` with a job id before processing; small JSON compatibility body is also accepted. |
| `GET /api/v1/ingestion/jobs/{job_id}` | `ingestion.run` | Returns a workspace/collection-scoped, whitelist-based job DTO. |
| `POST /api/v1/ingestion/jobs/{job_id}/cancel` | `ingestion.run` | Requests cancellation and returns the resulting safe DTO. |
| `POST /api/v1/ingestion/jobs/{job_id}/retry` | `ingestion.run` | Creates a new bounded attempt from caller-supplied replacement content; the failed/cancelled attempt remains immutable. |
| `POST /api/v1/ingestion/reindex` | `reindex.run` | Reindexes an authorized existing document from retained local source or bounded replacement content. |
| `GET /api/v1/documents` | `documents.read` | Returns published, ACL-filtered metadata only; supports bounded cursor pagination; chunks, source paths, and content are excluded. |
| `DELETE /api/v1/documents/{document_id}` | `documents.manage` | Removes indexed points, writes the knowledge tombstone, removes the local source, and refreshes local retrieval. |

## State and publication gate

The canonical job may move through `queued`, `validating`, `parsing`,
`chunking`, `embedding`, `indexing`, and `verifying` before it becomes
`published`. A failed or cancelled attempt never replaces the previous
published source. Failed post-write attempts compensate metadata, chunks, and
vector points on a best-effort basis, while retrieval revalidates publication,
workspace, and collection before indexing. The retrieval facade is refreshed
only after publication or successful deletion, so a failed write is not
represented as searchable content even if a storage adapter reports partial
state.

The application boundary also validates the adapter postcondition for reindex.
The returned job must carry the requested tenant/workspace/collection scope and
an opaque non-empty document identity. A replacement may legitimately receive
a new document version identity; when the adapter exposes canonical document
lookup, that new record must resolve to the exact requested scope before it is
accepted. Scope drift is rejected and a replacement source is removed or
retained in a bounded, private cleanup lease.

Page provenance is preserved as a complete `page_start`/`page_end` span. A
retry is an explicit fresh attempt with bounded replacement content; it does
not mutate or replay the original failed attempt.

All API-facing job data is whitelist-serialized. It contains bounded IDs,
state/progress, safe error codes/messages, timestamps, and the explicit
`process-local`/`private-temporary` lifecycle metadata. Raw exception text,
paths, filenames, source content, parser metadata, and heartbeat internals
are not public fields.

Tenant scope is mandatory at every public knowledge/lifecycle handoff. The
authenticated snapshot must carry a non-empty tenant explicitly; a missing
tenant is never interpreted as `default`. Internal document DTOs retain the
validated tenant long enough for the route boundary to re-check it, and the
public whitelist removes it from document metadata responses. Tenantless
legacy records are therefore invisible, including to the default tenant, while
non-default tenants retain their own published listing.

## Bounded local adapter

The API staging facade enforces:

- a maximum upload size (`API_MAX_UPLOAD_BYTES`, default 50 MiB);
- a maximum staged byte budget of two uploads in the default factory;
- a finite retained job count (`INGESTION_MAX_PENDING_JOBS`, default 64);
- bounded package heartbeat history (128 entries) and worker progress history
  (256 sanitized entries);
- fixed-size reads, generated server-side storage names, and mode `0700/0600`
  private temporary storage;
- a bounded one-worker queue moves synchronous package execution off the async request loop; and
- owner/workspace/collection checks before status, reindex, cancellation, or
  deletion.

Retained no-content reindex sources are also finite. When the source budget is
full, the oldest private source is evicted while its safe job snapshot remains
available; reindex callers can provide replacement content explicitly.

The API application owns a bounded one-worker process-local queue for public
uploads. `POST /documents/upload` returns a queued job immediately, and the
cancel route signals both queued and cooperatively running jobs. The canonical
package pipeline remains synchronous inside that worker. `apps/worker.LocalJobRunner`
is a separately tested generic seam; the API factory intentionally does not
import `apps.worker`, because application-to-application imports violate the
repository dependency boundary. A future integration must inject a durable
worker through an explicit package contract.

The application queue has a finite in-flight budget (`INGESTION_MAX_PENDING_JOBS`)
and retries are capped at three new attempts per failed/cancelled job. Without
the optional local `JobJournal`, queue records, source staging, and status
snapshots remain process-local and are lost on restart. With the journal
configured, a bounded whitelist of job state and private staging references is
reopened; published sources support reindex and recoverable non-terminal jobs
are resumed locally. Missing or malformed recovery sources/scopes become an
explicit opaque `recovery_required` failure. This is restartable local
plumbing, not a distributed queue or production durability claim.

Cleanup is fail-closed at the ownership boundary. A terminal source is not
forgotten before unlink succeeds: failed unlink keeps the path private in the
in-memory job and, when configured, in the journal for retry on restart. If the
journal write and unlink fail together, an atomic private cleanup lease under
`.cleanup-leases/` retains the last validated staging reference for the next
process. Sources
created before a job exists use a synthetic failed `recovery_required` job with
the already-authorized tenant/workspace/collection scope. The same rule covers
capacity eviction, reindex replacement retirement, cancellation, delete, and
unexpected application-boundary failures.

Application mutations use one admission protocol. Synchronous upload, reindex,
retry, and delete take the canonical operation guard before the application
state lock; an operation that has crossed shutdown admission therefore cannot
start after the local worker has been stopped. The canonical publication gate
and application cancellation share the application publication gate, including
the idempotent/deduplicated publication path. Cancellation signals the running
pipeline before waiting for canonical reconciliation; its response adopts a
visible canonical terminal result when one exists, so it cannot report a
cancelled placeholder after publication has won the gate.

The retrieval refresh hook is a derived read-model callback. It runs only after
the application mutation lock and canonical operation lock are released; its
admission lease still keeps dependent stores alive while it runs. Callback
failure is isolated from the already-committed job. The authoritative local
journal/cleanup bookkeeping remains inside the mutation transaction, while
optional event delivery is best effort and outside the application lock.

## Application lifecycle ownership

The root factory creates an application-owned local ingestion executor. Its
shutdown is tied to the ASGI lifespan so a `TestClient`/server close does not
leave a worker service alive after the application has stopped. The shutdown
path is idempotent, cancels queued local futures and cleans their private
staging references, waits for cooperatively cancellable running work before
closing dependent stores, and closes only resources constructed by the default
factory. Caller-injected providers remain caller-owned. This local lifecycle
binding is independently verified; it does not imply distributed worker,
external queue, or tenant/security acceptance.

The lifespan uses one finite five-second deadline covering queued cleanup,
best-effort shutdown telemetry, cooperative worker join, and owned-resource
closure. If a parser or native adapter ignores cooperative cancellation, the
app records an incomplete shutdown and deliberately leaves dependent stores
open rather than closing a resource still in use; Python cannot safely
preempt arbitrary blocking code. Admission remains closed after a failed stop;
the same service can be retried to complete worker/resource cleanup. An automatically
created `/tmp/rick-ingestion-*` root is removed only when it has no journal
owner; its private cleanup is itself deadline-aware and can be retried after a
slow filesystem call. Configured staging roots and journal-backed recovery
sources remain operator-owned. A lazily created API wrapper around an injected
canonical `ingest()` provider is app-owned and is closed without closing that
canonical provider. Starlette's lifespan runs when `TestClient` is used as a
context manager; calling `TestClient.close()` alone is not a lifespan proof.

## Rollout and readiness

`RICK_API_ROOT_KNOWLEDGE=0` preserves the legacy document-read facade, and
`RICK_API_ROOT_RETRIEVAL=0` is the explicit retrieval rollback. In
local/test/dev environments the default factory wires deterministic hash
embeddings and in-memory knowledge/vector stores, and the local stub backend
uses that retrieval path so the full upload-to-chat flow is reproducible
without credentials. Production does not silently use that fixture: startup
fails closed unless an external identity provider is injected, and the
production ingestion path remains unavailable until real storage, embedding,
queue, and recovery adapters are supplied. A configured legacy backend also
fails startup if its adapter cannot be loaded; it is never silently replaced by
the stub.

`/health/live` remains dependency-free. `/health/ready` reports selected local
components without diagnostic details; `/api/v1/admin/health` exposes only
sanitized bounded details. Readiness is not evidence that an external provider,
Qdrant, Redis, object store, or durable queue is reachable unless an integrator
registers an explicit check for that dependency.

## Evidence

Run `make api16-full` for the focused implementation matrix and
`make api16-verify` for the sanitized regression matrix. The generated
artifacts are:

- `docs/progress/phase-1.6-perf.json` — local timings, bounds, and dependency
  status; and
- `docs/progress/phase-1.6-verification.json` — command outcomes, child-tree
  cleanliness, and benchmark presence without captured command output.

These artifacts make no production throughput/latency or external-service
availability claim.
