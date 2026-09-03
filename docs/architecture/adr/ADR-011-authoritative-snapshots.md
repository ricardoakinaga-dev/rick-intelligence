# ADR-011 — Authoritative snapshot semantics

Date: 2026-09-03. Status: Accepted.

An explicit session permission list is final. `[]` denies everything; reduced
lists never regain entries via role defaults on refresh. This closes the
re-grant defect found in the Phase 1.3 app-local `has_permission` fallback.
Enforcement is triple-layered: engine API (`authoritative=True` has no fallback
branch), provider persistence (snapshots stored, refresh never recomputes),
static test (fallback pattern banned from app code).
