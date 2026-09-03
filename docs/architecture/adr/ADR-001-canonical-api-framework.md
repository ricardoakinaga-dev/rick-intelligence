# ADR-001 — FastAPI remains the canonical platform HTTP kernel

Date: 2026-09-03. Status: Accepted.

Context: CVG API already owns authN/session/RBAC/workspace-security/documents/
search/admin/telemetry; Professor is Fastify/Node for the compat surface.

Decision: `apps/api` is Python/FastAPI. No Node rewrite: it would re-implement
the mature CVG security boundary for stylistic consistency with zero migration
benefit and high regression risk.

Consequences: compat surface stays an adapter, not a second server; TS expertise
remains for Professor extraction (1.4).
