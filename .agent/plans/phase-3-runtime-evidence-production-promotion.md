# Phase 3 runtime evidence and production promotion — living ExecPlan

<!-- engineering-framework: active_action_id=Q17-01.A:VERIFY-Q17-19A-DEPLOYED-INVENTORY -->

## Purpose / Big Picture

Move the root candidate from local State-of-Art preparation to a truthful
runtime promotion decision. The plan binds every claim to the exact commit,
artifact digest, environment, procedure, reviewer and limitation while
preserving the frozen Gauntlet bar, Phase 2 history and legacy repositories.

## Progress

- [x] (2026-09-10) Close the previously unimplemented disposable composition seam: `apps/worker/deployment_composition.py` now constructs the explicit Postgres/Redis/Qdrant/S3/provider/identity graph for API and Worker A/B, `StdlibS3HttpTransport` provides bounded endpoint-confined S3 wire behavior, worker/API images package the shared composition, the API transfers deployment ownership into lifecycle shutdown, and the dev Compose lab selects the external graph in `dev` mode so insecure loopback dependencies cannot be mistaken for production TLS evidence. Focused local tests pass; image build and live startup remain unrun because Docker access is unavailable.
- [x] (2026-09-10) Close the critic-identified runtime seams locally: Compose now runs checksummed migrations and idempotent Qdrant/bucket bootstrap jobs with scoped object credentials; API readiness excludes the unstarted worker process, shutdown preserves stores after a timeout, and the API image exposes optional OTLP tracing. Static Compose, API (463), fast, lint, typecheck, storage and migration checks pass; Docker/image/runtime evidence remains blocked.

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
- [x] (2026-09-10) Bound persisted SQLite/PostgreSQL audit JSON at source candidate 0cfe1cc2bf669b0d47b1993a38525804836f7a08 (tree 1b6c49a12925fbf1d355a56ec27d9d21dd12045f): audit reads cap JSON at 64 KiB, reject non-finite/malformed/recursive values and filter corrupt SQLite rows before JSON1 predicates; audit tests pass 10, the API matrix 443 and State-of-Art 295, while live external audit durability remains blocked.
- [x] (2026-09-10) Bound SQLite/PostgreSQL knowledge metadata JSON at source candidate 134ec271097c32caa33b774be1b5f3e3974ffb08 (tree aa93b2f1bc7ebd59355dfdfcc74b28c558857fbf): metadata writes cap canonical JSON at 256 KiB and reject non-finite values, reads omit corrupt collection/document/chunk rows; knowledge tests pass 22, the API matrix 443 and State-of-Art 295, while live durable-store evidence remains blocked.
- [x] (2026-09-10) Bound cleanup-lease marker JSON at source candidate 5b3a652fbfae2aa4d9e839d1dfacb156dbd6dae9 (tree 37359cb1cec80c40776d0d40e92d1df71719b708): private fallback markers cap finite JSON at 8 KiB, validate version/job/scope and leave sources untouched for corrupt markers; the job-journal suite passes 15, the API matrix 444 and State-of-Art 295, while live runtime evidence remains blocked.
- [x] (2026-09-10) Harden release, control-plane and recovery JSON boundaries at source candidate c179acc196ffa19ccdbae6a91ab5c05233af1314 (tree e02f74de83dd6d6f5bfff5d38a0e0e5831d386d6): preflight, review-control, quality-bar, backup/restore, release-manifest and Gauntlet state/history readers now reject duplicate keys, non-finite values, invalid UTF-8 and bounded-overflow inputs before projection; focused boundary checks pass 34 and the complete State-of-Art suite passes 314, with make validate, ops-static and compose-static green. The clean integrated packet reports 17 PASS, 24 BLOCKED_EXTERNAL, STATE_OF_ART_CANDIDATE and exit 2; Docker, runtime/provider/corpus, independent-review, sealing and human Go-No-Go remain external blockers.
- [ ] (2026-09-17 recovery) Execute the disposable runtime after explicit configuration/authority and readiness proof; Lead's Docker 29.1.3 report contradicts historical daemon denial but does not close the lab gate.
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

1. [Q17-01.A:VERIFY-Q17-19A-DEPLOYED-INVENTORY] C13 is ACCEPTED for its exact local scope. Q17-17.A local outbox/restart evidence and Q17-19.B live canonical PostgresJobQueue lifecycle evidence pass; Q17-01.B maps to approved REC-M0 V15 and Q17-03.B to verified tenant-security V11. Compare D02-authorized deployed migration histories/checksums with the already-tested local 0004/0005 compatibility matrix; do not mutate an installation or rewrite applied history.
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

### Recovery observation — 2026-09-17

The current HEAD is `b52f32c141916a2ea3af1a6b913bd91f380606e0`, tree
`b205d9cbd1dcb719b4a8c2f5dcd8ac68009f326f`; the working tree is dirty.
The four Q17 documents and `.opencode/` were pre-existing untracked work and
remain untouched. The initial 13-file product patch covers migration 0005
(portable JSON key count and regex), Compose/Prometheus/worker shutdown and
SSE metadata/parser changes. Concurrent product workers continue changing
files (including Professor tests); this is not a frozen acceptance candidate.
The controller writer owns only the five requested canonical artifacts and
existing generator outputs; product workers do not write controller state.

