# Strict readiness and authentication response ordering

Scope SA-READINESS-REVIEW: correct two observed state-interpretation failures.
No new role, credential, endpoint, cookie policy, external service or deployment.
This is not approval of all readiness/authentication behavior or the full AAA bar.

## Observed baseline

The actual /health/ready route returns200 ready for a required hook reporting
ok='false'. A failing hook with required=[] becomes200 degraded. Valid explicit
required=False remains200 degraded; valid required=True remains503 not_ready.
Fifteen isolated normalizer probes had10 failures5 passes. The mistake is boolean
truthiness coercion, not the existing1s budget or bounded thread/task ownership.

Chromium against the actual local Next application reproduced a delayed auth/me
401 arriving after successful login: the browser reached /app, then returned to
/login?next=%2Fapp when that old response cleared SessionProvider state. All API
responses in this probe were synthetic in-memory interceptions, not external
accounts. Probe /tmp/rick-login-ordering-UnhI74/probe.cjs exited1 on its invariant.
Earlier transpiled-component execution with simulated hooks found the same race;
that lesser evidence is not substituted for the observed browser behavior.

## Required contract

- R1: ok and required are booleans, never truthiness-coerced. Invalid ok means
  failed health. Invalid required means failed, required health. Explicit valid
  optional policy is preserved. Invalid flags expose only a fixed safe diagnostic.
- R2: existing selected-component mandatory policy, redaction, public/admin
  status contracts, total readiness deadline, finite admission and cancellation
  behavior remain unchanged. Invalid helper default_required is rejected rather
  than becoming an implicit policy.
- L1: an older authentication refresh success or failure cannot overwrite a
  newer signIn/signOut intent/result. Out-of-order refreshes cannot overwrite the
  newest refresh. A stale signIn result cannot falsely drive successful navigation.
- L2: caller-visible success/failure stays truthful; errors cannot resurrect a
  session, hide a current login failure or produce an unhandled UI rejection.
  Existing redirect allowlist, busy guard and server-owned identity stay intact.
- V1: actual HTTP and Chromium order-controlled tests reject the old behavior;
  complete backend/browser/type/lint/build checks and fresh scoped review follow.

## Target design and ownership

Backend owner: lead, core/lifecycle.py and new test_readiness_flags.py. Normalize
flags by exact boolean membership without invoking arbitrary __bool__; preserve
valid optional checks; fail invalid policy closed. Keep existing readiness task
and thread control architecture and API schemas.

Frontend owner: one bounded builder, components/session-provider.tsx,
components/app-shell.tsx's logout error consumer, and new
tests/session-ordering.spec.ts only. Use provider-local monotonic operation
generations and current-operation guards, with no global cross-session state.
Invalidate outstanding reads at auth mutation boundaries, including reads started
while mutation is pending. Do not add dependencies or mutate the server protocol.
Concurrent mutation handling must remain bounded and truthful; report a needed
contract change before broadening ownership. Do not change visual layout/copy.

Lead owns all control/docs and browser/API test ports. Builder may run focused
browser checks on owned test ports only when lead confirms no competing server,
build, typecheck or browser run. One builder plus one later fresh critic; no
descendants. Lead backend checks can run concurrently without shared writes.
Residual local change risk MEDIUM, T4, CROSS_SYSTEM; no human authority for
credential/production/high-risk acceptance is inferred. Restore forward through
small patches; preserve dirty user changes and every failed observation.

## Separately routed required gap

SA-DI-ISOLATION remains uncorrected: actual AppA returned503 for its required
failed check before AppB creation; after creating healthy AppB, AppA returned200
and exposed AppB check names. dependencies/services.py uses a process-global
provider pointer. Correct app-local provider binding and cross-app authorization/
data/readiness isolation in that separate task; this contract does not accept
that defect or certify complete API/security readiness.

## Backend implementation evidence

The new46-case flag regression first had32 failures14 passes. The implementation
now rejects nonboolean flags without arbitrary truthiness, preserves valid
optional policy, and rejects invalid default_required before starting work.
All70 focused readiness/health cases passed. Complete API/package/worker suite:
449 passed138 dependency deprecation warnings in11.86s. Frontend ordering work
and fresh integrated independent acceptance are still pending; this is not a
combined readiness/login approval.

