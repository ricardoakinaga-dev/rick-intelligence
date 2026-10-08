#!/usr/bin/env python3
"""Validate the canonical Compose topology without starting containers."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]

try:
    from scripts.state_of_art.json_boundary import loads_json
except ModuleNotFoundError:  # Direct execution from the scripts/phase11 directory.
    sys.path.insert(0, str(ROOT))
    from scripts.state_of_art.json_boundary import loads_json

REQUIRED_SERVICES = {
    "postgres",
    "redis",
    "qdrant",
    "object-store",
    "jaeger",
    "otel-collector",
    "collector-ready",
    "alertmanager",
    "metrics",
    "api",
    "worker",
    "worker-b",
    "web",
}
STATEFUL_SERVICES = {"postgres", "redis", "qdrant", "object-store"}
READ_ONLY_SERVICES = REQUIRED_SERVICES - STATEFUL_SERVICES
COMPOSES = (
    ("docker-compose.dev.yml", "infrastructure/compose/.env.dev.example"),
    ("docker-compose.staging.yml", "infrastructure/compose/.env.staging.example"),
)


def run(compose: str, env_file: str, *args: str) -> tuple[int, str]:
    completed = subprocess.run(
        ["docker", "compose", "--env-file", env_file, "-f", compose, *args],
        cwd=ROOT,
        # Validate examples only: ambient deployment variables must not replace
        # their placeholders or expose populated credentials in rendered output.
        env={
            **{key: os.environ[key] for key in ("PATH", "HOME", "LANG") if key in os.environ},
            "COMPOSE_INTERACTIVE_NO_CLI": "1",
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    return completed.returncode, completed.stdout.strip()


def _validate_rendered_services(compose: str, payload: object) -> list[str]:
    """Validate security and finite-resource policy from Compose's JSON output."""

    if not isinstance(payload, dict) or not isinstance(payload.get("services"), dict):
        return [f"{compose}: rendered config has no services object"]

    services = payload["services"]
    errors: list[str] = []
    init_service = services.get("object-store-init")
    if not isinstance(init_service, dict):
        errors.append(f"{compose}:object-store-init: bootstrap service is required")
    else:
        environment = init_service.get("environment")
        if not isinstance(environment, dict):
            errors.append(f"{compose}:object-store-init: scoped credential environment is required")
        else:
            if {"MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD"} & environment.keys():
                errors.append(f"{compose}:object-store-init: root credentials are forbidden")
            for key in ("OBJECT_STORE_ACCESS_KEY_ID", "OBJECT_STORE_SECRET_ACCESS_KEY"):
                if not environment.get(key):
                    errors.append(f"{compose}:object-store-init: {key} is required")
    jaeger = services.get("jaeger")
    if compose == "docker-compose.staging.yml" and isinstance(jaeger, dict):
        environment = jaeger.get("environment")
        if not isinstance(environment, dict) or environment.get("SPAN_STORAGE_TYPE") != "memory":
            errors.append(f"{compose}:jaeger: staging tracing must declare ephemeral memory storage")
        if jaeger.get("volumes"):
            errors.append(f"{compose}:jaeger: staging memory tracing must not claim a persistent volume")
    for service_name in sorted(REQUIRED_SERVICES):
        service = services.get(service_name)
        if not isinstance(service, dict):
            continue
        security_opt = service.get("security_opt")
        if not isinstance(security_opt, list) or "no-new-privileges:true" not in security_opt:
            errors.append(f"{compose}:{service_name}: no-new-privileges is required")
        cap_drop = service.get("cap_drop")
        if not isinstance(cap_drop, list) or "ALL" not in cap_drop:
            errors.append(f"{compose}:{service_name}: all Linux capabilities must be dropped")
        if service.get("init") is not True:
            errors.append(f"{compose}:{service_name}: init must be enabled")
        if service_name in READ_ONLY_SERVICES and service.get("read_only") is not True:
            errors.append(f"{compose}:{service_name}: stateless service must use a read-only root filesystem")
        deploy = service.get("deploy")
        resources = deploy.get("resources") if isinstance(deploy, dict) else None
        limits = resources.get("limits") if isinstance(resources, dict) else None
        if not isinstance(limits, dict):
            errors.append(f"{compose}:{service_name}: finite deploy resource limits are required")
            continue
        for field in ("cpus", "memory"):
            value = limits.get(field)
            if isinstance(value, (int, float)):
                finite = value > 0
            elif isinstance(value, str):
                normalized = value.strip().upper()
                finite = bool(normalized) and normalized not in {"0", "0.0", "0M", "0MB"}
            else:
                finite = False
            if not finite:
                errors.append(f"{compose}:{service_name}: deploy.resources.limits.{field} must be finite")
        if service.get("privileged") is True:
            errors.append(f"{compose}:{service_name}: privileged mode is forbidden")
        if service.get("network_mode") in {"host", "none"}:
            errors.append(f"{compose}:{service_name}: unsupported network_mode is forbidden")
    return errors


