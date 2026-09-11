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
the exact prompt state enum. The verifier packet is regenerated after each
clean implementation commit and is authoritative for the candidate commit,
tree, artifact digest, worktree state and classification. A diagnostic packet
with exit `2` / `STATE_OF_ART_CANDIDATE` records typed external blockers and
sets `promotion_allowed=false`; it is not a promotion approval. No report text
substitutes for that same-run packet.

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
   `scripts/phase11/multi_worker_runtime_gate.py` now emits explicit
   `PROCESS_ISOLATION`, `ONE_OWNER_CLAIM`, `HEARTBEAT_FENCING`,
   `SINGLE_PUBLICATION`, `PUBLICATION_OUTBOX_FENCE`,
   `STALE_WORKER_ACK_REJECTED`, `STALE_WORKER_PUBLISH_REJECTED`,
   `DUPLICATE_PUBLICATION_REJECTED`, `LEASE_RECLAIM_AFTER_EXPIRY` and
   `CRASH_RECOVERY_SUCCEEDS` results, and checks the lifecycle plus durable
   `rick_outbox` counts. These are source-level and gate-contract closure;
   they are not a live result in this environment. The gate still does not
   prove the real `WorkerRuntime` boundary or every section 16 crash point
   until the disposable PostgreSQL Worker A/B run is executed.

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

## 65. Distributed trace boundary closure — 2026-09-10

Source candidate `d29a4504493de0363d7acf3712171e6e92327774` (tree
`b4e22d5e92f9aaea0b54bad86364664f5303d87e`) adds process-owned OTLP setup for
the API and worker, bounded W3C `traceparent`/`tracestate` propagation across
the durable upload job, and stage spans at identity, authorization, retrieval,
evidence, decision, provider, storage, queue and worker boundaries. Baggage,
request payloads and automatic exception messages/stack traces are excluded;
error spans retain only bounded type/code identity. Idempotency comparison
ignores trace lineage so retries remain the same request.

Focused local evidence passes: API matrix **471**, worker runtime **10**,
ingestion **9**, jobs contracts **14**, lint and typecheck. This closes the
source and hermetic-test portion of the observability contract. It does not
prove collector delivery, a single live API→queue→worker trace, alert/SLO
authority, measured DR, independent review or promotion. Docker remains
inaccessible (`permission denied` on the configured daemon socket), so the
runtime evidence columns remain blocked and promotion remains **NO-GO**.

## 66. RealWorkerRuntime multi-process gate closure — 2026-09-10

Source candidate `9ea14048a7431e9f7f8e65c1c749a8dc57b84b9e` (tree
`3b2e314986dffdefc2023baab39aead62c5334e4`) changes the gate's concurrent
worker path to execute the canonical runtime.

The multi-worker gate now executes the canonical `RealWorkerRuntime` in each
isolated worker process for its concurrent claim path. The handler waits for a
heartbeat emitted by the runtime before returning a bounded `JobResult`, and
the observed runtime result plus durable outbox count are required before the
local fencing cases can pass. Hermetic tests cover success, an idle worker and
heartbeat loss preventing publication; **17** runtime/gate tests pass.

This strengthens the executable gate contract without claiming external proof.
The crash fixture remains a queue-level after-claim termination, the complete
eight-point crash matrix is still absent, and the PostgreSQL Worker A/B run,
stale publish result and production publication path remain unobserved. The
candidate therefore stays **BLOCKED_EXTERNAL / NO-GO**.

## 67. Downstream W3C HTTP propagation closure — 2026-09-10

Source candidate `36dcbb74311d8f35199e7c3e29e0a0530a7d156a` (tree
`7e256b03a5fa54e6b3062d7c47b654e1c0271552`) adds the downstream HTTP
propagation boundary. It now projects bounded W3C
`traceparent`/`tracestate` identity into provider, Qdrant and S3-compatible HTTP
requests after their request/authentication setup. The shared helper copies
only those two fields, rejects oversized or non-ASCII values, excludes
`baggage` and arbitrary context, and remains safe when the OpenTelemetry SDK is
not installed. Focused local evidence passes: observability **11**, provider
**63**, Qdrant **16**, S3 transport **15**, and the existing storage suite
**15** tests.

This closes the source and hermetic-test portion of downstream HTTP trace
projection. It does not prove collector delivery, live trace continuity,
runtime service readiness, independent review, or promotion; Docker remains
unavailable to this user and the candidate remains **BLOCKED_EXTERNAL / NO-GO**.

## 68. Redis coordination span closure — 2026-09-10

