# Phase 3 runtime evidence and production promotion — living ExecPlan

<!-- engineering-framework: active_action_id=PH3-2-LAB-READINESS:WAIT_RUNTIME -->

## Purpose / Big Picture

Move the root candidate from local State-of-Art preparation to a truthful
runtime promotion decision. The plan binds every claim to the exact commit,
artifact digest, environment, procedure, reviewer and limitation while
preserving the frozen Gauntlet bar, Phase 2 history and legacy repositories.

## Progress

- [x] (2026-09-09) Read the exact Phase 3 prompt and verified its byte-exact copy and SHA-256.
- [x] (2026-09-09) Froze HEAD `56a76004a75ec94178e35c82eab8405b5ac74729` and completed the current audit.
- [x] (2026-09-09) Verified the canonical local control, static, API and frontend baseline.
- [x] (2026-09-09) Created the public Phase 3 plan and preserved the Phase 2 plan as historical context.
- [x] (2026-09-09) Implement and locally verify Phase 3.1 evidence binding, required-row coverage, runtime envelopes, negative release tests, canonical conditional lanes and dynamic local-check records; fresh independent review found no local P0/P1/P2 defect.
- [x] (2026-09-09) Implement and independently review Phase 3.2 readiness-aware Compose lifecycle, explicit local project/socket scoping, Worker A/B topology, bounded diagnostics and safe teardown parsing; live startup remains blocked externally.
  - [x] (2026-09-09) Close the corrected Phase 3.1 evidence boundary at reviewed source candidate 7ea1f287f452ac14d6126060f5811d2fc00920a7; 90 local tests and a fresh independent I1 review passed, while runtime promotion remains blocked.
- [x] (2026-09-10) Add the real two-process PostgreSQL multi-worker gate at source implementation candidate 3fae7e6c7d993d03e71cdf79f43393fcffb1ca0c, including heartbeat, crash/reclaim and stale-ACK fencing assertions; 153 local tests and fail-closed static checks pass, while execution remains blocked without an approved disposable runtime.
- [x] (2026-09-10) Correct the canonical Redis slice at source implementation candidate 8f2741d39d83622dc966b859fac06630848d916b: the two-process gate now drives two real `apps/api` HTTP processes, verifies replay/tenant/bounded-TTL behavior, and binds production composition and admission to the injected Redis client/namespace; local API, locking and State-of-Art suites pass, while the real Redis run remains BLOCKED_EXTERNAL.
- [x] (2026-09-10) Bind citation-support metrics to strict Decision gates at source candidate 4302d48ae90bd17aec9380bbc3ab2d2e1244dbcb; local decision/evidence/Professor/API suites pass, while live golden/provider evidence remains required.
- [x] (2026-09-10) Harden the release packet at source candidate 7f8fcdfec613085af0384fc76a5bcdb9184ef994: command exit zero cannot override blocked/invalid phase3 or release artifacts, mandatory runtime gates consume named envelopes (including multi-replica Redis and DR/citation/decision), and runtime/frontend/operational diagnostics are transported by the same CI run; `297` combined tests, `make validate`, YAML parsing and independent patch review pass, while promotion remains blocked.
- [x] (2026-09-10) Harden release-manifest consistency at source candidate b4c8ac0c8fee311ede12c417d0be1cbfd5aada38 (tree b8e92492f2216c0c5c0ecdc90ccdfd5807c77d15): conflicting evidence aliases, status aggregates and gate/declaration reviewer identity mismatches now fail closed; `300` combined tests and `make validate` pass, while runtime promotion remains blocked.
- [x] (2026-09-10) Bind the canonical local CI lanes at source candidate 957b534d7b33a025525cb1dd667872791239ed43 (tree 65dcad96347adbd34e267537c424bef444ec48d7): bounded redacted raw artifacts carry same-run GitHub provider/workflow/run/attempt/ref/SHA provenance, release validation rejects replay/mismatch/path/hash errors, `supply-chain` keeps runtime primary, and the frontend runtime job emits the Phase 3 envelope; `256` State-of-Art tests and static/API checks pass, while live runtime promotion remains blocked.
- [ ] (2026-09-09) Execute the disposable runtime; currently blocked by Docker daemon access and unresolved external authority.
- [ ] (2026-09-09) Complete independent runtime/design/security reviews and the human Go/No-Go.

