from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest


SPEC = importlib.util.spec_from_file_location(
    "migrate_under_test", Path(__file__).parents[1] / "migrate.py"
)
migrate = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(migrate)


class FakeCursor:
    def __init__(self, history: list[tuple[str, str, str]], *, fail_on: str | None = None) -> None:
        self.history = history
        self.initial_history = list(history)
        self.fail_on = fail_on
        self.executed: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, query: str, params: tuple[object, ...] = ()) -> None:
        self.executed.append((query, params))
        if self.fail_on is not None and self.fail_on in query:
            raise RuntimeError("synthetic SQL failure")
        if query.startswith("INSERT INTO rick_schema_migrations"):
            version, checksum, application = params
            self.history.append((version, checksum, application))

    def fetchall(self) -> list[tuple[str, str, str]]:
        return list(self.history)

    def close(self) -> None:
        return None

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        return None


class FakeConnection:
    def __init__(self, history: list[tuple[str, str, str]], *, fail_on: str | None = None) -> None:
        self.history = history
        self.initial_history = list(history)
        self.cursor_instance = FakeCursor(history, fail_on=fail_on)
        self.rollbacks = 0

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, exc_type, _exc, _tb) -> None:
        if exc_type is not None:
            self.rollbacks += 1
            self.history[:] = self.initial_history

    def cursor(self) -> FakeCursor:
        return self.cursor_instance


class FakePsycopg(ModuleType):
    def __init__(self, connection: FakeConnection) -> None:
        super().__init__("psycopg")
        self.connection = connection

    def connect(self, _dsn: str) -> FakeConnection:
        return self.connection


def migration_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "migrations"
    directory.mkdir()
    (directory / "0001_first.sql").write_text("CREATE TABLE first();", encoding="utf-8")
    (directory / "0002_second.sql").write_text("CREATE TABLE second();", encoding="utf-8")
    return directory


def run_apply(monkeypatch: pytest.MonkeyPatch, directory: Path, connection: FakeConnection) -> None:
    monkeypatch.setitem(sys.modules, "psycopg", FakePsycopg(connection))
    migrate.apply(directory, "postgresql://synthetic")


def test_apply_records_only_after_all_sql_and_rejects_checksum_drift(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    directory = migration_dir(tmp_path)
    connection = FakeConnection([])
    run_apply(monkeypatch, directory, connection)
    assert [row[0] for row in connection.history] == ["0001", "0002"]

    drifted = FakeConnection([("0001", "wrong", migrate.APPLICATION)])
    monkeypatch.setitem(sys.modules, "psycopg", FakePsycopg(drifted))
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        migrate.apply(directory, "postgresql://synthetic")
    assert not any("CREATE TABLE second" in query for query, _params in drifted.cursor_instance.executed)


@pytest.mark.parametrize(
    ("history", "message"),
    [
        (["unknown"], "unknown version"),
        (["gap"], "gap"),
        (["application"], "application mismatch"),
    ],
)
def test_history_divergence_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    history: list[str],
    message: str,
) -> None:
    directory = migration_dir(tmp_path)
    checksums = {version: digest for version, _path, digest in migrate.migration_files(directory)}
    if history == ["unknown"]:
        rows = [("0003", "x", migrate.APPLICATION)]
    elif history == ["gap"]:
        rows = [("0002", checksums["0002"], migrate.APPLICATION)]
    else:
        rows = [("0001", checksums["0001"], "other-application")]
    connection = FakeConnection(rows)
    monkeypatch.setitem(sys.modules, "psycopg", FakePsycopg(connection))
    with pytest.raises(RuntimeError, match=message):
        migrate.apply(directory, "postgresql://synthetic")


def test_apply_exception_rolls_back_and_does_not_append_history(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    directory = migration_dir(tmp_path)
    connection = FakeConnection([], fail_on="CREATE TABLE second")
    monkeypatch.setitem(sys.modules, "psycopg", FakePsycopg(connection))
    with pytest.raises(RuntimeError, match="synthetic SQL failure"):
        migrate.apply(directory, "postgresql://synthetic")
    assert connection.rollbacks == 1
    assert connection.history == []
