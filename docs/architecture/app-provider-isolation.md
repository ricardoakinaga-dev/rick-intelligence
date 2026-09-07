# App-local dependency isolation correction

Specification for the separately required correction. Source changes require
its bound implementation-ready gate; this document is not a passing behavior claim.

Existing architectural basis: docs/architecture/api-kernel.md requires a
deterministic create_app(settings, providers), injected fakes and HTTP objects
remaining outside domain code. Request threading proposed here stays entirely
inside routes/dependencies; application services still receive only their own
domain inputs. The kernel's historical middleware list should link the current
accepted transport-order document rather than imply a second stack design.

## Observed defects and protected assets

Eleven synthetic probes were run in two groups (9fail then2fail), using actual
TestClient routes plus provider-container ownership checks. AppA loses its own
session after AppB creation, accepts B's admin cookie, lists/revokes B sessions,
uses B compatibility key/cookie config, writes B audit, and returns B readiness.
A controlled thread test creates B between A's real token validation and its
canonical history route: A's authenticated request then returns B's marker.
Reusing an injected Providers object also mutates A's settings and shares health
registration dictionaries. Raw probe source is preserved at
.gauntlet-state-of-art/evidence/provider-isolation-baseline/test_isolation.py. Only synthetic users/data/keys were used; no external authority assumed.

Current uncorrected cross-instance exposure is HIGH: reproducible identity,
data and configuration boundary bypass under multi-app hosting/tests. Scope of
the proposed action is reversible local correction of the existing app/request
isolation contract, not acceptance of that exposure, privilege expansion,
deployment, real credentials or an external security-policy decision. It needs
failure-first proof, full regression, fresh I1 review and reassessed residual
risk before any scoped completion. Full security/release risk remains open.

## Acceptance contract (D1–D6)

D1: actual app receiving a request resolves its own identity, session cookie,
permission enforcement, session listing/revocation and audit. A token belonging
only to B cannot authenticate/revoke through A, with existing safe responses.
D2: A's readiness, compatibility key, limits, data/ingestion/history providers
remain A's after constructing/serving B. Mandatory readiness policy is unchanged.
D3: factory owns each app's provider container and health registration mappings;
constructing a new app cannot mutate the supplied container or prior app config.
Explicitly injected service objects remain caller-owned shared references: no
deep-copy of external clients, database isolation or multi-tenancy is invented.
Preserve supported custom runtime_checks/readiness_checks mappings and adapters.
D4: synchronous handlers, async waits, worker-thread calls and streaming event
closures retain the request's app selection through completion/error/cancel.
No process-global provider fallback or ambient provider execution context.
D5: actual interleaving/auth/data/config positives and negatives, reused-container
tests, complete existing API/package/worker/transport and browser regressions,
unchanged OpenAPI, and strongest available fresh scoped peer evidence required.
D6: preserve external authority boundaries and dirty/child repos; no full AAA,
external production composition or independently isolated shared-adapter claim.

## Implementation and ownership

Prefer explicit get_providers(request: Request), resolving request.app.state.
Pass Request through every route/helper/dependency caller, including audit after
await and knowledge/ingestion helper chains. Missing app binding fails closed;
remove unused global setter/factory registration. Preserve transport stack.
Factory makes an app-owned shallow provider-container copy with owned check
mappings before assigning immutable settings; injected service references stay
intact. No new dependency or public endpoint/cookie/role contract.

Lead: dependencies/services.py, app.py, new isolation test module, all docs and
controls. One bounded builder: dependencies/identity.py and the route consumer
files auth/sessions/admin/health/chat/search/knowledge/compatibility_openai.py;
Request parameters and explicit helper threading only, no policy behavior edits.
Coordinate source coupling by establishing getter signature first, then builder
works while lead extends independent integration tests. No descendant agents.

