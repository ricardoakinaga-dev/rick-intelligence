"""Typed audit event boundary (AUD24-018).

One allow-listed shape for the events emitted by auth/dependencies. The
transport sink still sanitizes again; this module only prevents route code from
inventing fields or leaking an untyped payload into the audit boundary.
"""

from __future__ import annotations

from typing import NotRequired, Required, TypedDict, cast

from services.audit import AUDIT_EVENT_FIELDS


class AuditEvent(TypedDict, total=False):
    action: Required[str]
    status: NotRequired[str]
    actor_user_id: NotRequired[str]
    target_id: NotRequired[str]
    target_type: NotRequired[str]
    tenant_id: NotRequired[str]
    workspace_id: NotRequired[str]
    request_id: NotRequired[str]
    correlation_id: NotRequired[str]
    reason: NotRequired[str]
    error_code: NotRequired[str]
    user_id: NotRequired[str]
    session_id: NotRequired[str]
    collection_id: NotRequired[str]


def make_audit_event(action: str, **fields: object) -> AuditEvent:
    if not isinstance(action, str) or not action.strip():
        raise ValueError("audit action is required")
    event: dict[str, object] = {"action": action.strip()}
    for key, value in fields.items():
        if key not in AUDIT_EVENT_FIELDS:
            raise ValueError(f"unknown audit field: {key}")
        if value is None:
            continue
        if not isinstance(value, str):
            raise ValueError(f"audit field {key} must be text")
        value = value.strip()
        if value:
            event[key] = value
    return cast(AuditEvent, event)


__all__ = ["AuditEvent", "make_audit_event"]
