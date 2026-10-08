#!/usr/bin/env python3
"""Materialize the retired legacy sources as a read-only differential reference.

The three retired components (`cvg-master-rag-v2`, `rick-professor`,
`modulo-redis-locker`) are no longer part of the checkout, but the differential
lanes still need their implementations to prove that the canonical root code
matches what they replaced. This script extracts the legacy tree from the git
object store into `.runtime/legacy-reference/` — a generated, gitignored
directory — so the comparison stays reproducible from a single SHA.

Because AUD07-02 removed `cvg-master-rag-v2` from `HEAD`, the reference is read
from `SOURCE_REF`: the last commit that still contained it (`8c35b1f^`).
History is immutable, so a clean checkout of any later commit can rebuild the
same bytes; nothing retired returns to the working tree.

Exit codes: 0 extracted (or already current), 1 failure, 2 reference not in
this repository's history.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DESTINATION = ROOT / ".runtime" / "legacy-reference"
LEGACY_COMPONENT = "cvg-master-rag-v2"
REF_SUFFIX = ".aud07-ref"
SOURCE_REF = "b52f32c141916a2ea3af1a6b913bd91f380606e0"


def resolve_ref(ref: str) -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    if completed.returncode:
        return None
    return completed.stdout.strip() or None


def component_in_ref(ref: str) -> bool:
    completed = subprocess.run(
        ["git", "ls-tree", "-d", "--name-only", ref, "--", LEGACY_COMPONENT],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    return completed.returncode == 0 and LEGACY_COMPONENT in completed.stdout.split()


def _read_marker(destination: Path) -> str:
    marker = destination / f"{LEGACY_COMPONENT}{REF_SUFFIX}"
    try:
        return marker.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _write_marker(destination: Path, sha: str) -> None:
    marker = destination / f"{LEGACY_COMPONENT}{REF_SUFFIX}"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(sha + "\n", encoding="utf-8")


def extract(destination: Path) -> int:
    sha = resolve_ref(SOURCE_REF)
    if not sha:
        print(
            "FAIL: SOURCE_REF does not resolve; cannot materialize the legacy reference",
            file=sys.stderr,
        )
        return 1
    if not component_in_ref(sha):
        print(
            f"FAIL: {LEGACY_COMPONENT} is absent from {sha}; this repository cannot rebuild "
            "the differential reference",
            file=sys.stderr,
        )
        return 2
    if _read_marker(destination) == sha and (destination / LEGACY_COMPONENT / "src").is_dir():
        print(f"PASS: legacy reference already current at {sha}")
        return 0

    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="legacy-ref-") as scratch:
        completed = subprocess.run(
            ["git", "archive", sha, LEGACY_COMPONENT],
            cwd=ROOT, capture_output=True, check=False,
        )
        if completed.returncode:
            print(f"FAIL: git archive {LEGACY_COMPONENT}: {completed.stderr.decode()}", file=sys.stderr)
            return 1
        subprocess.run(["tar", "-x"], cwd=scratch, input=completed.stdout, check=True)
        staged = Path(scratch) / LEGACY_COMPONENT
        if not staged.is_dir():
            print(f"FAIL: archive produced no {LEGACY_COMPONENT} directory", file=sys.stderr)
            return 1
        target = destination / LEGACY_COMPONENT
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(staged), str(target))
        _write_marker(destination, sha)
    print(f"PASS: materialized {LEGACY_COMPONENT} from {sha} into {destination}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--check", action="store_true", help="report status without extracting")
    args = parser.parse_args(argv)
    if args.check:
        source = resolve_ref(SOURCE_REF)
        current = _read_marker(args.destination)
        ready = (
            bool(source)
            and current == source
            and (args.destination / LEGACY_COMPONENT / "src").is_dir()
        )
        print(
            f"legacy reference ready={ready} marker={current or 'none'} "
            f"source={source or 'unresolved'}"
        )
        return 0 if ready else 1
    return extract(args.destination)


if __name__ == "__main__":
    raise SystemExit(main())