def _validate_observability_topology(compose: str, payload: object) -> list[str]:
    """Check rendered wiring, mounts and isolation; no daemon access is needed."""

    if not isinstance(payload, dict) or not isinstance(payload.get("services"), dict):
        return [f"{compose}: observability requires a rendered services object"]
    services = payload["services"]
    errors: list[str] = []
    for name in REQUIRED_SERVICES:
        if not isinstance(services.get(name), dict):
            errors.append(f"{compose}:{name}: canonical service is required")
    if errors:
        return errors

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(f"{compose}:{message}")

    mounts = {
        "otel-collector": {
            "/etc/otelcol-contrib/config.yaml": "infrastructure/compose/otel-collector-config.yaml",
        },
        "metrics": {
            "/etc/prometheus/prometheus.yml": "infrastructure/compose/prometheus.yml",
            "/etc/prometheus/alerts.yml": "infrastructure/compose/alerts.yml",
            "/etc/prometheus/prometheus.rules.yml": "infrastructure/monitoring/prometheus.rules.yml",
        },
        "alertmanager": {
            "/etc/alertmanager/alertmanager.yml": "infrastructure/compose/alertmanager.yml",
        },
    }
    for name, required in mounts.items():
        volumes = services[name].get("volumes", [])
        for target, source in required.items():
            matches = [v for v in volumes if isinstance(v, dict) and v.get("target") == target]
            require(
                len(matches) == 1 and matches[0].get("type") == "bind"
                and matches[0].get("read_only") is True
                and matches[0].get("source") == str(ROOT / source),
                f"{name}: required read-only config mount {target} must bind {source}",
            )

    collector = services["otel-collector"]
    require(collector.get("image") == "otel/opentelemetry-collector-contrib:0.123.0",
            "otel-collector: v0.123.0 is required")
    require(not collector.get("healthcheck"), "otel-collector: scratch image cannot run a shell healthcheck")
    ready = services["collector-ready"]
    require(ready.get("image") == services["api"].get("image"),
            "collector-ready: must reuse the immutable API image")
    require(ready.get("entrypoint") == ["python", "-c"],
            "collector-ready: must override the API entrypoint with Python")
    probe = ready.get("healthcheck", {}).get("test", [])
    require(isinstance(probe, list) and probe[:3] == ["CMD", "python", "-c"]
            and len(probe) == 4 and "urllib.request.urlopen(" in probe[3]
            and "http://otel-collector:13133/" in probe[3] and "timeout=4" in probe[3],
            "collector-ready: bounded real Collector HTTP health probe is required")
    require(ready.get("depends_on", {}).get("otel-collector", {}).get("condition") == "service_started",
            "collector-ready: Collector must start before the probe")
    for name in ("api", "worker", "worker-b", "metrics"):
        depends = services[name].get("depends_on", {})
        require(depends.get("collector-ready", {}).get("condition") == "service_healthy",
                f"{name}: must wait for healthy collector-ready")
        require("otel-collector" not in depends, f"{name}: must not wait on scratch Collector health")

    manager = services["alertmanager"]
    require(manager.get("image") == "prom/alertmanager:v0.28.1", "alertmanager: v0.28.1 is required")
    require(manager.get("user") == "65534:65534", "alertmanager: uid/gid 65534 is required")
    require(not manager.get("ports"), "alertmanager: published ports are forbidden")
    command = manager.get("command", [])
    require("--config.file=/etc/alertmanager/alertmanager.yml" in command
            and "--storage.path=/alertmanager" in command
            and "--cluster.listen-address=" in command,
            "alertmanager: explicit config, writable storage and disabled peer listener are required")
    data = [v for v in manager.get("volumes", []) if isinstance(v, dict) and v.get("target") == "/alertmanager"]
    require(len(data) == 1 and data[0].get("type") == "volume"
            and data[0].get("source") == "alertmanager-data" and not data[0].get("read_only")
            and not data[0].get("volume", {}).get("nocopy"),
            "alertmanager: writable named volume with image ownership copy-up is required")
    secret_name = "rick-alert-webhook-url"
    require(any(isinstance(s, dict) and s.get("source") == secret_name and s.get("target") == secret_name
                for s in manager.get("secrets", [])),
            "alertmanager: reviewed webhook URL file secret mount is required")
    secret = payload.get("secrets", {}).get(secret_name, {})
    require(isinstance(secret, dict) and bool(secret.get("file")) and "environment" not in secret,
            "alertmanager: webhook secret must come from a reviewed file")
    require(services["metrics"].get("depends_on", {}).get("alertmanager", {}).get("condition") == "service_healthy",
            "metrics: must wait for healthy alertmanager")

    networks = payload.get("networks", {})
    require(networks.get("private", {}).get("internal") is True, "private: internal network is required")
    for name, egress in (("alertmanager", "alert-egress"), ("worker", "worker-egress"), ("worker-b", "worker-egress")):
        attached = services[name].get("networks", {})
        require(set(attached) == {"private", egress}, f"{name}: private and dedicated {egress} networks are required")
        require(egress in networks and networks[egress].get("internal") is not True,
                f"{name}: {egress} must allow outbound connections")
    for egress, allowed in (("alert-egress", {"alertmanager"}), ("worker-egress", {"worker", "worker-b"})):
        users = {name for name, service in services.items() if egress in service.get("networks", {})}
        require(users == allowed, f"{egress}: must be dedicated to {', '.join(sorted(allowed))}")
    for name in ("otel-collector", "collector-ready", "metrics"):
        require(set(services[name].get("networks", {})) == {"private"}, f"{name}: private-only network is required")
    if compose == "docker-compose.staging.yml":
        for name in ("otel-collector", "collector-ready", "metrics", "alertmanager"):
            require(not services[name].get("ports"), f"{name}: staging observability ports must not be published")
    return errors


