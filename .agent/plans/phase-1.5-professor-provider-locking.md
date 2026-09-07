# Phase 1.5 — Professor, Providers & Locking Extraction

Status: IMPLEMENTATION_READY. This is the next user-authorized strangler slice
after the verified Phase 1.4 RAG extraction. It adds root-owned contracts and
runtime packages, wires the canonical API behind an explicit rollout switch,
and keeps `rick-professor/` and `modulo-redis-locker/` byte-identical.

## Goal

Provide one root-owned, testable Professor orchestration path that consumes the
verified retrieval engine, validates evidence provenance, uses typed provider
and lease contracts, propagates cancellation/correlation, and exposes the same
platform/OpenAI-compatible API shapes with a reversible rollout. No production
deployment or live provider quality claim is made by this phase.

## Authorization and constraints

- Authorization: local implementation explicitly requested by the user.
- Mode: execute, multi-round, local-write only.
- Preserve all unrelated work and all three preserved component histories.
- Do not edit `cvg-master-rag-v2/`, `rick-professor/`, or
  `modulo-redis-locker/`.
- Do not read or emit secrets, contact external systems, deploy, publish, or
  fabricate a corpus/provider result.
- Legacy and stub paths remain available as rollback controls until fresh
  integrated evidence proves the root path.

## Frozen quality bar v1

| ID | Dimension | Required target | Exact evidence | Priority |
| --- | --- | --- | --- | --- |
| PH15-CONTRACTS | contract integrity | Versioned provider, lease, Professor result and citation contracts are strict, serializable, and contain no credentials, raw provider bodies, or chain-of-thought | package contract tests + serialization inspection | critical |
| PH15-PROVIDER | provider boundary | Root provider performs OpenAI-compatible HTTP through one typed boundary; validates models/content/embedding dimensions; timeout and bounded retry preserve one correlation ID; errors are safe and classified | local disposable HTTP protocol fixture covering success, timeout, unavailable, 429, 5xx, malformed/missing/invalid JSON, model and dimension failures | critical |
| PH15-LOCK | concurrency/safety | Lease acquire/renew/release is owner-bound, expiry-aware, cancellation-safe, and never silently releases another owner; failures are typed and bounded | deterministic in-memory race/expiry/failure suite + HTTP contract fixture | critical |
| PH15-PROFESSOR | grounded behavior | Root Professor requires trusted RetrievalContext, uses root retrieval, distinguishes no/weak/approved evidence, never emits unverified citations or source text, and returns a safe bounded result | unit/property negatives + end-to-end deterministic retrieval/provider/lease fixture | critical |
| PH15-API | public integration | `/api/v1/chat` and `/v1/chat/completions` can use the root Professor backend under a validated rollout setting; response/SSE/error contracts remain compatible; rollback is explicit | API matrix with root backend enabled/disabled, compat checks, streaming, errors, and OpenAPI generation | critical |
| PH15-OBS | reliability/diagnostics | request/correlation IDs and provider/lease metadata propagate without secret/URL/body leakage; cancellation releases resources | focused observability and cancellation tests + redaction inspection | high |
| PH15-REGRESSION | compatibility | Phase 1.4 package/API/ACL/differential gates stay green and preserved legacy trees remain unchanged | `make api14-full`, `make api-test`, focused root suite, Git/diff checks | critical |
| PH15-PERF | performance | deterministic root orchestration has a recorded bounded local baseline; no unmeasured claim of live-provider latency | reproducible benchmark artifact with workload/sample/environment | medium |
| PH15-REVIEW | independent judgment | fresh read-only Final Critic checks every required criterion against the integrated artifact and finds no material gap | non-inherited Critic response + mutation sentinel | critical |

## Workstreams and ownership

| Task | Owner | May edit | Dependencies | Validation |
| --- | --- | --- | --- | --- |
| PH15-CONTRACTS | Lead | `packages/contracts/**` | this bar | contract tests and import boundary |
| PH15-PROVIDER | Provider builder | `packages/providers/**` | PH15-CONTRACTS snapshot | local HTTP protocol fixture and unit tests |
| PH15-LOCK | Lock builder | `packages/locking/**` | PH15-CONTRACTS snapshot | race/expiry/failure tests |
| PH15-PROFESSOR | Professor builder | `packages/professor/**` | provider + locking contracts and Phase 1.4 retrieval | deterministic vertical tests |
| PH15-API | Lead/integrator | `apps/api/**`, `scripts/phase15/**`, `Makefile`, `.github/workflows/phase-1.5.yml` | Professor contract | API/compat/streaming/rollback checks |
| PH15-DOCS | Lead | `docs/architecture/**`, `docs/progress/**`, `README.md`, `.agent/**` | current evidence | cross-reference and state checks |
| PH15-REVIEW | fresh Critic | read-only; report returned to Lead | integrated candidate | criterion-level independent review |

Builders must not spawn descendants, change the bar, touch `.agent/` state, or
edit preserved child paths. The Lead owns shared contracts, integration and
the final verdict.

## Rollout contract

`RICK_API_CHAT_BACKEND=stub|professor|legacy` is validated at startup. Local
tests default to `stub`; production mode fails closed unless `professor` has a
configured provider and lease implementation. `legacy` is an explicit bridge,
not a default and not a second root implementation. A root Professor backend
without a configured live provider may use only the deterministic test/dev
provider; its responses are labelled non-production.

## Stop and promotion rules

The phase is `VERIFIED_CANDIDATE` only after every required gate has current
evidence, integrated checks pass, preserved trees are unchanged, and a fresh
Final Critic returns no material gap. Missing Docker, credentials, external
OpenWebUI, production network, or historical corpus evidence remains visible
as `NOT_RUN`/`BLOCKED`; it cannot be converted into a pass. Phase 1.6 web/worker
and production promotion remain separate scopes.
