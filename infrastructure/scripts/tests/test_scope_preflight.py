from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

SPEC = importlib.util.spec_from_file_location(
    "scope_preflight_under_test", Path(__file__).parents[1] / "scope_preflight.py"
)
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)
ROWS = [(name, 0) for name in sorted(preflight.CHECK_NAMES)]


def test_counts_require_exactly_the_four_aggregate_checks():
    assert preflight.counts(ROWS) == dict(ROWS)


@pytest.mark.parametrize("rows", [
    [], ROWS[:-1], ROWS + [ROWS[0]], ROWS + [("extra", 0)],
    [(ROWS[0][0], -1), *ROWS[1:]], [(ROWS[0][0], True), *ROWS[1:]],
    [(ROWS[0][0], 0.0), *ROWS[1:]], [(ROWS[0][0], "0"), *ROWS[1:]],
    [(ROWS[0][0], 0, "row content"), *ROWS[1:]], [None, *ROWS[1:]],
])
def test_counts_reject_missing_duplicate_unknown_and_malformed_results(rows):
    with pytest.raises(ValueError):
        preflight.counts(rows)


@pytest.mark.parametrize("identifier", ["", "../snapshot", "snapshot\nsecret", "x" * 129])
def test_invalid_snapshot_id_fails_before_database_access(identifier):
    with pytest.raises(ValueError, match="snapshot identifier"):
        preflight.inspect_scope("do not connect", identifier)


def test_cli_missing_dsn_does_not_use_implicit_external_configuration():
    env = {**os.environ, "RICK_EXTERNAL_DATABASE_DSN": "password=secret-dsn"}
    env.pop("RICK_PREFLIGHT_DATABASE_DSN", None)
    result = subprocess.run([sys.executable, str(preflight.__file__), "--snapshot-id", "synthetic"],
                            env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 2 and result.stdout == ""
    assert "RICK_PREFLIGHT_DATABASE_DSN is required" in result.stderr
    assert "secret-dsn" not in result.stderr


@pytest.mark.parametrize("status, exit_code", [("NO_CONFLICTS", 0), ("BLOCKED", 1)])
def test_cli_exit_status_and_json(monkeypatch, capsys, status, exit_code):
    monkeypatch.setattr(sys, "argv", ["scope_preflight.py", "--snapshot-id", "synthetic"])
    monkeypatch.setenv("RICK_PREFLIGHT_DATABASE_DSN", "synthetic-dsn")
    def inspect(dsn, identifier):
        assert (dsn, identifier) == ("synthetic-dsn", "synthetic")
        return {"status": status, "checks": dict(ROWS)}
    monkeypatch.setattr(preflight, "inspect_scope", inspect)
    assert preflight.main() == exit_code
    output = capsys.readouterr()
    assert json.loads(output.out)["status"] == status and output.err == ""


def test_connection_failure_redacts_diagnostics_and_limits_connection_time(monkeypatch, capsys):
    import psycopg
    def connect(dsn, **kwargs):
        assert dsn == "password=secret-dsn" and kwargs == {"connect_timeout": 5}
        raise psycopg.OperationalError("password=secret-dsn SQL and private row content")
    monkeypatch.setattr(psycopg, "connect", connect)
    monkeypatch.setattr(sys, "argv", ["scope_preflight.py", "--snapshot-id", "synthetic"])
    monkeypatch.setenv("RICK_PREFLIGHT_DATABASE_DSN", "password=secret-dsn")
    assert preflight.main() == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "scope preflight: scope preflight database error (SQLSTATE unknown)\n"


def test_local_sql_read_failure_does_not_expose_paths(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(preflight, "SQL_PATH", tmp_path / "sensitive-private-path.sql")
    monkeypatch.setattr(sys, "argv", ["scope_preflight.py", "--snapshot-id", "synthetic"])
    monkeypatch.setenv("RICK_PREFLIGHT_DATABASE_DSN", "do not connect")
    assert preflight.main() == 2
    output = capsys.readouterr()
    assert output.out == "" and output.err == "scope preflight: cannot read local SQL inputs\n"