Source candidate `10b25c445505ed522cd57d873635319a5c174c08` (tree
`6a5c406ca895e7d6e15e3258942864e51b172182`) wraps the injected Redis/
distributed backend in the API rate-limit adapter's
bounded `redis.rate_limit` stage span and records only safe error identity
when the backend fails. The hermetic rate-limit suite remains green (**10**
tests), while the live Redis/multi-replica trace remains an external gate.

This completes the source-level trace stage list for the Redis boundary without
claiming a live collector chain, latency metrics, failover behavior or
promotion. The candidate remains **BLOCKED_EXTERNAL / NO-GO**.

## 69. Prior exact-candidate revalidation — 2026-09-10

The current clean candidate is `5723884a9de9b0a7ac1aa55f077ef798a2e2ab7e`
with tree `d6e5af4a73c2d2b559ad45bc58d842f3cc4bd16e`. The archived prompt
still matches the supplied attachment byte-for-byte (27,366 bytes; SHA-256
`064be5e04ed483d5d95ef803a66faf6675f7c1f00633cdea83d5abfdd5370d5f`).

Fresh same-candidate local evidence is green: `make ci`,
`make triple-aaa-capability-matrix`, focused observability **11**, rate-limit
**10**, provider **63**, Qdrant **16**, S3 transport **15** and storage **15**
tests. The release manifest is clean and bound to the same commit/tree with
artifact digest `14545fb432847375dc3dbdc3bc006d17ab2100446ed310fcf39b628b9a4963ac`.

The integrated verifier produced `STATE_OF_ART_CANDIDATE`, exit **2**, with
**17** local PASS lanes and **24** `BLOCKED_EXTERNAL` mandatory lanes. A fresh
`make up` attempt failed closed before starting services because immutable image
configuration was absent; the independent Docker probe still returns
permission denied for `/run/docker.sock`. No host services were adopted and no
runtime, distributed failure, recovery, independent-review or sealed-promotion
claim is made. Promotion remains **NO-GO**.

## 70. Complete local CI envelope coverage — 2026-09-10

Source candidate `736180e71e00023404520f1ef0814352aa87a770` (tree
`04a3d242b848a349c4b83079edbadf42fb5aac8a`) binds the RAG-EVAL and FRONTEND
workflow jobs to the bounded `ci_lane_evidence.py` envelope. The release job
downloads those same-run artifacts; the manifest treats RAG-EVAL as the local
`integration` gate and uses the frontend envelope only as a supplement to the
separate live browser/accessibility lanes. This prevents a direct command's
exit code from being mistaken for a typed promotion artifact.

Focused release-manifest and CI-envelope tests pass (**40** tests combined).
This closes the local CI evidence-shape gap without changing runtime status;
Docker, live services, remote provenance, independent review and promotion
sealing remain unavailable.

## 71. Reviewed faithfulness contract — 2026-09-10

Source candidate `038faa5` (tree `fd0570621837116309fd02ad95ed211a261b984f`)
closes the retrieval-evaluation faithfulness contract. The evaluator now
accepts only an explicit reviewed boolean or bounded numeric annotation; it
does not infer faithfulness from lexical overlap or citation identifiers.
Citation support therefore reports five fields — citation correctness,
completeness, entailment, citation validity and reviewed faithfulness — with
missing faithfulness remaining `INCONCLUSIVE`. The local fixture and Rec22
pack carry the explicit annotation, and the decision contract can require the
metric; the canonical golden runtime policy requires all five fields.

Focused evaluator, decision, API and golden-runtime checks pass, and the full
State-of-Art suite passes **330** tests. This closes the local contract and
fixture gap only. Approved provider/corpus evidence, live retrieval quality,
independent review and runtime promotion remain unavailable.

## 72. CI envelope provenance hardening — 2026-09-10

The bounded CI envelope now records `started_at`, `finished_at` and
`exit_code` in addition to its observation timestamp. Release evidence
validation checks schema, lifecycle ordering, status/exit consistency,
candidate commit/tree/fingerprint, current-clean sentinel, lane/gate
identity, promotion scope, command statuses and raw-artifact hash before an
envelope can support promotion. The corresponding release-integrity checks
apply the same lifecycle and exit-status rules. This is local provenance
hardening; it does not create remote same-SHA, runtime or authority evidence.

## 73. Worker crash-point coverage boundary — 2026-09-10

