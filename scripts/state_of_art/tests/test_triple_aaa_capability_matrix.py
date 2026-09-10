from pathlib import Path

from scripts.state_of_art.triple_aaa_capability_matrix import ALLOWED_STATES, validate


ROOT = Path(__file__).resolve().parents[3]


def test_current_matrix_has_only_prompt_states_and_required_columns():
    result = validate(ROOT / "docs/reports/triple-aaa-runtime-capability-matrix.json")
    assert result["status"] == "PASS", result
    assert result["rows"] >= 10
    assert "MISSING" not in ALLOWED_STATES
