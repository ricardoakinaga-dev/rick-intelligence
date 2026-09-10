#!/usr/bin/env python3
"""Generate non-authoritative review pointers and verify preserved sidecar history."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import os

try:  # Package import for module execution; script-directory fallback for direct execution.
    from scripts.state_of_art.archive_controller import digest, scoped_path
    from scripts.state_of_art.json_boundary import load_json
except ImportError:  # pragma: no cover - exercised by direct script execution.
    from archive_controller import digest, scoped_path
    from json_boundary import load_json


MAX_CONTROL_STATE_BYTES = 32 * 1024 * 1024


def expected_views(root: Path) -> dict[str, str]:
    state = load_json(root / ".agent/state.json")
    backlog = load_json(root / ".agent/backlog.json")
    view = {
        "schema_version": "derived-task-view.v1",
        "authoritative": False,
        "source_state": ".agent/state.json",
        "source_backlog": ".agent/backlog.json",
        "source_revision": state["state_revision"],
        "goal": state["goal"],
        "active_task": state["active_task"],
        "active_action_id": state["active_action_id"],
        "tasks": [{key: item[key] for key in ("id", "status", "dependencies", "owner", "next_action")}
                  for item in backlog["items"]],
        "notes": "Derived task graph only; live agent status comes from tool handles, not this file.",
    }
    pointer = {"schema_version": "review-run-reference.v1", "authoritative": False,
               "active_run": ".gauntlet/state.json", "frozen_bar": ".gauntlet/bar.json",
               "historical_reports": ".gauntlet-state-of-art/reports",
               "archive_manifest": ".review-control-history/manifest.json",
               "notes": "Historical scoped judgments are not imported as full-criterion approval."}
    render = lambda value: json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    return {
        ".orchestrate/state.json": render(view),
        ".orchestrate-state-of-art/state.json": render(view),
        ".gauntlet-state-of-art/state.json": render(pointer),
        ".gauntlet/state.md": "# Current Gauntlet run\n\n"
            "See `progress.md` and `state.json` in this directory for the active full AAA run.\n"
            "The prior phase16 state.md is preserved in\n"
            "`.review-control-history/phase16-gauntlet/state.md` from repository root.\n",
        ".gauntlet-state-of-art/state.md": "# Active review control\n\n"
            "The canonical run is `.gauntlet/state.json`; its frozen bar is `.gauntlet/bar.json`.\n"
            "Original phase16 and unvalidated AAA pointers are preserved by\n"
            "`.review-control-history/manifest.json`. Scoped reports remain under\n"
            "`.gauntlet-state-of-art/reports/`; they are not full-product approvals.\n"
            "Task status comes only from `.agent/backlog.json`.\n",
    }


def verify_history(root: Path) -> int:
    manifest = load_json(scoped_path(root, ".review-control-history/manifest.json"))
    entries = manifest["files"]
    if manifest.get("schema_version") != 1 or not isinstance(entries, list) or not entries:
        raise ValueError("invalid review history manifest")
    seen = set()
    for entry in entries:
        relative = Path(entry["archived"])
        if not relative.parts or relative.parts[0] != ".review-control-history" or str(relative) in seen:
            raise ValueError("invalid or duplicate review history path")
        seen.add(str(relative))
        if digest(scoped_path(root, relative)) != entry["sha256"]:
            raise ValueError("review history digest mismatch")
    actual = {str(p.relative_to(root)) for p in (root / ".review-control-history").rglob("*")
              if p.is_file() and p != root / ".review-control-history/manifest.json"}
    if actual != seen:
        raise ValueError("review history inventory mismatch")
    return len(entries)


def verify_bar(root: Path) -> None:
    original_path = root / ".gauntlet-state-of-art/bar.json"
    original = load_json(original_path)
    canonical = load_json(root / ".gauntlet-state-of-art/bar.canonical.json")
    actual = load_json(root / ".gauntlet/bar.json")
    if actual != canonical or canonical["goal"] != original["goal"] or len(canonical["criteria"]) != len(original["criteria"]):
        raise ValueError("frozen bar differs from canonical recovery")
    goal = (root / ".gauntlet-state-of-art/goal.txt").read_text().strip()
    state = load_json(root / ".gauntlet/state.json", maximum_bytes=MAX_CONTROL_STATE_BYTES)
    if state["goal"] != {"text": goal, "sha256": hashlib.sha256(goal.encode()).hexdigest()}:
        raise ValueError("active run goal differs from the original request")
    for old, new in zip(original["criteria"], canonical["criteria"]):
        for key, mapped in (("id", "id"), ("target", "target"), ("required", "required"),
                            ("severity", "priority"), ("evidence", "evidence_method")):
            if old[key] != new[mapped]:
                raise ValueError("original acceptance criterion changed during schema recovery")
        if new["snapshot_sha256"] != digest(original_path):
            raise ValueError("criterion source digest mismatch")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--write", action="store_true", help="regenerate derived views after canonical state changes")
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        count = verify_history(root)
        for relative, content in expected_views(root).items():
            path = scoped_path(root, relative)
            if args.write:
                path.parent.mkdir(parents=True, exist_ok=True)
                descriptor, temporary = tempfile.mkstemp(prefix=".view-", dir=path.parent)
                try:
                    with os.fdopen(descriptor, "w") as stream:
                        stream.write(content)
                    os.replace(temporary, path)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
            elif path.read_text() != content:
                raise ValueError(f"stale derived view: {relative}")
        if not args.write:
            verify_bar(root)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"FAIL: {exc}")
        return 1
    print(f"PASS: derived review views and {count} historical files verified" +
          ("; frozen bar check deferred until initialization" if args.write else "; original acceptance preserved"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
