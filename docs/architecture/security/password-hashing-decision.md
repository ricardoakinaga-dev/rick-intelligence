# Password hashing decision

## Decision

Argon2id migration is **formally deferred to Phase 1**. This is not a silent
security closure and it is not a reason to start Phase 1 from the current
Phase 0.6 gate.

The current implementation uses a per-user random salt with PBKDF2-HMAC-SHA256
at 100,000 iterations, verifies legacy/demo records during migration, and
does not expose password hashes, salts, reset tokens, or bearer values in API
responses or audit metadata. No evidence in the Phase 0.6 review demonstrates
that this existing bounded implementation is unsafe for the current local
scope.

## Deferred task

Before Phase 1 can be promoted to production readiness, add an approved
Argon2id dependency and parameters, migrate on successful login or through an
operator-controlled rehash job, preserve constant-time verification and
account lock/rate-limit behavior, and remove the old PBKDF2 path after the
inventory proves that no legacy hashes remain. The task must include a
version-pinned dependency audit, migration rollback plan, test vectors, and a
fresh password-reset/session-invalidation review.

## Trigger and owner evidence

This decision must be revisited if password policy, threat model, deployment
exposure, compliance requirements, or the accepted KDF parameters change. The
current Phase 0.6 report records the deferment and keeps it visible in the
promotion matrix.

Evidence: `cvg-master-rag-v2/src/services/admin_service.py`,
`cvg-master-rag-v2/src/services/enterprise_service.py`,
`docs/architecture/security/identity-model.md`, and
`docs/progress/phase-0.6-report.md`.
