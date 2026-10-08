# C11 backend decision — exact workspace session membership

## Problem and invariants

One global account may have active memberships in multiple workspaces under the same tenant. Session refresh must validate the membership represented by that session, not an arbitrary membership selected for the tenant. A legacy session record with no `workspace_id` retains the documented `default` scope; malformed or absent tenant/workspace scope fails closed.

## Decision

The identity `UserStore` contract now requires `get_by_id_for_tenant_workspace(user_id, tenant_id, workspace_id)`. Session validation normalizes the session tenant and workspace first, uses only this exact lookup, then checks membership/account state and credential/role versions. A repository without the exact method fails closed. The in-memory adapter compares the stored tenant/workspace pair, and PostgreSQL uses its existing query with both predicates. A missing legacy workspace resolves to `default`, and the returned session snapshot exposes that same default.

## Consequences and verification

Adapters that can represent multiple memberships must implement the exact lookup; tenant-only selection is not sufficient for session validation. Regressions cover two active same-tenant workspace sessions, the default for a legacy session without `workspace_id`, and live PostgreSQL validation of both memberships. The real PostgreSQL recovery integration also confirms that successful account-wide password recovery revokes both workspace sessions. Local evidence: identity 30, API 742, PostgreSQL migrations 108; lint, typecheck, web lint and web typecheck pass. These results do not establish deployed authentication or production acceptance.
