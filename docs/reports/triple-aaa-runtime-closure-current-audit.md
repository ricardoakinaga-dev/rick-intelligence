# Triple AAA runtime closure — current entry audit

Date: 2026-09-10. This is an entry audit, not a promotion approval.

## Candidate and source of requirements

- Frozen entry HEAD (main): `e17be6eabeedb5666e502ac9f6812c9a9ea0ac2d`.
- Tree: `f8fecd71a4f582ed15200e5aee552ec937bc8bc8`.
- Worktree was clean before this audit; local `origin/main` matched HEAD.
  No remote fetch or same-SHA CI success is inferred from that observation.
- Exact current prompt: [archived attachment](../prompts/triple-aaa-runtime-closure-2026-09-10.txt),
  27,366 bytes, SHA-256 `064be5e04ed483d5d95ef803a66faf6675f7c1f00633cdea83d5abfdd5370d5f`.
  None of the four previously archived prompts matched these bytes.
- Full goal remains all 64 sections of this attachment, including every
  runtime negative, failure point, review and the section 61 definition of done.

The current slice adds local composition/runtime closure changes, but those
changes do not establish distributed runtime. This recovery therefore
prioritizes the new runtime prompt over repeating JSON reader hardening.

## Fresh observations

`docker info --format '{{.ServerVersion}}'` exited 1 with permission denied
connecting to `unix:///var/run/docker.sock`. No service was started and no
host-owned listener was adopted. The production-like lab remains
`BLOCKED_EXTERNAL`; this was a fresh probe, not an assumption from state.

`make validate` passed before changes: boundaries, archived hashes, controller
reconciliation and existing quality-bar validation. `make compose-static`
passed for both canonical Compose files, each rendering fourteen services
(including migration, Qdrant and object-store bootstrap jobs).
These commands establish local scope only. FAST/UNIT/CONTRACT/SECURITY/
RAG_EVAL/FRONTEND/SUPPLY_CHAIN/PHASE3_EVIDENCE have not all been rerun here.
Historical counts in older reports are not current same-SHA CI evidence.

After this slice, `make triple-aaa-capability-matrix` passes with 11 rows and
the exact prompt state enum. A fresh `make triple-aaa-verify` produced a
current packet but returned exit `1` / `DEVELOPMENT` because the checkout is
dirty and release evidence is therefore not sealable; the packet also retains
the expected external runtime blockers. This is a truthful failed working-tree
verification, not promotion evidence. Once the changes are committed, the
same verifier must be rerun on the exact clean SHA and is expected to return
`2` while live gates remain externally blocked.

The inspected sources include README, Makefile, CONTRIBUTING, active `.agent`
state/plan/ledger tails, existing gap/promotion/blocker reports, Phase 3 matrix
generator/validator, quality workflow, Compose lab instructions, migrations
inventory and SLO document. This is not yet a complete file-by-file security,
architecture or operational review.

## Requirement drift and actionable gaps

1. **P0 — current requirements were not archived.** The exact copy above now
   preserves the attachment. Historical copies and their hashes remain intact.
2. **P0 — historical Phase 3 generator still binds the earlier prompt.**
   `scripts/state_of_art/generate_phase3_evidence.py` still points to
   `phase-3-triple-aaa-closure-2026-09-09.txt` and the older audit. The new
   prompt is now bound by `triple_aaa_verify.py` and the new canonical matrix;
   the historical generator remains explicitly predecessor evidence until its
   consumers are migrated.
3. **P0 — legacy matrix schema remains separate.**
   `scripts/state_of_art/phase3_evidence.py` still allows capability state
   `MISSING`, which the current prompt excludes. The new
   `triple-aaa-runtime-capability-matrix.json` and validator use only the
   current enum and include OWNER. The old schema remains fail-closed history,
   not current-prompt promotion evidence.
4. **P0 — live readiness remains unproven.** Canonical Compose static success
   does not satisfy service health, readiness, endpoint inventory or runtime
   hardening. Docker access must become available before these are observable.
5. **CLOSED LOCALLY — SLO scope was reconciled.** `docs/operations/slo.md`
   now has explicit LOCAL OBSERVATION, STAGING SLO and PRODUCTION SLO sections
   and retains `no_data` semantics. No listed target is presented as a
   measurement.
6. **CLOSED LOCALLY — report structure was reconciled.** The current report
   now has the prompt's 29 named sections and 26 scorecard dimensions.
   Required independent reviews, zero Critical/High and a sealed packet remain
   unproven.
7. **P0 — disposable composition was missing at entry.**
   This slice now adds `apps/worker/deployment_composition.py`, packages it
   into both images, supplies the API-side S3 HTTP transport and uses explicit
   Postgres/Redis/Qdrant/provider/identity factories. The dev Compose lab now
   selects `RICK_ENV=dev` while using the external graph, so its HTTP-compatible
   disposable endpoints do not bypass production TLS admission. This is
   locally verified composition only; image build, startup and service
   readiness remain unobserved. A fresh I1 reviewer initially rejected the
   slice for the missing migration/bootstrap services and worker lifecycle
   hazards; migration, bucket, collection, API readiness and shutdown seams
   are now corrected in source and static Compose.