RECOVERY, not completion: these patches preceded Q17 prerequisite
reconciliation. They do not satisfy Q17-01.B, Q17-02.A, Q17-06.A/B or Q17-26.A
by implication. Lead reports Docker 29.1.3 access, contradicting the old
session's daemon denial, but not proving full lab readiness or D02 authority.
Lead also reports PostgreSQL 16.4: empty migration succeeded, invalid 33-key
payload rejected the exact contract, valid four rows became two QUEUED and
two SUCCEEDED with zero residual legacy rows, and owned container
`rick-migverify-pg16` was removed. Earlier agent reports cite 480 API,
12 contract and 39 Docker tests plus Compose; Lead reports ops-static, lint
and typecheck exit 0. These are attributed reports, not independent checks
by this writer, not fresh integrated product acceptance and not a T4 gate.
Migration repair for installations that already applied 0005 is NOT proven;
inventory/checksums, corrective migration or approved pre-application repair,
rollback/restart and failure/concurrency evidence remain required. Never
rewrite applied checksums or treat an empty/disposable DB as that proof.

D06 is confirmed by the user's explicit request to implement all PE17 and
this controller delegation. It activates reconciliation only within the
stated permissions. D01 (data/tenants/retention), D02 (runtime/secrets/TLS/trust),
D03 (provider/endpoints/cost), D04 (corpus/domain/policy), D05 (SLO/DR/load/
windows) and D07 (promotion/signing/deployment) remain unresolved; no broad
implementation request or Docker observation supplies these decisions.
PH3 runtime remains blocked on explicit disposable configuration/authority
and current integrated evidence. Preserve all historical gates; the old
PH3 implementation gate is not an entry gate for Q17 recovery. BUILD/RECOVER
with PARTIAL verification does not authorize IMPLEMENT or promotion.

The next action is bounded reconciliation of the combined patch, ownership,
prerequisite contracts and migration-repair gap before integrated acceptance.
Then Q17-02.A and Q17-26.A establish the full requirements matrix and
failure-first harnesses; Q17-01.B/Q17-06.A establish affected contracts before
accepting early product patches. No Q17 product task is declared DONE here.

### Q17 ownership crosswalk (61 subtasks; references, not duplicate statuses)

Each row gives the single canonical backlog owner and functional responsibility.
Grouped IDs are explicitly enumerated. Existing local closures remain scoped
historical evidence; mapping to a DONE owner does not complete new Q17 scope.
The lead must explicitly reopen that owner with fresh scoped evidence when
selecting new work. Catalog dependencies and external decisions still apply.
Q17-01.A is the sole new reconciliation item; all remaining IDs are scope
references to existing owners, never a parallel mutable execution backlog.

| Q17 subtask IDs | Canonical backlog owner | Functional responsibility |
|---|---|---|
| Q17-01.A | Q17-01.A | Sole delegated controller writer; Lead integration |
| Q17-01.B, Q17-01.C | REC-M0 | Architecture/contracts and final equivalence |
| Q17-02.A, Q17-02.B, Q17-02.C | REC-M0 | Requirements traceability and current documentation |
| Q17-03.A, Q17-03.B | SA-SECURITY-TENANT-LOCAL | Identity/session policy and migration |
| Q17-04.A, Q17-04.B | SA-SECURITY-TENANT-LOCAL | Authorization and tenant isolation |
| Q17-05.A, Q17-05.B | SA-SECURITY-TENANT-LOCAL | HTTP security and lifecycle boundary |
| Q17-06.A, Q17-06.B | REC-M0 | Versioned API/SSE/client contracts |
| Q17-07.A, Q17-07.B | REC-M0 | Knowledge store parity and provenance |
| Q17-08.A, Q17-08.B, Q17-08.C | SA-INGESTION-APP-LIFECYCLE | Ingestion/publication and failure recovery |
| Q17-09.A, Q17-09.B | REC-M0 | Retrieval and scoped fallback |
| Q17-10.A, Q17-10.B | REC-M0 | Evidence consistency and citations |
| Q17-11.A, Q17-11.B | REC-M0 | Domain decision policy and outcomes |
| Q17-12.A, Q17-12.B | REC-M0 | Professor grounding and budgets |
| Q17-13.A, Q17-13.B | REC-M0 | Provider transport and approved live matrix |
| Q17-14.A, Q17-14.B | REC-M0 | Evaluation harness and domain-approved corpus |
| Q17-15.A, Q17-15.B | REC-25 | Chat metadata/history and frontend integration |
| Q17-16.A, Q17-16.B | SA-VISUAL | Documents/upload/jobs interface |
| Q17-17.A, Q17-17.B, Q17-17.C | REC-M0 | Admin/audit/cases consistency and interface |
| Q17-18.A, Q17-18.B | PH3-2-LAB-READINESS | Platform composition and authorized readiness |
| Q17-19.A, Q17-19.B | PH2-P0-02-POSTGRES-ADAPTER | Jobs database/checksum-safe migration repair |
| Q17-20.A, Q17-20.B | PH2-P0-03-REAL-WORKER-RUNTIME | Worker health/shutdown/fencing/crash matrix |
| Q17-21.A, Q17-21.B | PH3-2-LAB-READINESS | Redis topology and distributed coordination |
| Q17-22.A, Q17-22.B | PH3-2-LAB-READINESS | Storage integrity and persistent bootstrap |
| Q17-23.A, Q17-23.B | SA-OBSERVABILITY | Bounded sink/export/metrics/alerts |
| Q17-24.A, Q17-24.B, Q17-24.C | SA-EXTERNAL | Authorized DR/capacity/chaos/soak evidence |
| Q17-25.A, Q17-25.B, Q17-25.C, Q17-25.D | PH3-1-CI-RELEASE-CLOSURE | Release integrity, CI and promotion authority |
| Q17-26.A, Q17-26.B, Q17-26.D | REC-M0 | Failure-first QA, CI coverage and independent review |
| Q17-26.C | SA-VISUAL | API-backed browser/visual/accessibility matrix |

