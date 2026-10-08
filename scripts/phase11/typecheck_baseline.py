#!/usr/bin/env python3
"""Gradual Python type check driven by the versioned mypy baseline (AUD07-17).

The baseline (docs/baselines/mypy-baseline.txt) is the single explicit
declaration of coverage and of tolerated error counts. A package is type-checked
only because its source directory appears there and in mypy.ini `files`;
an error above the recorded limit fails `make typecheck` (and therefore
`make ci`), while a result below the limit is reported so the limit can be
lowered — never raised silently.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "docs" / "baselines" / "mypy-baseline.txt"
CONFIG = ROOT / "mypy.ini"
ERROR_LINE = re.compile(r"^(?P<path>\S+?):\d+: error: ")


def parse_baseline(text: str, source: str) -> tuple[list[tuple[str, int]], list[str]]:
    """Parse ``<dir> = <max errors>`` entries; ``#`` starts a comment."""
    entries: list[tuple[str, int]] = []
    errors: list[str] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        path, sep, value = line.partition("=")
        if not sep:
            errors.append(f"{source}:{lineno}: expected '<directory> = <max errors>'")
            continue
        path, value = path.strip(), value.strip()
        try:
            limit = int(value)
        except ValueError:
            errors.append(f"{source}:{lineno}: max errors must be an integer, got {value!r}")
            continue
        if not path or limit < 0:
            errors.append(f"{source}:{lineno}: invalid entry {raw.strip()!r}")
            continue
        entries.append((path, limit))
    return entries, errors


def count_errors(lines: Iterable[str], roots: Sequence[str]) -> tuple[dict[str, int], list[str]]:
    """Map mypy error lines onto baseline roots (longest prefix wins)."""
    ordered = sorted(roots, key=len, reverse=True)
    counts = {root: 0 for root in roots}
    unmatched: list[str] = []
    for line in lines:
        match = ERROR_LINE.match(line)
        if not match:
            continue
        path = match.group("path")
        for root in ordered:
            if path == root or path.startswith(root.rstrip("/") + "/"):
                counts[root] += 1
                break
        else:
            unmatched.append(line)
    return counts, unmatched


def run_mypy(roots: Sequence[str]) -> tuple[int, list[str]]:
    """Run mypy over ``roots`` with the canonical config; return code + output."""
    command = [
        sys.executable, "-m", "mypy",
        "--config-file", str(CONFIG),
        "--no-error-summary", "--no-pretty",
        *roots,
    ]
    completed = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, check=False,
    )
    output = [line for line in completed.stdout.splitlines() if line.strip()]
    if completed.returncode not in (0, 1):
        detail = completed.stderr.strip() or completed.stdout.strip()
        output.append(f"mypy terminou com exit {completed.returncode}: {detail}")
        return 2, output
    return completed.returncode, output


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    baseline_path = Path(argv[0]) if argv else BASELINE
    try:
        source = str(baseline_path.relative_to(ROOT))
    except ValueError:
        source = str(baseline_path)
    try:
        text = baseline_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"FAIL: baseline indisponível: {exc}")
        return 1

    entries, errors = parse_baseline(text, source)
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    if not entries:
        print(f"FAIL: {source} declara cobertura vazia")
        return 1

    roots = [path for path, _ in entries]
    missing = [path for path in roots if not (ROOT / path).is_dir()]
    if missing:
        for path in missing:
            print(f"FAIL: {source}: diretório inexistente: {path}")
        return 1
    if not CONFIG.is_file():
        print(f"FAIL: configuração ausente: {CONFIG.relative_to(ROOT)}")
        return 1

    exit_code, output = run_mypy(roots)
    if exit_code == 2:
        for line in output:
            print(f"FAIL: {line}")
        return 1

    counts, unmatched = count_errors(output, roots)
    failures = [
        f"erro mypy fora da cobertura declarada: {line}" for line in unmatched
    ]
    for path, limit in entries:
        actual = counts[path]
        if actual > limit:
            failures.append(f"{path}: {actual} erro(s) mypy, baseline aceita {limit}")
        elif actual < limit:
            print(f"AVISO: {path}: {actual} erro(s) < baseline {limit} — rebaixe a linha do baseline")

    for line in output:
        print(line)
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        print(f"FAIL: type checking gradual ({source}): {sum(counts.values())} erro(s) "
              f"cobertos, {len(failures)} violação(ões) de baseline")
        return 1
    print(f"PASS: type checking gradual — " + ", ".join(
        f"{path}={counts[path]}/{limit}" for path, limit in entries
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
