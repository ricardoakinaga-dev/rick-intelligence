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

`npm run test:coverage` runs Vitest with an 85% line minimum over the explicit
ten-file denominator in `vitest.config.ts`: navigation, permissions,
presentation, chat response parsing, API errors, session scope keys, the session
provider, app shell, case workspace, and UI primitives. Parser tests run against native
streams; React component tests use jsdom. Routes, the other
workspaces, API request wrappers, and dependencies are outside this unit
denominator. Playwright exercises complementary browser behavior. Reports
default to `.runtime/qa/web/`; `RICK_WEB_COVERAGE_DIR` selects another destination.
The repository's sanitized summary validator must declare the same source set
when integrating this expanded denominator.

Private component state is discarded when session identity, tenant, workspace,
role or permissions change. Case callbacks from the discarded instance are
invalidated, including list, detail, catalog and mutation success/error paths.
This client behavior supplements server authorization; it cannot discover a
server revocation until an authoritative session update arrives.

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
