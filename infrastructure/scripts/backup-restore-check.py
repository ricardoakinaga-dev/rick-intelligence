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
    if args.manifest.is_dir():
        try:
            from backup_restore import verify_backup

            report = verify_backup(args.manifest)
        except Exception:
            print("backup payload verification failed", file=sys.stderr)
            return 2
        print(
            f"backup payload: PASS; backup_id={report['backup_id']}; "
            f"files={report['file_count']}; bytes={report['byte_count']}"
        )
        return 0
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
