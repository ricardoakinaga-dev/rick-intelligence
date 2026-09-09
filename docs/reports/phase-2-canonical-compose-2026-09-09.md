# Phase 2.7.2 — Canonical Compose implementation review

**Date:** 2026-09-09
**Decision:** `IMPLEMENTED / LOCAL_VERIFIED / RUNTIME BLOCKED_EXTERNAL`

## Delivered topology

Both root Compose files now declare the same canonical service boundary:

`postgres → redis → qdrant → object-store → jaeger → otel-collector → metrics
→ api → worker → web`.

The stack includes:

- explicit Postgres, Redis, Qdrant and MinIO credentials/endpoints;
- API, worker and web immutable image inputs;
- OpenTelemetry Collector OTLP gRPC/HTTP receivers;
- Jaeger trace storage and Prometheus metrics storage;
- collector health gating before API/worker readiness;
- private/internal dependency networking and declared persistent volumes;
- environment templates with mandatory `RICK_OTEL_ENDPOINT`.

No service silently falls back to a process-local or unauthenticated dependency
when a required value is absent.

## Verification

| Check | Result | Boundary |
| --- | --- | --- |
| `make compose-static` | `PASS` | Both Compose files render with their example environment and contain all 10 canonical services. |
| YAML parse of both Compose files and observability configs | `PASS` | Syntax/config files are structurally readable. |
| `make validate` | `PASS` | Root boundaries and control-plane records remain valid. |
| `make dev` | blocked before startup | It maps to Compose `up`, then fails closed on missing required image/environment values in this checkout. |
| Docker daemon probe | `BLOCKED_EXTERNAL` | The host Docker socket is inaccessible; no containers, volumes or networks were started or changed. |

Static rendering is not runtime evidence. Live health, migrations, queue
fencing, telemetry propagation, trace/metric collection, shutdown, recovery,
cross-tenant smoke and teardown remain unexecuted until an authorized
disposable Docker daemon and non-production credentials are available.

The next slice is **Phase 2.7.3 — PostgreSQL Runtime Gate**. Its harness must
run against real PostgreSQL and preserve fail-closed behavior when the daemon
is unavailable; scripted/fake connections cannot promote the queue or worker.
