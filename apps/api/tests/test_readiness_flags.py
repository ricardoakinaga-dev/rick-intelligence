"""Malformed health flags cannot become successful or optional by truthiness."""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import create_app
from conftest import make_settings
from core.lifecycle import DependencyState, evaluate_checks, evaluate_readiness, safe_dependency_state


def request_state(flags, as_state=False):
    app = create_app(make_settings())
    result = DependencyState(name="flag-probe", **flags) if as_state else flags
    app.state.providers.health_checks = {"flag-probe": lambda: result}
    with TestClient(app) as client:
        response = client.get("/health/ready")
    check = next(item for item in response.json()["checks"] if item["name"] == "flag-probe")
    return response, check


@pytest.mark.parametrize("as_state", [False, True])
@pytest.mark.parametrize("value", ["false", "unavailable", 1, [], None])
def test_malformed_ok_is_never_healthy_at_http_boundary(as_state, value):
    response, check = request_state({"ok": value, "required": True}, as_state)
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert check == {"name": "flag-probe", "ok": False, "required": True}


@pytest.mark.parametrize("as_state", [False, True])
@pytest.mark.parametrize("ok", [False, True])
@pytest.mark.parametrize("value", [None, [], 0, "", "false"])
def test_invalid_required_flag_is_failed_and_mandatory(as_state, ok, value):
    response, check = request_state({"ok": ok, "required": value}, as_state)
    assert response.status_code == 503
    assert check["ok"] is False
    assert check["required"] is True


@pytest.mark.parametrize("as_state", [False, True])
@pytest.mark.parametrize("ok,required,status,body_status", [
    (True, True, 200, "ready"), (True, False, 200, "ready"),
    (False, True, 503, "not_ready"), (False, False, 200, "degraded"),
])
def test_valid_boolean_policy_is_preserved(as_state, ok, required, status, body_status):
    response, check = request_state({"ok": ok, "required": required}, as_state)
    assert response.status_code == status
    assert response.json()["status"] == body_status
    assert check["ok"] is ok and check["required"] is required


def test_invalid_health_does_not_override_explicit_valid_optional_policy():
    response, check = request_state({"ok": "false", "required": False})
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert check["ok"] is False and check["required"] is False


@pytest.mark.parametrize("field", ["ok", "required"])
def test_invalid_flags_do_not_execute_arbitrary_truthiness(field):
    class NoTruthiness:
        def __bool__(self):
            raise AssertionError("arbitrary truthiness must not execute")
    flags = {"ok": True, "required": True, field: NoTruthiness()}
    state = safe_dependency_state(DependencyState("probe", **flags, detail="private detail"))
    assert state.ok is False and state.required is True
    assert state.detail == "invalid_check_state"


@pytest.mark.parametrize("value", [None, [], 0, 1, "false"])
def test_invalid_default_policy_is_rejected_before_starting_work(value):
    invoked = []
    def check():
        invoked.append(True)
        return True
    with pytest.raises(ValueError, match="default_required"):
        asyncio.run(evaluate_checks({"probe": check}, default_required=value))
    assert invoked == []


@pytest.mark.parametrize("ok,required,expected", [
    ("false", True, ("not_ready", 503)),
    (False, [], ("not_ready", 503)),
    (True, None, ("not_ready", 503)),
    ("false", False, ("degraded", 200)),
    (True, False, ("ready", 200)),
])
def test_direct_evaluator_applies_the_same_strict_flag_contract(ok, required, expected):
    assert evaluate_readiness([DependencyState("probe", ok, required)]) == expected


@pytest.mark.parametrize("registered", [False, True])
@pytest.mark.parametrize("as_state", [False, True])
@pytest.mark.parametrize("ok", [False, True])
@pytest.mark.parametrize("required", [None, [], "false", False, True])
def test_selected_component_validates_flags_before_enforcing_mandatory_policy(registered, as_state, ok, required):
    flags = dict(name="storage", ok=ok, required=required, detail="adapter diagnostic")
    result = DependencyState(**flags) if as_state else flags
    app = create_app(make_settings())
    app.state.providers.storage = SimpleNamespace(health_check=lambda: result)
    if registered:
        app.state.providers.health_checks["storage"] = lambda: result
    with TestClient(app) as client:
        response = client.get("/health/ready")
    expected_ok = ok and isinstance(required, bool)
    assert response.status_code == (200 if expected_ok else 503)
    check = next(item for item in response.json()["checks"] if item["name"] == "storage")
    assert check == {"name": "storage", "ok": expected_ok, "required": True}