8. **P0 — multi-worker publication proof is incomplete.**
   `scripts/phase11/multi_worker_runtime_gate.py` drives `PostgresJobQueue`
   directly and labels counting acknowledged lifecycle events as
   recovered-single-publication. Queue ACK count does not prove actual
   publication or outbox fencing. Extend proof through the real worker and
   durable result/publication boundary, including every section 16 crash point.

## Current capability summary

This entry summary is not a replacement for the machine matrix. Owners below
identify engineering responsibility, not invented reviewer approval.

The machine-readable matrix is
[`triple-aaa-runtime-capability-matrix.json`](triple-aaa-runtime-capability-matrix.json)
and is validated by `make triple-aaa-capability-matrix`. It deliberately uses
the current prompt's state enum and keeps missing evidence as a blocker or
`NOT_RUN`; it does not reuse the historical Phase 3 `MISSING` state.

| CAPABILITY | STATE | SOURCE EVIDENCE | TEST EVIDENCE | RUNTIME EVIDENCE | INDEPENDENT REVIEW | BLOCKER | OWNER | PRIORITY | PROMOTION CONDITION |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Current prompt preservation | DONE_LOCAL_SCOPE | Exact archived bytes above | Byte/hash comparison | Not applicable | Not performed | None for archive | Lead | P0 | Preserve exact source and bind downstream requirements |
| Control and canonical CI | PARTIAL | Makefile; quality.yml | Fresh make validate PASS | Same-SHA CI not inspected | Not performed | Eight-lane result absent | Verification lead | P0 | All eight requested lanes pass on candidate |
| Capability/release binding | PARTIAL | generate_phase3_evidence.py; phase3_evidence.py | Existing validator passes old bar only | Current complete packet absent | Not performed | Requirement drift | Release engineer | P0 | Bind full current prompt and current evidence |
| Production-like lab | BLOCKED_EXTERNAL | Canonical Compose files; phase11 runner | Fresh compose-static PASS | Docker permission denied | Not performed | Docker daemon access | Runtime operator | P0 | All mandatory services healthy and ready in isolated lab |
| PostgreSQL and Worker A/B | BLOCKED_EXTERNAL | Migrations; postgres_jobs.py; multi_worker_runtime_gate.py | Historical local tests only | No current run | Not performed | Disposable database/lab | Database engineer | P0 | Full migration/fencing/crash matrices |
| Redis and API replicas | BLOCKED_EXTERNAL | Redis runtime and multi-replica gates | Historical local tests only | No current run | Not performed | Disposable Redis/lab | Distributed systems engineer | P0 | Shared bucket, isolation, fencing and recovery |
| S3 and Qdrant | BLOCKED_EXTERNAL | object_qdrant_runtime_gate.py | Historical local tests only | No current run | Not performed | Disposable services/lab | Storage engineer | P0 | Full lifecycle, failure, rebuild and restore matrices |
| Golden path and lineage | BLOCKED_EXTERNAL | golden_runtime_gate.py; external_ingestion.py | Historical local tests only | No current run | Not performed | Full lab/provider | AI platform engineer | P0 | Upload through grounded response with exact lineage |
| Tenant, Evidence, provider, citations | PARTIAL | Tenant/provider gates; Evidence/Decision packages | Historical local tests only | No current full negative matrix | Not performed | Lab and provider scope | Security and AI engineers | P1 | Every named security and decision case |
| OTel, metrics, SLO and DR | PARTIAL | Observability/restore gates; slo.md | Static/local evidence only | No trace chain or measured RPO/RTO | Not performed | Lab; SLO reconciliation | SRE | P1 | Exported/redacted traces and measured recovery |
| Frontend, accessibility, supply chain | PARTIAL | apps/web; frontend_supply gate; workflow | Historical local evidence only | No current API-backed matrix/image proof | Not performed | Full lab and independent reviewers | Frontend/release engineers | P1 | Real states at 375/768/1440; accessibility and image checks |
| Performance, chaos and soak | NOT_RUN | Operational lane tooling | Not rerun | No current baseline/fault/soak results | Not performed | Isolated running lab | SRE | P2 | Complete named workloads/faults and measured budgets |
| Final reviews and sealed promotion | NOT_RUN | packet_seal.py; final promotion report | Not rerun | No current sealed packet | Not performed | All mandatory gates | Release authority | P2 | Section 61 and independent final Go/No-Go |

## Recovery and next action

Recovered profile: brownfield, BUILD/RUN, T4, cross-system. The existing
controller consistently points to `PH3-2-LAB-READINESS:WAIT_RUNTIME`; its
repository summary names an older source candidate. It remains historical
context, not proof that this new attachment has been fulfilled.

Coordination: independent scouts and a fresh-context critic inspected local
runtime gaps; the lead owns the implementation and final audit. The critic's
I1 rejection is recorded above and is not treated as approval. No visual
change is proposed:
design acceptance still requires real rendered states and fresh review.

Next executable action: run packaging/import checks in the built API and worker
images, then execute `make up` against the approved isolated daemon. Preserve
prior evidence and rerun affected
validation. Retry the isolated lab only when its actual
access/configuration changes; do not use host services or fake a live gate.

Promotion remains **NO-GO**. This audit does not establish STATE_OF_ART, AAA
or TRIPLE_AAA, and the full objective remains active.