This crosswalk is not the 64-section/26-dimension/gate/case matrix required by
Q17-02.A. No current gate or historical verification is broadened by it.

### Implementation-wave reconciliation — 2026-09-17

This addendum supersedes the earlier ownership-only recovery for the 16 explicitly
reported implementation subtasks. The handoff says “12” but enumerates 16 IDs:
Q17-08.A, Q17-09.A, Q17-12.A, Q17-13.A, Q17-15.A, Q17-16.A (partial),
Q17-17.A, Q17-18.A, Q17-19.A, Q17-20.A (partial), Q17-22.A, Q17-23.A,
Q17-26.A, Q17-11.A, Q17-14.A (partial), Q17-06.B (partial). All 16 receive
canonical entries in `.agent/backlog.json`; the crosswalk above remains historical
for those IDs and continues to resolve the other 44 scope references plus
Q17-01.A. Existing legacy owners retain their historical scope/evidence, not
parallel authority over these newly activated slices. No planning catalog or
preserved audit copy is changed.

The Lead integrator imports reported red/green evidence as EXTERNAL_RECORD /
PARTIAL / freshness UNKNOWN, not independent review or a replay of the red phase.
Recovery transitions record import steps now, not invented historical execution
or satisfied implementation prerequisites. Original catalog dependencies remain
unproven and are explicit acceptance blockers; no new implementation is selected.
All 16 slices await integrated independent review; none is DONE. Q17-01.A remains
in progress for verification and the acceptance snapshot. D06 authorizes this
bounded reconciliation; D01-D05 and D07 remain unresolved.

Observed local runs by this integrator on dirty HEAD b52f32c: `make validate`,
`make lint`, `make typecheck`, `make api16-root` (599 tests), `make api16-domain`
(204), `make api16-worker` (89), `make api15-professor` (60),
`make api15-provider` (76), `make jobs-test` (44), `make compose-static`
(two topologies, 14 services each) and `make ops-static` (six migration files)
all exited 0. Counts overlap and must not be added as unique tests. Root lint
and typecheck cover preserved components; Python compilation is not full typing,
and canonical web/browser verification was not executed. Static migration checks
are not database execution. Exact per-command records are appended to the ledger.
`make eval-retrieval-pack` failed (make exit 2, evaluator exit 1): alpha
Recall@1 = 0.5 < 0.75, beta = 1.0, aggregate = 0.75; two positive and three
negative cases, all three negatives PASS. The new per-group rigor exposes a
fixture violation; thresholds and fixtures remain unchanged.

Touched areas: ingestion embedding/vector batching and source-size admission;
retrieval sparse/scoped SDK search; Professor citation enforcement; provider
bounded SSE/retry behavior; API/SSE metadata, shared client parser and contract
validation; documents UI recovery; admin/audit pending completion; Compose,
Prometheus and worker shutdown; jobs/migration 0005; bounded observability sink;
route-policy/equivalence regression harnesses; conservative domain decision;
evaluation per-group thresholds and RAG evaluation documentation. Tests in the
corresponding packages/apps changed in the implementation wave, not by this writer.

Open acceptance defects and gaps (NO-GO):

1. Canonical HTTP retrieval remains dense-only; HTTP-store sparse schema migration
   and scoped end-to-end proof are required (Q17-09.A).
2. Admin durable pending-completion registration exists, but no reconciliation
   worker replays it (Q17-17.A).
3. Every query escalates to ESCALATE / risk_unknown until D04 domain policy exists;
   the product answer path is disabled by design (Q17-11.A).
4. Migration 0005 changed after baseline; checksum-safe repair for installations
   that already applied it remains unproven (Q17-19.A stays open).
5. Visual/e2e/live runtime/provider/corpus acceptance is NOT_RUN or
   BLOCKED_EXTERNAL; local tests and attributed reports do not close it.