The multi-worker gate now enumerates all eight requested crash points:
`after_claim`, `after_heartbeat`, `during_handler`, `before_result`,
`in_transaction`, `after_commit`, `before_publish` and `after_publish`.
The canonical `RealWorkerRuntime` and `PostgresJobQueue` paths now have
hermetic opt-in injection and assertions for all eight points, including
heartbeat renewal, transaction rollback/commit distinctions, stale/lease
recovery, audit and outbox uniqueness. The gate still emits
`production_safe=false` unless every point passes in the approved external
deployment; no live PostgreSQL Worker A/B evidence is claimed.

## 74. Browser-run isolation hygiene — 2026-09-10

The managed frontend gate assigns each run an ephemeral
`apps/web/.next-phase3-<port>` build directory through `NEXT_DIST_DIR` and
restores generated `next-env.d.ts` and `tsconfig.json` snapshots during
teardown. The repository ignores those per-run directories, so a browser
attempt cannot leave tracked Next metadata dirty. This improves local
repeatability and clean-sentinel integrity; it does not prove live
API-backed browser states, accessibility approval, image provenance or
promotion.

## 75. Tenant metadata and timing negative closure — 2026-09-10

Source commits `85942fc` and `31e8cc9` expand the tenant/evidence runtime
contract from eight to **16** negative cases. The matrix now covers tenant and
document enumeration, differential error shape, timing-sensitive identifiers,
object/job/collection existence and telemetry identifiers in addition to
forged, cross-tenant, stale, checksum, unknown-chunk, prompt-injection and
polyglot cases. Metadata cases require an explicit `metadata_leak_free` proof;
the timing case requires `timing_leak_free`; unique probe markers and the
mutation values themselves are checked against the bounded response projection.

The focused hermetic suite passes **7** tests. This closes the local negative
contract and rejects reflected metadata; it does not establish a live Tenant
A/B runtime, timing distribution, provider corpus or promotion evidence.

## 76. Complete hermetic worker crash seams — 2026-09-10

Source candidate `780e02d` adds opt-in, fail-closed fault seams to the
canonical `RealWorkerRuntime` and `PostgresJobQueue`. The eight requested
points are routed distinctly: `after_claim`, `after_heartbeat`,
`during_handler`, `before_result`, `in_transaction`, `after_commit`,
`before_publish` and `after_publish`. Pre-commit crashes require lease expiry,
reclaim, stale ACK/publication rejection and one final lifecycle/audit/outbox
record; `after_commit` verifies that the committed success is retained without
duplicate publication. The production runtime never enables these seams
implicitly, and `production_safe` remains false until the same matrix runs
against an approved PostgreSQL Worker A/B deployment.

The focused crash/worker tests pass **14** cases and the full State-of-Art
suite passes **336** tests. No external database or distributed runtime claim
is made.

## 77. Final source-candidate revalidation — 2026-09-10

The implementation candidate immediately before this report-only editorial
update was `6d2f7998527805c17e3c30eb67937704a4dc2606` with tree
`4259796dd45a567c31be5a7e927a0e3c222e01e5`. The archived prompt still
matches the supplied attachment byte-for-byte (27,366 bytes; SHA-256
`064be5e04ed483d5d95ef803a66faf6675f7c1f00633cdea83d5abfdd5370d5f`).

Fresh local validation passes: `make validate`,
`make triple-aaa-capability-matrix` and `make eval-retrieval-pack`. The
pre-update release manifest and integrated verifier were bound to that clean
candidate; its artifact-set digest was
`0caba7cb80ce3b81e3fb9e9b1546ef82bcd588fcfa57dc36af1f8dffa8bd26e0` and its
checkout fingerprint was
`c5200b2a32f5393bed0602d27c86b64d4cac46dde8aca2bdbc4ab06d145e518f`.

That verifier was `STATE_OF_ART_CANDIDATE`, exit **2**, with **17** local PASS
lanes and **24** `BLOCKED_EXTERNAL` mandatory lanes. The post-update packet is
the authoritative source for the final commit/tree binding. Docker still
cannot be accessed from this environment, so no live service, distributed
failure/recovery, independent-review or sealed-promotion claim is made. The
candidate remains **NO-GO**.

## 78. Provider release gate and strict nightly boundary — 2026-09-10

The release manifest previously carried a provider runtime artifact mapping,
but `REQUIRED_GATES` did not require the `provider` gate. This left a schema
gap: a typed manifest could omit the provider envelope while still satisfying
its mandatory gate set. The manifest now requires `provider` and rejects
unsupported gate IDs; focused release-manifest and generator tests pass (**38**
cases). The current provider envelope remains externally blocked and is not
promoted by this schema correction.

