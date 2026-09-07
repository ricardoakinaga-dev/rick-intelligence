#!/usr/bin/env python3
"""Offline migration filename/checksum sanity check; no Postgres connection."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re
import sys

PATTERN = re.compile(r"^(\d{4})_[a-z0-9][a-z0-9_-]*\.sql$")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    rows = []
    for path in sorted(args.directory.glob("*.sql")):
        match = PATTERN.fullmatch(path.name)
        if match is None:
            print(f"invalid migration filename: {path.name}", file=sys.stderr)
            return 2
        rows.append((int(match.group(1)), path))
    versions = [version for version, _ in rows]
    if len(versions) != len(set(versions)):
        print("duplicate migration version", file=sys.stderr)
        return 2
    for version, path in rows:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        print(f"{version:04d} {path.name} sha256:{digest}")
    print(f"migration filenames: PASS ({len(rows)} file(s)); execution: NOT_RUN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
