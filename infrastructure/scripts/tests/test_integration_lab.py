import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

SPEC = importlib.util.spec_from_file_location("integration_lab", Path(__file__).parents[1] / "integration_lab.py")
lab = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lab)


def secrets():
    return {name: "synthetic-local-only" for name in lab.SECRETS}


def test_environment_drops_remote_context_and_provider_credentials():
    result = lab.environment({**secrets(), "DOCKER_HOST": "ssh://remote", "DOCKER_CONTEXT": "remote", "LLM_API_KEY": "private"})
    assert set(result) == set(lab.SECRETS) | {"COMPOSE_DISABLE_ENV_FILE"}


@pytest.mark.parametrize("name", lab.SECRETS)
def test_secret_failure_identifies_name_not_value(name):
    values = secrets()
    values[name] = "private"
    with pytest.raises(lab.LabError) as error:
        lab.check_secrets(values)
    assert name in str(error.value)
    assert "private" not in str(error.value)


def test_commands_never_delete_volumes_or_use_another_project():
    for action in ("preflight", "start", "status", "stop"):
        args = lab.command(action)
        assert "unix:///var/run/docker.sock" in args
        assert lab.PROJECT in args
        assert not {"down", "rm", "prune", "--volumes", "-v"}.intersection(args)
    with pytest.raises(lab.LabError):
        lab.command("down")


def test_project_name_is_stable_for_this_checkout_but_not_global():
    assert lab.PROJECT.startswith("rick-rec-local-")
    assert len(lab.PROJECT.rsplit("-", 1)[-1]) == 10


def test_missing_runtime_is_blocked(monkeypatch):
    monkeypatch.setattr(lab.shutil, "which", lambda *a, **kw: None)
    with pytest.raises(lab.LabError, match="unavailable"):
        lab.run("preflight", source=secrets())


def test_driver_failure_is_redacted(monkeypatch):
    monkeypatch.setattr(lab.shutil, "which", lambda *a, **kw: "/usr/bin/docker")
    monkeypatch.setattr(lab.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=1, stderr="private-url-and-secret"))
    with pytest.raises(lab.LabError) as error:
        lab.run("start", source=secrets())
    assert "private-url-and-secret" not in str(error.value)


def test_status_reports_only_allowlisted_running_service_names(monkeypatch):
    monkeypatch.setattr(lab.shutil, "which", lambda *a, **kw: "/usr/bin/docker")
    monkeypatch.setattr(lab.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0, stdout="postgres\nprivate-secret\nidentity\n"))
    assert lab.run("status", source=secrets()) == ("identity", "postgres")


def test_topology_is_private_and_has_no_application_or_global_volumes():
    data = yaml.safe_load(lab.COMPOSE.read_text())
    assert set(data["services"]) == {"postgres", "object-store", "qdrant", "identity"}
    for service in data["services"].values():
        assert all(port.startswith("127.0.0.1:") for port in service["ports"])
        assert "latest" not in service["image"]
        assert service["networks"] == ["integration"]
    assert data["networks"]["integration"]["internal"] is True
    assert all(not value for value in data["volumes"].values())
