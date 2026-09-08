# `infrastructure/compose`

Reserved for production-like development/staging compose after canonical apps,
readiness, volumes, secret handling, and internal Locker networking are
specified. No fake root compose is shipped in Phase 1.1.

The reference worker image is a non-HTTP process. Its healthcheck invokes the
fail-closed worker launcher and requires an externally reviewed
`RICK_WORKER_COMPOSITION=module:factory`; it does not probe a port that the
worker does not serve.
