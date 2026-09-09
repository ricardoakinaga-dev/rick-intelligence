#!/usr/bin/env python3
"""Validate the canonical Compose topology without starting containers."""

from __future__ import annotations

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
        code, output = run(compose, env_file, "config", "--quiet")
        if code != 0:
            errors.append(f"{compose}: config --quiet failed: {output}")
            continue
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
