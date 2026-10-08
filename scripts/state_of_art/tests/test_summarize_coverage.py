from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from scripts.state_of_art.summarize_coverage import WEB_COVERAGE_SOURCES, main


def _invoke(tmp_path: Path, monkeypatch, report: dict, minimum: int = 75) -> tuple[int, dict]:
    source = tmp_path / "coverage.json"
    destination = tmp_path / "summary.json"
    source.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["summarize_coverage.py", "api", str(source), str(destination), str(minimum)])
    result = main()
    summary = json.loads(destination.read_text(encoding="utf-8")) if destination.exists() else {}
    return result, summary


def test_api_coverage_uses_exact_statement_ratio(tmp_path: Path, monkeypatch) -> None:
    report = {
        "files": {
            "apps/api/src/app.py": {"summary": {"covered_lines": 1, "num_statements": 2, "excluded_lines": 1}},
            "apps/api/src/routes/chat.py": {"summary": {"covered_lines": 2, "num_statements": 2, "excluded_lines": 1}},
        },
        "totals": {"covered_lines": 3, "num_statements": 4, "excluded_lines": 2},
    }

    result, summary = _invoke(tmp_path, monkeypatch, report)

    assert result == 0
    assert summary["covered_statements"] == 3
    assert summary["total_statements"] == 4
    assert summary["statements_percent"] == 75.0
    assert summary["minimum_statements_percent"] == 75
    assert summary["excluded_lines"] == 2
    assert summary["scope"] == "apps/api/src/**/*.py"
    assert summary["source_file_count"] == 2


def test_api_coverage_rejects_ratio_below_floor_without_rounding(tmp_path: Path, monkeypatch) -> None:
    report = {
        "files": {"apps/api/src/app.py": {"summary": {"covered_lines": 749, "num_statements": 1000, "excluded_lines": 0}}},
        "totals": {"covered_lines": 749, "num_statements": 1000, "excluded_lines": 0},
    }
    source = tmp_path / "coverage.json"
    source.write_text(json.dumps(report), encoding="utf-8")
    destination = tmp_path / "summary.json"
    monkeypatch.setattr(sys, "argv", ["summarize_coverage.py", "api", str(source), str(destination), "75"])

    with pytest.raises(SystemExit, match="below 75%"):
        main()

    assert not destination.exists()


def test_api_coverage_rejects_totals_that_disagree_with_source_files(tmp_path: Path, monkeypatch) -> None:
    report = {
        "files": {"apps/api/src/app.py": {"summary": {"covered_lines": 3, "num_statements": 4, "excluded_lines": 0}}},
        "totals": {"covered_lines": 4, "num_statements": 4, "excluded_lines": 0},
    }
    source = tmp_path / "coverage.json"
    source.write_text(json.dumps(report), encoding="utf-8")
    destination = tmp_path / "summary.json"
    monkeypatch.setattr(sys, "argv", ["summarize_coverage.py", "api", str(source), str(destination), "75"])

    with pytest.raises(SystemExit, match="differs from production-file summaries"):
        main()

    assert not destination.exists()


def test_api_coverage_rejects_excluded_line_count_mismatch(tmp_path: Path, monkeypatch) -> None:
    report = {
        "files": {"apps/api/src/app.py": {"summary": {"covered_lines": 3, "num_statements": 4, "excluded_lines": 1}}},
        "totals": {"covered_lines": 3, "num_statements": 4, "excluded_lines": 0},
    }
    source = tmp_path / "coverage.json"
    source.write_text(json.dumps(report), encoding="utf-8")
    destination = tmp_path / "summary.json"
    monkeypatch.setattr(sys, "argv", ["summarize_coverage.py", "api", str(source), str(destination), "75"])

    with pytest.raises(SystemExit, match="differs from production-file summaries"):
        main()

    assert not destination.exists()


@pytest.mark.parametrize("path", ["apps/api/tests/test_app.py", "apps/worker/app.py", "../apps/api/src/app.py"])
def test_api_coverage_rejects_files_outside_production_scope(tmp_path: Path, monkeypatch, path: str) -> None:
    report = {"files": {path: {"summary": {"covered_lines": 3, "num_statements": 4, "excluded_lines": 0}}},
        "totals": {"covered_lines": 3, "num_statements": 4}}

    with pytest.raises(SystemExit, match="stay under apps/api/src"):
        _invoke(tmp_path, monkeypatch, report)


def _web_report() -> dict:
    files = {"/runner/repository/apps/web/" + path: {"lines": {"covered": 9, "total": 10}}
        for path in WEB_COVERAGE_SOURCES}
    return {"total": {"lines": {"covered": 90, "total": 100}}, **files}


def _web_invoke(tmp_path: Path, monkeypatch, report: dict) -> dict:
    source, destination = tmp_path / "web.json", tmp_path / "summary.json"
    source.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["summarize_coverage.py", "web", str(source), str(destination), "85"])
    assert main() == 0
    return json.loads(destination.read_text())


def test_web_coverage_includes_all_ten_declared_behavior_modules(tmp_path: Path, monkeypatch) -> None:
    summary = _web_invoke(tmp_path, monkeypatch, _web_report())
    assert summary["source_file_count"] == 10
    assert summary["lines_percent"] == 90
    assert summary["minimum_lines_percent"] == 85
    assert "components/cases/case-workspace.tsx" in summary["scope"]


@pytest.mark.parametrize("mutation", ["missing-component", "wrong-directory", "duplicate-file", "wrong-total", "below-floor", "bool-count"])
def test_web_coverage_rejects_incomplete_or_false_reports(tmp_path: Path, monkeypatch, mutation: str) -> None:
    report = _web_report()
    key = "/runner/repository/apps/web/components/ui.tsx"
    if mutation == "missing-component":
        report.pop(key)
    elif mutation == "wrong-directory":
        report["/runner/repository/apps/web/tests/ui.tsx"] = report.pop(key)
    elif mutation == "duplicate-file":
        report["components/ui.tsx"] = report[key]
    elif mutation == "wrong-total":
        report["total"]["lines"]["covered"] = 100
    elif mutation == "below-floor":
        for path, entry in report.items():
            entry["lines"]["covered"] = 80 if path == "total" else 8
    else:
        report[key]["lines"]["covered"] = True
    with pytest.raises(SystemExit):
        _web_invoke(tmp_path, monkeypatch, report)


def test_web_source_set_matches_vitest_include() -> None:
    import re
    config = Path(__file__).resolve().parents[3] / "apps/web/vitest.config.ts"
    source = config.read_text()
    includes = re.search(r'include:\s*\[([^\]]+)\],\s*reportsDirectory:', source)
    assert includes is not None
    assert set(re.findall(r'"([^"]+)"', includes.group(1))) == WEB_COVERAGE_SOURCES
