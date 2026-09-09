# Phase 3 — Runtime Evidence & Production Promotion: current audit

**Audit date:** 2026-09-09
**Audit scope:** the exact Phase 3 prompt copied to [`docs/prompts/phase-3-runtime-evidence-production-promotion-2026-09-09.txt`](../prompts/phase-3-runtime-evidence-production-promotion-2026-09-09.txt)
**Prompt SHA-256:** `1e039f28c1ac52bc483412de2168193e24077f95dae7839e3a4f5ec5d091f301`
**Frozen source HEAD:** `56a76004a75ec94178e35c82eab8405b5ac74729`
**Branch / remote:** `main` / `origin/main` at the same commit
**Current classification:** `STATE_OF_ART_CANDIDATE`
**Promotion decision:** `NO-GO — Phase 3 evidence is not yet complete`

## 1. Audit purpose and non-negotiable boundaries

This audit is the entry record required by Phase 3. It freezes the current
candidate, separates local implementation evidence from executable runtime
evidence, identifies P0/P1/P2 work, and establishes the order for the next
implementation slice. It does not promote a local adapter test into a live
service result and does not rewrite the frozen Gauntlet bar or historical
controller ledgers.

The repository is brownfield. The three preserved child repositories remain
out of scope for source mutation. Production deployment, host permission
changes, paid provider calls, external corpus use, secret provisioning and
destructive data operations require the responsible human owner and are not
implied by this audit.

## 2. Frozen baseline

The checkout was clean before the exact prompt copy was added. The prompt copy
was verified with `cmp --silent` and has the SHA-256 above. The present dirty
worktree therefore contains exactly one intentional entry:

```text
?? docs/prompts/phase-3-runtime-evidence-production-promotion-2026-09-09.txt
```

The frozen source commit is still bound to `origin/main`. The current dirty
state is expected until this work is reviewed and the user explicitly requests
the commit/push handoff. A release manifest generated before the prompt copy
is Phase 2 evidence and cannot be reused as a clean Phase 3 promotion packet.

The historical `.gauntlet/bar.json` remains unchanged. Its current SHA-256 is
`f1ea9aa44d0d66e00bb47e75e30ad616ff575897de7d2a40bb5bc8e1f4936310`; it is the
frozen fourteen-criterion bar from the previous recovery run. Phase 3 adds a
runtime-evidence and promotion addendum; it does not lower or replace that
bar. The old `.gauntlet` state is stale for this Phase 3 prompt and remains
preserved as historical state.

## 3. Environment observation

| Dependency | Observation | Evidence class | Consequence |
| --- | --- | --- | --- |
| Python / Node / npm | Available for local checks | `LOCAL_VERIFIED` | Hermetic tests and static checks can run |
| Docker CLI / Compose | Installed; Compose 2.40.3 is present | `LOCAL_VERIFIED` | Compose syntax can be inspected |
| Docker daemon | Socket access denied by host policy | `BLOCKED_EXTERNAL` | No live lab, healthcheck, crash, restore or multi-worker claim |
| PostgreSQL client/runtime | No usable `psql`/live DSN observed | `BLOCKED_EXTERNAL` | Migration, locking, FK/trigger and queue runtime gates remain open |
| Redis CLI/runtime | No usable live Redis endpoint observed | `BLOCKED_EXTERNAL` | Lease, fencing, rate-limit and replica gates remain open |
| S3-compatible/Qdrant endpoints | No live disposable endpoints observed | `BLOCKED_EXTERNAL` | Object/vector lifecycle and restore gates remain open |
| Browser | Google Chrome is installed | `LOCAL_VERIFIED` | Tooling exists, but a real Phase 3 browser run was not executed in this audit |
| External credentials/corpus/authority | Not supplied | `NOT_RUN` | Provider, clinical/golden corpus and production decisions remain open |

## 4. Canonical local verification snapshot

The following checks were executed against the frozen candidate and are local
evidence only:

