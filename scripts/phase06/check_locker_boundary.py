#!/usr/bin/env python3
"""Enforce the Redis Locker's private deployment boundary.

The check intentionally has no third-party runtime dependency.  PyYAML is
used when it is available for structural validation; a conservative textual
fallback keeps the check runnable in a bare Python installation.  The check
is for deployment examples, not for the Locker's application listener: the
container may listen on its private service interface, but its host exposure
must be controlled by the deployment boundary.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATHS = (
    ROOT / "rick-professor" / "deploy" / "docker-compose.example.yml",
    ROOT / "modulo-redis-locker" / "README.md",
)

LOCKER_NAME_RE = re.compile(r"(?:^|[-_])locker(?:$|[-_])", re.IGNORECASE)
PROXY_MARKERS = ("traefik", "nginx", "caddy", "haproxy", "ingress", "reverse-proxy")


@dataclass(frozen=True)
class Finding:
    path: Path
    message: str


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _is_locker_name(value: object) -> bool:
    normalized = str(value).strip().lower().replace("_", "-")
    return bool(LOCKER_NAME_RE.search(normalized)) or normalized == "locker"


def _is_true(value: object) -> bool:
    return value is True or str(value).strip().lower() in {"true", "yes", "on", "1"}


def _walk_strings(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _walk_strings(key)
            yield from _walk_strings(item)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _walk_strings(item)


def _network_names(value: object) -> list[str]:
    if isinstance(value, dict):
        return [str(name) for name in value]
    if isinstance(value, (list, tuple)):
        return [str(name) for name in value if isinstance(name, (str, int, float))]
    return []


def _locker_services(services: object) -> dict[str, dict[str, Any]]:
    if not isinstance(services, dict):
        return {}

    result: dict[str, dict[str, Any]] = {}
    for name, config in services.items():
        if not isinstance(config, dict):
            continue
        build = config.get("build")
        build_text = " ".join(_walk_strings(build)).lower()
        image_text = " ".join(_walk_strings(config.get("image"))).lower()
        if _is_locker_name(name) or "locker" in build_text or "locker" in image_text:
            result[str(name)] = config
    return result


def _check_compose_structured(path: Path, document: object) -> list[Finding]:
    findings: list[Finding] = []
    if not isinstance(document, dict):
        return [Finding(path, "Compose document must be a mapping")]

    services = document.get("services")
    if not isinstance(services, dict):
        return [Finding(path, "Compose document must declare a services mapping")]

    lockers = _locker_services(services)
    if not lockers:
        return [Finding(path, "no Locker service was found")]

    top_networks = document.get("networks")
    if not isinstance(top_networks, dict):
        top_networks = {}

    for service_name, service in lockers.items():
        service_label = f"service {service_name!r}"
        ports = service.get("ports")
        if ports not in (None, "", [], {}):
            findings.append(Finding(path, f"{service_label} publishes a host port via ports"))

        network_mode = str(service.get("network_mode", "")).strip().lower()
        if network_mode == "host" or network_mode.startswith("service:"):
            findings.append(Finding(path, f"{service_label} uses a host/shared network namespace"))

        if any("0.0.0.0" in value for value in _walk_strings(service)):
            findings.append(Finding(path, f"{service_label} exposes or binds 0.0.0.0"))

        for value in _walk_strings(service.get("labels")):
            lowered = value.lower()
            if any(marker in lowered for marker in PROXY_MARKERS):
                findings.append(Finding(path, f"{service_label} declares a proxy/ingress label: {value}"))

        service_networks = service.get("networks")
        network_names = _network_names(service_networks)
        if not network_names:
            findings.append(Finding(path, f"{service_label} must attach to a named private network"))
            continue

        for network_name in network_names:
            definition = top_networks.get(network_name)
            if not isinstance(definition, dict) or not _is_true(definition.get("internal")):
                findings.append(
                    Finding(
                        path,
                        f"{service_label} network {network_name!r} is not declared internal: true",
                    )
                )

    return findings


def _strip_yaml_comment(line: str) -> str:
    # Deployment examples do not use # inside quoted scalars for the fields
    # inspected here.  Keeping this conservative avoids treating comments as
    # service configuration in the fallback parser.
    return line.split(" #", 1)[0].rstrip()


def _fallback_service_blocks(text: str) -> dict[str, list[tuple[int, str]]]:
    lines = text.splitlines()
    services_start = next(
        (index for index, line in enumerate(lines) if line.strip() == "services:" and not line.startswith(" ")),
        None,
    )
    if services_start is None:
        return {}

    starts: list[tuple[int, str]] = []
    for index in range(services_start + 1, len(lines)):
        raw = _strip_yaml_comment(lines[index])
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        match = re.fullmatch(r"([A-Za-z0-9_.-]+):(?:\s.*)?", raw.strip())
        if indent == 2 and match:
            starts.append((index, match.group(1)))
        elif indent == 0 and raw.strip().endswith(":"):
            break

    blocks: dict[str, list[tuple[int, str]]] = {}
    for position, (start, name) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        blocks[name] = [(line_number + 1, _strip_yaml_comment(lines[line_number])) for line_number in range(start, end)]
    return blocks


def _fallback_service_networks(block: list[tuple[int, str]]) -> list[str]:
    lines = [line for _, line in block]
    in_networks = False
    names: list[str] = []
    for line in lines:
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))
        if indent == 4 and stripped == "networks:":
            in_networks = True
            continue
        if not in_networks:
            continue
        if indent <= 4:
            break
        if indent == 6 and stripped.startswith("-"):
            names.append(stripped[1:].strip().strip("'\""))
        elif indent == 6 and re.fullmatch(r"[A-Za-z0-9_.-]+:", stripped):
            names.append(stripped[:-1])
    return names


def _fallback_internal_networks(text: str) -> set[str]:
    lines = text.splitlines()
    networks_start = next(
        (index for index, line in enumerate(lines) if line.strip() == "networks:" and not line.startswith(" ")),
        None,
    )
    if networks_start is None:
        return set()

    internal: set[str] = set()
    current_name: str | None = None
    for line in lines[networks_start + 1 :]:
        raw = _strip_yaml_comment(line)
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if indent == 0:
            break
        if indent == 2:
            match = re.fullmatch(r"([A-Za-z0-9_.-]+):", raw.strip())
            current_name = match.group(1) if match else None
            continue
        if current_name and indent == 4 and re.fullmatch(r"internal:\s*(?:true|yes|on|1)", raw.strip(), re.IGNORECASE):
            internal.add(current_name)
    return internal


def _check_compose_fallback(path: Path, text: str) -> list[Finding]:
    findings: list[Finding] = []
    blocks = _fallback_service_blocks(text)
    lockers = {
        name: block
        for name, block in blocks.items()
        if _is_locker_name(name)
        or any(
            re.search(r"^\s{4,}(?:image|build):.*locker", line, re.IGNORECASE)
            for _, line in block
        )
    }
    if not lockers:
        return [Finding(path, "no Locker service was found (fallback YAML parser)")]

    internal_networks = _fallback_internal_networks(text)
    for service_name, block in lockers.items():
        service_label = f"service {service_name!r}"
        block_text = "\n".join(line for _, line in block)
        if re.search(r"^\s{4}ports:\s*", block_text, re.MULTILINE):
            findings.append(Finding(path, f"{service_label} publishes a host port via ports"))
        if re.search(r"^\s{4}network_mode:\s*(?:host|service:)", block_text, re.IGNORECASE | re.MULTILINE):
            findings.append(Finding(path, f"{service_label} uses a host/shared network namespace"))
        if "0.0.0.0" in block_text:
            findings.append(Finding(path, f"{service_label} exposes or binds 0.0.0.0"))
        if any(marker in block_text.lower() for marker in PROXY_MARKERS):
            findings.append(Finding(path, f"{service_label} declares a proxy/ingress marker"))
        network_names = _fallback_service_networks(block)
        if not network_names:
            findings.append(Finding(path, f"{service_label} must attach to a named private network"))
        else:
            for network_name in network_names:
                if network_name not in internal_networks:
                    findings.append(
                        Finding(
                            path,
                            f"{service_label} network {network_name!r} is not declared internal: true",
                        )
                    )
    return findings


def check_compose(path: Path) -> list[Finding]:
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError:
        return _check_compose_fallback(path, text)

    try:
        document = yaml.safe_load(text)
    except Exception as exc:  # noqa: BLE001 - report parse failures without hiding them
        return [Finding(path, f"YAML parse failed: {exc}")]
    return _check_compose_structured(path, document)


def check_readme(path: Path) -> list[Finding]:
    text = path.read_text(encoding="utf-8")
    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if re.search(r"(?:^|\s)-p\s+(?:\S+\s+)?(?:0\.0\.0\.0:)?\d+:3000\b", line):
            findings.append(Finding(path, f"line {line_number} publishes the Locker port with docker -p"))
        if "0.0.0.0" in line:
            findings.append(Finding(path, f"line {line_number} mentions an unrestricted 0.0.0.0 Locker binding"))

    if "--network modulo-redis-locker-private" not in text:
        findings.append(Finding(path, "Docker run example must use the private Locker network"))
    if "docker network create --internal modulo-redis-locker-private" not in text:
        findings.append(Finding(path, "Docker run example must create an internal network"))
    if "internal: true" not in text:
        findings.append(Finding(path, "Compose example must declare internal: true"))
    return findings


def check_path(path: Path) -> list[Finding]:
    if not path.exists():
        return [Finding(path, "file does not exist")]
    if path.suffix.lower() in {".yml", ".yaml"}:
        return check_compose(path)
    if path.name.lower() == "readme.md":
        return check_readme(path)
    return [Finding(path, "unsupported input; pass a Compose YAML or Locker README")]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, help="Compose/README paths; defaults to preserved deployment examples")
    args = parser.parse_args()
    paths = [path if path.is_absolute() else ROOT / path for path in (args.paths or DEFAULT_PATHS)]

    findings = [finding for path in paths for finding in check_path(path)]
    if findings:
        print("Locker boundary check failed:", file=sys.stderr)
        for finding in findings:
            print(f"- {_relative(finding.path)}: {finding.message}", file=sys.stderr)
        return 1

    print("Locker boundary check OK: deployment examples keep Locker private and unauthenticated only behind the application boundary.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
