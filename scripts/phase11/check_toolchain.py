#!/usr/bin/env python3
"""Reject service-image drift from the declared current Compose and lab versions.

AUD07-04 retired the Phase 0.6 CI lane together with the legacy components, so
the historical `historical_ci_images` block and its `QDRANT_IMAGE`/`REDIS_IMAGE`
comparison went with it: those pins now exist only in git history. Current
Compose images and the canonical lab versions stay enforced.
"""

from __future__ import annotations

import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILES = ("docker-compose.dev.yml", "docker-compose.staging.yml")
IMAGE_PATTERN = re.compile(r"^\s+image:\s*['\"]?([^\s'\"#]+)", re.MULTILINE)


def check_images(source: str, text: str, expected: dict[str, str]) -> list[str]:
    """Require each declared image tag and reject every divergent occurrence."""
    found = {service: [] for service in expected}
    for image in IMAGE_PATTERN.findall(text):
        for service, prefix in (("qdrant", "qdrant/qdrant:"), ("redis", "redis:")):
            if image.startswith(prefix) and service in found:
                found[service].append(image)
    errors = []
    for service, wanted in expected.items():
        if not found[service]:
            errors.append(f"{source}: {service} image is missing")
        for image in found[service]:
            if image != wanted:
                errors.append(f"{source}: {service} image {image} differs from {wanted}")
    return errors


def check_toolchain(root: Path = ROOT) -> list[str]:
    """Compare current Compose and the inventoried historical CI lane."""
    toolchain = json.loads((root / "toolchain.json").read_text())
    services = toolchain["services"]
    current = {
        "qdrant": f"qdrant/qdrant:v{services['qdrant']}",
        "redis": f"redis:{services['redis']}-alpine",
    }
    errors = []
    lab = toolchain["canonical_lab_services"]
    for service, expected in (("qdrant", f"v{services['qdrant']}"), ("redis", services["redis"])):
        if lab.get(service) != expected:
            errors.append(f"toolchain.json: canonical_lab_services.{service} differs from services.{service}")
    for source in COMPOSE_FILES:
        errors.extend(check_images(source, (root / source).read_text(), current))
    return errors


def main() -> int:
    errors = check_toolchain()
    for error in errors:
        print(f"FAIL: {error}")
    if errors:
        return 1
    print("PASS: current Compose and historical CI service images match toolchain.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
