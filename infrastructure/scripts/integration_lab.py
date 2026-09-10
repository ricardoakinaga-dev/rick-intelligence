#!/usr/bin/env python3
"""Scoped local dependency laboratory. No production startup or volume deletion."""

from __future__ import annotations

import argparse
from hashlib import sha256
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "rick-rec-local-" + sha256(str(ROOT.resolve()).encode("utf-8")).hexdigest()[:10]
COMPOSE = ROOT / "infrastructure/compose/compose.integration.yml"
SECRETS = (
    "REC_POSTGRES_PASSWORD", "REC_S3_ACCESS_KEY", "REC_S3_SECRET_KEY",
    "REC_QDRANT_API_KEY", "REC_OIDC_ADMIN_PASSWORD",
)
PORTS = (15432, 19000, 19001, 16333, 18080)


class LabError(RuntimeError):
    pass


def environment(source: dict[str, str]) -> dict[str, str]:
    """Allow only required local settings; no ambient Docker remote context/LLM key."""
    values = {name: source[name] for name in ("PATH", "HOME", "XDG_RUNTIME_DIR") if name in source}
    values.update({name: source[name] for name in SECRETS if name in source})
    values["COMPOSE_DISABLE_ENV_FILE"] = "1"
    return values


def check_secrets(values: dict[str, str]) -> None:
    for name in SECRETS:
        value = values.get(name, "")
        if not value or value != value.strip() or len(value) < 12 or len(value) > 256 or any(ord(c) < 32 for c in value):
            raise LabError(f"Configure {name}: 12–256 visible characters, no surrounding whitespace")


def command(action: str) -> list[str]:
    arguments = {
        "preflight": ["config", "--quiet"],
        "start": ["up", "-d"],
        "status": ["ps", "--services", "--status", "running"],
        "stop": ["stop"],
    }
    if action not in arguments:
        raise LabError("Unsupported laboratory action")
    # Pin the local Unix socket: an ambient remote context must never be used.
    return ["docker", "--host", "unix:///var/run/docker.sock", "compose", "--env-file", "/dev/null",
            "--project-name", PROJECT, "--file", str(COMPOSE), *arguments[action]]


def run(action: str, *, source: dict[str, str] | None = None) -> tuple[str, ...]:
    values = environment(dict(os.environ) if source is None else source)
    check_secrets(values)
    if shutil.which("docker", path=values.get("PATH")) is None:
        raise LabError("Docker/Compose unavailable; install locally before integration")
    try:
        for args in (["docker", "--host", "unix:///var/run/docker.sock", "info", "--format", "{{.ServerVersion}}"], command("preflight")):
            result = subprocess.run(args, cwd=ROOT, env=values, capture_output=True, text=True, timeout=30)
            if result.returncode:
                raise LabError("Local Docker/Compose preflight failed; check installation, socket permission and configuration locally")
        if action != "preflight":
            result = subprocess.run(command(action), cwd=ROOT, env=values, capture_output=True, text=True, timeout=300)
            if result.returncode:
                raise LabError("Laboratory action failed; no service readiness inferred")
            if action == "status":
                allowed = {"postgres", "object-store", "qdrant", "identity"}
                return tuple(sorted(set(result.stdout.splitlines()) & allowed))
    except subprocess.TimeoutExpired:
        raise LabError("Laboratory command timed out; inspect its state before retrying") from None
    except OSError:
        raise LabError("Cannot execute local Docker/Compose") from None
    return ()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preflight", "start", "status", "stop"))
    args = parser.parse_args()
    try:
        running = run(args.action)
    except LabError as error:
        # Fixed messages/names only; never echo subprocess stderr or env values.
        print(f"BLOCKED: {error}", file=sys.stderr)
        return 2
    if args.action == "status":
        print("Running containers: " + (", ".join(running) or "none"))
    print(f"{PROJECT}: {args.action} command completed; API/OIDC journeys and readiness NOT_VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