| Check | Result | What it proves | What it does not prove |
| --- | --- | --- | --- |
| `make validate` | `PASS` with a dirty-worktree warning | Control-plane structure, history reconciliation and boundary checks | Clean release binding or remote CI execution |
| `make ops-static` | `PASS` | Migration checksums, shell syntax and backup/restore compilation | Migration execution or restore correctness |
| `make compose-static` | `PASS` | Compose topology renders; dev/staging each expose ten services | Service readiness, network, persistence or health |
| `make security-adversarial` | `PASS` | Bounded local adversarial records are generated/validated | Full distributed tenant isolation |
| `make api-contract` | `PASS` | OpenAPI generation and required paths; 49 paths observed | Provider, database or deployment behavior |
| `make web-lint` | `PASS` | Frontend lint gate | Browser interaction or visual approval |
| `make web-typecheck` | `PASS` | Frontend type contract | Runtime accessibility and viewport behavior |
| `make web-build` | `PASS` | Production Next build; 11 static pages/routes observed | Deployed frontend, telemetry or visual review |
| `docker info` | `BLOCKED_EXTERNAL` | The client can be invoked | The host denied access to the daemon socket |
| `make release-evidence` + strict integrity inspection | `BLOCKED_EXTERNAL` / `FAIL` | Phase 2 manifest generation and fail-closed behavior | A clean, current, promotable Phase 3 candidate |
| `.runtime/phase-2/triple-aaa-verify.json` | `STALE` for this scope | Historical Phase 2 packet exists | It does not include this prompt or Phase 3 gates |

The strict release inspection failed for the correct reasons: the intentional
prompt copy leaves the checkout dirty, the manifest is bound to the prior
Phase 2 artifact set, and live production evidence is not present. This is a
rejection, not a release failure in the product itself.

## 5. Capability matrix

Status vocabulary is intentionally limited to the Phase 3 contract:
`DONE_LOCAL_SCOPE`, `LOCAL_VERIFIED`, `VERIFIED_RUNTIME`, `PARTIAL`, `MISSING`,
`BLOCKED_EXTERNAL`, `FAILED` and `PROMOTABLE`.

