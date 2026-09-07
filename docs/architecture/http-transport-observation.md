# HTTP transport and error observation contract

Scope: SA-DISCONNECT, canonical API middleware and telemetry only. Preserve
routes, authorization, CSRF, body limits, public error envelopes, request IDs,
security headers, CORS and the response-header latency definition. No child
repository, database, deployment, provider or external-account mutation.

## Observed baseline

The actual app with immediate http.disconnect on GET /health/ready raises
RuntimeError: No response returned, writes a 500 response and records one SLO
observation with error_rate 1.0. A connected synthetic route raising that same
RuntimeError also records 500 and must continue to propagate the real error.
A connected StreamingResponse yielding one chunk then raising ValueError emits
status 200 and propagates the error, but incorrectly records error_rate 0.0.
These read-only in-memory route probes used the real middleware stack, a 2s
external wait bound, and no network or persistent application data.

## Required acceptance

- HTTP transport disconnects actually observed on receive or transport send
  are counted separately from service errors; they do not inflate the SLO error
  rate or masquerade as successful complete requests.
- An unobserved remote disconnect is not inferred. A send accepted by the ASGI
  server is not proof of delivery to a user.
- Real connected application exceptions remain propagated and counted, including
  a RuntimeError with the former framework message and post-header stream errors.
  No broad RuntimeError suppression or fake second response after headers.
- Streaming cancellation closes generators. Body limits remain enforced on
  actual bytes for JSON and multipart without prebuffering unbounded bodies.
- Every request has at most one terminal metrics observation. Header latency
  keeps its existing meaning; wire status and stream failure are distinct facts.
- No user IDs, query text, body, tokens or arbitrary paths enter metric labels.
- Non-HTTP ASGI scopes pass through unchanged. Existing security and HTTP
  contracts and combined API/package/worker regression remain passing.

## Chosen implementation and verification

Replace task/stream-bridging BaseHTTPMiddleware in the owned stack with ordinary
ASGI callables. Wrap receive/send without consuming extra input. Keep each
existing policy in its current owner; intercept response headers for IDs/security.
Observe transport closure at the boundary, not by matching exception messages.
Preserve caller context with finally cleanup. Treat server task cancellation
separately from application failure. Record terminal outcome once, retaining
header-start latency and separate bounded disconnect/cancellation counters.

Owned files: apps/api/src/core/middleware.py, core/telemetry.py, core/streaming.py,
core/errors.py's outer server-error response metadata,
apps/api/pyproject.toml's explicit tested AnyIO dependency,
related request context helper only if necessary, app.py composition, canonical
chat/compatibility route-class wiring, focused API tests and this contract. Public schemas/routes and provider interfaces are
unchanged. Local risk MEDIUM, service-wide regression surface, no stored-data
migration or human authority boundary. Preserve existing dirty changes; recover
forward from a failed focused test, never restore an entire worktree.

First add ASGI failure-first tests for early disconnect, body-read disconnect,
stream cancellation, connected pre/post-header failures, transport send closure,
and non-HTTP passthrough. Run targeted HTTP/security/stream/body-limit tests,
then the combined API/package/worker suite and browser regression. Require a
fresh-context read-only peer and clean mutation sentinel before scoped completion.
External-service and full AAA claims remain out of scope and unproven.

The initial task switch failed the controller's stage reconciliation (runtime
SPEC, backlog BUILD). The backlog now correctly records the current design
stage. No implementation was started under that inconsistent pointer.

## Implementation and evidence

The registered policy stack now uses ASGI callables without task/queue bridges.
Metrics classify outcomes once when the request coroutine terminates. Header
latency is captured at response start, while an exception after that start marks
the attempt failed without inventing a second response or changing its wire
status. Observed transport disconnects and server task cancellations have separate
bounded counters and are excluded from the SLO sample window. Real failures take
precedence over a coincident disconnect, including mixed exception groups.

The body guard counts actual received bytes, retains 413 for framework-caught
parser exceptions, rejects huge declared lengths without integer-parser failure,
and does not replace an already-started response. Request context is restored in
finally. Actual send failures are marked at the send boundary; matching an
application exception's message is never a disconnect signal.

