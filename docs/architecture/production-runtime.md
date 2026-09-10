# Production runtime architecture

Status: `LOCAL COMPOSITION VERIFIED / EXTERNAL RUNTIME GATE BLOCKED`.

Production starts from a reviewed composition factory. It receives already
owned clients and policies for PostgreSQL, Redis, Qdrant, S3-compatible object
storage, identity, provider and audit. Importing the API or worker never opens
a socket, reads a secret-bearing URL as proof of health, or silently installs a
process-local fallback.

The API must receive an externally composed `Providers` container. Required
components include identity, metadata store, durable queue, object store,
vector store, retrieval, ingestion, worker, audit, history and provider
boundaries. Readiness is the conjunction of explicit component probes; a
configured value without a successful probe is not ready.

The worker owns the polling loop, scoped lease, heartbeat, bounded handler
execution, cancellation, retry/dead-letter mapping and shutdown report. The
external composition injects the canonical `ProcessParserRunner`: each parser
gets a fresh `spawn` child, a wall-clock deadline, advisory CPU/memory limits
and process-group termination on timeout. The parser response crosses the
child boundary through a bounded versioned JSON envelope; child-controlled
bytes are never unpickled in the worker process. The local compatibility path keeps
the cooperative runner and is never used as proof of external runtime health.

## Failure policy

- database, queue, lease, object, vector, identity or provider failures map to
  typed safe errors and preserve the durable state transition;
- a lost lease or stale version cannot acknowledge or publish a job;
- a missing external capability fails startup in production;
- telemetry and audit delivery cannot mutate the job transaction;
- retries are bounded and poison jobs move to a dead-letter state;
- shutdown stops admission, waits within a finite budget and reports work that
  could not be drained.

The local test matrix proves contracts, fakes and the parser child boundary.
It does not prove network connectivity, PostgreSQL locking, two-worker
fencing, crash recovery, live SIGTERM, provider behavior or deployment health.