| ID / capability | Status | Code and tests | Runtime evidence | Commit / artifact | Environment / reviewer | Limitation and next action |
| --- | --- | --- | --- | --- | --- | --- |
| P0-01 control plane and canonical local CI lanes | `LOCAL_VERIFIED` | `make validate`, ops/Compose/security/API/web checks | None; local process only | `56a7600`; this audit and `quality.yml` | Local Python/Node; lead inspection | Add explicit Phase 3 lane names, artifacts and schedule; obtain remote CI run |
| P0-02 commit-bound release evidence | `PARTIAL` | Existing generator/integrity tests and fail-closed checks | No clean current promotion packet | Phase 2 ignored manifest; `scripts/state_of_art/*` | Local; lead inspection | Rebind every artifact to exact HEAD and add stale/wrong commit/hash/missing/blocked tests |
| P0-03 disposable lab lifecycle | `BLOCKED_EXTERNAL` | Static Compose and launcher code pass | Docker daemon unavailable; readiness not exercised | `docker-compose.dev.yml`, `.staging.yml`, runner | Host daemon denied; no independent runtime reviewer | Make `up` wait for health and fail closed; run `make up/down` only with approved lab |
| P0-04 PostgreSQL migrations, locking and durable queue | `BLOCKED_EXTERNAL` | Adapter and migration tests are local | No live DSN, migration, FK/trigger or lock evidence | Phase 2 adapter/runtime packet | No database; prior I1 was local scope only | Execute disposable migration/concurrency/crash/replay/retention matrix |
| P0-05 two workers, fencing and crash recovery | `BLOCKED_EXTERNAL` | Runtime/queue unit tests | No two-process or supervisor evidence | `apps/worker`, runtime packet | No Docker/DB; no live reviewer | Run A/B ownership, SIGTERM/crash, stale lease and replay gates |
| P0-06 Redis multi-replica lease/rate-limit behavior | `BLOCKED_EXTERNAL` | Redis seam/static tests | No Redis endpoint or replica run | `packages/locking`, Redis gate | No broker; no runtime reviewer | Run replica/fencing/TTL/failure matrix and preserve traces |
| P0-07 S3-compatible object and vector lifecycle | `BLOCKED_EXTERNAL` | Adapter/negative tests | No live put/read/delete/restore/vector lifecycle | storage/retrieval adapters and gate | No disposable endpoints | Execute checksum, tenant scope, delete/restore and Qdrant consistency gates |
| P0-08 golden ingestion, idempotency and lineage | `BLOCKED_EXTERNAL` | Parser/idempotency/lineage local tests | No end-to-end golden document through real services | ingestion/runtime packet | No live lab or approved corpus | Run upload → parse → chunk → embed → index → query, crash and replay matrix |
| P1-01 evidence authority and negative security | `PARTIAL` | Local evidence/decision/adversarial tests | No live closure against generated runtime artifacts | evidence/decision packages | Local; lead inspection | Add forged, cross-tenant, stale-version, checksum and unknown-chunk runtime tests |
| P1-02 provider and OpenAI-compatible runtime | `BLOCKED_EXTERNAL` | Provider isolation and contract tests | No approved real/local-compatible provider run | provider package and eval pack | No credentials/endpoint/budget authority | Obtain D03 and run provider/citation/budget evidence |
| P1-03 multi-tenancy and adversarial RAG | `PARTIAL` | Synthetic offline pack and ACL tests | No real multi-tenant service run | `docs/evaluation/packs/rec22-local-v1` | Local synthetic corpus; no product reviewer | Run approved corpus with leakage, ACL, citation and stale-index attacks |
| P1-04 OTel, redaction, metrics and SLO | `PARTIAL` | Local telemetry/readiness tests | Collector/export/alert/soak not observed | Compose/OTel/SLO docs | Local; no independent runtime review | Exercise distributed trace, redaction, metric cardinality, alert and SLO gates |
| P1-05 DR, restore, chaos, soak and performance | `NOT_RUN` | Static backup and benchmark preparation | No restore, chaos, load or soak run | operations docs/scripts | No lab or operational authority | Define budgets/RPO/RTO, run restore/chaos/soak/performance and retain raw artifacts |
| P1-06 frontend runtime, accessibility and visual review | `PARTIAL` | Lint/type/build and existing local browser history | Phase 3 independent viewport/accessibility review not run | `apps/web`, prior visual evidence | Local static evidence; no fresh independent review | Run 375/768/1440, keyboard/axe/contrast and independent visual review |
| P1-07 supply chain and release hardening | `PARTIAL` | Existing pinned workflow and partial audits | No signed image/provenance/container scan result | workflows/Dockerfiles | CI definition only | Add SBOM, secret scan, image scan/signature and immutable deployment evidence |
| P1-08 final independent reviews and human decision | `NOT_RUN` | Historical local reviews only | No fresh Phase 3 packet review or Go/No-Go | New promotion report required | Human authority absent | Commission fresh I1 visual/security/runtime review and record decision |
| P2-01 advanced retrieval/calibration/feature flags | `NOT_RUN` | Prior local foundations only | No runtime evaluation closure | retrieval/evaluation packages | Depends on P0/P1 closure | Enable only after baseline citation and runtime gates pass |

No row is `VERIFIED_RUNTIME` or `PROMOTABLE` in this audit. No score is
assigned from implementation volume or static test count.

## 6. P0 / P1 / P2 priority routing

### P0 — release truth and runtime foundation

1. Establish one canonical CI contract with FAST, UNIT, CONTRACT, RAG_EVAL,
   FRONTEND, SUPPLY_CHAIN, RELEASE, runtime, performance, chaos and nightly
   lanes; publish raw logs and exact commit/artifact bindings.
2. Make the canonical lab lifecycle deterministic: render, start, wait for
   health/readiness, verify endpoints, collect logs and tear down only owned
   resources. `make up` must fail closed when readiness is not achieved.
3. Close commit-bound release evidence with explicit rejection tests for stale
   evidence, wrong commit, wrong hash, missing evidence and blocked runtime.
4. Execute live Postgres, queue, worker/fencing, Redis, object/vector and
   golden-ingestion gates in dependency order.

### P1 — product and operational promotion evidence

1. Close evidence authority and mandatory negative tests at runtime boundaries.
2. Run approved provider, corpus, multi-tenancy, citation, OTel, SLO, restore,
   chaos, soak and performance matrices.
3. Run the frontend runtime/accessibility/visual matrix and supply-chain
   hardening with independent review.
4. Produce the promotion report and obtain human Go/No-Go for the exact
   artifact, deployment, rollback owner and monitoring window.

### P2 — advanced capability after closure

Advanced retrieval, calibration, reranking, hybrid search and other feature
flags remain disabled or explicitly experimental until their baseline runtime,
citation and release gates are current.

