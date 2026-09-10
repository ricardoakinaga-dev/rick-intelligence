#!/usr/bin/env python3
"""Validate the canonical Compose topology without starting containers."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
REQUIRED_SERVICES = {
    "postgres",
    "redis",
    "qdrant",
    "object-store",
    "jaeger",
    "otel-collector",
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
        env={**os.environ, "COMPOSE_INTERACTIVE_NO_CLI": "1"},
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
            rendered = json.loads(output)
        except json.JSONDecodeError:
            errors.append(f"{compose}: config --format json did not return JSON")
            continue
        errors.extend(_validate_rendered_services(compose, rendered))
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
    ):
        if not required_file.is_file():
            errors.append(f"{required_file.relative_to(ROOT)}: required observability config is absent")

    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print("PASS: canonical Compose topology is statically complete; runtime was not started")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
