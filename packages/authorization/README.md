# `packages/authorization`

Canonical permission semantics, role resolution, collection ACL and trusted
`RetrievalContext` construction, with no imports from API or legacy applications.

# Collection grant authority

`allowed_collection_ids_for_user` distinguishes an omitted legacy field from
an explicit empty list. Only omitted grants on legacy user records inherit
historical role defaults. Explicit empty/invalid grants and missing grants on
`AUTHORITATIVE`/`MIGRATED` records return `[]`. Explicit `['*']` retains wildcard
access; valid finite lists retain their scope and canonical collection aliases.

`intersect_grants(previous, current)` is an additive policy helper for runtime
revalidation and legacy migration. It intersects both grant ceilings with
explicit wildcard semantics, preserving empty and finite negative scopes.
