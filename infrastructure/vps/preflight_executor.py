#!/usr/bin/env python3
"""Diagnose executor compatibility without changing ownership/security policy.

This is not a deployment/readiness gate. Only a synthetic private input is read
by the real capture boundary; no service, privilege change or user config is used.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import tempfile

try:
    from .contracts import Refusal, capture
except ImportError:  # Direct script invocation, as with the installer utilities.
    from contracts import Refusal, capture


def inspect_executor(work_dir: Path | None = None) -> dict:
    result = {
        "schema": "rick.vps.executor-preflight/v1",
        "status": "BLOCKED_EXTERNAL",
        "lane_status": "NOT_RUN",
        "euid": os.geteuid(),
        "egid": os.getegid(),
        "capture": "NOT_RUN",
        "parent_metadata": [],
        "limitations": "A successful diagnostic is not the VPS test lane or production authorization. No chmod/chown, capabilities or namespace changes are performed.",
    }
    try:
        # TemporaryDirectory owns only this freshly created synthetic directory.
        # Verify containment before its context manager performs cleanup.
        parent = (work_dir or Path(tempfile.gettempdir())).resolve(strict=True)
        with tempfile.TemporaryDirectory(prefix="rick-vps-probe-", dir=parent) as temporary:
            directory = Path(temporary)
            assert directory.resolve().parent == parent and not directory.is_symlink()
            path = directory / "synthetic-private-input"
            payload = b"rick-executor-synthetic-input\n"
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
            for ancestor in reversed(path.parents):
                info = ancestor.stat()
                result["parent_metadata"].append({
                    "path": str(ancestor) if ancestor != directory else "<synthetic-private-directory>",
                    "uid": info.st_uid, "gid": info.st_gid,
                    "mode": oct(stat.S_IMODE(info.st_mode)),
                    "sticky": bool(info.st_mode & stat.S_ISVTX),
                })
            try:
                observed = capture(path, private=True)
                if observed != payload:
                    raise Refusal("synthetic capture bytes differ")
            except Refusal as error:
                result["capture"] = "REFUSED"
                result["reason"] = str(error)
            else:
                result["status"] = "PASS"
                result["capture"] = "PASS"
                result["reason"] = "synthetic private input passed the unchanged real capture boundary"
            assert directory.resolve().parent == parent and not directory.is_symlink()
    except (OSError, AssertionError):
        result["reason"] = "synthetic input directory is unavailable or its containment changed"
    result["next_action"] = (
        "Run the complete VPS positive and negative lane on this executor; this probe alone does not satisfy PROD12-003."
        if result["status"] == "PASS" else
        "Provide an authorized disposable Linux executor with representative mapped ownership and root-owned sticky parents; preserve all capture guards. Do not repair the host DAC to manufacture a pass."
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, help="Existing directory for a synthetic private probe; no user input is captured")
    args = parser.parse_args()
    result = inspect_executor(args.work_dir)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
