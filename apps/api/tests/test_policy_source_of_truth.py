"""Source-of-truth + duplication detectors (§43/44) and route policy hygiene (§28).

- CANONICAL_ROLES / ROLE_PERMISSIONS / CANONICAL_PERMISSION_IDS defined ONLY in
  packages/authorization (production code).
- Forbidden duplicate names outside canonical package (except approved fixtures):
  CANONICAL_PERMISSIONS, ROLE_PERMISSIONS, LEGACY_ROLE_MAP.
- Routes must not compare role strings (e.g. role == "admin").
- The forbidden fallback pattern (missing-permission -> role defaults) must not
  appear in apps/api production code.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CANONICAL_PKG = ROOT / "packages" / "authorization" / "src" / "rick_authorization"

PRODUCTION_SINGLETONS = ("CANONICAL_ROLES", "ROLE_PERMISSIONS", "CANONICAL_PERMISSION_IDS")
BANNED_DUPLICATES = ("CANONICAL_PERMISSIONS", "ROLE_PERMISSIONS", "LEGACY_ROLE_MAP")

# Explicitly approved non-production fixtures (test doubles, legacy read-only).
APPROVED_FIXTURE_SUBSTRINGS = ("tests/", "test_", "adapters/legacy/auth_facade.py")


def _py_files(scope: Path):
    return [p for p in scope.rglob("*.py") if "__pycache__" not in str(p)]


def _is_approved(path: Path) -> bool:
    text = str(path)
    return any(marker in text for marker in APPROVED_FIXTURE_SUBSTRINGS)


def test_singletons_live_only_in_canonical_package():
    for name in PRODUCTION_SINGLETONS:
        hits = []
        for scope in (ROOT / "apps", ROOT / "packages"):
            for f in _py_files(scope):
                if CANONICAL_PKG in f.parents or _is_approved(f):
                    continue
                for line in f.read_text(errors="ignore").splitlines():
                    stripped = line.strip()
                    if stripped.startswith(("#", '"', "'")):
                        continue
                    if re.match(rf"^{name}\s*[:=]", stripped):
                        hits.append(f"{f.relative_to(ROOT)}: {stripped[:100]}")
        assert not hits, f"duplicate canonical definition of {name}: {hits}"


def test_banned_duplicate_names_absent_from_production_code():
    for name in BANNED_DUPLICATES:
        hits = []
        for scope in (ROOT / "apps" / "api" / "src", ROOT / "packages"):
            for f in _py_files(scope):
                if CANONICAL_PKG in f.parents or _is_approved(f):
                    continue
                for line in f.read_text(errors="ignore").splitlines():
                    stripped = line.strip()
                    if stripped.startswith(("#", '"', "'")) or "rick_authorization" in line:
                        continue
                    if re.match(rf"^{name}\s*[:=]", stripped) or re.match(rf"^def {name}\b", stripped):
                        hits.append(f"{f.relative_to(ROOT)}: {stripped[:100]}")
        assert not hits, f"banned duplicate {name}: {hits}"


def test_routes_do_not_compare_role_strings():
    pattern = re.compile(r"""\brole\b\s*==\s*["']""")
    hits = []
    for f in _py_files(ROOT / "apps" / "api" / "src" / "routes"):
        for i, line in enumerate(f.read_text(errors="ignore").splitlines(), 1):
            if pattern.search(line):
                hits.append(f"{f.name}:{i}: {line.strip()[:120]}")
    assert not hits, f"role-string comparison in routes: {hits}"


def test_no_role_fallback_pattern_in_app_code():
    """Ban the exact defect in CODE (not prose): missing permission -> role defaults.

    Flags the `role_grant` identifier or direct `permissions_for_role(` derivation
    in app production code. Importing `canonical_role`/`permission_granted` from
    the canonical engine and delegating with authoritative=True is the blessed
    pattern, not a violation.
    """
    hits = []
    for f in _py_files(ROOT / "apps" / "api" / "src"):
        if _is_approved(f):
            continue
        for line in f.read_text(errors="ignore").splitlines():
            stripped = line.strip()
            if stripped.startswith(("#", '"', "'", "`", "*")):
                continue
            code = line.split("#", 1)[0]
            if "role_grant" in code or "permissions_for_role(" in code:
                hits.append(f"{f.relative_to(ROOT)}: {stripped[:120]}")
    assert not hits, f"role-fallback pattern in app code: {hits}"


def test_contract_drift_session_snapshot_is_canonical():
    """apps/api must re-export the canonical SessionSnapshot, not redefine it."""
    import models
    from rick_contracts.security import SessionSnapshot as Canonical

    assert models.SessionSnapshot is Canonical
