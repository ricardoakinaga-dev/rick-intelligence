from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType

import pytest


ROOT = Path(__file__).parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load(name: str, relative_path: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gate() -> ModuleType:
    return _load("phase11_restore_runtime_gate_under_test", "scripts/phase11/restore_runtime_gate.py")


@pytest.fixture(scope="module")
def adapter() -> ModuleType:
    return _load("phase3_restore_runtime_adapter_under_test", "scripts/state_of_art/run_phase3_restore.py")


def _runtime_source(
    gate: ModuleType,
    *,
    mode: str = "external_disposable",
    transport: str = "https",
    authorized: bool = True,
    external: bool = True,
    disposable: bool = True,
    missing_operation: str | None = None,
    restore_checksum: str | None = None,
    restore_scope: dict[str, list[str]] | None = None,
    rpo_source_state_at: str = "2026-09-10T12:00:01Z",
    rpo_backup_completed_at: str = "2026-09-10T12:00:02Z",
    production_safe: bool = False,
) -> str:
    base_scope = {
        "tenant_ids": ["tenant-a"],
        "workspace_ids": ["workspace-a"],
        "collection_ids": ["collection-a"],
    }
    restore_scope = restore_scope or base_scope
    components = list(gate.REQUIRED_COMPONENTS)
    checksums = {name: ("a" if index % 2 == 0 else "b") * 64 for index, name in enumerate(components)}
    checksum = "sha256:" + "c" * 64
    replacement_checksum = restore_checksum or checksum
    checks = {name: True for name in components}
    checks.update(
        {
            "destructive_authorized": True,
            "empty_target_ready": True,
            "clock_verified": True,
        }
    )
    source = f'''
SCOPE = {base_scope!r}
RESTORE_SCOPE = {restore_scope!r}
COMPONENTS = {components!r}
CHECKSUMS = {checksums!r}
CHECKSUM = {checksum!r}
RESTORE_CHECKSUM = {replacement_checksum!r}
CHECKS = {checks!r}

class Runtime:
    authorized = {authorized!r}
    external = {external!r}
    disposable = {disposable!r}
    production_safe = {production_safe!r}
    runtime_metadata = {{
        "authority": "contract-test-external-lab",
        "execution_mode": {mode!r},
        "transport": {transport!r},
        "service_boundary": True,
        "destructive_operations": True,
        "components": COMPONENTS,
        "clock_source": "external",
    }}

    def preflight(self):
        return {{"status": "PASS", "checks": CHECKS, "external": True, "disposable": True}}

    def seed(self, context=None):
        return {{"status": "PASS", "seed_id": "seed-001", "scope": SCOPE,
                "checksum": CHECKSUM, "component_checksums": CHECKSUMS,
                "components": COMPONENTS, "seeded_at": "2026-09-10T12:00:00Z",
                "completed_at": "2026-09-10T12:00:00Z"}}

    def backup(self, context=None):
        return {{"status": "PASS", "seed_id": "seed-001", "backup_id": "backup-001",
                "scope": SCOPE, "checksum": CHECKSUM, "component_checksums": CHECKSUMS,
                "components": COMPONENTS, "source_state_at": {rpo_source_state_at!r},
                "completed_at": {rpo_backup_completed_at!r}}}

    def destroy(self, context=None):
        return {{"status": "PASS", "backup_id": "backup-001", "scope": SCOPE,
                "checksum": CHECKSUM, "component_checksums": CHECKSUMS,
                "components": COMPONENTS, "destroyed": True,
                "destruction_observed": True, "remaining_components": [],
                "completed_at": "2026-09-10T12:00:03Z"}}

    def restore(self, context=None):
        return {{"status": "PASS", "backup_id": "backup-001", "scope": RESTORE_SCOPE,
                "checksum": RESTORE_CHECKSUM, "component_checksums": CHECKSUMS,
                "components": COMPONENTS, "restored_components": COMPONENTS,
                "restored": True, "completed_at": "2026-09-10T12:00:04Z"}}

    def rebuild(self, context=None):
        return {{"status": "PASS", "scope": SCOPE, "checksum": RESTORE_CHECKSUM,
                "component_checksums": CHECKSUMS, "components": COMPONENTS,
                "rebuilt": True, "qdrant_rebuilt": True, "index_rebuilt": True,
                "completed_at": "2026-09-10T12:00:05Z"}}

    def verify(self, context=None):
        return {{"status": "PASS", "scope": SCOPE, "checksum": RESTORE_CHECKSUM,
                "component_checksums": CHECKSUMS, "components": COMPONENTS,
                "verified": True, "jobs_reconciled": True, "audit_reconciled": True,
                "evidence_lineage": True, "qdrant_consistent": True,
                "no_data_loss": True, "completed_at": "2026-09-10T12:00:06Z",
                "secret": "must-never-be-persisted"}}

def create_runtime(**kwargs):
    return Runtime()
'''
    if missing_operation:
        start = source.find(f"    def {missing_operation}(self, context=None):")
        if start >= 0:
            end = source.find("\n    def ", start + 1)
            source = source[:start] + (source[end + 1 :] if end >= 0 else "")
    return source


def _write_runtime(tmp_path: Path, source: str) -> Path:
    path = tmp_path / "external_restore_runtime.py"
    path.write_text(source, encoding="utf-8")
    return path


def test_missing_runtime_is_blocked_without_a_runtime_claim(
    gate: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv(gate.GATE_ID, raising=False)

    report = gate.run_gate(root=tmp_path, output="restore.json")

    assert report["status"] == gate.BLOCKED_EXTERNAL
    assert report["runtime_claim"] is False
    assert report["production_safe"] is False
    assert (tmp_path / "restore.json").is_file()
    assert report["detail"] == "runtime_path_not_configured"
    assert [item["result"] for item in report["results"]] == [gate.BLOCKED_EXTERNAL] * len(gate.OPERATIONS)


def test_cli_missing_runtime_returns_blocked_exit(gate: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(gate.GATE_ID, raising=False)
    monkeypatch.setattr(gate, "ROOT", tmp_path)

    exit_code = gate.main(["--output", "restore.json"])

    assert exit_code == 2
    report = json.loads((tmp_path / "restore.json").read_text(encoding="utf-8"))
    assert report["status"] == gate.BLOCKED_EXTERNAL
    assert report["runtime_claim"] is False


def test_local_or_fake_composition_is_blocked_before_destructive_operations(
    gate: ModuleType,
    tmp_path: Path,
) -> None:
    path = _write_runtime(tmp_path, _runtime_source(gate, mode="in_memory", transport="local"))

    report = gate.run_gate(path, root=tmp_path, output="restore.json")

    assert report["status"] == gate.BLOCKED_EXTERNAL
    assert report["runtime_claim"] is False
    assert all(item["result"] == gate.BLOCKED_EXTERNAL for item in report["results"] if item["name"] in gate.OPERATIONS)


def test_missing_authorization_is_blocked_and_never_inferred_as_external(
    gate: ModuleType,
    tmp_path: Path,
) -> None:
    path = _write_runtime(tmp_path, _runtime_source(gate, authorized=False))

    report = gate.run_gate(path, root=tmp_path, output="restore.json")

    assert report["status"] == gate.BLOCKED_EXTERNAL
    assert report["runtime"]["authorized"] is False
    assert report["runtime_claim"] is False


def test_incomplete_external_composition_fails_closed(gate: ModuleType, tmp_path: Path) -> None:
    path = _write_runtime(tmp_path, _runtime_source(gate, missing_operation="rebuild"))

    report = gate.run_gate(path, root=tmp_path, output="restore.json")
    by_name = {item["name"]: item for item in report["results"]}

    assert report["status"] == gate.FAIL
    assert report["runtime_claim"] is False
    assert by_name["rebuild"]["result"] == gate.FAIL
    assert by_name["verify"]["result"] == gate.NOT_RUN


def test_valid_contract_executes_every_operation_and_measures_real_time_fields(
    gate: ModuleType,
    tmp_path: Path,
) -> None:
    path = _write_runtime(tmp_path, _runtime_source(gate))

    report = gate.run_gate(path, root=tmp_path, output="restore.json", rpo_seconds=2, rto_seconds=5)
    by_name = {item["name"]: item for item in report["results"]}
    stored = (tmp_path / "restore.json").read_text(encoding="utf-8")

    assert report["status"] == gate.PASS
    assert report["runtime_claim"] is True
    assert report["production_safe"] is False
    assert [by_name[name]["result"] for name in (*gate.OPERATIONS, "rpo", "rto")] == [gate.PASS] * 8
    assert report["rpo"]["measured_seconds"] == 1.0
    assert report["rto"]["measured_seconds"] == 3.0
    assert report["rpo"]["within_budget"] is True
    assert report["rto"]["within_budget"] is True
    assert report["scope"]["dimensions"] == {"tenant_ids": 1, "workspace_ids": 1, "collection_ids": 1}
    assert report["required_sequence"] == list(gate.OPERATIONS)
    assert report["executed_sequence"] == list(gate.OPERATIONS)
    assert report["sequence_valid"] is True
    assert "must-never-be-persisted" not in stored
    assert "contract-test-external-lab" not in stored
    assert "seed-001" not in stored
    assert report["results"][2]["observed"]["seed_id_digest"]


def test_restore_checksum_mismatch_fails_and_stops_before_rebuild(gate: ModuleType, tmp_path: Path) -> None:
    wrong = "sha256:" + "d" * 64
    path = _write_runtime(tmp_path, _runtime_source(gate, restore_checksum=wrong))

    report = gate.run_gate(path, root=tmp_path, output="restore.json")
    by_name = {item["name"]: item for item in report["results"]}

    assert report["status"] == gate.FAIL
    assert by_name["restore"]["result"] == gate.FAIL
    assert by_name["rebuild"]["result"] == gate.NOT_RUN
    assert report["runtime_claim"] is False


def test_scope_mismatch_fails_closed(gate: ModuleType, tmp_path: Path) -> None:
    scope = {"tenant_ids": ["tenant-b"], "workspace_ids": ["workspace-b"], "collection_ids": ["collection-b"]}
    path = _write_runtime(tmp_path, _runtime_source(gate, restore_scope=scope))

    report = gate.run_gate(path, root=tmp_path, output="restore.json")
    by_name = {item["name"]: item for item in report["results"]}

    assert report["status"] == gate.FAIL
    assert by_name["restore"]["result"] == gate.FAIL
    assert by_name["verify"]["result"] == gate.NOT_RUN


def test_destroy_requires_observed_empty_scope(gate: ModuleType, tmp_path: Path) -> None:
    source = _runtime_source(gate).replace('"remaining_components": [],', '"remaining_components": ["qdrant"],')
    path = _write_runtime(tmp_path, source)

    report = gate.run_gate(path, root=tmp_path, output="restore.json")
    by_name = {item["name"]: item for item in report["results"]}

    assert report["status"] == gate.FAIL
    assert by_name["destroy"]["result"] == gate.FAIL
    assert by_name["restore"]["result"] == gate.NOT_RUN


def test_verify_requires_evidence_lineage_and_reconciliation(gate: ModuleType, tmp_path: Path) -> None:
    source = _runtime_source(gate).replace('"evidence_lineage": True,', '"evidence_lineage": False,')
    path = _write_runtime(tmp_path, source)

    report = gate.run_gate(path, root=tmp_path, output="restore.json")
    by_name = {item["name"]: item for item in report["results"]}

    assert report["status"] == gate.FAIL
    assert by_name["verify"]["result"] == gate.FAIL
    assert by_name["verify"]["detail"] == "evidence_lineage_not_confirmed"


def test_invalid_budget_is_fail_closed(gate: ModuleType, tmp_path: Path) -> None:
    report = gate.run_gate(root=tmp_path, output="restore.json", rpo_seconds="not-a-number")

    assert report["status"] == gate.FAIL
    assert report["runtime_claim"] is False
    assert (tmp_path / "restore.json").is_file()


def test_rpo_budget_is_a_hard_gate(gate: ModuleType, tmp_path: Path) -> None:
    path = _write_runtime(
        tmp_path,
        _runtime_source(
            gate,
            rpo_source_state_at="2026-09-10T12:00:00Z",
            rpo_backup_completed_at="2026-09-10T12:00:03Z",
        ),
    )

    report = gate.run_gate(path, root=tmp_path, output="restore.json", rpo_seconds=2, rto_seconds=5)
    by_name = {item["name"]: item for item in report["results"]}

    assert report["status"] == gate.FAIL
    assert report["rpo"]["measured_seconds"] == 3.0
    assert report["rpo"]["within_budget"] is False
    assert by_name["rpo"]["result"] == gate.FAIL
    assert report["runtime_claim"] is False


def test_invalid_timestamps_do_not_allow_an_inferred_rpo(gate: ModuleType, tmp_path: Path) -> None:
    path = _write_runtime(tmp_path, _runtime_source(gate, rpo_source_state_at="not-a-timestamp"))

    report = gate.run_gate(path, root=tmp_path, output="restore.json")
    by_name = {item["name"]: item for item in report["results"]}

    assert report["status"] == gate.FAIL
    assert by_name["backup"]["result"] == gate.FAIL
    assert by_name["destroy"]["result"] == gate.NOT_RUN


def test_adapter_preserves_external_block_and_binds_capability(
    adapter: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    valid_checkout = {
        "available": True,
        "head": "a" * 40,
        "tree": "b" * 40,
        "fingerprint": "c" * 64,
        "status": "CLEAN",
        "errors": [],
    }

    def capture(_root: Path) -> dict[str, object]:
        return dict(valid_checkout)

    def blocked_gate(argv: list[str]) -> int:
        output = tmp_path / Path(argv[argv.index("--output") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                {
                    "schema_version": "phase11-restore-runtime-gate.v1",
                    "gate_id": "RICK_RESTORE_RUNTIME_PATH",
                    "status": "BLOCKED_EXTERNAL",
                    "runtime_claim": False,
                    "production_safe": False,
                    "results": [],
                }
            ),
            encoding="utf-8",
        )
        return 2

    monkeypatch.setattr(adapter, "capture_checkout", capture)
    monkeypatch.setattr(adapter.restore_runtime_gate, "main", blocked_gate)
    monkeypatch.setattr(adapter, "RAW_OUTPUT", "raw.json")

    envelope = adapter.run(tmp_path, output="evidence.json")

    assert envelope["capability_id"] == "P1-05"
    assert envelope["status"] == "BLOCKED_EXTERNAL"
    assert envelope["exit_status"] == 2
    assert envelope["production_safe"] is False


def test_adapter_forwards_runtime_and_recovery_budgets(adapter: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, object] = {}

    def fake_run(root: Path, *, output: str, argv: list[str]) -> dict[str, object]:
        observed["root"] = root
        observed["output"] = output
        observed["argv"] = list(argv)
        return {"status": "BLOCKED_EXTERNAL", "exit_status": 2}

    monkeypatch.setattr(adapter, "run", fake_run)

    exit_code = adapter.main(
        [
            "--output",
            "evidence.json",
            "--runtime-path",
            "/approved/runtime.py",
            "--timeout-seconds",
            "30",
            "--rpo-seconds",
            "10",
            "--rto-seconds",
            "20",
        ]
    )

    assert exit_code == 2
    assert observed["output"] == "evidence.json"
    assert observed["argv"] == [
        "--runtime-path",
        "/approved/runtime.py",
        "--timeout-seconds",
        "30",
        "--rpo-seconds",
        "10",
        "--rto-seconds",
        "20",
    ]


def test_gate_has_no_local_restore_fallback(gate: ModuleType) -> None:
    source = (ROOT / "scripts/phase11/restore_runtime_gate.py").read_text(encoding="utf-8")

    assert "RICK_RESTORE_RUNTIME_PATH" in source
    assert "infrastructure.scripts" not in source
    assert "InMemory" not in source
    assert "MockTransport" not in source
    assert "seed -> backup -> destroy -> restore -> rebuild -> verify" in source
