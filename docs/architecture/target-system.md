# RICK Intelligence target system

Status: `PROPOSED` for future phases; no target runtime is implemented by
Phase 1.1.

RICK Intelligence will be one platform with two first-class experiences:

- `/app` — Veterinary Clinical Workspace, containing Professor chat, history,
  authorized sources, optional deep search, and profile;
- `/admin` — Administration / Knowledge Management Console, containing corpus,
  ingestion, jobs, collections, RBAC, audit, evaluation, retrieval settings,
  security, health, backups, and settings.

The proposed root boundary is:

```text
rick-intelligence/
├── apps/
│   ├── web/              # native Next.js experience; future source from CVG frontend
│   ├── api/              # canonical HTTP boundary; future source from CVG API
│   └── worker/           # durable long-running work; future source from CVG jobs/ingestion
├── packages/
│   ├── identity/         # users, credentials, sessions, snapshots
│   ├── authorization/    # permissions, grants, retrieval context
│   ├── knowledge/        # documents, collections, versions, provenance
│   ├── ingestion/        # acquire → publish pipeline contracts
│   ├── retrieval/        # scoped dense/sparse/fusion/rerank/evidence
│   ├── professor/        # orchestration without HTTP concerns
│   ├── providers/        # LLM/embedding/reranker adapters and errors
│   ├── storage/          # repository/blob/vector seams
│   ├── locking/          # owner-safe acquire/renew/release contract
│   ├── audit/            # sensitive action event model
│   ├── observability/    # IDs, logs, metrics, traces
│   ├── contracts/        # canonical serialized cross-language contracts
│   └── shared/            # small dependency-free primitives
├── infrastructure/
│   ├── docker/ compose/ migrations/ monitoring/ scripts/
├── tests/
│   ├── contract/ integration/ e2e/ security/ regression/ concurrency/ performance/
└── docs/
```

This tree is a boundary contract, not permission to populate it with copied
runtime code. A package must have a stable contract, a caller, equivalence
evidence, and an explicit owner before it becomes executable.

## Ownership and direction

```text
apps -> packages -> shared/contracts
apps -> contracts (when direct boundary typing is required)
tests -> apps/packages/legacy adapters
infrastructure -> apps/packages (deployment only)
legacy components -/-> each other and -/-> new packages until adapted
```

Identity and authorization own permission semantics; retrieval receives an
already-built `RetrievalContext`; knowledge owns lifecycle/provenance but not
Qdrant HTTP; Professor owns orchestration but not server concerns; locking
owns lease semantics but not Professor policy.
