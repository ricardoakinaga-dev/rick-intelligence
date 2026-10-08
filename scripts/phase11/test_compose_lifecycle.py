"""Hermetic tests for the guarded root Compose lifecycle."""

from __future__ import annotations

import pytest

from scripts.phase11 import check_compose
from scripts.phase11 import runner


def test_compose_command_is_local_and_project_scoped() -> None:
    compose = runner.ROOT / "docker-compose.dev.yml"

    command = runner._compose_command(compose, "up", "--detach")

    assert command[:6] == [
        "docker",
        "--host",
        runner.LOCAL_DOCKER_HOST,
        "compose",
        "--project-name",
        runner._compose_project(compose),
    ]
    assert command[6:9] == ["--file", "docker-compose.dev.yml", "up"]
    assert "--detach" in command
    assert "--volumes" not in command
    assert "-v" not in command


def test_compose_teardown_can_parse_without_real_secrets() -> None:
    compose = runner.ROOT / "docker-compose.dev.yml"
    fallback = runner._compose_fallback_env_file(compose)

    command = runner._compose_command(
        compose,
        "down",
        "--remove-orphans",
        "--timeout",
        "30",
        env_file=fallback,
    )

    assert fallback is not None
    assert "--env-file" in command
    assert "REPLACE_WITH_DISPOSABLE_PASSWORD" not in command
    assert "--volumes" not in command