Recover with forward patches scoped to owned files; never reset shared work.
Keep current production deployment prohibited. A regression in streaming/error
composition or actual policy demands revalidation before acceptance. Outside
fixture output, no provider messages, tokens, credentials or private data in
reports. Authorization for real containment/rotation/deployment remains absent.

The local edit action has MEDIUM residual execution risk because it is confined
to reversible, hermetic repository changes with disjoint ownership, failure-first
checks and no deployment. This does not reduce the existing HIGH product exposure
or accept it. Runtime state retains HIGH until implemented controls have current
independent evidence; any remaining HIGH/CRITICAL acceptance needs human authority.
Settings remain authoritative from create_app's explicit settings argument (or
its existing environment default when omitted). No domain object receives Request.

Process-wide readiness/stream admission limits intentionally remain shared finite
budgets. App-local dependency selection is not independent resource capacity,
automatic deep isolation of shared external clients, or production containment.

## Local implementation evidence

Lead implemented explicit Request accessors and shallow app-owned provider/map
copies; bounded builder Sagan changed only dependencies/identity.py plus eight
route consumer files. Lead inspected all provider/helper callers, including
post-await audit and canonical streaming closures. No ambient provider calls or
setter remain in apps/api/src; domain services receive no Request. Factory
middleware composition is unchanged. Builder reported67 focused tests passed;
lead independently owns the following broader observations.

All16 new isolation tests pass (21 dependency warnings,1.33s), including the
eleven failure-first cases, mounted child applications, concurrent async
readiness, missing-binding failure and preserved/app-owned registration maps.
Complete API/package/worker plus20 earlier readiness-critic cases:530 passed,
218 dependency warnings,29.65s. Preserved transport5 and readiness57 critic probes
also pass62/62 (57 warnings,2.97s). Their initial isolated importlib collection
failed twice on hidden-directory package naming; rerunning only those uniquely
named archived modules with prepend import mode passed. No candidate source or
assertion was changed for that harness issue; main full suite retains importlib.

Full Chromium:48 passed,6 existing viewport skips,39.4s with fresh owned
API8001/web3010; both servers stopped. OpenAPI remains exactly equal34 paths.
Frontend source is unchanged from independently clean typecheck/lint/build.
The initial HIGH scenario now has implemented local mitigation evidence, but
its scoped residual-risk disposition and acceptance still await fresh independent
review. No external runtime, automatic shared-adapter isolation or fullAAA claim.

## Independent scoped acceptance

Fresh I1 Nietzsche initially rejected D5 because the lead's browser output was
not retained as an inspectable raw artifact. D1-D4 and D6 passed; this was an
evidence gap, not a newly observed code defect. The original rejection remains
unchanged in provider-isolation-review-1.md. With the candidate still frozen,
the same critic completed the missing browser run and issued a separate adendum
approving D1-D6. Reports and raw probes/logs are archived under
.gauntlet-state-of-art/reports/ and evidence/provider-isolation-review-1/.

Independent results:530 backend regressions,73 archived probes,11 new adversarial
tests,22 controller checks, unchanged34-path OpenAPI and48 browser passes with
six existing viewport skips, no failures, no retries. Browser source/config/tests
were31 byte-identical candidate files in a temporary copy, with fresh owned API
and Next processes subsequently stopped. The actual browser run contains both
real integration flows and unchanged existing mocks; multi-app probes provide
the direct dependency-isolation evidence. No full visual score is inferred.

The lead inspected raw probes, browser output, machine results and screenshots;
both critic and lead confirmed whole-artifact digest AND details equality against
candidate5c6235de821b2803a2630588931b84bb9b30f1a90a6ba48e50be524a92dd4b3c.
The historical HIGH wrong-app selection scenario now has implemented mitigation
and fresh independent actual-boundary evidence. Remaining local regression risk
is LOW in this hermetic scope, not acceptance of HIGH exposure or proof of
external/shared-adapter isolation. Full security, deployment and AAA gates remain
open. Changes to factory ownership, request binding or deferred consumer chains
invalidate this scoped acceptance and require renewed regression/review.
