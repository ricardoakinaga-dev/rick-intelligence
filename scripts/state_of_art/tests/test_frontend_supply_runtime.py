from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType

import pytest


ROOT = Path(__file__).parents[3]


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


gate = _load("frontend_supply_runtime_gate", ROOT / "scripts/phase11/frontend_supply_runtime_gate.py")
wrapper = _load("run_phase3_frontend_supply", ROOT / "scripts/state_of_art/run_phase3_frontend_supply.py")


def _write_node_component(root: Path, *, lock: dict | None = None, package: dict | None = None) -> None:
    package_value = package or {
        "name": "fixture-web",
        "version": "1.0.0",
        "dependencies": {"react": "1.0.0"},
    }
    lock_value = lock or {
        "name": package_value["name"],
        "version": package_value["version"],
        "lockfileVersion": 3,
        "requires": True,
        "packages": {
            "": {
                "name": package_value["name"],
                "version": package_value["version"],
                "dependencies": package_value.get("dependencies", {}),
                "devDependencies": package_value.get("devDependencies", {}),
            },
            "node_modules/react": {"name": "react", "version": "1.0.0", "license": "MIT"},
        },
    }
    for relative in gate.NODE_COMPONENTS:
        directory = root / relative
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "package.json").write_text(json.dumps(package_value), encoding="utf-8")
        (directory / "package-lock.json").write_text(json.dumps(lock_value), encoding="utf-8")


def _all_browser_checks(value: bool = True) -> dict[str, bool]:
    return {
        "browser_api_backed_states": value,
        "viewport_matrix": value,
        "keyboard": value,
        "focus": value,
        "axe": value,
        "reduced_motion": value,
        "contrast": value,
        "touch": value,
    }


def test_required_viewports_are_exact_native_matrix() -> None:
    assert [(item["width"], item["height"]) for item in gate.VIEWPORTS] == [
        (375, 812),
        (768, 1024),
        (1440, 1000),
    ]
    assert len({item["width"] for item in gate.VIEWPORTS}) == 3


def test_browser_evidence_cannot_promote_fixture_interception() -> None:
    report = {
        "status": "PASS",
        "runtime_claim": True,
        "real_runtime": True,
        "fixture_interception": True,
    }
    status, _detail, _projection = gate._browser_status_from_report(report)  # noqa: SLF001
    assert status == "FAIL"


def test_browser_evidence_requires_real_api_states_and_all_checks() -> None:
    report = {
        "status": "PASS",
        "runtime_claim": True,
        "real_runtime": True,
        "fixture_interception": False,
        "checks": _all_browser_checks(),
    }
    checks = gate._browser_checks_from_report(ROOT, report, ROOT / "apps/web/package.json")  # noqa: SLF001
    assert {item["status"] for item in checks} == {"PASS"}

    report["checks"] = _all_browser_checks()
    report["checks"]["axe"] = False
    checks = gate._browser_checks_from_report(ROOT, report, ROOT / "apps/web/package.json")  # noqa: SLF001
    assert next(item for item in checks if item["name"] == "axe")["status"] == "FAIL"


def test_source_audit_records_fixture_tests_without_using_them_as_evidence() -> None:
    result = gate.audit_frontend_sources(ROOT)
    assert result["status"] == "PASS"
    observations = result["observations"]
    assert observations["runtime_fixture_files_not_used"] is True
    assert observations["fixture_test_files_excluded_from_runtime"]
    assert observations["configured_viewports"] == {"375": "375x812", "768": "768x1024", "1440": "1440x1000"}
    assert observations["workflow_runtime_event_scope"] is True


def test_failed_browser_report_preserves_observed_dimension_results() -> None:
    report = {
        "status": "FAIL",
        "runtime_claim": False,
        "real_runtime": True,
        "fixture_interception": False,
        "error": "axe found a violation",
        "checks": _all_browser_checks(),
    }
    checks = gate._browser_checks_from_report(ROOT, report, ROOT / "evidence.json")  # noqa: SLF001
    assert next(item for item in checks if item["name"] == "browser-runtime-probe")["status"] == "FAIL"
    assert next(item for item in checks if item["name"] == "viewport-matrix")["status"] == "PASS"


def test_axe_incomplete_results_are_not_promoted() -> None:
    assert "item.incomplete && item.incomplete.length === 0" in gate._BROWSER_PROBE  # noqa: SLF001


def test_browser_screenshots_do_not_mutate_hydrated_inputs() -> None:
    assert gate._BROWSER_PROBE.count('caret: "initial"') == 3  # noqa: SLF001


def test_browser_probe_waits_for_client_hydration_before_interaction() -> None:
    assert 'document.documentElement.dataset.rickHydrated === "true"' in gate._BROWSER_PROBE  # noqa: SLF001


def test_browser_probe_targets_login_error_instead_of_next_route_announcer() -> None:
    assert '.login-form [role="alert"]' in gate._BROWSER_PROBE  # noqa: SLF001


def test_lockfile_structural_mismatch_fails_closed(tmp_path: Path) -> None:
    _write_node_component(tmp_path)
    package = json.loads((tmp_path / "apps/web/package.json").read_text(encoding="utf-8"))
    package["dependencies"]["react"] = "2.0.0"
    (tmp_path / "apps/web/package.json").write_text(json.dumps(package), encoding="utf-8")
    result = gate.check_lockfiles(tmp_path, npm=None)
    assert result["status"] == "FAIL"
    assert "apps/web:dependencies" in result["observations"]["manifest_mismatches"]


