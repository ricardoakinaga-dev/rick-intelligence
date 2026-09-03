# ADR-007 — Legacy adapter boundary

Date: 2026-09-03. Status: Accepted.

Only `apps/api/src/adapters/legacy/` may import preserved legacy paths.
Routes/services use typed adapter protocols with failure translation to canonical
codes. Rationale: incremental migration (new route → adapter → legacy service →
later root package) without scattering `sys.path` hacks or letting routes reach
Qdrant/Redis/OpenAI directly. CI enforces via import-boundary test; each adapter
records typed interface + deprecation state + migration owner.
