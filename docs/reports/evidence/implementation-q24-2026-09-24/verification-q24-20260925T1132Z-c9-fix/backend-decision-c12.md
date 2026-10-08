# C12 backend decision — durable reset membership scope

## Problem and invariants

Administrative password reset updates global credentials and revokes every session for the account. A `users.manage` actor must first prove the target has a membership in the actor's exact tenant and workspace; tenant membership alone is not authorization for a sibling workspace. The existing cross-tenant guard remains because credential and session effects are global. Rejected requests must leave credentials, sessions and audit outbox unchanged.

## Decision

Keep the global account row lock and cross-tenant membership guard, but resolve the reset target with `get_by_id_for_tenant_workspace(user_id, tenant_id, workspace_id)` using the actor's validated workspace. A missing exact membership fails with `forbidden` before credential update, session revocation or outbox insertion. The existing admin profile-update path keeps its tenant-global credential/version guard after its separate exact-workspace membership check.

## Consequences and verification

The unit regression proves a target present only in a sibling workspace is rejected without mutation, session effects or audit event. The live disposable PostgreSQL regression proves the same failure against real rows while retaining successful reset in the actor workspace and existing atomic rollback coverage. Focused admin mutation tests and the PostgreSQL integration pass. The next review packet will list every referenced quality-bar source and require the critic to hash only individually listed files, without directory-wide scans or transitive reads outside the inventory.
