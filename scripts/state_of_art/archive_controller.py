#!/usr/bin/env python3
"""Archive the v1 controller without rewriting decisions or overwriting history."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil


def digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"expected a regular file: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scoped_path(root: Path, relative: str | Path) -> Path:
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("path escapes archive scope")
    target = root / relative
    current = target
    while current != root:
        if current.is_symlink():
            raise ValueError("symlink in controller archive path")
        current = current.parent
    return target


def archive(root: Path) -> dict:
    destination = scoped_path(root, ".agent/legacy-v1")
    if destination.is_symlink():
        raise ValueError("archive must not be a symlink")
    sources = [root / ".agent" / name for name in (
        "state.json", "backlog.json", "execution-log.jsonl", "verification.jsonl", "PLANS.md",
    )]
    sources += sorted((root / ".agent/gates").glob("*.json"))
    sources += sorted((root / ".agent/plans").glob("*.md"))
    entries = []
    for source in sources:
        scoped_path(root, source.relative_to(root))
        relative = source.relative_to(root / ".agent")
        target = scoped_path(root, Path(".agent/legacy-v1") / relative)
        checksum = digest(source)
        if target.exists() and digest(target) != checksum:
            raise ValueError(f"refusing to overwrite archived history: {relative}")
        entries.append({"original": str(source.relative_to(root)),
                        "archived": str(target.relative_to(root)), "sha256": checksum})
    manifest = {"schema_version": 1, "purpose": "immutable pre-v2 controller history", "files": entries}
    manifest_path = destination / "manifest.json"
    if manifest_path.exists() and json.loads(manifest_path.read_text()) != manifest:
        raise ValueError("archive manifest already exists with different sources")
    for entry in entries:
        target = root / entry["archived"]
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(root / entry["original"], target)
        if digest(target) != entry["sha256"]:
            raise ValueError("archive copy checksum mismatch")
    if not manifest_path.exists():
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def verify(root: Path) -> int:
    manifest = json.loads(scoped_path(root, ".agent/legacy-v1/manifest.json").read_text())
    entries = manifest.get("files")
    if manifest.get("schema_version") != 1 or not isinstance(entries, list) or not entries:
        raise ValueError("invalid archive manifest")
    seen = set()
    for entry in entries:
        relative = Path(entry["archived"])
        if relative.is_absolute() or ".." in relative.parts or relative.parts[:2] != (".agent", "legacy-v1"):
            raise ValueError("archive path escapes scope")
        if str(relative) in seen:
            raise ValueError("duplicate archive entry")
        seen.add(str(relative))
        if digest(scoped_path(root, relative)) != entry["sha256"]:
            raise ValueError(f"archive integrity failure: {relative}")
    actual = {str(path.relative_to(root)) for path in (root / ".agent/legacy-v1").rglob("*")
              if path.is_file() and path.name != "manifest.json"}
    if actual != seen:
        raise ValueError("archive inventory differs from the manifest")
    return len(entries)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--archive", action="store_true", help="copy originals; never overwrite history")
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        if args.archive:
            archive(root)
        count = verify(root)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"FAIL: {exc}")
        return 1
    print(f"PASS: {count} historical files match their recorded SHA256")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