## Surprises & Discoveries

The existing local workflow already has useful FAST, UNIT, CONTRACT, RAG-EVAL,
FRONTEND and SUPPLY_CHAIN jobs. Phase 3 now binds release to successful
conditional runtime lanes and consumes the same-run capability artifact. The
root Compose topology is statically valid and the launcher now validates,
waits and captures bounded diagnostics. The prior release and triple-AAA
packets correctly reject incomplete evidence, but are Phase 2 artifacts and
stale for this prompt. The host provides the Docker client but denies daemon
access, so no live claim can be made.

## Decision Log

- 2026-09-09: Keep HEAD `56a76004a75ec94178e35c82eab8405b5ac74729` as the Phase 3 entry snapshot.
- 2026-09-09: Preserve `.gauntlet/bar.json`, `.gauntlet` history and all Phase 2 ledgers; add a Phase 3 runtime addendum.
- 2026-09-09: Treat the exact prompt copy as the only intentional current worktree change until implementation is reviewed.
- 2026-09-09: Keep unavailable Docker/services/provider/corpus as `BLOCKED_EXTERNAL` or `NOT_RUN`; no synthetic pass is allowed.
- 2026-09-09: Make CI/release evidence the first implementation slice before enabling advanced retrieval or promotion work.
- 2026-09-09: Require complete 17-row capability coverage and structured runtime envelopes; a subset can never be promoted.
- 2026-09-09: Treat `LOCAL_VERIFIED` as an executed local result, not a declaration; the matrix generator records command results before assigning it.
- 2026-09-09: Use Compose `--wait` with a bounded timeout and a fixed local socket/project; a failed start remains `NOT_READY` and emits redacted local diagnostics.
- 2026-09-09: Record the post-fix independent review as PASS for local implementation scope and CONDITIONAL only for the unavailable Docker/runtime evidence; move the active pointer to the external runtime wait.

- 2026-09-09: Record the final evidence-boundary review as PASS for exact candidate 7ea1f287f452ac14d6126060f5811d2fc00920a7; retain BLOCKED/NO-GO for all unavailable runtime and production gates.
- 2026-09-10: Rebind the living control plane to source implementation candidate 3fae7e6c7d993d03e71cdf79f43393fcffb1ca0c and preserve the 7ea1f287f452ac14d6126060f5811d2fc00920a7 review as historical; the new multi-worker gate is locally verified but its real PostgreSQL run remains BLOCKED_EXTERNAL.
- 2026-09-10: Bind the current Redis/API HTTP correction to source implementation candidate 8f2741d39d83622dc966b859fac06630848d916b with tree 2bf66ea20c2d7c2d0f92d3c343c6f4a2e2907d72; retain the fresh independent read-only findings as non-approval and keep the real Redis/runtime decision BLOCKED_EXTERNAL.
- 2026-09-10: Require artifact postconditions in the integrated verifier so a successful generator process cannot hide a blocked, invalid or missing matrix/manifest; preserve the mandatory Redis multi-replica binding and same-run CI artifact provenance, with local patch review separate from runtime promotion.
- 2026-09-10: Bind FAST/UNIT/CONTRACT/SECURITY/SUPPLY_CHAIN CI observations to the current GitHub Actions run and exact checkout; keep `supply-chain` runtime evidence primary, use CI only as a supplemental observation, and keep the frontend adapter envelope separate from local CI. A fresh post-fix read-only review found zero concrete findings; no runtime or Triple AAA claim is made.

## Outcomes & Retrospective

The entry audit established a reproducible baseline and separated local proof
from runtime proof. The candidate has meaningful local coverage, but the work
remaining is acceptance across real dependencies, distributed failure modes,
observability, operations, independent review and authority. The plan remains
active until those gates are either verified or explicitly blocked with an
owner and revalidation trigger.

## Context and Orientation

The root contains FastAPI under `apps/api`, Next.js under `apps/web`, a worker
under `apps/worker`, shared packages under `packages`, Docker/Compose under the
root and `infrastructure`, and evidence/control artifacts under `docs`,
`.agent` and `.gauntlet`. The entry audit is
`docs/reports/phase-3-runtime-evidence-current-audit.md`; the user-facing plan
is `docs/plans/phase-3-runtime-evidence-production-promotion.md`.

