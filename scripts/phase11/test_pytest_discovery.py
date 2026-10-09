"""Collect colliding suites together outside the checkout without PYTHONPATH."""

import os
from pathlib import Path
import subprocess

from scripts.phase13.pyenv import interpreter

ROOT = Path(__file__).resolve().parents[2]


def test_joint_collection_does_not_need_manual_path_or_rewrite_history(tmp_path: Path) -> None:
    paths = [
        "packages/identity/tests/test_provider.py",
        "packages/providers/tests/test_provider.py",
        "packages/identity/tests/test_aud03_postgres_live.py",
        "packages/knowledge/tests/test_aud03_postgres_live.py",
        "apps/api/tests/test_auth.py",
        "apps/api/tests/test_api_deployment_composition.py",
        "apps/worker/tests/test_deployment_composition.py",
        "apps/worker/tests/test_worker_provider_rework3_lifecycle.py",
        "infrastructure/vps/tests/test_safety.py",
    ]
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTEST_ADDOPTS", None)
    result = subprocess.run(
        [interpreter(), "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
         *[str(ROOT / path) for path in paths]],
        cwd=tmp_path, env=env, text=True, capture_output=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for path in paths:
        assert Path(path).name in result.stdout