The historical controller fixture failure (6 passed, 2 failed on directory-copy
prerequisites) is retained, not replayed or repaired here. Current structural
checker success is a separate claim. Next owners must resolve D01-D05/D07,
implement replay, migrate HTTP sparse schema, have the pack owner repair fixtures
without weakening frozen thresholds, establish applied-migration repair, then
run the authorized visual/AA and runtime campaigns plus independent review.
No gate, approval, deployment or promotion is created by this reconciliation.

### Post-import extension checkpoint — 2026-09-17 (revision 306 to 307)

Bounded CHECKPOINT appended by the sole delegated control-plane writer for this
interval. Two already-registered implementation-wave slices received
post-revision-306 extensions; both were reproduced with fresh commands by this
writer (not an attributed replay), and neither changes a status, gate or DONE.

1. Q17-08.A / Q17-09.A batching extension: `plan_upsert_batches`
   (`packages/retrieval/src/rick_retrieval/qdrant.py:712`) partitions upserts by
   serialized UTF-8 bytes and the configured `max_points`, rejects an oversized
   single point before I/O, and the ingestion seam
   (`packages/ingestion/src/rick_ingestion/pipeline.py:714-725`) consumes the
   planner with per-batch cancellation. `make api16-domain` exits 0 with 232
   passed (11.73s). The planner is store-side only; canonical HTTP retrieval
   remains dense-only and Q17-09.A stays blocked on the HTTP sparse schema.
2. Q17-13.A provider extension: `finish_reason="tool_calls"` is accepted by the
   provider allowlist (`packages/providers/src/rick_providers/client.py:60`) and
   by the contract Literals
   (`packages/contracts/src/rick_contracts/providers.py:202,226`), with the
   end-to-end regression in `packages/providers/tests/test_provider.py`.
   `make api15-provider` 76, `make api15-contracts` 12, `make api15-professor`
   60, `make api16-root` 599 and `make lint` exit 0.
3. Snapshot update: `docs/reports/estado-implementacao-2026-09-17.md` (EST17-v1)
   records the `finish_reason=tool_calls` defect as closed and six open defects:
   canonical HTTP retrieval dense-only; admin pending-completion has no replay
   worker; decision gate escalates all queries until D04; migration 0005
   applied-installation repair unproven; visual/e2e/live runtime/provider/corpus
   NOT_RUN; observability `timeout=None` synchronous path.

Registered as CHECKPOINT/TEST events and verification records tied to the
existing Q17-08.A, Q17-09.A, Q17-13.A and Q17-01.A items; no backlog item was
created, none is DONE, and no gate or promotion is created. These are local
hermetic reproductions on the dirty `b52f32c` checkout, not independent review,
live-provider or runtime acceptance; the NO-GO decision and the D01-D05/D07
blockers stand.

### Historical closure snapshot — 2026-09-10 (not current acceptance)

The then-current source implementation candidate was
c179acc196ffa19ccdbae6a91ab5c05233af1314 with tree
e02f74de83dd6d6f5bfff5d38a0e0e5831d386d6. It contains the corrected
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
with fail-closed corrupt recovery rows, plus bounded persisted SQLite and
PostgreSQL audit JSON reads with malformed-row filtering, plus bounded finite
knowledge metadata JSON with fail-closed corrupt collection/document/chunk
rows, plus bounded finite cleanup-lease marker JSON with fail-closed corrupt
private-source cleanup. The final
documentation/control-plane follow-up is bound to the resulting clean
checkout, while live provider/runtime evidence remains external.
It also hardens the root preflight, derived review-control, quality-bar,
backup/restore, release-manifest and vendored Gauntlet state/history readers
with bounded strict JSON, including duplicate-key, non-finite and invalid
UTF-8 rejection before control or recovery projection. The provider,
Professor, job-journal, audit, knowledge, API and State-of-Art suites have 66,
36, 16, 10, 23, 446 and 314 passing tests respectively and the
relevant static checks pass;
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

## Q24 implementation checkpoint — 2026-09-25T02:54:44Z

The 33 Q24 outcomes are now linked to existing canonical owners in `docs/reports/matriz-rastreabilidade-q24-2026-09-24.md`. The user authorized local implementation of all three Q24 plans. This supersedes the old statement that no new local implementation is selected; it does not invent clinical or promotion authority.

Observed local results and preserved red/green artifacts are in `docs/reports/estado-implementacao-q24-2026-09-24.md` and `docs/reports/evidence/implementation-q24-2026-09-24/resume-PMUl45/manifest.json`. Dependency installation and current scoped tests do not replace integrated runtime or independent acceptance. The six previously errored agents were closed; three bounded builders now own migration, Decision/publication and HTTP hybrid retrieval. Their work is pending inspection and is not imported as accepted evidence.

The next executable boundary is the isolated full-runtime API regression. Keep all historical Q17 scope and unresolved Q24 criteria active, preserve the frozen bars and prior ledgers, and integrate each returned artifact against its exact tests. No item becomes DONE in this checkpoint.

### Q24 local entry reconciliation

The first controller validation correctly rejected BUILD/VERIFY without a current IMPLEMENTATION_READY record and detected stale derived pointers. The scoped entry record `.agent/gates/q24-local-integration-implementation-ready.json` now binds the already specified, user-authorized reversible local integration to Q17-01.A. It is recorded at the present time and does not retrospectively approve earlier execution, claim a VERIFIED product, or remove later domain/runtime/release gates. Derived views are regenerated from canonical state.