## Scope and Constraints

The scope covers CI/release evidence, the disposable Postgres/Redis/Qdrant/
S3-compatible/API/Worker A+B/Web/OTel lab, live queue and ingestion behavior,
multi-tenancy, providers, RAG evaluation, observability, DR, chaos, soak,
performance, frontend QA, supply chain and promotion reporting. Preserve
legacy repositories, user changes, frozen bars and append-only ledgers. Do not
change host permissions, contact paid providers, deploy, delete unrelated
state or expose secrets without explicit authority.

## Architecture and Interfaces

The evidence path is `source HEAD → lane procedure → raw artifact → SHA-256
binding → capability record → release manifest → independent review → gate`.
The runtime path is `Web → API → typed application/service boundary → scoped
storage/provider/queue → Worker A/B → OTel`; tenant/workspace scope is required
at protected boundaries. The lab lifecycle owns only its loopback ports,
containers, networks and named volumes and must expose health/readiness before
any runtime gate runs.

## Milestones

### Phase 3.1 — CI, typed evidence and release integrity

Implement lane contracts, artifact binding, stale/wrong/missing/blocked
rejection tests, canonical CI scheduling and strict release output.

### Phase 3.2 — lab readiness and live P0 runtime

Implement readiness-aware Compose lifecycle, then execute Postgres, workers,
Redis, object/vector and ingestion gates when the host runtime is authorized.

### Phase 3.3 — P1 product and operations evidence

Close authority, provider, multi-tenancy, RAG, telemetry, SLO, DR, chaos,
soak, performance, frontend and supply-chain gates.

### Phase 3.4 — independent review and promotion

Rebind all evidence, run the frozen bar and Phase 3 addendum, publish the
promotion report and request the human decision.

## Plan of Work

Work in dependency order. First make evidence truthful and mechanically
rejectable. Next make the disposable lab deterministic. Then execute each live
P0 capability, retaining raw artifacts and independent review. Only after P0
closure run P1 provider, corpus and operational gates. Finally calculate the
scorecard from current evidence, resolve all Critical/High findings and obtain
human Go/No-Go. Advanced retrieval remains behind flags until the baseline is
closed.

## Concrete Steps

1. [PH3-2-LAB-READINESS:WAIT_RUNTIME] Await an approved disposable Docker daemon and private runtime configuration before executing live Compose readiness and teardown evidence.
2. [PH3-2-LAB-READINESS:VERIFY] Validate the readiness-aware Compose lifecycle and, with approved disposable daemon access, execute `make up/down` while retaining bounded health/log observations.
3. [PH3-3-POSTGRES:RUN] With approved disposable runtime access, execute migrations, queue claims, locking, fencing, retention and crash/replay evidence against real PostgreSQL.
4. [PH3-4-WORKERS:RUN] Exercise Worker A/B, SIGTERM/crash/restart, stale leases, duplicate delivery, timeout and optional process-isolation evidence.
5. [PH3-5-REDIS-STORAGE:RUN] Execute Redis replica/fencing/rate-limit and S3/Qdrant object/vector lifecycle gates with checksums, tenant scope and restore negatives.
6. [PH3-6-INGESTION-EVIDENCE:RUN] Run the approved golden ingestion and query/citation path, lineage, idempotency, partial failure and crash/replay matrix.
7. [PH3-7-NEGATIVE-AUTHORITY:VERIFY] Execute forged/cross-tenant/stale-version/wrong-checksum/unknown-chunk negatives and make runtime evidence authoritative only when bound.
8. [PH3-8-PROVIDER-RAG:RUN] After D03/D04 approval, run the approved real or local OpenAI-compatible provider, corpus, budget, ACL and adversarial RAG matrix.
9. [PH3-9-OBSERVABILITY-SLO:RUN] Exercise distributed traces, redaction, metrics, alerts and SLO evidence, then update the SLO operational contract.
10. [PH3-10-DR-RESILIENCE:RUN] Run backup/restore, RPO/RTO, chaos, soak, load and performance gates and publish the DR runtime report.
11. [PH3-11-FRONTEND:VERIFY] Run real 375/768/1440 browser, accessibility and visual checks with a fresh independent design review.
12. [PH3-12-SUPPLY-CHAIN:VERIFY] Run SBOM, dependency/license/secret/image/provenance/signing and hardened container checks with immutable digest binding.
13. [PH3-13-PROMOTION-REVIEW:REVIEW] Rebind the exact candidate, run the frozen fourteen criteria plus Phase 3 addendum, obtain independent reviews and record every residual risk.
14. [PH3-14-HUMAN-GONO-GO:DECIDE] Obtain explicit human Go/No-Go, deployment window, monitoring and rollback ownership for the exact artifact; publish the final Triple AAA promotion report only if all required gates pass.

