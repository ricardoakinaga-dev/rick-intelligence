"""Hermetic tests for the guarded root Compose lifecycle."""

from __future__ import annotations

import pytest

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
    monkeypatch.setattr(runner, "_collect_compose_diagnostics", lambda _compose: None)

    assert runner.mode_compose("up") == 1
    assert any("--wait" in command for command in calls)
    assert compose.is_file()