## Q24 integrated verification checkpoint — 2026-09-25T04:36:48Z

The isolated integrated API regression now passes with 686 tests and two dependency deprecation warnings. The domain lane passes 278 with five opt-in live-Qdrant tests skipped there; the separate disposable Qdrant v1.12.5 run passes all five, including scoped hybrid retrieval, schema rejection, batching, alias transition/rollback, and a lost-delete-ack compensation that restores four previous points and their published status. Authorization passes 10 tests. The disposable PostgreSQL 16.15 migration lane passes 107, including applied-history validation and backup/restore. `make validate lint typecheck` and `git diff --check` pass.

The real Qdrant rollback case exposed a sparse-weight float32 JSON round-trip mismatch. The adapter now compares the returned and recomputed weights by their float32 encoding, while requiring identical sparse indices; the focused contract test rejects a changed weight and the real rollback scenario passes. Both the original failing trace and final passing report remain in the evidence tree. Full run logs, runtime metadata, PostgreSQL backup/recovery evidence and checksums are under `docs/reports/evidence/implementation-q24-2026-09-24/verification-q24-20260925T0427Z/`; the current implementation checkpoint is `docs/reports/estado-implementacao-q24-2026-09-24.md`.

Independent read-only reviews of the API/authorization and retrieval/ingestion/migration diffs are in progress. Keep Q17-01.A `IN_PROGRESS` until their findings are reconciled. This local verification does not close any product/runtime/promotion criterion; in particular Q17-17.A still lacks its durable administrative reconciliation consumer, and provider/corpus, distributed service flow, operational recovery/capacity/stability, visual/accessibility and approval evidence remain outstanding. No backlog item is DONE and the entry-readiness gate is not a release gate.

## Q24 integrated verification follow-up — 2026-09-25T05:08:27Z

The final API/idempotency correction now has 28 focused streaming/history tests and the complete root API suite passes **694 tests** (387 dependency deprecation warnings). Idempotency keys are stripped, bounded, and reject whitespace-only or ASCII C0/DEL controls before deterministic IDs, replay lookups, or history writes; independent API review confirmed parity with the PostgreSQL history adapter. The retrieval/ingestion/migration review also passed after the rollback batching and float32 snapshot fixes.

The domain suite remains 281 passed/5 opt-in skips; the separate disposable Qdrant HTTP 1.12.5 run passed 5, PostgreSQL 16.15 migration run passed 107, and authorization passed 10. Fresh `make validate lint typecheck`, the quality-bar/controller checks, derived views and `git diff --check` pass after state reconciliation; the final post-ledger `make validate` also passes. The Qdrant and PostgreSQL resources were removed with teardown evidence. Fresh API, static and control logs are under `docs/reports/evidence/implementation-q24-2026-09-24/verification-q24-20260925T0427Z/`, and the manifest binds current logs and source/document hashes. The initial control metadata failure remains separately marked as superseded evidence.

Q17-01.A remains `IN_PROGRESS`. These independent reviews cover bounded code slices and do not constitute acceptance of the full product. Continue with Q24-19/Q24-20: durable mutation/audit consistency and the administrative reconciliation consumer. Full API/worker service flow, approved provider/corpus, operational restore/capacity/chaos/soak, visual/accessibility, release and promotion evidence remain open. The local implementation-entry gate is not a release gate; no historical task is marked DONE by this checkpoint.

## Initial Q24-19/Q24-20 implementation checkpoint — 2026-09-25 (superseded by the review disposition below)

The local PostgreSQL administration path now writes user/membership/session changes and a stable completion event in one transaction. A separate worker projects due events with `FOR UPDATE SKIP LOCKED`, idempotent audit insertion, bounded retries, dead-letter state and capped manual replay. Membership disablement is tenant-scoped while password reset invalidates sessions globally; legacy local-sink fallback reports `manual_review_required` when no automated reconciler owns its marker. Migration 0007 adds reconciliation fields/indexes and rejects blank event IDs.

Verification on the shared dirty checkout: API 702 passed, worker 115 passed, PostgreSQL 16 migration suite 108 passed, `make lint`, `make typecheck`, `make ops-static` and `git diff --check` passed. `make validate` and derived-view validation will run after this checkpoint is recorded. A fresh independent review of Q24-19/Q24-20 is in progress. Keep Q17-01.A `IN_PROGRESS`; no Q24 task is marked DONE, and this evidence does not prove the full API/worker runtime, operational acceptance or promotion.

## Q24-19/Q24-20 review disposition and current verification — 2026-09-25

C1 rejected its package because it did not establish process-level runtime recovery, PostgreSQL update rollback, concurrent consumers or clear handling of the legacy fallback. Those gaps received regressions and are documented in `docs/reports/review-q24-19-20-critic-c1-2026-09-25.md`. C2 rejected its package for non-atomic fallback on durable providers and cross-tenant global credential changes; C3 then identified shared `role_version` effects and a partial atomic-capability fallback. The package-specific findings and dispositions are preserved in `docs/reports/review-q24-19-20-critic-c2-2026-09-25.md` and `docs/reports/review-q24-19-20-critic-c3-2026-09-25.md`.