## Validation and Acceptance

Phase 3.1 implementation currently passes `make validate`, `make ops-static`,
`make compose-static`, `make security-adversarial`, `make api-contract`,
`make web-lint`, `make web-typecheck`, `make web-build`, evidence unit tests,
strict release-integrity negative tests, complete matrix coverage and workflow
structure checks. Fresh independent review passed the local scope. Phase 3.2+
additionally requires
real readiness and runtime observations; a local adapter test cannot satisfy
those gates. Final acceptance requires current commit/artifact bindings, no
Critical/High finding, all mandatory capability rows `VERIFIED_RUNTIME` or
`PROMOTABLE`, current independent review, the final report and human authority.

The current Redis/API slice additionally passes the full API matrix (432
tests), locking suite (52 tests), State-of-Art suite (148 tests), and the
fail-closed missing-runtime probe. The canonical gate executes real HTTP
requests against two independently spawned API processes when an approved
Redis URL is supplied; in this checkout it correctly emits
`BLOCKED_EXTERNAL`, so no live rate-limit or production-readiness claim is
made.

## Current candidate closure

The current source implementation candidate is
957b534d7b33a025525cb1dd667872791239ed43 with tree
65dcad96347adbd34e267537c424bef444ec48d7. It contains the corrected
PostgreSQL worker gate, canonical two-process Redis/API HTTP gate, strict
release artifact postconditions and manifest consistency checks, plus bounded
same-run CI envelopes with redacted raw artifacts, exact workflow/run/ref/SHA
provenance, runtime-primary supply-chain binding and frontend Phase 3
transport. The State-of-Art suite has 256 passing tests and the relevant
static/API checks pass; the full preserved `make test` remains incomplete
because the CVG dataset and local Playwright browser are unavailable. The
prior integrated verifier artifact is stale after this source change and is
not treated as current promotion evidence; live runtime, distributed,
operational, provider/corpus and human-approval gates remain open.

## Risks and Human Decisions

The dominant risks are false promotion from stale evidence, cross-tenant
leakage, claiming durability from local adapters, unbounded provider/corpus
use, missing restore/rollback evidence, telemetry redaction failures and
visual/accessibility regressions. Human decisions remain required for secrets,
external runtime, provider/corpus/clinical thresholds, SLO/RPO/RTO/retention,
deployment and rollback.

## Idempotence and Recovery

Static checks and manifest validation are repeatable. Live runs use disposable
owned resources and unique run identifiers; they never delete unrelated
volumes or rewrite historical evidence. A failed run preserves raw artifacts
and appends a new status. A source or deployment change invalidates affected
evidence and requires a new exact commit binding. If Docker remains unavailable,
keep the capability blocked and continue only with hermetic P0 implementation
and tests.

## Artifacts and Evidence

The current independent evidence-boundary report is
docs/reports/phase-3-evidence-boundary-independent-review-2026-09-09.md;
runtime artifacts are regenerated under .runtime/phase-3/ and remain ignored.

Entry artifacts are the exact prompt copy, current audit, public plan, this
ExecPlan, frozen `.gauntlet/bar.json`, current CI workflows, Phase 2 plan and
the existing local command outputs. Phase 3 now includes typed capability
records, local-check records, runtime envelopes, the PostgreSQL envelope
adapter, readiness-aware lifecycle tests, the post-fix independent review and
conditional CI artifact wiring and same-run CI provenance; the post-fix review is recorded at
`docs/reports/phase-3-post-fix-independent-review-2026-09-09.md`;
future slices add raw runtime logs/traces/metrics, signed manifests,
`docs/reports/disaster-recovery-runtime-evidence.md` and
`docs/reports/state-of-art-triple-aaa-promotion-report.md`. `.agent` state,
backlog and append-only ledgers remain the canonical execution pointers.
