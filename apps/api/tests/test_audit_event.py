from __future__ import annotations

import pytest

from services.audit_event import make_audit_event


def test_typed_event_keeps_only_allowlisted_text_and_omits_none():
    event = make_audit_event(
        "auth.logout", actor_user_id="user-1", tenant_id="tenant-1",
        request_id=None, status="effect_applied",
    )
    assert event == {
        "action": "auth.logout",
        "actor_user_id": "user-1",
        "tenant_id": "tenant-1",
        "status": "effect_applied",
    }


def test_typed_event_rejects_unknown_or_non_text_fields():
    with pytest.raises(ValueError):
        make_audit_event("auth.logout", private_document="secret")
    with pytest.raises(ValueError):
        make_audit_event("auth.logout", actor_user_id=123)
    with pytest.raises(ValueError):
        make_audit_event("")