def test_missing_npm_keeps_lockfile_result_not_run(tmp_path: Path) -> None:
    _write_node_component(tmp_path)
    result = gate.check_lockfiles(tmp_path, npm=None)
    assert result["status"] == "NOT_RUN"
    assert result["result"] == "NOT_RUN"


def test_sbom_parser_requires_non_empty_cyclonedx_components() -> None:
    assert gate._parse_sbom(json.dumps({"bomFormat": "CycloneDX", "components": [{"name": "react"}]}))[0] is True  # noqa: SLF001
    assert gate._parse_sbom(json.dumps({"bomFormat": "CycloneDX", "components": []}))[0] is False  # noqa: SLF001
    assert gate._parse_sbom("not-json")[0] is False  # noqa: SLF001


def test_secret_scan_finds_high_signal_candidate_without_echoing_value(tmp_path: Path) -> None:
    value = "sk-" + "A" * 40
    path = tmp_path / "source.txt"
    path.write_text(f"token={value}\n", encoding="utf-8")
    result = gate.check_secrets(tmp_path, tmp_path / "evidence", python=None, gitleaks=None)
    assert result["status"] == "FAIL"
    rendered = json.dumps(result)
    assert value not in rendered
    assert result["observations"]["finding_count"] == 1


def test_secret_scan_passes_dependency_free_clean_input(tmp_path: Path) -> None:
    (tmp_path / "source.txt").write_text("const token = 'test-only-placeholder';\n", encoding="utf-8")
    result = gate.check_secrets(tmp_path, tmp_path / "evidence", python=None, gitleaks=None)
    assert result["status"] == "PASS"
    assert result["tool"] == "built-in-static-scanner"


def test_license_allowlist_rejects_unknown_and_accepts_spdx(tmp_path: Path) -> None:
    _write_node_component(tmp_path)
    lock_path = tmp_path / "apps/web/package-lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["packages"]["node_modules/react"]["license"] = "MIT"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    assert gate.check_licenses(tmp_path)["status"] == "PASS"
    lock["packages"]["node_modules/react"]["license"] = "Custom-Proprietary"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    result = gate.check_licenses(tmp_path)
    assert result["status"] == "FAIL"
    assert result["observations"]["denied"][0]["license"] == "Custom-Proprietary"


def test_candidate_container_digest_requires_all_services_and_matching_ref(tmp_path: Path) -> None:
    directory = tmp_path / "infrastructure/docker"
    directory.mkdir(parents=True)
    digest = "sha256:" + "a" * 64
    manifest = {
        "status": "CANDIDATE",
        "images": [
            {"service": service, "digest": digest, "image_ref": f"registry/{service}@{digest}"}
            for service in ("api", "worker", "web")
        ],
    }
    (directory / "release-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert gate.check_container_digests(tmp_path, python=None, docker=None)["status"] == "PASS"
    manifest["images"][2]["image_ref"] = "registry/web:latest"
    (directory / "release-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert gate.check_container_digests(tmp_path, python=None, docker=None)["status"] == "FAIL"


def test_prepared_container_packet_is_not_claimed_as_digest_evidence(tmp_path: Path) -> None:
    directory = tmp_path / "infrastructure/docker"
    directory.mkdir(parents=True)
    (directory / "release-manifest.json").write_text(json.dumps({"status": "PREPARED_NOT_RUN", "images": []}), encoding="utf-8")
    result = gate.check_container_digests(tmp_path, python=None, docker=None)
    assert result["status"] == "NOT_RUN"


def test_missing_container_sbom_tool_is_not_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RICK_API_IMAGE", raising=False)
    monkeypatch.delenv("RICK_WORKER_IMAGE", raising=False)
    monkeypatch.delenv("RICK_WEB_IMAGE", raising=False)
    result = gate.check_container_sbom(tmp_path, tmp_path / "evidence", trivy=None, syft=None, docker=None)
    assert result["status"] == "NOT_RUN"
    assert "not an image SBOM" in result["detail"]


def test_redaction_never_persists_url_or_secret_assignment() -> None:
    value = "top-secret"
    rendered = json.dumps(gate.redact({"password": value, "detail": f"https://user:{value}@example.invalid/x"}))
    assert value not in rendered
    assert "[REDACTED]" in rendered


def test_wrapper_emits_blocked_commit_bound_envelope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def checkout(_root: Path) -> dict[str, object]:
        return {"available": True, "head": "a" * 40, "tree": "b" * 40, "fingerprint": "c" * 64, "status": "CLEAN", "errors": []}

    def fake_gate(argv: list[str]) -> int:
        output = tmp_path / Path(argv[argv.index("--output") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({"status": "BLOCKED_EXTERNAL", "runtime_claim": False, "production_safe": False, "checks": []}), encoding="utf-8")
        return 2

    monkeypatch.setattr(wrapper, "capture_checkout", checkout)
    monkeypatch.setattr(wrapper.frontend_supply_runtime_gate, "main", fake_gate)
    monkeypatch.setattr(wrapper, "RAW_OUTPUT", "raw.json")
    envelope = wrapper.run(tmp_path, output="evidence.json")
    assert envelope["status"] == "BLOCKED_EXTERNAL"
    assert envelope["exit_status"] == 2
    assert envelope["production_safe"] is False
    assert envelope["covered_capability_ids"] == ["P1-06", "P1-07"]
    assert (tmp_path / "evidence.json").is_file()
    supply = json.loads((tmp_path / wrapper.SUPPLY_OUTPUT).read_text(encoding="utf-8"))
    assert supply["capability_id"] == "P1-07"
    assert supply["raw_artifacts"] == envelope["raw_artifacts"]
