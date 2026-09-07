# Canonical web: truthful states and visual acceptance

Status: baseline reproduced and implementation design specified; gate binds the
authorized local correction before source edits.
Owner: Codex lead. Task SA-VISUAL. No frontend change is authorized by this
document alone; obtain the scoped implementation-ready gate first.

## Outcome and direction

Primary user: a veterinarian asking a workspace-scoped question and inspecting
returned evidence; knowledge managers additionally maintain the corpus, and
authorized administrators inspect runtime and audit. The primary clinical action
is asking a question, not reading operational vanity metrics.

Surface: existing canonical Next frontend, routes login, workbench, search,
chat, documents and admin. This is a refinement of the existing RICK product,
not a new landing page or brand. Design thesis: a calm evidence workbench with
clear question-to-answer-to-source order, visible uncertainty and useful density.

Identity locks: RICK name, teal accent, dark navigation rail and light reading
canvas. Preserve current server contracts, credentials, cookies, roles, actual
session ordering, logout failure/retry behavior, keyboard-safe mobile navigation,
document confirmation, citation metadata and legacy repositories. Existing API
responses are authoritative; client role hints never grant permissions.

Medium: code-native React/HTML/CSS and existing icons. No raster asset, stock
illustration, new paid font, external account or new provider is required.
Existing source and current renders are repository-existing identity/context
references, not pixel-reconstruction targets. No external visual reference was
supplied, so reference fidelity is N/A; no new raster asset acceptance is claimed.

## Observed baseline

At375x812,768x1024 and1440x1000, actual Chromium loaded byte-identical current
frontend source in an isolated temporary Next copy. Synthetic session is
VETERINARIAN; documents returns403 while readiness independently returns200.
All three rendered a zero document count, an empty-corpus invitation to upload,
and pending/attention runtime despite its successful response. The diagnostic
exit0 means this known-bad condition was observed, not that acceptance passed.
All three screenshots were directly inspected. Evidence:
.gauntlet-state-of-art/evidence/visual-state-baseline/permission-{mobile,tablet,desktop}.png
and probe.cjs. The copy matched all31 frozen frontend source/config/test files.
Next's development effect replay issued two requests per endpoint; this is not a
production request-count claim. The owned temporary server3011 was stopped.

The workbench Promise.all couples document and health failures; missing data is
rendered as zero/empty. Mobile and tablet stack oversized metric cards ahead of
the primary question action. The mobile action is below the first viewport.
There was no horizontal overflow in this diagnostic. The earlier visual78.69
score is historical SELF diagnosis only; no new complete score exists.

Source-only risks, NOT yet runtime-reproduced: search can accept a late result
after clearing a prior result while another search is pending; same-page identity
or workspace changes may retain or accept stale workbench/admin data. Reproduce
before correction and distinguish display correctness from server authorization.

## Required changes and acceptance

V1 Truth: loading, known empty,403, network/server error and successful data are
distinct. An unavailable count is a dash or explanatory state, never zero.
Documents403 cannot fabricate an empty corpus/upload invitation or suppress a
successful independent health result. Retry is explicit and bounded. Successful
empty data alone may invite a permitted next action; server denial stays visible.

V2 Async state: controlled delayed requests and identity/workspace changes cannot
restore obsolete results or private display data. Preserve server authority and
the already accepted session mutation ordering. A user clearing search must not
receive a late resurrected result. No new backend permission contract is inferred.

V3 Task hierarchy: at375/768/1440, primary question action precedes secondary
runtime/corpus detail and fits the initial workbench viewport. Search/chat inputs
retain labels and useful controls without decorative panels displacing evidence.
Answer, uncertainty and actual citation metadata remain distinguishable. Long
titles, localized copy and errors wrap without truncating essential information.

V4 Language and claims: plain Portuguese UI labels. Proposed action labels:
"Fazer uma pergunta", "Buscar evidências", "Documentos", "Tentar novamente".
Use "Sem acesso aos documentos" for403 and "Não foi possível carregar" for
unknown failures; do not conflate either with "Nenhum documento". Replace
unfounded confidence/approval assurances with descriptions of returned sources.
Do not manufacture citation text, navigable source URLs, clinical validity,
verified coverage, live metrics or external service health. Source details are
limited to the current citation contract; any new access API is a separate task.

V5 Accessibility and responsive quality: current native renders at375x812,
768x1024 and1440x1000; keyboard-only navigation, visible focus, semantic roles,
labels/errors, non-color states, reduced motion, touch targets, zoom/reflow and
measured contrast. Automated axe checks supplement manual inspection, not certify
WCAG by themselves. Installed axe-core4.13.0 is available transitively; explicit
test dependency pinning may be proposed at the implementation gate. No browser
connector is available: installed Playwright/Chrome is the documented fallback.

