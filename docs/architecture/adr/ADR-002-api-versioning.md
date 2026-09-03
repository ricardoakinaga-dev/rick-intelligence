# ADR-002 — API versioning

Date: 2026-09-03. Status: Accepted.

Platform surface is versioned (`/api/v1/*`); OpenAI compatibility keeps its own
unversioned-by-us namespace (`/v1/chat/completions`, `/v1/models`) to match
third-party client expectations. The two namespaces never share semantics:
platform version bumps do not change compat shapes, and compat fixes do not move
platform versions. Health (`/health/*`) is unversioned infrastructure.