The route now checks that the exact requested operation has its atomic method when the provider declares atomic support. Providers that are durable, unknown or in production cannot proceed without that method; only the explicitly volatile development provider can use manual fallback. PostgreSQL account and authorization-version edits lock the account and reject changes that could update global identity/version fields when it has a membership in another tenant. Live tests confirm a denied request leaves account fields, memberships, sessions and completion outbox unchanged; a single-tenant reset continues to pass.

Current local verification passes `make api16-root` (721), `make api16-worker` (116), and the complete opt-in PostgreSQL migration suite (108). Worker tests confirm that `build_worker()` injects the reconciler into `DeploymentRuntime`; PostgreSQL covers all four rollback paths, process restart recovery, concurrent consumers, retry/dead-letter behavior, and cross-tenant rejection for credentials, profile fields and authorization-version changes. `make lint`, `make typecheck` and `make ops-static` pass. Evidence logs are under `docs/reports/evidence/implementation-q24-2026-09-24/verification-q24-20260925T0757Z/`.

C5 rejected the reviewed snapshot because deactivation selected an arbitrary workspace membership and revoked tenant-wide sessions, while concurrent password recovery could save stale membership status and reactivate a disabled row. C6 found the global-disabled/active-membership state; C7 found tenant-wide administrator-demotion scope and password-recovery revocation limited to the token tenant. C8 rejected its exact snapshot because a volatile admin fallback treated an absent `production_safe` attribute as explicit `False`; the gate now requires `production_safe is False`. C9 rejected its exact snapshot for volatile mutations that crossed workspace scope and a recovery/deactivation race. C10 corrected those paths but was rejected because session validation resolved membership by tenant without workspace and its packet omitted frozen-bar source files. C11 corrected session validation and bar provenance but was rejected because durable password reset remained tenant-only; its reviewer also hashed three unlisted files. C12 remains rejected only for its exact snapshot. C13 is ACCEPTED by fresh path-bounded review: all eleven local criteria pass and the sparse admin PATCH/password recovery race fails before and passes after the account-lock correction. Q17-17.A/Q24-19-20 still needs durable outbox consumer restart/idempotence and integrated worker/runtime reconciliation; broader domain, operations, release and promotion criteria remain open. Q17-01.A stays `IN_PROGRESS/PARTIAL` and Q17-17.A stays `VERIFY`; full API/worker integration with external services, approved domain/provider/corpus criteria, operational recovery/capacity/chaos/soak, visual/accessibility, release and promotion evidence remain open.

## Q24-19/Q24-20 outbox consumer re-verification — 2026-09-25T14:32:52Z

The current worker suite passes 116 tests. A fresh run of the focused live PostgreSQL 16.15 integration passes 1 test and exercises atomic admin mutation/outbox projection, stable event IDs, pending-to-published API status, two consumers using `SKIP LOCKED`, interruption during projection, persisted retry state, recovery by a new `DeploymentRuntime` process, dead-letter and capped manual retry authorization. The fixture records the image digest and confirms teardown left zero owned containers. The initial run under global Python stopped before fixture setup because `psycopg` was absent; the retry under the declared API project environment passed. Logs and Docker resource/teardown evidence are under `docs/reports/evidence/implementation-q24-2026-09-24/verification-q24-20260925T1430Z-outbox/`.

This is current local evidence, not full production integration: the restart process used the real PostgreSQL reconciler and `DeploymentRuntime`, while `build_worker()` composition is covered by the worker suite. The complete API/worker graph with approved external services and D02 topology, deployed authentication, distributed identity/session isolation, operational recovery and promotion remain unproven. Q17-17.A stays `VERIFY`; Q17-01.A stays `IN_PROGRESS/PARTIAL`. The next active action is canonical reconciliation of Q17-01.B, Q17-19.B and Q17-03.B prerequisite evidence.

## Q17 prerequisite reconciliation — 2026-09-25T14:43:17Z

Q17-01.B resolves to REC-M0, whose bounded local V15 review is independently APPROVED; external REC criteria remain open. Q17-03.B resolves to SA-SECURITY-TENANT-LOCAL, whose V11 local tenant-security gate is VERIFIED; external identity/storage and full-product acceptance remain open. Q17-19.B resolves to PH2-P0-02-POSTGRES-ADAPTER, still BLOCKED because current migration tests do not invoke `PostgresJobQueue`; adapter unit tests use a fake connection. The owned disposable PostgreSQL fixture and project-scoped psycopg environment are available. Add a focused live adapter integration test without changing migration history or touching persistent databases.


## Q17-19.B live PostgreSQL queue verification — 2026-09-25T14:57:16Z

The opt-in live PostgresJobQueue integration passes against disposable PostgreSQL 16.15. It covers scoped idempotency and conflict handling, two consumers with a locked row (SKIP LOCKED), lease expiry and stale-owner fencing, retries/dead-letter attempt history, authorized replay/cancellation, transaction rollback before audit/outbox projection, and terminal retention that preserves durable audit/outbox projections. The integration exposed a state timestamp moving backward after PostgreSQL rounded persisted timestamps to microseconds; the adapter now uses monotonic transition times and PostgreSQL precision for persisted epoch values.

