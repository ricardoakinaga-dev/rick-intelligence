import json
from pathlib import Path

from scripts.state_of_art.triple_aaa_capability_matrix import (
    ALLOWED_STATES,
    EXPECTED_PROMPT,
    EXPECTED_PROMPT_SHA256,
    validate,
)


ROOT = Path(__file__).resolve().parents[3]


def test_current_matrix_has_only_prompt_states_and_required_columns():
    path = ROOT / "docs/reports/triple-aaa-runtime-capability-matrix.json"
    result = validate(path)
    assert result["status"] == "PASS", result
    assert result["rows"] >= 10
    assert "MISSING" not in ALLOWED_STATES

    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["prompt"] == EXPECTED_PROMPT
    assert document["prompt_sha256"] == EXPECTED_PROMPT_SHA256
    assert document["candidate_binding"]["packet"] == ".runtime/phase-3/triple-aaa-verify.json"