The scheduled `nightly` workflow job now waits for the integrated runtime,
browser, performance, chaos and soak jobs and fails closed when any dependency
is skipped or unsuccessful before validating the Phase 3 matrix. The existing
runtime packet remains responsible for the named PostgreSQL/worker, Redis,
Qdrant and object-storage lanes. This makes the nightly status a truthful
summary boundary; it does not create Docker, service, provider, chaos, soak or
performance evidence in this environment.

## 79. Process isolation and current-plan reconciliation — 2026-09-10

The ingestion boundary now exports `ProcessIsolatedExecutor` as the canonical
hard parser boundary while retaining `ProcessParserRunner` as a compatibility
name. A fresh child uses strict bounded JSON transport, hard wall-clock kill,
best-effort POSIX resource limits and discarded native stdout/stderr, so parser
diagnostics cannot become an unbounded worker log channel. The local default
remains cooperative/in-process; this does not establish hostile-corpus runtime
evidence in an approved isolated deployment.

The two 2026-09-09 Phase 3 plans now state explicitly that their historical
section and scorecard references are predecessor scope. The archived 2026-09-10
prompt, this audit, the 11-row capability matrix and the 29-section promotion
report are the active requirement sources.

Promotion packet validation also requires the signed body to carry the current
`state-of-art-triple-aaa-verify.v2` payload schema. A valid seal over a packet
with an omitted or foreign body schema is rejected before promotion; no external
packet is available in this environment.

## 80. PostgreSQL query-plan coverage — 2026-09-10

The PostgreSQL runtime gate now declares six explicit `EXPLAIN (FORMAT JSON)`
probes required by the prompt: job claim with `SKIP LOCKED`, lease lookup,
retry queue, dead-letter listing, tenant-scoped job lookup and document lookup.
Each probe is evaluated only inside the approved live DSN gate; the local
contract test verifies that the complete set cannot regress to a single
happy-path query. No plan result is claimed here because the disposable
PostgreSQL authority remains unavailable.

The provider boundary also enforces a finite tool-call budget before request
I/O and on complete or streamed responses. The local provider suite covers
pre-I/O rejection and oversized response rejection; live provider evidence
remains unavailable and therefore non-promotable.

## 81. Operational lane observation contract — 2026-09-10

The Phase 3 performance, chaos and soak parser now rejects an under-specified
`PASS`. Performance requires baseline metadata plus all five named workloads at
concurrency 1/10/50/100 with p50/p95/p99, throughput, error rate, CPU, RAM and
queue-depth measurements. Chaos requires all thirteen named faults and every
recovery assertion; soak requires both short and extended profiles with the
requested resource, drift and leak observations. A structured
`BLOCKED_EXTERNAL` observation may remain blocked without fabricating runtime
measurements. Local contract tests cover complete and incomplete matrices; no
live operational result is claimed while the approved lab is unavailable.

## 82. Runtime envelope provenance closure — 2026-09-10

Runtime evidence envelopes now carry the prompt's lane/gate identity, start and
finish timestamps, both `exit_status` and `exit_code`, command observations and
artifact hash list in addition to the existing checkout, preflight and raw
artifact binding. Release-integrity validation rejects a runtime envelope that
omits or contradicts any of those fields, including stale timestamps, a
different gate identity or a mismatched command/artifact result. Fixture tests
cover PASS, blocked, stale and malformed cases; this strengthens the evidence
boundary without creating runtime evidence.

## 83. Complete sealed-packet inventory — 2026-09-10

The promotion engine previously authenticated the packet and checked its lane
observations, candidate binding, critical/high count and final authority, but a
signed body could omit the evidence inventory required by prompt §§52–57. The
contract now requires the frozen quality-bar hash, non-empty CI/runtime,
performance, chaos, soak, DR, frontend and supply-chain evidence references,
all twelve independent review scopes, all eighteen critic checks, a risk
register, a derived 26-dimension scorecard at or above `96/100` and explicit
`final_classification: TRIPLE_AAA`. Medium risks require owner, risk
acceptance, mitigation, review date and future expiration; Critical/High risks
are counted from the register and reject promotion.

The focused promotion/seal suite passes **46** tests. This closes a local
underspecified-packet path; no packet is available here and no runtime or
independent-review evidence is claimed.

## 84. Nightly artifact and current-matrix binding — 2026-09-10

