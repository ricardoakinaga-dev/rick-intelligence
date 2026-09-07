#!/usr/bin/env python3
"""Validate a declared backup/restore evidence manifest without services."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REQUIRED = ("backup_id", "created_at", "components", "restore_target", "operator", "status")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    try:
        payload = json.loads(args.manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"invalid manifest: {exc}", file=sys.stderr)
        return 2
    if not isinstance(payload, dict) or any(not payload.get(key) for key in REQUIRED):
        print("manifest requires backup_id, created_at, components, restore_target, operator, status", file=sys.stderr)
        return 2
    status = payload["status"]
    if status not in {"PASS", "NOT_RUN", "BLOCKED"}:
        print("status must be PASS, NOT_RUN, or BLOCKED", file=sys.stderr)
        return 2
    print(f"backup manifest shape: PASS; declared status: {status}; restore execution: NOT_RUN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
