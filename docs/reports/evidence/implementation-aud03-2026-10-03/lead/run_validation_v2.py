"""Lead-owned evidence runner v2; records commands, effective environment and scoped source hashes.

Unlike v1 (preserved alongside), this runner does not force PYTHONDONTWRITEBYTECODE:
the launched command inherits the caller's setting unless --no-bytecode is passed.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
RECORDED = ("PYTHONPATH", "PYTHONDONTWRITEBYTECODE")


def hashes(scopes: list[str]) -> dict[str, str]:
    result = {}
    for scope in scopes:
        source = ROOT / scope
        explicit_file = source.is_file()
        files = [source] if explicit_file else list(source.rglob("*"))
        for path in files:
            if not path.is_file() or (not explicit_file and path.name != "Makefile" and path.suffix not in {".py", ".ts", ".tsx", ".json", ".jsonl", ".yml", ".yaml", ".cjs", ".in", ".lock", ".sql", ".toml"}):
                continue
            if any(part in {"node_modules", "__pycache__", ".next", "test-results", "coverage"} for part in path.parts):
                continue
            result[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return dict(sorted(result.items()))


def effective(command: list[str], env: dict[str, str]) -> dict[str, str | None]:
    """Apply a leading `env [-u NAME]... [NAME=VALUE]...` prefix to the launcher environment."""
    result = dict(env)
    if command[:1] == ["env"]:
        args = iter(command[1:])
        for arg in args:
            if arg == "-u":
                result.pop(next(args, ""), None)
            elif arg.startswith("--unset="):
                result.pop(arg.split("=", 1)[1], None)
            elif "=" in arg and not arg.startswith("-"):
                key, value = arg.split("=", 1)
                result[key] = value
            else:
                break
    return {key: result.get(key) for key in RECORDED}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--scope", action="append", default=[])
    parser.add_argument("--no-bytecode", action="store_true",
                        help="explicitly set PYTHONDONTWRITEBYTECODE=1 for the launched command")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not args.name.replace("-", "").isalnum():
        parser.error("name must be alphanumeric with optional hyphens")
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("command required")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), str(ROOT / "apps/api/src"),
        str(ROOT / "apps/api/tests"), str(ROOT / "apps/worker"),
        *[str(path) for path in sorted((ROOT / "packages").glob("*/src"))]])
    if args.no_bytecode:
        env["PYTHONDONTWRITEBYTECODE"] = "1"
    start = datetime.datetime.now(datetime.timezone.utc).isoformat()
    before = hashes(args.scope)
    with (OUT / (args.name + ".log")).open("w") as stream:
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT)
    after = hashes(args.scope)
    record = {"runner": "run_validation_v2.py", "command": command, "cwd": str(ROOT),
        "pythonpath": env["PYTHONPATH"],
        "launcher_environment": {key: env.get(key) for key in RECORDED},
        "effective_environment": effective(command, env),
        "started_at": start, "finished_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "exit_code": result.returncode, "before_hashes": before, "after_hashes": after,
        "source_unchanged": before == after, "log": args.name + ".log"}
    (OUT / (args.name + ".command.json")).write_text(json.dumps(record, indent=2) + "\n")
    print((OUT / (args.name + ".log")).read_text()[-6500:])
    print(json.dumps({"exit_code": result.returncode, "source_unchanged": before == after,
        "source_count": len(before), "evidence": str(OUT / (args.name + ".command.json"))}))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
