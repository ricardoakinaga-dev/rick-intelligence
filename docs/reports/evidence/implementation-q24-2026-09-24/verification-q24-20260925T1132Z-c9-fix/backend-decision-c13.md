# C13 backend decision — serialize sparse profile writes with password recovery

## Problem and invariant

`PostgresUserStore.save` upserts a complete user projection, including global `password_hash` and `password_version`. `admin_update_user` previously locked and reloaded the global account only when a profile field such as email, role or permissions was present. An empty PATCH or an unchanged-workspace-only PATCH could therefore read a stale account projection, let password recovery commit, and then write the old credentials back.

Every admin profile update that uses the full-row save must acquire the same global account row lock as password recovery before loading the target membership projection. The membership must still be resolved in the actor's exact tenant/workspace, and the existing cross-tenant guard for account-global changes remains in force.

## Decision

`admin_update_user` now calls `_lock_account_in_exact_workspace` unconditionally inside its transaction before applying fields or saving the row. That helper locks the global user row, retains the cross-tenant membership guard, and reads the actor's exact workspace membership after the lock. Password recovery already locks the global user row before locking its exact membership and updating credentials, so the two full-row writers serialize in the same account-first order.

## Consequences and verification

The live PostgreSQL regression pauses an empty admin PATCH after it reads the account, starts password recovery, and proves recovery cannot pass the account lock until the PATCH commits. It then verifies the recovered hash and incremented password version remain in the database and the prior password no longer verifies. Before the correction, the same regression failed because recovery completed while the stale PATCH was paused.

The previous sparse path therefore cannot overwrite credentials changed by recovery. This decision covers the PostgreSQL provider; volatile in-memory profile updates remain process-local and do not use the durable password-recovery path.
