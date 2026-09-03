# ADR-020 — Legacy caller-switch policy

Date: 2026-09-03. Status: Accepted.

Switches are per-caller, default-reversible via env flags
(RICK_API_ROOT_KNOWLEDGE=1 default on for reads; RICK_API_ROOT_RETRIEVAL=0
default off for chat evidence), each with differential evidence and a rollback
path in rag-migration.md. Heavy upload/worker paths switch last. No deletions
in Phase 1.4.
