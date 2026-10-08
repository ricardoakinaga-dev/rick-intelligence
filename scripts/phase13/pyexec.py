#!/usr/bin/env python3
"""Re-execute a command under the canonical interpreter (AUD07-08).

Recipes that must see the hash-locked environment invoke this shim as
``python3 scripts/phase13/pyexec.py <argv...>``. The shim swaps only the
interpreter: the environment (including an explicit ``PYTHONPATH`` written by
the Makefile) is passed through unchanged, so a recipe's import surface is
exactly what it already declared. When no bootstrap venv exists, ``pyenv``
resolves to the current interpreter and the shim is a no-op, which keeps CI
images that install ``requirements/test.lock`` into their own interpreter
working without a bootstrap step.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
try:
    from scripts.phase13.pyenv import interpreter
except ModuleNotFoundError:  # Direct execution from the scripts/phase13 directory.
    sys.path.insert(0, str(ROOT))
    from scripts.phase13.pyenv import interpreter


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: pyexec.py <command> [args...]", file=sys.stderr)
        return 2
    executable = interpreter()
    if os.path.exists(executable):
        os.execve(executable, [executable, *argv], os.environ)
    # No canonical interpreter on disk: fall back to this one unchanged.
    os.execvpe(argv[0], argv, os.environ)
    return 1  # pragma: no cover - exec* never returns on success


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
