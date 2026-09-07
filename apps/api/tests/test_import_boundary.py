"""Import boundary: packages/* never touch legacy; only adapters/legacy may import them."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LEGACY_MARKERS = ("cvg-master-rag-v2", "rick-professor", "modulo-redis-locker")
ALLOWED = (Path("apps/api/src/adapters/legacy"),)
BOUNDARY_DOC = Path("apps/api/src/adapters/__init__.py")  # documents the allowlist; not an import

_IMPORT_RE = re.compile(r"^\s*(import|from)\s+(\S+)", re.MULTILINE)


def _legacy_imports(text: str) -> list[str]:
    hits = []
    for match in _IMPORT_RE.finditer(text):
        module = match.group(2)
        # The canonical Phase 1.5 Python package is named rick_professor.  It
        # is distinct from the preserved filesystem component rick-professor;
        # the historical marker normalization must not classify the root
        # package as a legacy import.
        if module == "rick_professor" or module.startswith("rick_professor."):
            continue
        for marker in LEGACY_MARKERS:
            norm = marker.replace("-", "_").replace("/", ".")
            if marker in module or norm in module.replace("-", "_"):
                hits.append(match.group(0).strip())
    # Also flag sys.path hacks mentioning legacy outside the adapter boundary.
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "sys.path" in line and any(m in line for m in LEGACY_MARKERS):
            hits.append(stripped[:120])
    return hits


def _files(scope: Path):
    return [p for p in scope.rglob("*.py") if ".venv" not in str(p) and "__pycache__" not in str(p)]


def test_packages_have_no_legacy_imports():
    violations = []
    for pkg in (ROOT / "packages").iterdir():
        if not pkg.is_dir():
            continue
        for f in _files(pkg):
            # Tests are allowed legacy consumers (direction: tests -> legacy_adapters).
            if "tests" in f.parts:
                continue
            text = f.read_text(errors="ignore")
            if any(m in text for m in LEGACY_MARKERS):
                violations.append(str(f))
    assert not violations, f"packages import legacy: {violations}"


def test_root_rag_packages_have_no_legacy_imports():
    """Hard CI rule (§47): knowledge/ingestion/retrieval never import legacy or apps."""
    import re as _re

    _import_re = _re.compile(r"^\s*(import|from)\s+(\S+)")
    violations = []
    for pkg in ("knowledge", "ingestion", "retrieval", "identity", "authorization", "contracts", "shared"):
        src = ROOT / "packages" / pkg / "src"
        if not src.is_dir():
            continue
        for f in _files(src):
            for match in _import_re.finditer(f.read_text(errors="ignore")):
                module = match.group(2)
                if ("cvg" in module or "rick-professor" in module or "locker" in module
                        or module.startswith("apps") or module == "app" or module.startswith("app.")):
                    violations.append(f"{f.relative_to(ROOT)}: {match.group(0).strip()[:100]}")
    assert not violations, f"root packages breach boundary: {violations}"


def test_only_legacy_adapters_import_legacy():
    violations = []
    scope = ROOT / "apps" / "api" / "src"
    for f in _files(scope):
        rel = f.relative_to(ROOT)
        if rel == BOUNDARY_DOC:
            continue  # boundary manifest documents the allowlist; not an import
        if any(str(rel).startswith(str(a)) for a in ALLOWED):
            continue
        hits = _legacy_imports(f.read_text(errors="ignore"))
        if hits:
            violations.append(f"{rel}: {hits}")
    assert not violations, f"non-adapter files import legacy: {violations}"


def test_routes_have_no_direct_legacy_or_infra_imports():
    violations = []
    for f in _files(ROOT / "apps" / "api" / "src" / "routes"):
        text = f.read_text(errors="ignore")
        for marker in ("qdrant", "openai", "ioredis", "redis", *LEGACY_MARKERS):
            if marker in text.lower() and "observability.read" not in text.lower():
                # routes may mention permission names; flag real imports only
                if f"import {marker}" in text.lower() or f"from {marker}" in text.lower():
                    violations.append(f"{f.name}: {marker}")
    assert not violations, f"routes touch infra directly: {violations}"