def test_compose_environment_removes_ambient_remote_context(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in runner.COMPOSE_ENV_REMOVE:
        monkeypatch.setenv(name, "ambient-value")

    environment = runner._compose_environment()

    assert all(name not in environment for name in runner.COMPOSE_ENV_REMOVE)
    assert environment["COMPOSE_INTERACTIVE_NO_CLI"] == "1"


def test_compose_inventory_parser_rejects_duplicate_fields() -> None:
    output = '{"Service":"api","Service":"worker"}'

    assert runner._parse_compose_json_records(output) == []
    assert check_compose._parse_rendered_config('{"services":{},"services":{"api":{}}}') is None


@pytest.mark.parametrize(
    "name",
    ["OBJECT_STORE_SECRET_ACCESS_KEY", "RICK_OBJECT_STORE_SECRET_ACCESS_KEY"],
)
def test_diagnostics_redact_both_object_store_secret_names(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    secret = "disposable-object-store-secret"
    monkeypatch.setenv(name, secret)

    output = runner._redact_diagnostic_output(f"credential={secret}")

    assert secret not in output
    assert output == "credential=[REDACTED]"


def test_diagnostics_redact_unexported_nested_secrets_and_urls() -> None:
    output = runner._redact_diagnostic_output(
        r'{"password":"unexported-password", "nested":{"token":"nested-token"}, '
        r'"dsn":"postgresql://user:dsn-secret@example.invalid/db", '
        r'"client_secret":"safe \" escaped-secret"}'
    )

    assert "unexported-password" not in output
    assert "nested-token" not in output
    assert "dsn-secret" not in output
    assert "escaped-secret" not in output
    assert "[REDACTED]" in output


@pytest.mark.parametrize("raw", ["0", "-1", "1801", "not-a-number"])
def test_invalid_compose_wait_timeout_is_rejected(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("RICK_COMPOSE_WAIT_TIMEOUT", raw)

    with pytest.raises(ValueError):
        runner._compose_wait_timeout()


def test_up_validates_inventory_and_waits_for_health(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    compose = runner.ROOT / "docker-compose.dev.yml"
    inventory = "\n".join(sorted(runner.COMPOSE_REQUIRED_SERVICES)) + "\n"

    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setenv("RICK_COMPOSE_FILE", "docker-compose.dev.yml")
    monkeypatch.setenv("RICK_COMPOSE_WAIT_TIMEOUT", "37")

    def fake_run_case(_label: str, command: list[str], **_kwargs: object) -> bool:
        calls.append(command)
        return True

    monkeypatch.setattr(runner, "run_case", fake_run_case)
    monkeypatch.setattr(runner, "_compose_capture", lambda *_args, **_kwargs: (True, inventory))
    monkeypatch.setattr(runner, "_write_phase3_preflight", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(runner, "_collect_compose_diagnostics", lambda *_args, **_kwargs: None)

    assert runner.mode_compose("up") == 0
    assert len(calls) == 2
    assert calls[0][-2:] == ["config", "--quiet"]
    assert calls[1][6:9] == ["--file", "docker-compose.dev.yml", "up"]
    assert "--detach" in calls[1]
    assert "--wait" in calls[1]
    assert calls[1][calls[1].index("--wait-timeout") + 1] == "37"
    assert "--remove-orphans" in calls[1]


def test_up_does_not_start_when_config_validation_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setenv("RICK_COMPOSE_FILE", "docker-compose.dev.yml")

    def fake_run_case(_label: str, command: list[str], **_kwargs: object) -> bool:
        calls.append(command)
        return False

    monkeypatch.setattr(runner, "run_case", fake_run_case)

    assert runner.mode_compose("up") == 1
    assert not any("up" in command for command in calls)


def test_up_failure_is_not_reported_as_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    compose = runner.ROOT / "docker-compose.dev.yml"
    inventory = "\n".join(sorted(runner.COMPOSE_REQUIRED_SERVICES)) + "\n"

    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setenv("RICK_COMPOSE_FILE", "docker-compose.dev.yml")

    def fake_run_case(_label: str, command: list[str], **_kwargs: object) -> bool:
        calls.append(command)
        return not any(argument == "up" for argument in command)

    monkeypatch.setattr(runner, "run_case", fake_run_case)
    monkeypatch.setattr(runner, "_compose_capture", lambda *_args, **_kwargs: (True, inventory))
    monkeypatch.setattr(runner, "_collect_compose_diagnostics", lambda *_args, **_kwargs: None)

    assert runner.mode_compose("up") == 1
    assert any("--wait" in command for command in calls)
    assert compose.is_file()


def test_up_started_but_shared_preflight_failed_is_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    inventory = "\n".join(sorted(runner.COMPOSE_REQUIRED_SERVICES)) + "\n"

    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setenv("RICK_COMPOSE_FILE", "docker-compose.dev.yml")
    monkeypatch.setattr(runner, "_compose_capture", lambda *_args, **_kwargs: (True, inventory))
    monkeypatch.setattr(runner, "_write_phase3_preflight", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(runner, "_collect_compose_diagnostics", lambda *_args, **_kwargs: None)

    def fake_run_case(_label: str, command: list[str], **_kwargs: object) -> bool:
        calls.append(command)
        return True

    monkeypatch.setattr(runner, "run_case", fake_run_case)

    assert runner.mode_compose("up") == 1
    assert any("up" in command for command in calls)


def test_down_invalidates_shared_preflight_before_teardown(monkeypatch: pytest.MonkeyPatch) -> None:
    invalidations: list[bool] = []

    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setenv("RICK_COMPOSE_FILE", "docker-compose.dev.yml")
    monkeypatch.setattr(runner, "_invalidate_phase3_preflight", lambda: invalidations.append(True))
    monkeypatch.setattr(runner, "_collect_compose_diagnostics", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runner, "run_case", lambda *_args, **_kwargs: True)

    assert runner.mode_compose("down") == 0
    assert invalidations == [True]


def _rendered_service(*, read_only: bool = True) -> dict[str, object]:
    return {
        "security_opt": ["no-new-privileges:true"],
        "cap_drop": ["ALL"],
        "init": True,
        "read_only": read_only,
        "deploy": {"resources": {"limits": {"cpus": "1.00", "memory": "1G"}}},
    }


def _rendered_payload() -> dict[str, dict[str, dict[str, object]]]:
    services = {
        name: _rendered_service(read_only=name not in check_compose.STATEFUL_SERVICES)
        for name in check_compose.REQUIRED_SERVICES
    }
    services["object-store-init"] = {
        "environment": {"OBJECT_STORE_ACCESS_KEY_ID": "scoped", "OBJECT_STORE_SECRET_ACCESS_KEY": "synthetic"}
    }
    services["jaeger"]["environment"] = {"SPAN_STORAGE_TYPE": "memory"}
    return {"services": services}


def test_rendered_compose_requires_hardening_and_resource_limits() -> None:
    payload = _rendered_payload()

    assert check_compose._validate_rendered_services("docker-compose.staging.yml", payload) == []


def test_rendered_compose_rejects_unbounded_or_privileged_services() -> None:
    payload = _rendered_payload()
    api = payload["services"]["api"]
    assert isinstance(api, dict)
    api["privileged"] = True
    api["deploy"] = {"resources": {"limits": {"cpus": "0", "memory": ""}}}
    errors = check_compose._validate_rendered_services("fixture.yml", payload)

    assert "fixture.yml:api: privileged mode is forbidden" in errors
    assert "fixture.yml:api: deploy.resources.limits.cpus must be finite" in errors
    assert "fixture.yml:api: deploy.resources.limits.memory must be finite" in errors


def test_rendered_compose_rejects_root_bootstrap_and_false_staging_persistence() -> None:
    payload = _rendered_payload()
    init = payload["services"]["object-store-init"]
    environment = init["environment"]
    assert isinstance(environment, dict)
    environment["MINIO_ROOT_PASSWORD"] = "synthetic-root"
    jaeger = payload["services"]["jaeger"]
    jaeger["environment"] = {"SPAN_STORAGE_TYPE": "badger"}
    jaeger["volumes"] = ["trace-data:/data"]

    errors = check_compose._validate_rendered_services("docker-compose.staging.yml", payload)

    assert "docker-compose.staging.yml:object-store-init: root credentials are forbidden" in errors
    assert "docker-compose.staging.yml:jaeger: staging tracing must declare ephemeral memory storage" in errors
    assert "docker-compose.staging.yml:jaeger: staging memory tracing must not claim a persistent volume" in errors


def test_full_test_mode_runs_only_canonical_lanes(monkeypatch: pytest.MonkeyPatch) -> None:
    """AUD07-02: the retired CVG/Professor/Locker lanes must not come back."""
    calls: list[tuple[str, list[str], object, object, int]] = []

    monkeypatch.setattr(
        runner,
        "run_cases",
        lambda cases: calls.extend(cases) or True,
    )

    assert runner.mode_test() == 0
    labels = [case[0] for case in calls]
    expected = [
        "current root boundary validator",
        "canonical Python suites (packages, API, differential)",
        "canonical worker suite",
    ]
    assert labels[: len(expected)] == expected
    retired = ("cvg-master-rag-v2", "rick-professor", "modulo-redis-locker")
    for case in calls:
        assert not any(component in case[0] for component in retired)
        command_text = " ".join(str(part) for part in case[1])
        assert not any(component in command_text for component in retired)