Validation passed: focused queue integration 1; complete PostgreSQL migration/integration suite 110; make api16-worker 116; make jobs-test 44; make lint; make typecheck. The owned PostgreSQL fixtures record image digest/server version and teardown with zero remaining containers. Logs and fixture evidence are under docs/reports/evidence/implementation-q24-2026-09-24/verification-q17-19b-live-20260925T1447Z/.

This closes only the local Q17-19.B adapter evidence. PH2-P0-02-POSTGRES-ADAPTER remains BLOCKED because no approved inventory of installations that applied 0005 or D02-authorized database access is available for Q17-19.A. Full D01/D02 runtime, Redis coordination, worker process health/shutdown, operations, domain, release and promotion criteria remain open. The next active action is a read-only inventory of migration histories/checksums and a safe corrective-path assessment; no already-applied migration is rewritten.


## PostgreSQL owner status reconciliation — 2026-09-25T15:12:41Z

The control-plane check showed that the PH2 adapter owner's latest declared transition was still BLOCKED. The live Q17-19.B queue proof is now current, but the owner's broader acceptance includes Q17-19.A repair safety for databases that may already have applied migration 0005. Since no approved installation/checksum inventory or D02-authorized database access is available, retain PH2-P0-02 as BLOCKED with that precise reason. Q17-01.A remains IN_PROGRESS/PARTIAL; its next local step is read-only migration-history inventory and safe-path analysis.


## Q17-19.A local migration compatibility inventory — 2026-09-25T15:17:41Z

Read-only inspection found that the exact historical 0005 Git bytes have SHA-256 d577b70fb1af2790851c0f42d50d2269e80da412405cff2dfde53d63bb873a03 and the corrected local source is 58878320223f9f30d42aea840c7e58795eb5c448daf90a0877adedc781cc9774. The migration runner pins this exact pair, preserves recorded checksum/applied_at, checks the persisted canonical jobs/attempt/trigger boundary, and applies a separately checksummed 0004 operation-guard repair. The live PostgreSQL suite (110 passed) exercises populated pre-0005 upgrades, actual execution/retention of historical 0005 bytes, rollback, repeatability and historical 0004 repair. Offline migration checksum validation passes; detail is in docs/reports/evidence/implementation-q24-2026-09-24/verification-q17-19b-live-20260925T1447Z/migration-source-inventory.log and docs/operations/migration-upgrade-2026-09-24.md.

This proves the repository's compatibility path and synthetic installation states only. No deployed database was inspected. Q17-19.A remains VERIFY for a D02-authorized read-only inventory of installed history/checksums, and PH2-P0-02 remains BLOCKED until that inventory, maintenance bounds and fresh exact-snapshot review are available. Q17-01.A stays IN_PROGRESS/PARTIAL.


## Q17-20.A worker launcher process verification — 2026-09-25T15:25:15Z

Added a subprocess regression that launches the actual worker-entrypoint with a temporary fake composition, waits until the worker loop is active, sends SIGTERM, and asserts the injected stop method runs, the process exits successfully, and shutdown receives its fixed 30-second timeout. The launcher module passes 8 tests; make lint passes. This closes only the local launcher signal/cleanup boundary. Canonical PostgreSQL/Redis composition, worker fencing/crash/restart, container health and D02-approved runtime remain open.

## Q24 local continuation — 2026-09-25

Additional reversible local slices advanced Q24 without changing the ordered active Q17 action above. Q24-06 retains its synthetic v2 pack and now has an offline campaign manifest/harness: fixture checks pass, while the real campaign stays `NOT_RUN` and `BLOCKED` for corpus rights/representativeness, provider, domain approval, sample size and split. Q24-21 has a passing PostgreSQL regression for sparse admin PATCH/password-recovery serialization (4 focused cases; API/identity 773), scoped to that race only. Q24-25 has a document-collection error/retry UX correction; final focused browser tests pass 27/27 after layout fixes, and a fresh independent visual review reports zero P0–P3 findings. The full 321-test matrix passed before the final visual-only refinements. Q24-26 has a 36-test local harness covering configuration identity, path/split guards, strata, fixture source/citation/ACL metrics and descriptive uncertainty; no real provider or generated-answer abstention was observed.

Manifests, raw logs, screenshots and limitations are in `docs/reports/evidence/implementation-q24-2026-09-24/verification-q24-06-evaluation-20260925/`, `verification-q24-21-tenant-race-20260925/`, `verification-q24-25-web-collection-error-review-resolved-20260925/` and `verification-q24-26-campaign-harness-20260925/`. These are local slices, not completion of their Q24 tasks or runtime/promotion gates. Preserve the active Q17-01.A action: obtain D02-authorized read-only inventory of actually deployed migration histories/checksums; leave Q17-01.A `IN_PROGRESS/PARTIAL`.

## Q24-05 retry bytes and Q24-26 evaluation strata — 2026-09-25