V6 Regression and visual verdict: typecheck, lint, production build, actual full
browser suite, focused failure-first state tests, current raw logs/exit codes and
render hashes. Preserve existing skips only where their viewport reason applies.
Measure applicable frontend LCP/CLS and content stress with environment stated;
local synthetic performance does not establish external production performance.
Fresh host-observed blind independent critic must inspect the actual artifact,
states and region evidence before any full visual approval.

## Viewport, state and region matrix

All three viewports: login default/error; workbench loading/success/empty/403/
network error; search default/results/empty/error/long content; chat response/
empty citations/error/long content; document list/empty/error and confirmation;
admin allowed/denied/runtime/audit error. Relevant keyboard focus and navigation
states, delayed-response interactions and zoom/reflow require executable evidence
even where a full-page screenshot adds no information. State-specific semantic
regions are navigation, page header, primary action, input/filter, result/evidence,
status/recovery and administrative/list detail where actually applicable.

Every material ledger finding binds an id, location, render_id, viewport, state,
expected/observed behavior, severity, inspectable evidence, proposed fix and
status. Initial workbench truth finding is HIGH/OPEN; primary-action hierarchy is
MEDIUM/OPEN. Source-only race hypotheses remain NOT RUN. No FIXED label without
fresh rendering and relevant interaction evidence. Do not inflate completeness
with inapplicable region/state combinations or count old images as current.

## Quality bar, budget and ownership

Full visual threshold remains95/100 with HIGH evidence confidence, no unresolved
Critical/High finding and required accessibility gates; no threshold reduction.
Use all applicable controlled rubric dimensions: hierarchy, typography,
spacing-layout, color, consistency, usability, responsiveness, accessibility,
brand-identity, polish, interaction-quality, information-density and product-
specificity. Reference-fidelity and new raster asset-quality are N/A with the
above rationale; existing icons still undergo consistency/accessibility checks.
Report applicable weight denominator and evidence per score. A numerical mean
cannot erase a failed required gate; no self-score is independent acceptance.

Budget: at most four material visual correction cycles for this run, with fresh
renders after each. Stop honestly at acceptance, no justified material correction,
budget exhaustion or missing required capability; a failed bounded run does not
close the full user goal. Missing external environment remains separately open.
Portable benchmark validation/scoring is contract checking, never independent
semantic approval. Bind any future run packet to actual artifact/render/inspection/
critic/decision evidence, not generated success placeholders.

Lead owns visual direction, shared CSS, integration and all control records.
Only disjoint page/test lanes may be delegated after the gate; document exact
writers before edits. Critics are read-only fresh contexts receiving constraints,
artifact and criteria without builder rationale or self-score. Preserve failures
and missing evidence, including the DI browser-log lesson. No external writes,
deployments, policy expansion or residual HIGH acceptance are authorized.

## Cycle1 implementation boundary

Actual Chromium reproduced late search resurrection after Clear: first result
visible, second request held at the HTTP boundary, Clear empties the input/URL,
then released second response displays its result. Raw probe/log/screenshot:
.gauntlet-state-of-art/evidence/visual-search-baseline/. Exit0 confirms failure.

HOW: workbench owns independent discriminated async document and health states,
with generation guards and invalidation on cleanup/refresh. No stale success is
shown under a new load/error. Use a compact primary question panel before a
secondary status definition list; no decorative hero orbit or false metric zero.
AppShell keys private page content by session/user/tenant/workspace/role identity
so a changed authenticated identity remounts page-local state synchronously.
This is display hygiene, not an authorization mechanism. Preserve SessionProvider
and logout/navigation behavior. Per-page generation guards reject stale results
after clear, superseding request or unmount, including StrictMode replay.

Search treats URL state and submitted queries deliberately, preserves existing
query/collection/top_k contract, enforces integer limits1-20, and keeps metadata
readable in a compact summary/disclosure rather than three oversized KPI cards.
Admin clears unavailable/stale summary values on refresh/error and independently
represents runtime/audit errors without invented success; existing role hints and
backend decisions remain unchanged. Chat keeps question/result/source meaning,
current submit/copy behavior, and exact citation data with truthful explanatory
copy. Documents retain mutation/confirmation/job semantics; visual wrapping,
readability and touch/focus refinements only unless a new failure is reproduced.