def _parse_rendered_config(output: str) -> object | None:
    try:
        return loads_json(output)
    except json.JSONDecodeError:
        return None


def _validate_public_config_permissions(path: Path) -> list[str]:
    """Public bind-mounted YAML must be readable by non-host service UIDs.

    os.access would test the builder's UID, which can read its own 0600 file
    even when the Collector's uid 10001 cannot.
    """

    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o644:
        return [f"{path}: public mounted config must have mode 0644 (observed {mode:04o})"]
    return []


def main() -> int:
    if shutil.which("docker") is None:
        print("BLOCKED_EXTERNAL: docker executable is unavailable", file=sys.stderr)
        return 2
    errors: list[str] = []
    for compose, env_file in COMPOSES:
        compose_path = ROOT / compose
        env_path = ROOT / env_file
        if not compose_path.is_file():
            errors.append(f"{compose}: compose file is absent")
        if not env_path.is_file():
            errors.append(f"{env_file}: environment template is absent")
        if not compose_path.is_file() or not env_path.is_file():
            continue
        code, output = run(compose, env_file, "config", "--format", "json")
        if code != 0:
            errors.append(f"{compose}: config --format json failed: {output}")
            continue
        try:
            rendered = _parse_rendered_config(output)
        except json.JSONDecodeError:
            errors.append(f"{compose}: config --format json did not return JSON")
            continue
        if rendered is None:
            errors.append(f"{compose}: config --format json did not return JSON")
            continue
        errors.extend(_validate_rendered_services(compose, rendered))
        errors.extend(_validate_observability_topology(compose, rendered))
        code, output = run(compose, env_file, "config", "--services")
        if code != 0:
            errors.append(f"{compose}: service listing failed: {output}")
            continue
        services = set(output.splitlines())
        missing = sorted(REQUIRED_SERVICES - services)
        if missing:
            errors.append(f"{compose}: missing canonical services: {', '.join(missing)}")
        print(f"PASS {compose}: {len(services)} services rendered")

    for required_file in (
        ROOT / "infrastructure/compose/otel-collector-config.yaml",
        ROOT / "infrastructure/compose/prometheus.yml",
        ROOT / "infrastructure/compose/alerts.yml",
        ROOT / "infrastructure/compose/alertmanager.yml",
        ROOT / "infrastructure/monitoring/prometheus.rules.yml",
    ):
        if not required_file.is_file():
            errors.append(f"{required_file.relative_to(ROOT)}: required observability config is absent")
        else:
            errors.extend(_validate_public_config_permissions(required_file))

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print("PASS: canonical Compose topology is statically complete; runtime was not started")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
