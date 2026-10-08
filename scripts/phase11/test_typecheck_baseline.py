"""Gradual Python type-check baseline must reject new typed errors (AUD07-17)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from scripts.phase11.typecheck_baseline import count_errors, main, parse_baseline

VALID_BASELINE = """
# comment
packages/contracts/src = 0
packages/authorization/src = 2   # tolerated while the package is adopted
"""


def test_parse_baseline_reads_entries_and_ignores_comments() -> None:
    entries, errors = parse_baseline(VALID_BASELINE, "baseline.txt")

    assert errors == []
    assert entries == [
        ("packages/contracts/src", 0),
        ("packages/authorization/src", 2),
    ]


def test_parse_baseline_rejects_malformed_entries() -> None:
    entries, errors = parse_baseline(
        "packages/contracts/src 0\npackages/authorization/src = zero\npkg = -1\n",
        "baseline.txt",
    )

    assert entries == []
    assert len(errors) == 3
    assert all(error.startswith("baseline.txt:") for error in errors)


def test_count_errors_uses_the_longest_matching_root() -> None:
    roots = ["packages/contracts", "packages/contracts/tests"]
    lines = [
        "packages/contracts/src/a.py:1: error: boom [misc]",
        "packages/contracts/tests/test_a.py:2: error: boom [misc]",
        "packages/contracts/tests/test_a.py:3: error: boom [misc]",
        "apps/api/src/x.py:4: error: outside coverage [misc]",
    ]

    counts, unmatched = count_errors(lines, roots)

    assert counts == {"packages/contracts": 1, "packages/contracts/tests": 2}
    assert unmatched == ["apps/api/src/x.py:4: error: outside coverage [misc]"]


def _write_package(root: Path, name: str, body: str) -> Path:
    """A unique module name keeps mypy's cache from aliasing fixture runs.

    mypy keys its cache by module name: a fixture reused in a later session
    would otherwise be reported at the stale path recorded in .mypy_cache.
    """
    package = root / f"{name}_{uuid4().hex[:8]}"
    package.mkdir()
    (package / "__init__.py").write_text(body, encoding="utf-8")
    return package


def _write_baseline(tmp_path: Path, package: Path, limit: int) -> Path:
    baseline = tmp_path / f"baseline-{package.name}.txt"
    baseline.write_text(f"{package} = {limit}\n", encoding="utf-8")
    return baseline


def test_a_new_typed_error_above_the_baseline_fails(tmp_path: Path, capsys) -> None:
    package = _write_package(tmp_path, "typed_fixture_over_limit", 'VALUE: int = "not an int"\n')
    baseline = _write_baseline(tmp_path, package, 0)

    assert main([str(baseline)]) == 1
    assert "baseline aceita 0" in capsys.readouterr().out


def test_the_same_error_is_accepted_only_while_the_baseline_says_so(
    tmp_path: Path, capsys,
) -> None:
    package = _write_package(tmp_path, "typed_fixture_within_limit", 'VALUE: int = "not an int"\n')
    baseline = _write_baseline(tmp_path, package, 1)

    assert main([str(baseline)]) == 0
    out = capsys.readouterr().out
    assert "PASS" in out and "FAIL" not in out


def test_a_covered_package_without_typed_errors_passes(tmp_path: Path, capsys) -> None:
    package = _write_package(tmp_path, "typed_fixture_clean", "VALUE: int = 1\n")
    baseline = _write_baseline(tmp_path, package, 0)

    assert main([str(baseline)]) == 0
    assert "PASS" in capsys.readouterr().out


def test_a_baseline_above_the_measured_error_count_is_reported_for_lowering(
    tmp_path: Path, capsys,
) -> None:
    package = _write_package(tmp_path, "typed_fixture_headroom", 'VALUE: int = "not an int"\n')
    baseline = _write_baseline(tmp_path, package, 3)

    assert main([str(baseline)]) == 0
    out = capsys.readouterr().out
    assert "AVISO" in out and "rebaixe a linha do baseline" in out


def test_a_covered_directory_that_no_longer_exists_fails(tmp_path: Path, capsys) -> None:
    baseline = tmp_path / "baseline.txt"
    baseline.write_text("docs/does-not-exist-for-aud07-17 = 0\n", encoding="utf-8")

    assert main([str(baseline)]) == 1
    assert "diretório inexistente" in capsys.readouterr().out
