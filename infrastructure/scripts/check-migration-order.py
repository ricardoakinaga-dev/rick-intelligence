#!/usr/bin/env python3
"""Offline migration filename/checksum sanity check; no Postgres connection."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from migrate import OPERATION_REPAIR_NAME, OPERATION_REPAIR_SHA256, migration_files


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    try:
        rows = migration_files(args.directory)
    except (OSError, ValueError) as exc:
        print(f"migration: {exc}", file=sys.stderr)
        return 2
    for version, path, digest in rows:
        print(f"{version} {path.name} sha256:{digest}")
    if any(version == "0004" for version, _path, _digest in rows):
        print(f"repair {OPERATION_REPAIR_NAME} sha256:{OPERATION_REPAIR_SHA256}")
    print(f"migration filenames: PASS ({len(rows)} file(s)); execution: NOT_RUN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