Execution topology: multi-workstream local-write. One builder owns only
apps/web/app/app/search/page.tsx, apps/web/app/admin/page.tsx and a new
apps/web/tests/search-state.spec.ts. Lead owns workbench, AppShell, chat, shared
CSS, remaining tests, package/lockfile if explicit axe pin is needed, benchmarks
and all docs/controls. No shared CSS writes, public API changes or descendants.
Installed live tool supports fork_context:false and shared filesystem; disjoint
ownership is enforced by packet. One builder, then two fresh blind subjective
critics with a fresh adjudicator only on material disagreement; final full-bar
critic remains separately required. Each implementation lane gets one bounded
cycle and at most two targeted rework attempts per new hypothesis; full visual
run ceiling remains four cycles. No external spend is authorized or needed.

Lead alone owns Next3011 and generated build outputs. Builder may inspect that
server or run browser-only temporary config with outputs under/tmp; it must not
run root typecheck/build/lint concurrently, edit installed modules, or bind ports.
Stop Next before final typecheck/build, then run production rendering and complete
regression. Forward scoped patches are recovery; no reset of the dirty worktree.
Current risk is MEDIUM for reversible local UI changes; any public security/data
contract expansion or residual HIGH acceptance requires a new authority boundary.

## Cycle1 implemented / local regression observed

Lead implemented workbench independent discriminated resource states, current
generation invalidation, task-first composition, AppShell identity-keyed private
content, shared readable/touch/focus styles and truthful chat copy. Sartre's
bounded builder changed only search/admin and new search-state.spec.ts; no
descendants. Lead inspected the returned files and strengthened delayed-response
tests to wait for actual Response.text consumption plus a task/two render frames.
Builder status remains IMPLEMENTED, not independent acceptance; its handle closed.

The same403-to-empty defect was then reproduced on Documents, including two
upload invitations and a false empty state. The existing V1/V2 gate covers this
now-observed correction: catalog errors/counts are distinct, stale read results
are invalidated, collections do not overwrite newer selection, and optional
collection lookup ignores completion after unmount. Job polling stops issuing
new reads after unmount; mutation endpoints, confirmation and outcome semantics
were not changed. The standard upload control does not infer write permission
from catalog-read permission; the false empty-state upload invitation is removed.

Focused browser:15 workbench,9 document and15 builder search/admin cases passed.
Complete development suite:87 passed,6 existing viewport skips,1.3m. Complete
production suite after final helper cleanup:87 passed,6 same skips,38.0s, zero
failures or retries. Production history initialization/supersession repeated
three times per viewport:18 passed,19.3s. Current typecheck, clean lint and
production build exit0; axe-core4.13.0 is now an explicit existing-engine test
dependency. Its workbench403-only scan found0 violations/0 incomplete rules at
all three viewports, NOT whole-app or manual WCAG acceptance. All owned test
servers3010/3011/8001 stopped; unrelated8000 untouched. Raw logs and results:
.gauntlet-state-of-art/evidence/visual-cycle-1/{lead,search}/.

Preserved failures: workbench's first9 failures were test selectors also matching
Next's hidden route-announcer alert;6 other cases passed. Selectors were scoped
to the actual workspace status region without relaxing expected state. Initial
lint had two cleanup-ref warnings; stable invalidation callbacks removed them.
Builder's early run had6 generic-alert harness failures plus one tablet history
duplicate (expected3, observed4 requests). The original trace proves Fast Refresh
rebuilding at monotonic22465.246 and done at22884.001; the extra identical request
began22884.396, while the AppShell source modification timestamp fell inside the
run. This is direct evidence of a contaminated development run; HMR causation is
a supported inference, not a new production code-fix claim. Stable-source full
production and repeated13-request/13-consumed-response histories did not reproduce
the duplicate. Pre/post frontend file manifests match exactly. Preserve the old
trace rather than relabeling that execution PASS.

Current mobile search/chat/documents and three-view permission screenshots were
directly inspected. Primary question CTA now fits the first viewport and readable
metadata wraps. Remaining required evidence: complete benchmark state/region
matrix; identity remount runtime coverage beyond source inspection; manual
keyboard/contrast/zoom/reduced-motion/content stress across all surfaces; measured
LCP/CLS; complete scored rubric; two fresh blind visual critics and final decision.
Cycle1 is implemented with local regression evidence, not a completed visual
cycle acceptance, full WCAG certificate,95-point score or AAA promotion.

Final control-package check initially had21 passes/1 failure: the isolated
controller fixture copies verification artifacts, but the newly introduced
benchmark was only referenced by backlog/gate, not by a typed observation.
Root make validate itself passed. The actual benchmark validator was rerun and
its PASS/file recorded explicitly so the existing fixture copies real evidence.
No verifier, threshold or source implementation was weakened for this correction.
