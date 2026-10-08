"""Canonical interpreter and import-path discovery for the phase lanes.

Retired components (`cvg-master-rag-v2`, `rick-professor`, `modulo-redis-locker`)
are no longer part of the checkout, so no lane prepends their `src` directories.
Everything the lanes run resolves through `apps/*/src` and `packages/*/src`,
which is the single source of truth for PYTHONPATH.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VENV_PYTHON = ROOT / ".runtime" / "venvs" / "cvg" / "bin" / "python"

# apps/api keeps its code under src/; apps/worker is importable as-is
# (external_ingestion, admin_audit_outbox, deployment_composition, ...).
APP_SOURCES = (("api", "src"), ("worker", ""))
PACKAGE_SOURCES = (
    "contracts", "authorization", "identity", "observability", "knowledge",
    "ingestion", "retrieval", "providers", "locking", "professor", "evidence",
    "decision", "storage", "jobs",
)


def venv_ready() -> bool:
    """True when the runtime venv exists and actually carries pytest."""

    if not VENV_PYTHON.is_file():
        return False
    site_packages = sorted(VENV_PYTHON.parent.parent.glob("lib/python*/site-packages"))
    return any((path / "pytest" / "__init__.py").is_file() for path in site_packages)


def interpreter() -> str:
    """Prefer the bootstrapped venv; fall back to the launching interpreter.

    An unbootstrapped venv (created but never seeded) has no pytest, so the
    fallback is decided on importability rather than mere file existence.
    """

    return str(VENV_PYTHON) if venv_ready() else sys.executable


def source_paths() -> list[Path]:
    paths = [ROOT / "apps" / name / suffix for name, suffix in APP_SOURCES]
    paths.extend(ROOT / "packages" / name / "src" for name in PACKAGE_SOURCES)
    return [path for path in paths if path.is_dir()]


def pythonpath() -> str:
    existing = os.environ.get("PYTHONPATH", "")
    parts = [str(path) for path in source_paths()]
    if existing:
        parts.append(existing)
    return os.pathsep.join(parts)


def test_environment(**overrides: str) -> dict[str, str]:
    """Process environment for a lane: canonical PYTHONPATH plus test defaults."""

    env = os.environ.copy()
    env["PYTHONPATH"] = pythonpath()
    env.setdefault("RAG_SKIP_QDRANT_BOOTSTRAP", "1")
    env.setdefault("SESSION_COOKIE_SECURE", "false")
    env.setdefault("OPENAI_API_KEY", "")
    env.setdefault("RERANKING_ENABLED", "false")
    env.update(overrides)
    return env