Frontend integration finding: the builder's focused browser suite currently
passes12 and fails3 because AppShell invokes void signOut without catching a
truthful logout503 rejection. An intermediate15/15 result suppressed those
failures and was deliberately removed. Lead extends the same builder ownership
only to AppShell's logout consumer to catch and display a safe logout failure
across the login redirect, while keeping private content hidden and stale refresh
ignored. This satisfies existing L2 without changing server credentials, cookies,
permissions or API; entry gate remains applicable. Error presentation must not
claim server logout succeeded or swallow failure, and must support a safe retry.

## Final local integration and preserved corrections

The logout consumer now catches the provider's truthful rejection, immediately
keeps private content hidden, displays a fixed safe alert across the redirect,
and permits a bounded retry. Lead added an actual browser regression for a new
successful login after failed logout: all three viewports initially retained the
obsolete retry notice. AppShell now clears that notice when a new authenticated
session supersedes it. The resulting browser suite passed48 with6 existing
viewport skips (37.1s);18 cases exercise session ordering at375/768/1440.
Screenshots logout-failure-{mobile,tablet,desktop}.png under
artifacts/visual/state-of-art were directly inspected: the notice and retry
remain readable without horizontal overflow. This is scoped error-state
inspection, not a new full visual score or WCAG certification.

Lead also tested the direct evaluate_readiness consumer with malformed flags:
four failures and one pass exposed residual truthiness despite the normalized
HTTP boundary. It now applies the same safe normalization while classifying,
without duplicating the sequence. The complete backend suite now passes454
tests (138 dependency deprecation warnings,11.64s). OpenAPI remains byte-value
equivalent to the committed schema,34 paths.

Typecheck, ESLint and production build succeeded. An initial ESLint warning about
incrementing the generation ref in effect cleanup was removed by using a stable
nextGeneration callback shared by all invalidation sites; no rule was disabled.
The full browser suite passed again after this equivalent counter refactor:
48 passed,6 existing viewport skips,42.4s; typecheck/lint/build all exited0 with
no lint warnings. Fresh independent acceptance remains required, and provider isolation remains a
separately open defect. No external runtime or full AAA approval is claimed.

Fresh I1 review1 REJECT: the selected-component adapter overwrote invalid
required before normalization, laundering malformed policy into healthy state.
The critic reproduced12 HTTP failures with8 valid controls;454 existing tests
still passed. Lead verified the frozen digest/details and inspected raw probes.
Correct the same R1 contract by normalizing before forcing selected components
mandatory, retain valid optional-to-mandatory policy, add the missing HTTP matrix
and rerun regression before a new fresh review. The existing entry gate applies;
this is not a server identity/cookie/protocol or broader scope change.

Lead correction1 evidence: the new40-case selected-component HTTP matrix first
failed12/passed28. _required_component_result now uses _state_from_result before
forcing required=True, retaining invalid_check_state and failed health instead
of erasing malformed input. The combined API/package/worker suite plus the
preserved critic20-case probe passes514 (198 dependency warnings,24.93s).
Full Chromium suite passes48 with6 existing viewport skips (35.1s); OpenAPI is
still identical34 paths. Frontend source is unchanged from the clean
typecheck/lint/production build. Fresh independent review2 remains required.

Fresh I1 review2 Boole APPROVE R1/R2/L1/L2/V1, candidate
c99901a80d06351128c744ec677253737aafb630e304eb65542632ae3e5ea2a8.
Lead inspected raw57-case HTTP/deadline probes, negative controls, session
logic/browser probes and byte comparison. Independent checks:514 backend,
57 additional backend,6 simulated session scenarios,48 Chromium/6 explicit
skips and21 focused Chromium passed; type/lint/build passed on byte-identical
temporary frontend. Both historical failure mechanisms were detected by negative
controls; a critic-only locator failure was corrected and preserved in its
report. Lead independently confirmed complete pre/post digest AND details.
This accepts only the five criteria here, not app isolation, full auth protocol,
full visual quality, external infrastructure or overall AAA readiness.
