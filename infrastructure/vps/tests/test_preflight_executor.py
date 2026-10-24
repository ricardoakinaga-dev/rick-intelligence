from pathlib import Path

import preflight_executor as preflight
from contracts import Refusal


def test_preflight_reports_real_refusal_without_repair_or_false_lane_pass(tmp_path, monkeypatch):
    seen = []
    def refuse(path, *, private):
        seen.append(path)
        assert private is True
        assert path.resolve().is_relative_to(tmp_path.resolve())
        assert path.stat().st_mode & 0o777 == 0o600
        raise Refusal("unprotected input parent")
    monkeypatch.setattr(preflight, "capture", refuse)
    result = preflight.inspect_executor(tmp_path)
    assert result["status"] == "BLOCKED_EXTERNAL"
    assert result["capture"] == "REFUSED"
    assert result["lane_status"] == "NOT_RUN"
    assert result["reason"] == "unprotected input parent"
    assert result["parent_metadata"]
    assert not seen[0].exists()
    assert result["euid"] == preflight.os.geteuid()


def test_synthetic_success_still_does_not_certify_the_vps_lane(tmp_path, monkeypatch):
    # This models diagnostic rendering only, NOT a proof of real DAC/capture.
    monkeypatch.setattr(preflight, "capture", lambda path, *, private: path.read_bytes())
    result = preflight.inspect_executor(tmp_path)
    assert result["status"] == result["capture"] == "PASS"
    assert result["lane_status"] == "NOT_RUN"
    assert "complete VPS positive and negative lane" in result["next_action"]


def test_mismatched_synthetic_bytes_never_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(preflight, "capture", lambda path, *, private: b"other")
    assert preflight.inspect_executor(tmp_path)["status"] == "BLOCKED_EXTERNAL"


def test_missing_probe_directory_is_a_reported_blocker(tmp_path):
    result = preflight.inspect_executor(tmp_path / "missing")
    assert result["status"] == "BLOCKED_EXTERNAL"
    assert result["capture"] == result["lane_status"] == "NOT_RUN"


def test_default_probe_is_private_and_cli_uses_explicit_blocked_exit(monkeypatch, capsys):
    monkeypatch.setattr(preflight, "inspect_executor", lambda work_dir: {"status": "BLOCKED_EXTERNAL", "lane_status": "NOT_RUN"})
    monkeypatch.setattr(preflight.os, "chown", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not chown")))
    monkeypatch.setattr(preflight.os, "chmod", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not chmod")))
    monkeypatch.setattr("sys.argv", ["preflight_executor.py"])
    assert preflight.main() == 2
    assert '"NOT_RUN"' in capsys.readouterr().out
