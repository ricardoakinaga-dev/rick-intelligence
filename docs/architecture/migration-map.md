# Phase 1 migration map

Status: `PROPOSED`, with Phase 1.1 safety scaffolding only. The current
implementations remain authoritative until the exit evidence in this map is
available.

| Preserved source | Contract/adapter seam | Target boundary | Phase 1.1 action | Removal/switch gate |
| --- | --- | --- | --- | --- |
| `cvg-master-rag-v2/frontend/` | browser/API contract and route behavior | `apps/web` | reserve directory; record `/app` and `/admin` split | native route smoke, accessibility, ACL negatives, and reload persistence |
| `cvg-master-rag-v2/src/api/` | HTTP/error/session contract | `apps/api` | reserve directory; no source move | API contract, authz, error, and integration equivalence |
| `cvg-master-rag-v2/src/services/` | knowledge/ingestion/retrieval interfaces | `packages/knowledge`, `ingestion`, `retrieval`, `storage` | record ownership; do not copy modules | RAG contract-v1, provenance, ACL, idempotency, and regression evidence |
| CVG controlled ingestion/jobs | job lifecycle and worker contract | `apps/worker`, `packages/ingestion` | reserve worker boundary | partial cleanup/recovery, durable job semantics, and restart evidence |
| `rick-professor/src/core/` | Professor orchestration/evidence contract | `packages/professor` | reserve package boundary; retain compatibility service | grounded citation, provider error, lock cleanup, and OpenWebUI contract evidence |
| `rick-professor/src/lib/openai.ts` | provider protocol/error taxonomy | `packages/providers` | document seam only | real protocol, retry, correlation, schema, and dimension tests |
| `rick-professor/src/lib/qdrant.ts` | scoped retrieval adapter | `packages/retrieval` | document named-vector/ACL mismatch as open | shared collection, workspace filter, provenance, and dual-result equivalence |
| `modulo-redis-locker/server.js` | `acquire/renew/release` owner-safe lease contract | `packages/locking` or internal service | reserve both options; keep Locker private | atomic compare-delete/renew, TTL, contention, cleanup, and deployment boundary evidence |
| child JSON/filesystem persistence | repository/blob contract | `packages/storage`; future PostgreSQL/object storage | no migration in 1.1 | dual-read/write, reconciliation, rollback/roll-forward, and restore tests |

## Migration rules

1. No target package imports a legacy directory directly.
2. A compatibility adapter may depend on an old implementation temporarily,
   but the dependency and expiry condition must be explicit.
3. Stable serialized contracts are defined once under `packages/contracts`;
   Python/TypeScript representations are generated or tested against it in a
   later phase.
4. A legacy path is removed only after the new app/package is wired, dual
   verification passes, the relevant E2E path passes, and rollback is
   documented.
5. The root command layer may invoke old commands for evidence, but it does
   not change their behavior or claim that they are already consolidated.

## Phase 1.3.1 closure (identity/auth canonicalization)

- `packages/authorization` (`rick_authorization`) is the single policy engine;
  `packages/identity` (`rick_identity`) the lifecycle source of truth;
  `packages/contracts` owns `SessionSnapshot`/`RetrievalContext`/security DTOs.
- `apps/api` services/dependencies are thin facades (no local registries, maps,
  or role fallback). `models.SessionSnapshot` re-exports the canonical contract.
- Preserved CVG `services/authorization.py` + `enterprise_service.py` remain
  byte-identical; engine-level differential parity proven
  (`apps/api/tests/test_differential_auth.py`); caller switch via
  `apps/api/src/adapters/legacy/auth_facade.py` deferred per route to Phase 1.4+.
