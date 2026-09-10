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


def _load(name: str, filename: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gate() -> ModuleType:
    return _load("phase11_golden_runtime_gate", "scripts/phase11/golden_runtime_gate.py")


@pytest.fixture(scope="module")
def adapter() -> ModuleType:
    return _load("phase3_golden_runtime_adapter", "scripts/state_of_art/run_phase3_golden_runtime.py")


def _lineage(gate: ModuleType) -> dict[str, str]:
    return {
        "document_id": "doc-golden-1",
        "document_version": "sha256:" + "1" * 64,
        "ingestion_version": "ing-1",
        "parser_version": "parser-1",
        "chunker_version": "chunker-1",
        "embedding_model": "embedding-model-1",
        "embedding_version": "embedding-1",
        "index_version": "index-1",
        "checksum": "sha256:" + "2" * 64,
        "object_ref": "uploads/fixture",
        "created_at": "2026-09-10T12:00:00Z",
        "verified_at": "2026-09-10T12:00:01Z",
        "published_at": "2026-09-10T12:00:02Z",
    }


def test_missing_runtime_path_is_blocked_and_makes_no_claim(
    gate: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv(gate.GATE_ID, raising=False)

    report = gate.run_gate(root=tmp_path, output="gate.json")

    assert report["status"] == gate.BLOCKED_EXTERNAL
    assert report["runtime_claim"] is False
    assert report["production_safe"] is False
    assert (tmp_path / "gate.json").is_file()
    assert "runtime_path_not_configured" in {
        item["detail"] for item in report["results"] if "detail" in item
    }
    assert report["failure_matrix"]["expected_points"] == list(gate.FAILURE_POINTS)
    assert all(
        item["result"] == gate.BLOCKED_EXTERNAL
        for item in report["failure_matrix"]["points"].values()
    )
    assert report["invariants"]["failed_version_never_replaces_last_verified"] == gate.BLOCKED_EXTERNAL


def test_unavailable_factory_does_not_leak_exception_text(
    gate: ModuleType,
    tmp_path: Path,
) -> None:
    secret = "never-persist-this-token"
    runtime_file = tmp_path / "runtime.py"
    runtime_file.write_text(
        "def build_golden_runtime():\n"
        f"    raise RuntimeError({secret!r})\n",
        encoding="utf-8",
    )

    report = gate.run_gate(runtime_file, root=tmp_path, output="gate.json")
    encoded = (tmp_path / "gate.json").read_text(encoding="utf-8")

    assert report["status"] == gate.BLOCKED_EXTERNAL
    assert report["runtime_claim"] is False
    assert secret not in encoded
    assert "runtime_unavailable" in encoded


def test_explicit_but_incomplete_composition_cannot_pass(
    gate: ModuleType,
    tmp_path: Path,
) -> None:
    runtime_file = tmp_path / "runtime.py"
    runtime_file.write_text(
        "def build_golden_runtime():\n"
        "    return {'authorized': True, 'external': True, 'preflight': lambda: True}\n",
        encoding="utf-8",
    )

    report = gate.run_gate(runtime_file, root=tmp_path, output="gate.json")
    result_by_name = {item["name"]: item for item in report["results"]}

    assert report["status"] != gate.PASS
    assert report["runtime_claim"] is False
    assert result_by_name["external_preflight"]["result"] == gate.PASS
    assert result_by_name["interface.upload"]["result"] == gate.FAIL
    assert result_by_name["interface.failure_matrix"]["result"] == gate.BLOCKED_EXTERNAL


def test_unauthorized_composition_is_blocked_before_local_diagnostics(
    gate: ModuleType,
    tmp_path: Path,
) -> None:
    runtime_file = tmp_path / "runtime.py"
    runtime_file.write_text(
        "def build_golden_runtime():\n"
        "    return {'authorized': False, 'external': True, 'preflight': lambda: True}\n",
        encoding="utf-8",
    )

    report = gate.run_gate(runtime_file, root=tmp_path, output="gate.json")

    assert report["status"] == gate.BLOCKED_EXTERNAL
    assert report["runtime_claim"] is False
    assert [item["name"] for item in report["results"]] == [
        "runtime_composition",
        "external_authorization",
    ]


def test_lineage_requires_verified_at_and_keeps_projection_consistent(gate: ModuleType) -> None:
    lineage = _lineage(gate)
    scope = {"tenant_id": "tenant-1", "workspace_id": "workspace-1", "collection_id": "collection-1"}
    document = {**scope, **lineage, "status": "published"}
    chunks = [{
        "chunk_id": "chunk-1",
        "document_id": lineage["document_id"],
        "tenant_id": scope["tenant_id"],
        "checksum": lineage["checksum"],
        "parser_version": lineage["parser_version"],
        "chunker_version": lineage["chunker_version"],
        "embedding_version": lineage["embedding_version"],
    }]
    projection = {
        **lineage,
        **scope,
        "checksum": lineage["checksum"],
    }

    result, observed = gate.check_lineage(
        document,
        chunks,
        scope=scope,
        lineage=lineage,
        vector_projection=projection,
    )

    assert result.result == gate.PASS
    assert observed["verified_at"] == lineage["verified_at"]

    incomplete = dict(lineage)
    del incomplete["verified_at"]
    document_without_verification = dict(document)
    del document_without_verification["verified_at"]
    missing_result, _ = gate.check_lineage(
        document_without_verification,
        chunks,
        scope=scope,
        lineage=incomplete,
    )
    assert missing_result.result == gate.FAIL
    assert missing_result.detail == "lineage_fields_missing"


def test_failed_version_invariant_requires_replay_and_rejects_replacement(gate: ModuleType) -> None:
    baseline = {"document_version": "version-verified", "checksum": "checksum-verified"}
    safe_case = {
        "status": "PASS",
        "injected": True,
        "failed": True,
        "last_verified_preserved": True,
        "published_version": baseline["document_version"],
        "published_checksum": baseline["checksum"],
        "replay_verified": True,
    }
    assert gate.check_failed_version_invariant(safe_case, baseline).result == gate.PASS

    replaced_case = {**safe_case, "new_version_published": True}
    assert gate.check_failed_version_invariant(replaced_case, baseline).result == gate.FAIL

    matrix, all_pass = gate.evaluate_failure_matrix(
        {point: safe_case for point in gate.FAILURE_POINTS},
        baseline,
    )
    assert all_pass is True
    assert all(item.result == gate.PASS for item in matrix.values())

    bad_matrix, bad_all_pass = gate.evaluate_failure_matrix(
        {**{point: safe_case for point in gate.FAILURE_POINTS}, "after_publish": replaced_case},
        baseline,
    )
    assert bad_all_pass is False
    assert bad_matrix["after_publish"].result == gate.FAIL


def test_failure_matrix_missing_boundary_is_not_fabricated_as_pass(gate: ModuleType) -> None:
    matrix, all_pass = gate.evaluate_failure_matrix({}, {"document_version": "v", "checksum": "c"})

    assert all_pass is False
    assert set(matrix) == set(gate.FAILURE_POINTS)
    assert all(item.result == gate.NOT_RUN for item in matrix.values())


def test_stage_trace_must_explicitly_observe_parse_and_normalize(gate: ModuleType) -> None:
    complete = [{"stage": stage, "status": "PASS"} for stage in gate.PATH_STAGES]
    assert gate.check_stage_trace(complete).result == gate.PASS

    without_normalize = [item for item in complete if item["stage"] != "normalize"]
    result = gate.check_stage_trace(without_normalize)
    assert result.result == gate.FAIL
    assert result.detail == "stage_observation_incomplete"


def test_gate_source_does_not_select_hermetic_memory_clients(gate: ModuleType) -> None:
    source = (ROOT / "scripts/phase11/golden_runtime_gate.py").read_text(encoding="utf-8")

    assert "InMemory" not in source
    assert "DeterministicHashEmbedding" not in source
    assert gate.GATE_ID == "RICK_GOLDEN_RUNTIME_PATH"


def _checkout(_root: Path) -> dict[str, object]:
    return {
        "available": True,
        "head": "a" * 40,
        "tree": "b" * 40,
        "fingerprint": "c" * 64,
        "status": "CLEAN",
        "errors": [],
    }


def test_phase3_adapter_preserves_blocked_status(
    adapter: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_gate(argv: list[str]) -> int:
        output = tmp_path / Path(argv[argv.index("--output") + 1])
        output.write_text(
            json.dumps({
                "status": "BLOCKED_EXTERNAL",
                "runtime_claim": False,
                "production_safe": False,
                "results": [],
            }),
            encoding="utf-8",
        )
        return 2

    monkeypatch.setattr(adapter, "RAW_OUTPUT", "raw.json")
    monkeypatch.setattr(adapter, "capture_checkout", _checkout)
    monkeypatch.setattr(adapter.golden_runtime_gate, "main", fake_gate)

    envelope = adapter.run(tmp_path, output="evidence.json")

    assert envelope["status"] == "BLOCKED_EXTERNAL"
    assert envelope["exit_status"] == 2
    assert envelope["production_safe"] is False
    assert (tmp_path / "evidence.json").is_file()
