"""OBS31 static wiring regressions; binary and delivery proof remain separate."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
import re

import pytest
import yaml

from scripts.phase11 import check_compose as CHECK


ROOT = Path(__file__).resolve().parents[3]
COMPOSES = ("docker-compose.dev.yml", "docker-compose.staging.yml")
PUBLIC_CONFIGS = (
    "infrastructure/compose/otel-collector-config.yaml",
    "infrastructure/compose/prometheus.yml",
    "infrastructure/compose/alerts.yml",
    "infrastructure/compose/alertmanager.yml",
    "infrastructure/monitoring/prometheus.rules.yml",
)


def read_yaml(path: str) -> dict:
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


def rendered_fixture(name: str) -> dict:
    """Normalize only Compose's mount/network shapes, without running Docker.

    The CLI is also tested against real Compose JSON by check_compose.py.
    Values remain nonsecret template inputs here.
    """
    payload = deepcopy(read_yaml(name))
    for service in payload["services"].values():
        service["networks"] = {network: {} for network in service.get("networks", [])}
        volumes = []
        for mount in service.get("volumes", []):
            source, target, *flags = mount.split(":")
            is_bind = source.startswith("./")
            volumes.append({"type": "bind" if is_bind else "volume",
                            "source": str(ROOT / source) if is_bind else source,
                            "target": target, "read_only": "ro" in flags})
        service["volumes"] = volumes
    return payload


@pytest.mark.parametrize("name", COMPOSES)
def test_canonical_topology_meets_existing_and_observability_policy(name: str) -> None:
    payload = rendered_fixture(name)
    assert CHECK._validate_rendered_services(name, payload) == []
    assert CHECK._validate_observability_topology(name, payload) == []


@pytest.mark.parametrize("name", COMPOSES)
@pytest.mark.parametrize("service", ["collector-ready", "alertmanager"])
def test_missing_monitoring_service_is_rejected(name: str, service: str) -> None:
    payload = rendered_fixture(name)
    del payload["services"][service]
    assert any(f"{service}: canonical service is required" in error
               for error in CHECK._validate_observability_topology(name, payload))


@pytest.mark.parametrize("service,target", [
    ("metrics", "/etc/prometheus/prometheus.yml"),
    ("metrics", "/etc/prometheus/alerts.yml"),
    ("metrics", "/etc/prometheus/prometheus.rules.yml"),
    ("otel-collector", "/etc/otelcol-contrib/config.yaml"),
    ("alertmanager", "/etc/alertmanager/alertmanager.yml"),
])
@pytest.mark.parametrize("fault", ["missing", "writable", "wrong-source", "duplicate"])
def test_mount_policy_rejects_missing_writable_or_misdirected_configs(service: str, target: str, fault: str) -> None:
    payload = rendered_fixture(COMPOSES[1])
    mounts = payload["services"][service]["volumes"]
    mount = next(item for item in mounts if item["target"] == target)
    if fault == "missing":
        mounts.remove(mount)
    elif fault == "writable":
        mount["read_only"] = False
    elif fault == "wrong-source":
        mount["source"] = str(ROOT / "unreviewed.yml")
    else:
        mounts.append(deepcopy(mount))
    assert any(target in error for error in CHECK._validate_observability_topology(COMPOSES[1], payload))


@pytest.mark.parametrize("name", COMPOSES)
@pytest.mark.parametrize("fault", ["scratch-shell", "api-entrypoint", "false-probe", "wrong-image", "early-start"])
def test_readiness_cannot_be_satisfied_by_an_unrelated_process(name: str, fault: str) -> None:
    payload = rendered_fixture(name)
    ready = payload["services"]["collector-ready"]
    if fault == "scratch-shell":
        payload["services"]["otel-collector"]["healthcheck"] = {"test": ["CMD-SHELL", "wget localhost:13133"]}
    elif fault == "api-entrypoint":
        ready.pop("entrypoint")
    elif fault == "false-probe":
        ready["healthcheck"]["test"] = ["CMD", "python", "-c", "print('healthy')"]
    elif fault == "wrong-image":
        ready["image"] = "python:latest"
    else:
        ready["depends_on"] = {}
    assert CHECK._validate_observability_topology(name, payload)


@pytest.mark.parametrize("service", ["api", "worker", "worker-b", "metrics"])
def test_application_and_scraper_cannot_bypass_collector_readiness(service: str) -> None:
    payload = rendered_fixture(COMPOSES[1])
    payload["services"][service]["depends_on"] = {"otel-collector": {"condition": "service_healthy"}}
    errors = CHECK._validate_observability_topology(COMPOSES[1], payload)
    assert any(f"{service}: must wait for healthy collector-ready" in error for error in errors)
    assert any(f"{service}: must not wait on scratch" in error for error in errors)


@pytest.mark.parametrize("service", ["collector-ready", "alertmanager"])
def test_new_services_retain_hardening_and_finite_resources(service: str) -> None:
    payload = rendered_fixture(COMPOSES[1])
    payload["services"][service].update(read_only=False, privileged=True, cap_drop=[], deploy={})
    errors = CHECK._validate_rendered_services(COMPOSES[1], payload)
    assert any(f"{service}: stateless service must use a read-only" in error for error in errors)
    assert any(f"{service}: finite deploy resource limits" in error for error in errors)
    assert any(f"{service}: all Linux capabilities" in error for error in errors)


@pytest.mark.parametrize("fault", ["root", "host-port", "no-secret", "env-secret", "readonly-data", "bind-data", "no-copy", "no-egress", "shared-egress", "internal-egress"])
def test_alert_delivery_rejects_unsafe_or_inoperative_configuration(fault: str) -> None:
    payload = rendered_fixture(COMPOSES[1])
    manager = payload["services"]["alertmanager"]
    data = next(m for m in manager["volumes"] if m["target"] == "/alertmanager")
    if fault == "root":
        manager["user"] = "0:0"
    elif fault == "host-port":
        manager["ports"] = [{"target": 9093, "published": "9093"}]
    elif fault == "no-secret":
        manager["secrets"] = []
    elif fault == "env-secret":
        payload["secrets"]["rick-alert-webhook-url"] = {"environment": "WEBHOOK_URL"}
    elif fault == "readonly-data":
        data["read_only"] = True
    elif fault == "bind-data":
        data["type"] = "bind"
    elif fault == "no-copy":
        data["volume"] = {"nocopy": True}
    elif fault == "no-egress":
        manager["networks"] = {"private": {}}
    elif fault == "shared-egress":
        payload["services"]["metrics"]["networks"]["alert-egress"] = {}
    else:
        payload["networks"]["alert-egress"]["internal"] = True
    assert CHECK._validate_observability_topology(COMPOSES[1], payload)


@pytest.mark.parametrize("service", ["worker", "worker-b"])
def test_workers_need_dedicated_outbound_provider_access(service: str) -> None:
    payload = rendered_fixture(COMPOSES[1])
    payload["services"][service]["networks"] = {"private": {}}
    assert any(f"{service}: private and dedicated worker-egress" in error
               for error in CHECK._validate_observability_topology(COMPOSES[1], payload))


@pytest.mark.parametrize("service", ["otel-collector", "collector-ready", "metrics", "alertmanager"])
def test_staging_must_not_publish_observability_ports(service: str) -> None:
    payload = rendered_fixture(COMPOSES[1])
    payload["services"][service]["ports"] = [{"target": 8888, "published": "8888"}]
    assert any("staging observability ports must not be published" in error
               for error in CHECK._validate_observability_topology(COMPOSES[1], payload))


def test_collector_exposes_own_metrics_with_the_v0123_reader_schema() -> None:
    collector = read_yaml("infrastructure/compose/otel-collector-config.yaml")
    metrics = collector["service"]["telemetry"]["metrics"]
    assert "address" not in metrics
    readers = metrics["readers"]
    assert len(readers) == 1
    assert readers[0]["pull"]["exporter"]["prometheus"] == {"host": "0.0.0.0", "port": 8888}
    assert collector["exporters"]["prometheus"]["endpoint"] == "0.0.0.0:8889"
    assert collector["extensions"]["health_check"]["endpoint"] == "0.0.0.0:13133"


def test_prometheus_scrapes_distinct_replicas_and_collector_self_and_routes_alerts() -> None:
    config = read_yaml("infrastructure/compose/prometheus.yml")
    jobs = {job["job_name"]: job for job in config["scrape_configs"]}
    api = jobs["rick-api"]
    assert api["metrics_path"] == "/metrics"
    assert "static_configs" not in api
    assert api["dns_sd_configs"] == [{"names": ["api"], "type": "A", "port": 8000, "refresh_interval": "15s"}]
    # Default instance labels are each address:port; never relabel to 'api'.
    assert not api.get("relabel_configs")
    assert api.get("honor_labels", False) is False
    assert jobs["otel-collector-self"]["static_configs"] == [{"targets": ["otel-collector:8888"]}]
    assert jobs["otel-collector"]["static_configs"] == [{"targets": ["otel-collector:8889"]}]
    assert config["alerting"]["alertmanagers"][0]["static_configs"] == [{"targets": ["alertmanager:9093"]}]
    assert set(config["rule_files"]) == {"/etc/prometheus/alerts.yml", "/etc/prometheus/prometheus.rules.yml"}


def test_rules_preserve_holds_and_missing_replica_identity() -> None:
    rules = {rule["alert"]: rule for group in read_yaml("infrastructure/compose/alerts.yml")["groups"] for rule in group["rules"]}
    assert rules["RickApiSloBreach"]["for"] == "5m"
    assert rules["RickApiSloBreach"]["expr"] == 'rick_api_slo_status{status="breach"} == 1'
    no_data = rules["RickApiSloNoData"]
    assert no_data["for"] == "10m"
    assert 'rick_api_slo_status{job="rick-api",status="no_data"} == 1' in no_data["expr"]
    assert re.search(r"unless on \(job, instance\) rick_api_slo_status\{job=\"rick-api\"\}", no_data["expr"])
    assert 'max_over_time(up{job="rick-api"}[1h])' in no_data["expr"]
    assert "max by (environment)" not in no_data["expr"]
    assert rules["RickApiUnavailable"]["for"] == "5m"
    assert 'up{job="rick-api"} == 0' in rules["RickApiUnavailable"]["expr"]
    assert 'unless on (job, instance) up{job="rick-api"}' in rules["RickApiUnavailable"]["expr"]
    assert rules["RickCollectorUnavailable"]["for"] == "5m"
    assert rules["RickCollectorUnavailable"]["expr"] == 'up{job="otel-collector-self"} == 0 or absent(up{job="otel-collector-self"})'


def test_error_budget_uses_only_business_counters_and_existing_thresholds() -> None:
    rules = {rule["alert"]: rule for group in read_yaml("infrastructure/monitoring/prometheus.rules.yml")["groups"] for rule in group["rules"]}
    burn = rules["RickApiErrorBudgetBurn"]
    assert burn["expr"] == "sum(rate(rick_api_http_business_errors_total[5m])) / clamp_min(sum(rate(rick_api_http_business_requests_total[5m])), 1) > 0.05"
    assert burn["for"] == "10m"
    expected = {
        "RickApiReadinessMissing": ('rick_api_readiness_status{service="api",status=~"unknown|degraded|not_ready"} == 1', "5m"),
        "RickWorkerDeadLetterGrowth": ('increase(rick_api_worker_jobs_total{status="dead"}[15m]) > 0', "1m"),
        "RickRetrievalLatencyP95": ('histogram_quantile(0.95, sum by (le) (rate(rick_api_retrieval_latency_ms_bucket[10m]))) > 1500', "10m"),
        "RickProviderFailureGrowth": ('increase(rick_api_provider_failures_total[15m]) > 0', "5m"),
    }
    for name, (expression, hold) in expected.items():
        assert (rules[name]["expr"], rules[name]["for"]) == (expression, hold)


def test_alertmanager_delivers_firing_and_resolved_through_file_only() -> None:
    config = read_yaml("infrastructure/compose/alertmanager.yml")
    receiver = next(item for item in config["receivers"] if item["name"] == config["route"]["receiver"])
    webhook = receiver["webhook_configs"][0]
    assert webhook["url_file"] == "/run/secrets/rick-alert-webhook-url"
    assert "url" not in webhook
    assert webhook["send_resolved"] is True
    assert webhook["timeout"] == "10s"
    assert webhook["max_alerts"] == 20
    assert {"alertname", "job", "instance"} <= set(config["route"]["group_by"])
    for name in COMPOSES:
        assert read_yaml(name)["secrets"]["rick-alert-webhook-url"]["file"].startswith("${RICK_ALERT_WEBHOOK_URL_FILE:?")


@pytest.mark.parametrize("name", COMPOSES)
def test_python_probe_queries_real_collector_and_propagates_failures(name: str) -> None:
    health = read_yaml(name)["services"]["collector-ready"]["healthcheck"]["test"]
    assert health[:3] == ["CMD", "python", "-c"]
    response = Mock()
    with patch("urllib.request.urlopen", return_value=response) as request:
        exec(compile(health[3], "collector-readiness", "exec"), {})
        request.assert_called_once_with("http://otel-collector:13133/", timeout=4)
        response.read.assert_called_once_with()
    for failure in (URLError("connection refused"), HTTPError("http://otel-collector:13133/", 503, "unready", {}, None)):
        with patch("urllib.request.urlopen", side_effect=failure), pytest.raises(type(failure)):
            exec(compile(health[3], "collector-readiness", "exec"), {})


def test_compose_example_check_ignores_ambient_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RICK_ALERT_WEBHOOK_URL_FILE", "/unreviewed/ambient/file")
    monkeypatch.setenv("POSTGRES_PASSWORD", "synthetic-canary")
    with patch.object(CHECK.subprocess, "run", return_value=Mock(returncode=0, stdout="{}")) as run:
        assert CHECK.run(COMPOSES[0], "infrastructure/compose/.env.dev.example", "config", "--format", "json") == (0, "{}")
    environment = run.call_args.kwargs["env"]
    assert "RICK_ALERT_WEBHOOK_URL_FILE" not in environment
    assert "POSTGRES_PASSWORD" not in environment
    assert run.call_args.args[0][2:4] == ["--env-file", "infrastructure/compose/.env.dev.example"]


@pytest.mark.parametrize("path", PUBLIC_CONFIGS)
def test_public_mounted_configs_are_readable_by_service_uids(path: str) -> None:
    assert CHECK._validate_public_config_permissions(ROOT / path) == []


@pytest.mark.parametrize("mode", [0o600, 0o640, 0o664, 0o755])
def test_permission_check_rejects_owner_only_group_only_writable_or_executable_yaml(tmp_path: Path, mode: int) -> None:
    config = tmp_path / "nonsecret.yml"
    content = b"receivers: {}\n"
    config.write_bytes(content)
    config.chmod(mode)
    errors = CHECK._validate_public_config_permissions(config)
    assert len(errors) == 1
    assert f"observed {mode:04o}" in errors[0]
    config.chmod(0o644)
    assert CHECK._validate_public_config_permissions(config) == []
    assert config.read_bytes() == content
