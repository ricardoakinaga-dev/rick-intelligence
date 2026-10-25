"""Load an explicitly selected, already running canonical dev lab in memory.

No secret is printed or copied into an artifact. Only the canonical project is
inspected, plus a provider fixture container explicitly named by the caller.
This is a local probe convenience, never a production composition or launcher.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
from urllib.parse import urlsplit, urlunsplit

from scripts.state_of_art.runtime_preflight import canonical_compose_project


def replace_url_host(raw: str, address: str) -> str:
    parsed = urlsplit(raw)
    userinfo, separator, _authority = parsed.netloc.rpartition("@")
    host = f"[{address}]" if ":" in address else address
    netloc = (userinfo + "@" if separator else "") + host
    if parsed.port is not None:
        netloc += f":{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def _inspect(name: str) -> dict:
    result = subprocess.run(["docker", "--host", "unix:///var/run/docker.sock", "inspect", name],
                            capture_output=True, timeout=15, check=False)
    if result.returncode:
        raise ValueError("local_lab_container_unavailable")
    payload = json.loads(result.stdout)
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise ValueError("invalid_container_inventory")
    if payload[0].get("State", {}).get("Running") is not True:
        raise ValueError("local_lab_container_not_running")
    return payload[0]


def from_dev_compose(root: Path, *, provider_container: str) -> dict[str, str]:
    if not provider_container or provider_container.startswith("-") or "/" in provider_container:
        raise ValueError("explicit_provider_fixture_container_required")
    project = canonical_compose_project(root, "docker-compose.dev.yml")
    inventory = {}
    for service in ("api", "worker", "postgres", "redis", "qdrant", "object-store"):
        item = _inspect(f"{project}-{service}-1")
        labels = item.get("Config", {}).get("Labels", {})
        if labels.get("com.docker.compose.project") != project or labels.get("com.docker.compose.service") != service:
            raise ValueError("container_project_mismatch")
        inventory[service] = item
    inventory[provider_container] = _inspect(provider_container)
    api = inventory["api"]
    environment = dict(item.split("=", 1) for item in api["Config"]["Env"] if "=" in item)
    if environment.get("RICK_ENV") not in {"dev", "local", "test"}:
        raise ValueError("local_lab_refuses_production")
    selected = {key: value for key, value in environment.items()
                if key.startswith(("RICK_", "LLM_", "EMBEDDING_", "SESSION_", "CORS_"))}
    worker = dict(item.split("=", 1) for item in inventory["worker"]["Config"]["Env"] if "=" in item)
    dimension = worker.get("EMBEDDING_DIMENSION")
    if not dimension or (selected.get("EMBEDDING_DIMENSION") not in {None, dimension}):
        raise ValueError("api_worker_embedding_dimensions_differ")
    selected["EMBEDDING_DIMENSION"] = dimension
    api_networks = set(api["NetworkSettings"]["Networks"])
    for key in ("RICK_EXTERNAL_DATABASE_DSN", "RICK_REDIS_URL", "RICK_QDRANT_URL",
                "RICK_OBJECT_STORE_ENDPOINT", "LLM_BASE_URL", "EMBEDDING_BASE_URL"):
        if not selected.get(key):
            continue
        parsed = urlsplit(selected[key])
        if parsed.hostname not in inventory:
            # Literal loopback/private URLs still face the probe's local-only
            # target policy. Unknown DNS names are never resolved implicitly.
            continue
        networks = inventory[parsed.hostname]["NetworkSettings"]["Networks"]
        common = sorted(set(networks) & api_networks)
        # The fixture may live on a separate local bridge. This access is
        # allowed only by the probe's explicit private-container opt-in.
        choices = common or sorted(networks)
        if not choices:
            raise ValueError("local_lab_network_unavailable")
        address = networks[choices[0]].get("IPAddress")
        if not address:
            raise ValueError("local_lab_address_unavailable")
        selected[key] = replace_url_host(selected[key], address)
    return selected
