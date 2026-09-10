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
- [x] (2026-09-10) Harden the promotion packet at source candidate ca54b4ab9db1f39f94a14ad600f690d438cd144b (tree 354485c5e88aacf9b9217cc92b6d87c68e60bfbc): Ed25519 signatures require an explicit trust store, bind all seal metadata and the current clean checkout, and reject stale/future packets; `264` State-of-Art tests, `make validate`, workflow parsing and a fresh independent crypto review pass, while live runtime and human promotion remain blocked.
- [x] (2026-09-10) Correct scoped frontend-lane projection at source candidate fe0f06ccc4deed9a56e1a806842b71d3da8ace66 (tree 0080bb23a61486e538fbf5876c5bd38e81a23ab1): execute the shared frontend/supply adapter once, preserve source exit `2`, project browser/accessibility PASS independently from blocked image evidence, and cover missing/failed/malformed artifact negatives; 51 focused tests pass and the clean integrated packet reports `STATE_OF_ART_CANDIDATE` / exit `2`.
- [x] (2026-09-10) Bind the scoped frontend projection to the exact verifier checkout at source candidate 96b69cf8b8dd69314f08296b850b6b1424022309 (tree 4343081d0cf004c0dc58526972362f6d9b6408dd): require matching commit/tree/fingerprint, a clean/current envelope and explicit checkout availability, and reject a cross-commit artifact fail-closed; 102 focused promotion/Phase 3 tests and `make validate` pass, while the clean integrated packet remains `STATE_OF_ART_CANDIDATE` / exit `2`.
- [x] (2026-09-10) Make the release-test environment reproducible at source candidate 39c391b3d8ee252f88f1474df39e257a92258ec7 (tree ec80ca7ff803c216863c0a02bb4283fcff1732f9): pin the provider test dependencies, export a contiguous internal-package `PYTHONPATH` in both canonical workflows, and validate the full clean venv suite; the same-SHA remote release run reaches explicit checks and returns typed `2` for external blockers.
- [x] (2026-09-10) Reconcile the current control plane and public pointers at checkout candidate 928bcd10cde225bedb6c237c0cc979a259919989 (tree 8da40a5b95bfa9787c2314aa89b7a0d3563c6eee): the exact packet is current and clean with 17 local foundation lanes PASS and 24 mandatory lanes `BLOCKED_EXTERNAL`; this documentation-only reconciliation does not authorize promotion.
- [x] (2026-09-10) Bound synchronous provider embeddings at source candidate ea6fd613ffcc8b18fc11d55941266e28387f9b92 (tree c8ae0fb2614bee70a4e096c6676c8e4d1a9f782e): provider timeout is validated and enforced both outside and inside an active event loop, cancellation is requested before return, and clean API/State-of-Art matrices pass 437/295 tests; live provider/runtime evidence remains external.
- [x] (2026-09-10) Execute the canonical `make up` readiness attempt: Compose rejected the missing required `RICK_WORKER_IMAGE` before starting services, and the Docker daemon remains inaccessible at `/var/run/docker.sock`; no runtime readiness claim or promotion inference was made.
- [x] (2026-09-10) Close the local provider tool/structured-response boundary at source candidate 09a467652c3c9ba85770937e3cdce8c39f545e44 (tree bdb09d2e7ff379e654eac310f3b9f7503c8685a8): bounded function tools are serialized, complete and streaming tool calls are typed, JSON arguments are validated, and the live gate requires a tool-call contract alongside health/chat/JSON/stream/embedding; provider/API/State-of-Art matrices pass 59/437/295, while approved live provider evidence remains external.
- [x] (2026-09-10) Bind the clean integrated provider-contract packet at candidate de4c9ff0f2895ebce97026f9686acc545abfe031 (tree 09f00954c902e2efa7db970082f8918bafe670ee): `make validate` passes, the packet returns exit 2 with `STATE_OF_ART_CANDIDATE`, 17 foundation lanes PASS and 24 mandatory lanes BLOCKED_EXTERNAL; promotion remains disallowed.
- [x] (2026-09-10) Extend the provider boundary at source candidate 6095bafcc368a4b7ee7d468bd4bac98e7b153faf (tree 10f363d35567e1c5763652161004a399f02cc51e): streaming function-tool and JSON deltas are reassembled and checked for strict JSON, terminal completion, fragment conflicts and extra indexes; the resilient wrapper rejects an over-budget prompt before I/O; normal `json_object` responses reject invalid semantic content without retry; the hermetic gate, provider and contract suites pass 3/64/6, while approved live provider evidence remains external.
- [x] (2026-09-10) Enforce the Professor `max_tool_calls` budget at source candidate 63a195a96a588231acf5a885d11916385b438a18 (tree 1ee17a5c2b9cc1dbe26222a0498150ee4a35da1d): normal, provider-fallback and streaming paths count complete/distinct tool calls and fail with `tool_calls_budget_exceeded` before execution or result acceptance; Professor/API/State-of-Art suites pass 29/437/295, while external runtime and promotion evidence remain blocked.
- [x] (2026-09-10) Tighten streaming Professor tool-budget enforcement at source candidate a480e6cc67ada68fc91e0c7034a37f53f23051b3 (tree 3e470607d31cc0ff45d2d2648f35ae9eaa647c14): reject a newly observed over-budget tool-call index immediately, before publishing a content delta; the focused Professor, API and State-of-Art suites pass 29/437/295, while external runtime and promotion evidence remain blocked.
- [x] (2026-09-10) Make Professor budget configuration type-strict at source candidate eced09b7431de92fa064d9910d9ff7d489bb5dc1 (tree 6f2f162009e7bcda9327922b20e49796a79fc5d5): reject boolean/float values in integer limits and boolean timeout values; Professor/API/State-of-Art suites pass 36/437/295, while external runtime and promotion evidence remain blocked.
- [x] (2026-09-10) Harden observability redaction at source candidate 7af6d7be4118b9ecbb237d673e39229691901cc9 (tree c2671184f2a2a20052b5aef47bd1bb0bb51d0be3): normalize JSON-escaped URL slashes before credential/query stripping; observability, API and State-of-Art suites pass 10/437/295, while external runtime and promotion evidence remain blocked.
- [x] (2026-09-10) Close free-form observability secret redaction at source candidate e2043c05fb1b064b4618395e3358d2a22a5b2cd0 (tree 6774e6ab8662c0b5a085fd0d62d108c6f61ecc32): redact inline assignments, bearer headers and nested JSON/CLI secret values in non-sensitive text fields; observability/API/State-of-Art suites pass 10/437/295, while external runtime and promotion evidence remain blocked.
- [x] (2026-09-10) Bound parser result transport at source candidate 19ca87d987a2348a0be6346221bb1d2b61d2b831 (tree a9bc35f7809ed7529c9e8f46ce2727cfecfa96dc): validate parser text/pages/sections/metadata and cap the serialized child response before transport; ingestion security/admission/full tests pass 100, while API/State-of-Art suites remain green at 437/295 and external runtime evidence remains blocked.
- [x] (2026-09-10) Reject invalid UTF-8 at source candidate bacfc9ee569e07357d3412f3588f4a7bda554c73 (tree 4c05c1348224f1cefe845d891d62634d9981cc9b): remove the permissive TXT Latin-1 fallback and convert decoder failures into a bounded `validation_error` for both TXT and Markdown; ingestion security/admission/full tests pass 102, focused file-security/runtime adapter tests 79, and API/State-of-Art suites remain green at 437/295 while external runtime evidence remains blocked.
- [x] (2026-09-10) Remove Pickle from the parser result wire at source candidate 714355e346adf900960725bb863b99cbfda52900 (tree b3456248f0774ed7a4bb99b1d81753bb03457673): return values now cross the child pipe as a bounded versioned JSON envelope, and the parent rejects legacy or malicious Pickle payloads; ingestion security/admission/full tests pass 103, focused file-security/runtime adapter tests 79, and API/State-of-Art suites remain green at 437/295 while external runtime evidence remains blocked.
- [x] (2026-09-10) Bound durable-job JSON decoding at source candidate b3229685b432be6c4313609d95f56b316ecc0885 (tree 43cf3eff8bfbcca3500887c729d5ddd6d99364d5): reject database JSON above 256 KiB, non-finite constants and recursive decoder failures as corruption before job-contract parsing; worker tests pass 50, while API/State-of-Art suites remain green at 437/295 and external runtime evidence remains blocked.
- [x] (2026-09-10) Bound legacy durable-queue payload decoding at source candidate 594a8474a600f78fe09aa5d3ff52db5ae8c5e02e (tree d4de0a8d3ef4487b4377bcdc143c0719bd9575a7): SQLite and PostgreSQL queue reads now cap persisted JSON at 32 KiB, reject non-finite constants and malformed/recursive or non-string payload values through the write contract; focused queue tests pass 14, the full worker suite 52 and API/State-of-Art suites 437/295, while live runtime evidence remains blocked.
- [x] (2026-09-10) Bound persisted SQLite vector decoding at source candidate 8035d9995d6715afa5f4571de9bf26c9ce456b4e (tree 0f7010ceaa716670340f3445c9fe41c852c3c445): read-side JSON is capped before parsing, non-finite/invalid vectors and oversized payloads fail closed, and checksum validation remains canonical; retrieval tests pass 37, the combined knowledge/ingestion/retrieval domain suite 158 and API/State-of-Art suites 437/295, while live Qdrant evidence remains blocked.
- [x] (2026-09-10) Bound persisted chat-history JSON at source candidate 3ce7bc177046d4d4675278ab4bbfc44cdff85874 (tree b2d2661e0ae385e08e00329fd9a6f2633dacf260): SQLite and PostgreSQL history reads cap JSON before parsing, reject non-finite/recursive data and skip corrupt response rows; history tests pass 13, the API matrix 439 and State-of-Art 295, while live PostgreSQL/runtime evidence remains blocked.
- [x] (2026-09-10) Bound persisted SQLite case JSON at source candidate 49784e50c16baa92eac41280a7d14d84ae1a8515 (tree e20480c92212957423a55ff938be896ae56fcad5): a shared finite/byte-bounded decoder rejects oversized, non-finite, malformed and recursive case fields, and corrupt case rows fail closed; case tests pass 12, the API matrix 440 and State-of-Art 295, while live runtime evidence remains blocked.
- [x] (2026-09-10) Hardened persisted PostgreSQL identity JSON at source candidate b075d446b41a259b08a4106294c57fe99a586a8e (tree a919928f99aaf093a0f399d8a229a58b95d50bcc): user ACLs and authoritative session snapshots now reject oversized, non-finite and structurally invalid values, writes are bounded before `jsonb` casts, and corrupt rows fail closed; identity/authorization tests pass 31 and the API matrix 440, while live PostgreSQL/runtime evidence remains blocked.
- [x] (2026-09-10) Bound persisted local job-journal JSON at source candidate 12a473c6b661c04a8d565fefddc490faad91aa96 (tree a398e479e6eefa6b47fbb6fbc98e4b8526ed1e28): journal reads cap JSON at 32 KiB, reject non-finite/malformed/recursive mappings and omit corrupt recovery rows; the journal suite passes 14, the API matrix 441 and State-of-Art 295, while live durable-runtime evidence remains blocked.
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
- 2026-09-10: Reject self-declared promotion authority: require Ed25519 verification against an explicit trust store, require current clean checkout binding and reject seals outside the bounded freshness window. Preserve external runtime and human authority as separate blockers.
- 2026-09-10: Keep the combined frontend adapter as one current observation while deriving independent `frontend-e2e`, `frontend-accessibility` and `supply-chain` lane statuses. A real browser/API PASS must remain visible even when image digest/SBOM evidence is externally blocked; production safety and promotion remain false.
- 2026-09-10: Require the integrated verifier to bind the frontend envelope to the checkout captured before lane execution. Cross-commit, dirty, unavailable or non-current identity now fails closed; the browser/accessibility projection remains diagnostic only and never authorizes promotion.
- 2026-09-10: Treat CI dependency/path reproducibility as a release prerequisite. A clean venv must import the real provider boundary; missing `httpx`/`pydantic` or whitespace-corrupted package paths are CI defects, while the remote release gate may still return `2` for genuine external runtime blockers.
- 2026-09-10: Treat the synchronous embedding bridge as a bounded reliability boundary. A provider awaitable that exceeds the configured timeout must cancel cooperatively and raise a typed timeout instead of blocking API/ingestion indefinitely; this local correction does not replace live provider and budget evidence.
- 2026-09-10: Treat the canonical Compose start as an evidence-producing gate. A missing immutable image reference or unavailable daemon must stop before service startup and remain `BLOCKED_EXTERNAL`; no local environment failure may be relabeled as runtime PASS.
- 2026-09-10: Treat provider tools and structured responses as explicit typed contracts. Bound tool definitions and arguments, fail closed on malformed calls, preserve partial tool deltas during streaming, and require `tool-call-contract` in the live gate; hermetic tests do not close the approved provider/corpus/runtime authority.
- 2026-09-10: Treat streaming function-tool output and context budgets as separate acceptance boundaries. The gate must reassemble typed deltas, reject conflicting or unexpected fragments, validate the final strict JSON object and prove local over-budget rejection before I/O; this remains diagnostic until an approved external provider run is current.

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
12a473c6b661c04a8d565fefddc490faad91aa96 with tree
a398e479e6eefa6b47fbb6fbc98e4b8526ed1e28. It contains the corrected
PostgreSQL worker gate, canonical two-process Redis/API HTTP gate, strict
release artifact postconditions and manifest consistency checks, plus bounded
same-run CI envelopes with redacted raw artifacts, exact workflow/run/ref/SHA
provenance, runtime-primary supply-chain binding, frontend Phase 3 transport,
authenticated promotion packet sealing, scoped frontend-lane projection,
checkout-bound frontend evidence, reproducible release-test dependencies and
a bounded, cancellation-aware synchronous provider-embedding bridge, plus
bounded provider function-tool, JSON and streaming-call contracts and a
streaming function-tool/JSON reassembly assertions, context-budget assertion
in the live gate, normal JSON-object response validation and Professor
`max_tool_calls` enforcement across normal/fallback/streaming paths, including
immediate rejection before a streamed content delta is published, and strict
runtime types for every integer budget plus timeout booleans, escaped-URL
credential/query redaction and inline assignment, bearer-header, nested-JSON
and CLI-value secret redaction in observability, plus schema-checked parser
output with bounded auxiliary metadata and a hard serialized-result ceiling
before child transport through a versioned JSON-only envelope, never
unpickles child-controlled bytes, and rejects invalid UTF-8 with a bounded
parser error instead of silently decoding text with a permissive fallback,
and bounds durable-job JSON decoding before applying the canonical job
contract, plus bounded legacy SQLite/PostgreSQL queue payload decoding at
the adapter read boundary, bounded persisted SQLite vector decoding with
finite vector/canonical checksum checks, bounded persisted chat-history
decoding across SQLite/PostgreSQL, plus a shared finite/byte-bounded decoder
and fail-closed persisted SQLite case-row decoding, plus bounded and
structurally validated PostgreSQL identity ACL/session JSON with fail-closed
corrupt authorization rows, plus bounded persisted local job-journal JSON
with fail-closed corrupt recovery rows. The final
documentation/control-plane follow-up is bound to the resulting clean
checkout, while live provider/runtime evidence remains external.
The provider, Professor, job-journal, API and State-of-Art suites have 64, 36,
14, 441 and 295 passing tests respectively and the relevant static checks pass;
the full preserved `make test` remains incomplete
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
- [x] (2026-09-10) Make provider readiness truthful at source candidate 2238b99ec797b0b2416208dd0e0b02c74897f7d9 (tree 6dad82375d875faf0521e7f012c839889e5cc040): the OpenAI-compatible client performs a bounded authenticated `/models` probe, ResilientProvider delegates live health separately from local circuit state, composition selects that live check, and the provider runtime gate requires it before chat/embedding PASS; provider/API/State-of-Art matrices pass 54/437/295 tests, while approved live provider evidence remains external.
- 2026-09-10: Treat provider readiness as a live dependency check in the canonical production composition. The local circuit-state signal remains available for cheap callers, but `/health/ready` must use the bounded authenticated provider probe; hermetic tests cannot close the approved external provider/corpus gate.