The scheduled nightly boundary now downloads the exact runtime, frontend,
performance, chaos and soak artifacts produced by its dependency jobs before
regenerating or verifying the Phase 3 evidence. The runtime job exports the
current 2026-09-10 prompt matrix bound to the verifier packet's commit, tree,
checkout fingerprint, artifact digest, classification and exit code; release
and nightly validation reject a missing or drifted projection. The historical
2026-09-09 Phase 3 schema remains available as predecessor evidence, while the
current matrix is now carried as a same-run artifact instead of being checked
only from the source checkout.

## 85. Sealed reference byte verification — 2026-09-10

Promotion packet references now accept retained immutable `artifact://` objects
or verify checkout-local files against their declared SHA-256. Local paths
must stay relative to the checkout, cannot traverse symlinks, and must exist;
missing, unreadable or mismatched bytes reject the packet. The verifier passes
the current checkout as the evidence root, closing the underspecified-reference
anti-gaming path without inventing external artifacts.

## 86. Operational projection redaction — 2026-09-10

Performance, chaos and soak projections now pass through the shared runtime
redactor before they are returned or persisted. URLs, bearer values, DSNs and
secret-bearing keys are removed even when the operational harness is invoked
directly; the bounded projection remains finite and structured. A live
operational run is still unavailable and no runtime PASS is claimed.

## 87. Malformed sealed-reference fail-closed handling — 2026-09-10

The sealed-packet boundary now treats malformed local reference bytes, including
embedded NULs and unencodable Unicode, as typed `PACKET_BINDING_REJECTED`
failures. Packet seal digest verification likewise returns a rejection instead
of raising when canonical JSON cannot be encoded. Regression tests cover both
paths; this closes an exception-based anti-gaming/availability gap without
creating any runtime or promotion evidence.

## 88. Current matrix integrity and coverage — 2026-09-10

The current prompt matrix now requires the exact eleven canonical capability
names. A truncated or substituted row set is rejected, and `VERIFIED_RUNTIME`
or `PROMOTABLE` rows require both runtime evidence and independent review
references. When a verifier packet declares the current matrix projection, the
validator recomputes its SHA-256 and checks that the declared path is the
projection being validated. A prior projection is removed before each verifier
run, so a failed bind cannot be silently reused. These are local integrity
controls; the matrix remains `BLOCKED_EXTERNAL` where live evidence is absent.

## 89. Sealed prompt and final-authority binding — 2026-09-10

The sealed-packet contract now requires the byte-exact archived closure prompt,
its frozen SHA-256, and a current-matrix reference. The independent final
verifier consumes the sealed packet and the exact integrated observation packet
without rerunning runtime lanes, then writes a typed final-promotion artifact.
The scheduled release job requires a protected `triple-aaa-promotion`
environment containing the external packet, trust store and immutable
reference; missing authority fails closed. No seal or independent Go/No-Go is
present in this environment.

## 90. Browser and supply-chain projection closure — 2026-09-10

Browser evidence now requires an approved `production_safe` runtime claim; a
managed development runtime cannot project a frontend PASS. The accessibility
projection includes screen-reader semantics and 200% zoom checks. Required
browser state names cover upload, documents, sources, jobs, offline,
interrupted stream, permission denied, worker unavailable, provider unavailable
and slow backend; absent observations remain non-PASS. The supply-chain lane
reads its dedicated P1-07 envelope and requires lockfiles, SBOM, secret scan,
licenses, immutable image digests and image SBOM. These checks remain blocked
until the approved browser/lab and image authority are available.

## 91. Same-run artifact topology and teardown snapshots — 2026-09-10

The integrated runtime job remains the canonical owner of the shared preflight
and packet. Auxiliary frontend, performance, chaos and soak artifacts are
downloaded into supplemental directories, preventing independent job
preflights from overwriting the canonical identity. Successful Compose startup
and pre-teardown now retain bounded redacted `ps`/log snapshots before the
preflight is invalidated or services are removed. This preserves evidence
without converting a local snapshot into runtime PASS.

## 92. Database and Redis fault-authority closure — 2026-09-10

The PostgreSQL gate now emits a live `transaction-rollback` result and names
`crash-before-commit` and `crash-after-commit` as separate required results.
Those crash outcomes remain `BLOCKED_EXTERNAL` until an explicitly supplied
`RICK_POSTGRES_CRASH_HARNESS` returns their JSON assertions; hermetic queue
tests are not treated as database crash proof. The Redis gate similarly emits
real heartbeat renewal and pool-disconnect reconnect checks, and requires an
explicit `RICK_REDIS_FAULT_HARNESS` result for circuit recovery. No harness or
live service is available in this checkout, so these controls preserve the
external blocker rather than manufacturing a PASS.