Initial eight ASGI tests reproduced five failures and three passing controls.
The first implementation pass had 46/47 focused tests passing: the remaining
test expected a bare ValueError where native StreamingResponse now preserves an
ExceptionGroup containing that exact error. The assertion now accepts only the
same sole underlying ValueError/message, retaining its metrics assertions; this
fixes a wrapper-shape assumption without hiding application failure. Thirteen
transport cases now pass, including generator cleanup observed before event-loop
shutdown, mixed errors, task cancellation, context restoration and huge headers.

Distinct lead self-review inspected policy ordering, response replacement,
exception-group handling, context cleanup and bounded metric labels. Additional
cleanup/cancellation cases were executed after that review. This is I0 evidence,
not independent acceptance. Browser regression passed 30 tests with six existing
viewport skips; test servers were confirmed stopped afterwards. No visual score,
live dependency, delivery-to-client or production guarantee is inferred.

The first independent review rejected retained-generator cleanup and missing
headers on CSRF rejections. Deterministic closure belongs to a route-level
wrapper around the actual StreamingResponse, which owns its async body iterator;
the transport observer cannot discover that iterator from ASGI messages. Canonical
streaming routers and new app routes use the wrapper. Closure runs in shielded,
bounded cleanup; real response and cleanup errors must both remain visible.
Header wrappers now surround CSRF. These are implementation refinements to the
unchanged cleanup/header criteria, not relaxed acceptance. Upstream provider
finalizers must cooperate with cancellation; arbitrary blocking code cannot be
preempted by an asynchronous deadline.

Lead follow-up also reproduced known503 responses excluded from the SLO when
body send failed, and missing correlation/security headers on outer500 handling.
Known service failures now take precedence over coincident transport abandonment;
the server-error handler supplies the same canonical headers because it renders
outside registered middleware. Focused tests first failed on both cases. Route
wrappers preserve native response behavior and close owned async iterators under
a one-second cooperative cleanup bound. Canonical SSE event loops explicitly
close their nested service event iterator as well.

Current local verification after these refinements:370 combined backend/package/
worker tests passed (99 dependency deprecation warnings),20 transport tests passed,
and the first critic's seven isolated probes all passed when rerun by the lead.
Browser regression again passed30 tests with six existing viewport skips; the
owned test servers stopped. OpenAPI was recomputed in memory and compared equal
to the stored34-path schema; no schema rewrite was needed. The directly used
AnyIO dependency is now pinned to the tested installed4.15.0 version. A new
fresh-context review is still required; lead reruns do not approve the correction.

The second peer rejected another ordering case: response-start status was skipped
when receive had already observed disconnect. Both returned503 and mapped ApiError
503 cases initially failed their new regressions. Status/header-generation timing
is now observed before suppressed transport I/O, without claiming delivery.
The current combined suite passes372 tests; all nine second-peer isolated probes
pass when rerun by the lead. Browser and independent acceptance are revalidated
on the final scoped artifact rather than inferred from earlier passes.

## Third-review correction — target contract v2

The third review disproved the earlier bounded-cleanup claim: native response
teardown can block before explicit aclose begins. It also found that outer500
sends bypass the observer and can replace the original exception. Preserve the
earlier results as history, not current acceptance.

The observer must wrap the native ServerErrorMiddleware, while create_app still
returns a FastAPI instance. Error500 response transport failure must not replace
the original application failure; unrelated secondary failures remain visible.
All sends, including outer500, pass the same disconnect guard and metrics owner.

Frozen shared interface: core.transport.get_transport(scope) returns one
TransportState stored in scope['rick.transport']; it exposes disconnected
(asyncio.Event), disconnected_at (monotonic float or None), and disconnect()
(idempotently sets time/event). Only actual receive disconnect or send OSError
signals it. Non-HTTP remains passthrough. No raw request data is stored.

The stream owner runs the native response plus explicit iterator closure in an
owned task. Healthy streams have no added lifetime timeout. Observed disconnect,
transport closure, response cleanup, or caller cancellation starts a total
one-second teardown wait budget. A shielded finalizer cannot extend the request
wait indefinitely: expiry raises explicit TimeoutError, retains task ownership,
retrieves late exceptions, and retains its admission slot until actual completion.
No forced preemption of blocking Python/native code or host shutdown guarantee.