## 7. CI audit and canonicalization findings

`.github/workflows/quality.yml` is the current broad quality workflow and has
read-only permissions, pinned action versions and local FAST/UNIT/CONTRACT/
RAG-EVAL/FRONTEND/SUPPLY_CHAIN/RELEASE jobs. Its gaps for Phase 3 are:

- runtime is `workflow_dispatch` only and calls the existing integrated packet;
- there is no explicit scheduled/nightly runtime, performance, chaos or soak
  lane;
- the frontend job records that browser E2E is separate instead of executing
  the required browser matrix;
- supply-chain checks cover only a subset of dependencies and do not yet prove
  SBOM, signed provenance or hardened image acceptance;
- release runs fail closed, but the generated manifest is not yet a complete
  Phase 3 capability matrix bound to all required runtime artifacts.

`.github/workflows/state-of-art-quality.yml` is a narrower release-integrity
workflow. The Phase 3 plan will make the broad workflow plus the release
integrity workflow a single documented canonical contract, with each lane
emitting an explicit status rather than silently treating unavailable runtime
as pass.

## 8. Architectural and process gaps found before implementation

- `scripts/phase11/runner.py` validates the Compose path and invokes
  `docker compose up -d`, but does not itself wait for service health or
  perform a readiness contract. This is a P0 implementation gap.
- The Phase 2 manifest and ignored runtime packet are correctly fail-closed,
  but stale for this prompt and must not be cited as Phase 3 promotion proof.
- `.agent/state.json` and `.agent/plans/rec-implementation.md` still point to
  the Phase 2 REC-05 runtime blocker. A forward replan is required; historical
  REC/Phase 2 records remain immutable.
- `.gauntlet/progress.md` and `.gauntlet/state.json` describe the previous run
  and are stale for the new prompt. They remain preserved under the writer-lock
  rule; Phase 3 uses a linked addendum until a fresh Gauntlet run is authorized.
- Static local tests are valuable evidence but cannot establish distributed
  locking, durability, provider correctness, telemetry delivery, restore or
  production readiness.

## 9. Entry decision and next action

The entry audit is complete and the current candidate remains
`STATE_OF_ART_CANDIDATE`. Phase 3.1 is implementation-ready only for the
canonical CI/release-evidence closure and the deterministic lab readiness
contract. The active implementation is now in fresh verification, as recorded
in the active ExecPlan:

`PH3-2-LAB-READINESS:WAIT_RUNTIME`

The implementation slice adds executable evidence contracts, negative tests,
dynamic local checks and readiness guards without claiming live service
success. Docker access, real service execution, external credentials, approved
corpus and any production promotion remain explicit human/runtime
prerequisites.

## 10. Phase 3.1/3.2 implementation update — 2026-09-09

The entry findings were converted into executable controls without changing the
frozen HEAD or upgrading unavailable runtime evidence:

- the Phase 3 matrix now requires all 17 approved P0/P1/P2 capability IDs when
  evaluated for release;
- `VERIFIED_RUNTIME` and `PROMOTABLE` require an independent reviewer, a zero
  exit status, per-capability procedure/timestamp and a distinct structured
  runtime-evidence envelope bound to the candidate;
- missing/invalid matrix verification returns non-zero, while a valid but
  externally blocked matrix remains explicitly blocked;
- the release aggregator depends on conditional runtime, browser,
  performance, chaos, soak and nightly lanes;
- `make up` now validates the selected Compose configuration and service
  inventory, pins the local Docker socket/project, waits for health/readiness,
  fails closed on timeout and retains bounded redacted diagnostics;
- both canonical Compose topologies expose distinct `worker` and `worker-b`
  identities, and `make down` parses from the non-secret example when no local
  environment file is present, without removing named volumes.

Local evidence for this update: 81 focused tests passed across Phase 3,
release-integrity, Compose lifecycle and the preserved integration-lab tests;
both Compose files rendered 11 services; compilation, workflow structure,
control-plane validation, static checks and `git diff --check` passed. The
independent critic's redaction finding was addressed for both object-store
secret variable names, and a fresh post-fix review passed the local scope. Docker
socket access remains `BLOCKED_EXTERNAL`, so no health/readiness, endpoint,
migration or worker runtime claim is made.
