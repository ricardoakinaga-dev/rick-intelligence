# ADR-018 — Disk fallback policy

Date: 2026-09-03. Status: Accepted.

Disk fallback is a degraded-read path with identical ACL, engaged only when the
primary yields nothing. It never accepts writes or publishes. Rationale:
availability without a second source of truth or a leak path (leakage-tested).
