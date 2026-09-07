# Phase 1.6 — Operational Ingestion and Lifecycle

## Objective

Continue the canonical root construction by replacing the document-upload and
job facades with a bounded, authenticated ingestion slice. A successful upload
must travel through generated private storage, the canonical parser/chunker /
embedding/index pipeline, verification, publication, and retrieval refresh.
Operators must be able to inspect safe job state and request cancellation. The
readiness endpoint must report the dependencies actually selected by the
runtime, while preserving the explicit local/hermetic fallback.

This phase is additive and brownfield-safe. The three preserved child
repositories remain read-only and no live credentials or external service are
required for verification.

## Frozen quality bar

| ID | Criterion | Severity | Required evidence |
| --- | --- | --- | --- |
| PH16-INGESTION | Authenticated manager upload accepts supported multipart content, enforces filename/size/type validation, writes only to generated private storage, and invokes the canonical ingestion pipeline. | critical | API tests + package tests |
| PH16-JOBS | Job state is queryable through a safe contract; terminal publication/failure/cancellation is explicit; cancellation and retry semantics cannot corrupt published data. | critical | API/package tests |
| PH16-INDEX | Published ingestion refreshes root retrieval with complete provenance, stable IDs, ACL filtering, and no stale vector drift on reindex/delete. | critical | RAG E2E + API tests |
| PH16-API | Documents are listed from the knowledge store with workspace/collection authorization; upload and reindex routes return stable job/document envelopes; missing resources are non-leaky. | critical | API contract/security tests |
| PH16-READINESS | Liveness stays dependency-free; readiness includes selected provider, lease, retrieval, and ingestion/storage checks with required/optional semantics and no secret detail. | high | health tests + manual JSON inspection |
| PH16-REGRESSION | Phase 1.5 and Phase 1.4 suites remain green; legacy children are unchanged. | critical | full command matrix + preservation check |
| PH16-PERF | Bounded local upload/retrieval path has recorded p50/p95 and explicit limits; no unbounded queue, retry, or response buffering. | high | benchmark artifact |
| PH16-REVIEW | A fresh-context critic inspects the resulting artifacts and reports PASS or actionable findings. | critical | independent review artifact |

## Allowed mutation scope

- `packages/knowledge/**`
- `packages/ingestion/**`
- `packages/retrieval/**`
- `apps/api/**`
- `apps/worker/**`
- `scripts/phase16/**`
- `docs/architecture/**`, `docs/progress/**`, `README.md`, `Makefile`,
  `.github/workflows/phase-1.6.yml`, and phase-control files under `.agent/`

## Forbidden mutation scope

- `cvg-master-rag-v2/**`, `rick-professor/**`, `modulo-redis-locker/**`
- database migrations or claims of durable distributed queue/storage
- frontend redesign (`apps/web` remains a reserved consumer boundary)
- deployment, live provider/Qdrant/Redis calls, or credential creation
- raw corpus fabrication, secrets in fixtures/logs, document text in audit
- unbounded retries, unbounded request/file reads, wildcard client ACLs
- weakening or deleting existing tests, gates, or preservation history

## Delivery lanes

1. **Domain/index lane** — knowledge listing/deletion interfaces, ingestion
   safety and provenance, retrieval refresh and metadata preservation.
2. **API lifecycle lane** — bounded upload storage/application service, document
   routes, job routes, admin observability, DI wiring and compatibility.
3. **Worker/readiness lane** — bounded in-process runner boundary and truthful
   health checks; no distributed worker claim.
4. **Verification lane** — contract/security/E2E tests, benchmark, sanitized
   evidence and independent fresh-context review.

Lanes must not edit outside their ownership without an explicit handoff.

## Honest limitations

The phase provides a complete hermetic/local vertical slice. The default job
runner is process-local and storage is temporary/private to the application
instance; restart recovery, durable queues, object storage, Qdrant, Redis
Locker, real provider rollout, and the production web client remain subsequent
gates.