Q24-05 adds a regression through the HTTP upload/retry routes and local ingestion service. The same synthetic DOCX container is staged on both attempts; a one-shot vector-store failure makes the original job terminal `failed`, and the explicit multipart retry publishes a distinct job. The test compares bytes and SHA-256 at the ingestion boundary and checks filename, tenant/workspace/collection, authorized collection scope and immutable original attempt state. It validates the DOCX ZIP container but injects a deterministic parser adapter because `python-docx` is not installed in the Python environment used by the root API target. The focused route suite passes 13 and `make api16-root` passes 749. D01 source-retention/reload decisions and parser runtime validation remain open.

Q24-26 advances the offline campaign harness to result schema v4. Campaign manifests can declare dimensions; every fixture case must provide exactly those labels, and product readiness requires both `risk` and `ambiguity`. Positive cases inherit absent `model_id`/`corpus_id` from pack-manifest metadata. Quality metrics and Hit@1 intervals remain separate by exact positive model/corpus pair and labels, or negative expectation and labels; `uncertainty.overall` is explicitly pooled. Every non-empty identity string, including whitespace-only strings, is preserved exactly; identity components are percent-encoded, while canonical dimension JSON uses reversible unpadded URL-safe base64. Regressions cover separator collisions, whitespace-distinct IDs and labels, metadata defaults, ID joins across strata/quality/uncertainty, and exact dimension decoding. The synthetic latency contrast still reports distinct 11 ms and 15 ms p95 rows; observed answer abstention remains `NOT_MEASURED`. No D04 labels, domain categories or thresholds were invented. The checked-in campaign has no labels and remains `campaign_status=NOT_RUN` / `eligibility_status=BLOCKED`. The 20 campaign and 15 pack tests, `make eval-retrieval-pack`, lint and typecheck pass. Valid reviews successively found and fixed separator/pin coverage, whitespace/hash, pack-default, whitespace-only and pooled-interval documentation gaps; a fresh review of the current snapshot is pending. These results do not close Q24-05/Q24-26 or authorize the representative campaign.

Q24-03 aligns `apps/api/pyproject.toml` and `uv.lock`, `requirements/runtime.in`/`runtime.lock`, and standalone CI pins at FastAPI 0.141.1, Starlette 1.7.0 and Uvicorn 0.54.0. The five direct-install workflows now all pin the five checked packages, including `python-multipart==0.0.32` in phase-1.5. A clean Python 3.12 environment resolves 45 hash-pinned runtime packages; PyPI/OSV audits, `pip check`, `uv lock --check`, and `make api16-root` (749 tests) pass. The TestClient emits one upstream HTTPX deprecation warning, documented as a test-dependency follow-up. No immutable image was built or inventoried; Q24-03 stays partial pending the D02-authorized image/base and inventory boundary.

The active pointer is unchanged: Q17-01.A remains `IN_PROGRESS/PARTIAL` with `Q17-01.A:VERIFY-Q17-19A-DEPLOYED-INVENTORY` as the D02-authorized read-only deployed migration-history action. No task status or promotion gate is advanced here. Detailed logs and hashes are in `docs/reports/evidence/implementation-q24-2026-09-24/verification-q24-03-runtime-deps-q24-26-strata-identity-20260925T1938Z/`.

## Q24-08 worker process shutdown — 2026-09-25 local continuation

Recovery confirmed revision 378 and the unchanged global deployed-inventory
pointer. The pending authorized outside-sandbox regression settled with exit 0:
129 worker/API health/telemetry tests passed with one TestClient deprecation
warning. Earlier sandbox timeouts remain diagnostic failures with unproven
precise cause, not passing evidence.

The actual worker script owns a finally drain of its already-loaded diagnostic
lane with a two-second budget. Imported main() retains shared-process ownership;
unused package shutdown allocates no threads. Seven original subprocess cases
failed before the hook. The final Docker/observability package suite passes 46
tests, including SIGTERM/SIGINT, cleanup events, health/normal/failure exits and
bounded behavior for permanently blocked callbacks. An exact-budget/outcome
regression rejects a 3.0-second in-memory mutation in nine combinations. Lint,
typecheck/compilation, pre-checkpoint validation and diff check pass.

Sartre's initial independent scoped review passed with one LOW timing-tolerance
finding, addressed by the exact-budget test. The updated six-file candidate is
frozen at fingerprint a6ded820e0ba2a3c54399154a8917d2186c951b90c17d7bcfa3b5e11efe54d05.
Gibbs independently reviewed C1–C6 with PASS and no findings, recomputing all
six file hashes. Tests were not independently rerun by that reviewer. Canonical
reconciliation and validation are recorded separately from this scoped review.
Evidence is
under `docs/reports/evidence/implementation-q24-2026-09-24/verification-q24-08-worker-shutdown-20260925/`.

Q17-23.A remains VERIFY for API process-owner and external/distributed runtime
evidence; Q17-01.A remains IN_PROGRESS/PARTIAL. The global active task/action,
frozen bar, all historical gates and deployed database histories are unchanged.
No production change, paid provider call, deployment or promotion was performed.
