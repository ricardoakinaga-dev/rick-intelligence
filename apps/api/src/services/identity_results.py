"""Typed results for identity mutations that also feed the audit boundary."""

from __future__ import annotations


class ResetEffect(int):
    """Revoked-session count carrying the scope of the completed reset.

    ``int`` keeps the existing public contract (and comparisons) while letting
    the HTTP layer emit a tenant-scoped audit event without a second lookup.
    The attributes are server-derived; none of them comes from request input.
    """

    user_id: str | None
    tenant_id: str | None
    workspace_id: str | None
    operation_id: str | None

    def __new__(
        cls,
        value: int,
        *,
        user_id: str | None,
        tenant_id: str | None,
        workspace_id: str | None,
        operation_id: str | None = None,
    ) -> "ResetEffect":
        instance = super().__new__(cls, value)
        instance.user_id = user_id
        instance.tenant_id = tenant_id
        instance.workspace_id = workspace_id
        instance.operation_id = operation_id
        return instance
