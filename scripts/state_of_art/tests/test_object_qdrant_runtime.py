from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

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
    return _load("object_qdrant_runtime_gate_under_test", "scripts/phase11/object_qdrant_runtime_gate.py")


@pytest.fixture(scope="module")
def adapter() -> ModuleType:
    return _load("phase3_object_qdrant_adapter_under_test", "scripts/state_of_art/run_phase3_object_qdrant.py")


def test_missing_external_configuration_is_blocked_without_secret_output(
    gate: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    for name in (
        "RICK_TEST_QDRANT_URL",
        "RICK_QDRANT_URL",
        "QDRANT_URL",
        "RICK_TEST_OBJECT_STORE_ENDPOINT",
        "RICK_OBJECT_STORE_ENDPOINT",
        "OBJECT_STORAGE_ENDPOINT",
        "S3_ENDPOINT_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    gate.ROOT = tmp_path
    secret = "never-persist-this-secret"

    exit_code = gate.main(
        [
            "--output",
            "gate.json",
            "--qdrant-url",
            "",
            "--qdrant-api-key",
            secret,
            "--object-endpoint",
            "",
            "--object-bucket",
            "",
            "--object-region",
            "",
            "--object-access-key",
            secret,
            "--object-secret-key",
            secret,
        ]
    )

    payload = json.loads((tmp_path / "gate.json").read_text(encoding="utf-8"))
    rendered = (tmp_path / "gate.json").read_text(encoding="utf-8")
    assert exit_code == 2
    assert payload["status"] == "BLOCKED_EXTERNAL"
    assert payload["runtime_claim"] is False
    assert payload["production_safe"] is False
    assert secret not in rendered
    assert payload["object_gate"]["status"] == "BLOCKED_EXTERNAL"
    assert payload["vector_gate"]["status"] == "BLOCKED_EXTERNAL"


def test_endpoint_policy_is_fail_closed(gate: ModuleType) -> None:
    endpoint = gate._parse_endpoint("http://127.0.0.1:6333/", allow_nonlocal=False, require_tls=False)
    assert endpoint.raw == "http://127.0.0.1:6333"
    assert endpoint.report()["host_scope"] == "loopback"

    with pytest.raises(gate._BlockedExternal):
        gate._parse_endpoint("http://198.51.100.10:6333", allow_nonlocal=False, require_tls=False)
    with pytest.raises(gate._InvalidConfiguration):
        gate._parse_endpoint("http://user:password@127.0.0.1:6333", allow_nonlocal=False, require_tls=False)
    with pytest.raises(gate._InvalidConfiguration):
        gate._parse_endpoint("http://127.0.0.1:6333", allow_nonlocal=False, require_tls=True)


def test_response_body_bound_rejects_a_reader_that_exceeds_the_limit(gate: ModuleType) -> None:
    class Reader:
        def __init__(self, body: bytes) -> None:
            self.body = body

        def __call__(self, _size: int) -> bytes:
            body, self.body = self.body, b""
            return body

    assert gate._read_bounded(Reader(b"abc"), 3) == b"abc"
    with pytest.raises(gate._ResponseTooLarge):
        gate._read_bounded(Reader(b"abcd"), 3)


def test_qdrant_json_boundaries_reject_duplicate_fields(gate: ModuleType) -> None:
    response = gate._QdrantResponse(
        200,
        b'{"result":{"status":"ok"},"result":{"status":"ok","points":[{"id":"forged"}]}}',
        {},
    )
    with pytest.raises(RuntimeError, match="malformed"):
        gate._qdrant_json_body(response)

    transport = gate._QdrantTransport()
    transport._observe_filter(
        b'{"filter":{"must":[]},"filter":{"must":[{"key":"tenant_id","match":{"value":"forged"}}]}}'
    )
    assert transport.filter_observations == []


def test_qdrant_transport_records_only_scope_filter_shape(gate: ModuleType) -> None:
    transport = gate._QdrantTransport()
    transport._observe_filter(
        json.dumps(
            {
                "filter": {
                    "must": [
                        {"key": "tenant_id", "match": {"value": "tenant-a"}},
                        {"key": "workspace_id", "match": {"value": "workspace-a"}},
                        {"key": "collection_id", "match": {"any": ["collection-a"]}},
                    ]
                }
            }
        ).encode("utf-8")
    )

    assert gate._filter_observation_matches(transport, "tenant-a", "workspace-a", "collection-a")
    assert not gate._filter_observation_matches(transport, "tenant-b", "workspace-a", "collection-a")


def test_fault_policy_without_real_fault_services_stays_blocked(gate: ModuleType) -> None:
    args = SimpleNamespace(qdrant_fault_url="", qdrant_timeout_url="", allow_nonlocal=False, require_tls=False)
    results, blocked = gate._run_qdrant_failure_policy(
        args,
        gate._parse_endpoint("http://127.0.0.1:6333", allow_nonlocal=False, require_tls=False),
        "",
        "run-id",
    )

    assert blocked is True
    assert {item.name for item in results} == {"retry-circuit", "timeout"}
    assert all(item.result == "BLOCKED_EXTERNAL" for item in results)


def test_overall_status_never_upgrades_a_blocked_lane(gate: ModuleType) -> None:
    assert gate._overall_status({"status": "PASS"}, {"status": "BLOCKED_EXTERNAL"}) == "BLOCKED_EXTERNAL"
    assert gate._overall_status({"status": "PASS"}, {"status": "PASS"}) == "PASS"
    assert gate._overall_status({"status": "FAIL"}, {"status": "PASS"}) == "FAIL"


def test_phase3_adapter_forwards_real_fault_endpoints(adapter: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, object] = {}

    def fake_run(root: Path, *, output: str, argv: tuple[str, ...] | list[str]) -> dict[str, object]:
        observed["root"] = root
        observed["output"] = output
        observed["argv"] = list(argv)
        return {"status": "BLOCKED_EXTERNAL", "capability_id": "P0-07", "exit_status": 2}

    monkeypatch.setattr(adapter, "run", fake_run)
    exit_code = adapter.main(
        [
            "--output",
            "evidence.json",
            "--qdrant-url",
            "http://127.0.0.1:6333",
            "--qdrant-fault-url",
            "http://127.0.0.1:6334",
            "--qdrant-timeout-url",
            "http://127.0.0.1:6335",
        ]
    )

    assert exit_code == 2
    assert observed["output"] == "evidence.json"
    assert observed["argv"] == [
        "--qdrant-url",
        "http://127.0.0.1:6333",
        "--qdrant-fault-url",
        "http://127.0.0.1:6334",
        "--qdrant-timeout-url",
        "http://127.0.0.1:6335",
    ]


def test_runtime_gate_contains_real_boundary_and_no_local_fallback(gate: ModuleType) -> None:
    source = (ROOT / "scripts/phase11/object_qdrant_runtime_gate.py").read_text(encoding="utf-8")
    assert "_UrllibTransport" in source
    assert "_QdrantTransport" in source
    assert "S3ObjectStore" in source
    assert "QdrantHttpVectorStore" in source
    assert "InMemory" not in source
    assert "MockTransport" not in source
