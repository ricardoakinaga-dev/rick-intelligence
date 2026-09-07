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
- root `/admin` boundary for the next operational slice;
- keyboard-visible focus, reduced motion, loading, empty, error and permission
  states.

## Commands

```bash
npm ci
npm run lint
npm run typecheck
npm run build
npm run test:e2e
```

The repository validation target uses the production bundle explicitly:
`make web-validate` builds with `RICK_API_TEST_PORT`, serves with `next start`,
and runs the 375/768/1440 matrix with a single-worker lab profile. This
keeps the LCP/CLS sample representative of the built artifact. Direct
`npm run test:e2e` remains the faster development-server workflow; set
`RICK_WEB_E2E_PRODUCTION=1` when reproducing the production profile manually.

By default the browser calls its own origin and Next forwards `/api/*` and
`/health/*` to `RICK_API_INTERNAL_URL` (locally
`http://127.0.0.1:8000`). Set `NEXT_PUBLIC_API_BASE_URL` only when the deploy
does not use the same-origin proxy; that external API must enforce restrictive
CORS and secure cookies.