Admission is bounded to64 in-flight route operations per process, no queue,
acquired before invoking a ClosingStreamingRoute endpoint. Nonstream/error paths
release immediately; streaming ownership releases only after actual teardown.
Saturation returns the existing safe503 provider_unavailable envelope, before
allocating endpoint-owned resources. This conservative local capacity bound is
not a performance-bar PASS; production workload/capacity measurements remain
required. One idempotent release per slot, thread-safe across event loops.

Verification adds real-app outer500 exception identity/suppression probes and
shielded-finalizer bounded wait, capacity exhaustion/recovery, cooperative close,
caller cancellation and combined real/cleanup-error cases. Existing22 transport
cases, canonical SSE ownership, security/envelopes and OpenAPI stay unchanged.
The retained-task registry must not grow beyond admission capacity or claim a
resource closed before its task finishes. Late failures use bounded safe counters,
not provider exception text; request metrics still have one terminal owner.

Contract v2 implementation evidence: the fresh builder Tesla owned only the
outer HTTP boundary and its new tests; lead owned streaming teardown and capacity
tests. Builder returned IMPLEMENTED, never approval. Seven new boundary probes
failed before its patch; all33 error/transport focused cases then passed. Lead's
two shielded-finalizer/caller-cancellation tests failed before the ownership patch.
Capacity tests now demonstrate no endpoint allocation during saturation, retained
ownership after timeout, release after actual finish, retrieved late failures and
no late transport sends. Healthy streams may exceed the cleanup budget; completed
body/background teardown does not. Only fixed late-outcome counter names are kept.

An expanded regression exposed a completed task still awaiting its scheduled
release callback:389 passed1 failed. The completion reconciliation is now
idempotent and immediate before returning to the caller; this failure is retained,
not hidden by inserting a test sleep. Current combined regression:390 passed,
99 dependency warnings. Browser:30 passed6 existing viewport skips at375/768/1440
using new owned servers on8001/3010,23.8 seconds. OpenAPI remains identical34 paths.
Control regression22 passed before final metadata synchronization and is rerun
after it. These are implementation/integration observations pending a new critic,
not current independent acceptance or external performance/production evidence.

Fourth peer review rejected the nested service iterator boundary on both canonical
chat routes: plain aclosing can be cancelled mid-close and replaces an original
iteration error when closure also fails. Outer task bounds are insufficient if
inner ownership has already been discarded. Replace the nested context manager
with a shared shielded-close owner that retains both exception leaves. Its work
remains inside the outer bounded task and admission slot; no new detached tasks.
This is a known implementation correction under unchanged contract v2 and entry
gate002. Add canonical-route cooperative-close and dual-failure regressions before
implementation, then retained nested cleanup and complete regression evidence.

Nested correction evidence: all four peer reproductions first failed in the root
regression file, then passed. The shared closing_stream context manager shields
cooperative aclose and retains both iteration and cleanup failures. A private
per-scope callback notifies the outer owner when nested teardown begins (including
normal exhaustion), without asserting a transport disconnect. It also preserves
a known original exception if nested teardown itself exceeds the wait budget.
Eight additional canonical-route cases cover exhaustion, error, disconnect and
caller cancellation with resistant close; all retain admission until actual finish.
The four focused files pass52 tests.

The first full integration had390 passes12 failures: the legacy differential
test loader purged all API service submodules but restored only its root. Later
tests imported new service classes while canonical routes held their original
identities. A failure-first cache-preservation test confirmed this; the root test
loader now restores its complete prior service-module mapping. No child file was
changed and no cleanup/security assertion was relaxed. Current full regression
passes403 tests99 warnings in11.24s. Browser regression on the same production
source passed30 tests6 existing skips in27.8s, and OpenAPI remained identical34
paths. A fresh independent review is still required after this integration.

Scoped acceptance: fresh Hume I1 reviewed the frozen integrated artifact,
reran403 combined tests and five independent actual-route/64-slot probes, and
approved T1-T5 without a material gap. Lead verified raw probes and full pre/post
sentinel details/digest equality. Report transport-review-5.md and typed
VER-SA-TRANSPORT-PEER-5 bind this acceptance; the scoped VERIFIED gate is
.agent/gates/state-of-art-disconnect-verified.json. Previous rejections remain
preserved. Full product, visual, readiness/login and external gates are not implied.
