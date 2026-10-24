# RICK Intelligence — canonical web

This is the root-owned Next.js caller for the State of Art program. The
preserved `cvg-master-rag-v2/frontend/` remains read-only and continues to
serve the legacy contract; this app talks only to the canonical `/api/v1/*`
boundary.

## Current slice

- cookie-backed login and session boundary;
- responsive `/app` clinical workbench;
- documents catalog, bounded upload and ingestion job polling;
- grounded chat with confidence and evidence cards;
- gated human case records with structured hypotheses, evidence references,
  human review, and auditable feedback;
- root `/admin` boundary for the next operational slice;
- keyboard-visible focus, reduced motion, loading, empty, error and permission
  states.
- offline connection status, draft preservation, and explicitly non-final
  interrupted chat streams with retry.

## Commands

```bash
npm ci
npm run lint
npm run typecheck
npm run build
npm run test:coverage
npm run test:e2e
```

`npm run test:coverage` keeps the **85% line minimum** over the explicit
**19-file denominator** in [Vitest configuration](<vitest.config.ts>): all twelve
current library modules (including real API transport, response guards, client
authority, durable session coordination and job observation), session provider, app shell, UI primitives, case
workspace, both chat modules and the documents page. This preserves the original
ten modules and adds nine risk surfaces; it is **not whole-frontend coverage**.
Other routes/workspaces and dependencies remain outside this unit denominator.
Parser tests use native streams; React component tests use jsdom, including real
provider + shell + workspace integration. Playwright supplies complementary
browser evidence, not real IdP/store/provider acceptance. Reports default to
`.runtime/qa/web/`; `RICK_WEB_COVERAGE_DIR` selects an isolated destination. The
[sanitized summary validator](<../../scripts/state_of_art/summarize_coverage.py>)
requires exactly the same nineteen sources and rejects missing files or false totals.

Private component state is discarded when session identity, tenant, workspace,
role or permissions change. Case callbacks from the discarded instance are
invalidated, including list, detail, catalog and mutation success/error paths.
This client behavior supplements server authorization; it cannot discover a
server revocation until an authoritative session update arrives.

Focus, visibility and same-origin session-change announcements revalidate that
authority. During validation, the previous tree exists only in memory and is
**hidden and inert**; private JSON/FormData/SSE admission is suspended, in-flight
requests are aborted and their late bodies/events are fenced by epoch. The same
session restores its drafts and focus without remounting; another identity or
changed scope discards them. A remote pending login/logout cannot be bypassed by
focus. An orphaned remote transaction stays fail-closed and needs resolution in
the other tab/support, rather than a timer inventing authority. No credentials,
session records or private drafts are broadcast or persisted for this mechanism.
The v2 coordinator stores independent opaque pending-operation markers: settling
B cannot erase pending C, and a fresh observer checks every marker before
validation/commit/admission. Missing or unstable storage fails closed. Only the
writer removes its own operation; no timer clears another writer's marker.

This guarantee is for **cooperating v2 clients**. Observed legacy announcements
are tracked conservatively, but the old single-value protocol cannot reconstruct
a pending writer already overwritten before observer startup. Mixed-version
rolling deployment is **not validated** and needs an explicitly authorized
cutover/reload policy; this implementation does not invent that release decision.
Do not clear unknown markers automatically to make a pending session appear ready.

An aborted mutation is **not rollback**. Case creation/review/feedback retain
newer drafts and display an indeterminate-result warning; use the explicit
refresh to consult records before repeating. There is no automatic retry or
invented server idempotency for case mutations/uploads. Chat alone retains the
same idempotency key for its explicit recoverable retry. Case lists expose
server totals and explicit next-page loading beyond the first fifty records.

Job observation has a 9,600 ms wall-clock budget and bounded backoff; timeout,
transport failure or pause do not imply cancellation, publication or failure of
the server job. Resume observes the **same identifier**, without upload/retry.
After a remount, an authorized user can enter the identifier manually; the
browser does not persist it or the original source. A genuine new attempt is an
explicit retry with a source file and can return a successor job identifier.
Malformed 2xx envelopes, booleans and inconsistent identifiers are rejected before
consumers announce success. These client guards supplement server ACLs.

The SSE protocol requires one completion followed by `[DONE]`. Completion
freezes the payload; another nonterminal frame before `[DONE]` is invalid.
Frames after `[DONE]` are ignored, and the reader is canceled immediately rather
than waiting for EOF. Error, malformed frames, consumer errors and abort also
cancel and unlock the reader. EOF without both terminal events is incomplete.
Busy confirmation dialogs focus their dialog container, announce `aria-busy`,
contain Tab/Shift+Tab, block Escape during the operation and restore the opener
on close.

The repository validation target uses the production bundle explicitly:
`make web-validate` includes the unit coverage floor, builds with `RICK_API_TEST_PORT`, serves with `next start`,
and runs the 375/768/1440 matrix with a single-worker lab profile. This
keeps the LCP/CLS sample representative of the built artifact. Direct
`npm run test:e2e` remains the faster development-server workflow; set
`RICK_WEB_E2E_PRODUCTION=1` when reproducing the production profile manually.
The Phase 3 API-backed browser gate supplies a per-run `NEXT_DIST_DIR`, so a
managed development server cannot rewrite the production E2E routes manifest
when both lanes run on the same checkout.

By default the browser calls its own origin and Next forwards `/api/*` and
`/health/*` to `RICK_API_INTERNAL_URL` (locally
`http://127.0.0.1:8000`). Set `NEXT_PUBLIC_API_BASE_URL` only when the deploy
does not use the same-origin proxy; that external API must enforce restrictive
CORS and secure cookies.


`make web-e2e` writes new visual/performance evidence under
`.runtime/qa/web-e2e`, preserving authenticated historical CI control inputs.
Set `WEB_CURRENT_EVIDENCE_DIR=/absolute/owned/run-directory` to isolate another
run. Playwright's raw output can separately use `RICK_WEB_TEST_OUTPUT_DIR`.
Historical `.gauntlet-state-of-art` snapshots are inputs to control restoration,
not the default destination for new measurements.
