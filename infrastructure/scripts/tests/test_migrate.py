from __future__ import annotations

import importlib.util
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from types import ModuleType
import uuid

import pytest


SPEC = importlib.util.spec_from_file_location(
    "migrate_under_test", Path(__file__).parents[1] / "migrate.py"
)
migrate = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(migrate)
PREFLIGHT_SPEC = importlib.util.spec_from_file_location(
    "scope_preflight_live_under_test", Path(__file__).parents[1] / "scope_preflight.py"
)
scope_preflight = importlib.util.module_from_spec(PREFLIGHT_SPEC)
PREFLIGHT_SPEC.loader.exec_module(scope_preflight)
ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS = ROOT / "infrastructure/migrations"


class FakeDatabaseError(Exception):
    sqlstate = "23514"


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

    def fetchall(self) -> list[tuple[object, ...]]:
        query = self.executed[-1][0] if self.executed else ""
        if "FROM pg_proc" in query:
            statements = {
                version: (MIGRATIONS / name).read_text(encoding="utf-8")
                for version, name in (("0004", "0004_durable_jobs_contract.sql"),
                                      ("0005", "0005_rewrite_legacy_jobs.sql"))
            }
            bodies = migrate.expected_job_function_sources(statements)
            names = self.executed[-1][1]
            return [(name, bodies[name], True, "plpgsql") for name in names]
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
    Error = FakeDatabaseError

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


@pytest.mark.parametrize("state", ["empty", "pre0005", "applied-old", "current"])
def test_supported_history_paths_preserve_recorded_checksums(monkeypatch, capsys, state) -> None:
    rows = migrate.migration_files(MIGRATIONS)
    count = {"empty": 0, "pre0005": 4, "applied-old": 5, "current": len(rows)}[state]
    history = [(version, digest, migrate.APPLICATION) for version, _path, digest in rows[:count]]
    if state == "applied-old":
        history[-1] = ("0005", migrate.LEGACY_REWRITE_ORIGINAL, migrate.APPLICATION)
    original = list(history)
    connection = FakeConnection(history)
    run_apply(monkeypatch, MIGRATIONS, connection)
    assert connection.history[:count] == original
    assert [row[0] for row in connection.history] == [row[0] for row in rows]
    queries = [query for query, _params in connection.cursor_instance.executed]
    assert "pg_advisory_xact_lock" in queries[0]
    assert not any(query.lstrip().startswith(("UPDATE rick_schema_migrations", "DELETE FROM rick_schema_migrations")) for query in queries)
    if state in {"applied-old", "current"}:
        assert not any("CREATE OR REPLACE FUNCTION rick_require_canonical_job_write" in query for query in queries)
    if state == "applied-old":
        assert "recognized historical checksum retained" in capsys.readouterr().out
        guard = next(i for i, query in enumerate(queries) if "DO $q24_verify$" in query)
        lineage = next(i for i, query in enumerate(queries) if "ADD COLUMN IF NOT EXISTS ingestion_version" in query)
        assert guard < lineage


@pytest.mark.parametrize("field", ["version", "filename", "local", "recorded"])
def test_compatibility_does_not_accept_other_artifacts(field) -> None:
    args = ["0005", Path(migrate.LEGACY_REWRITE_NAME), migrate.LEGACY_REWRITE_CURRENT, migrate.LEGACY_REWRITE_ORIGINAL]
    args[{"version": 0, "filename": 1, "local": 2, "recorded": 3}[field]] = Path("0005_other.sql") if field == "filename" else "unknown"
    assert not migrate.compatible_checksum(*args)


@pytest.mark.parametrize("history", [
    [("0001", "x")],
    [("0001", None, migrate.APPLICATION)],
    [("bad-version", "x", migrate.APPLICATION)],
    [("0001", "x", migrate.APPLICATION), ("0001", "x", migrate.APPLICATION)],
])
def test_malformed_or_duplicate_history_is_rejected(tmp_path, history) -> None:
    with pytest.raises(RuntimeError, match="malformed|duplicate"):
        migrate.validate_history(migrate.migration_files(migration_dir(tmp_path)), history)


def test_legacy_compatibility_does_not_mask_other_checksum_drift(monkeypatch) -> None:
    rows = migrate.migration_files(MIGRATIONS)
    history = [(version, digest, migrate.APPLICATION) for version, _path, digest in rows[:5]]
    history[3] = ("0004", migrate.LEGACY_REWRITE_ORIGINAL, migrate.APPLICATION)
    history[4] = ("0005", migrate.LEGACY_REWRITE_ORIGINAL, migrate.APPLICATION)
    connection = FakeConnection(history)
    with pytest.raises(RuntimeError, match="checksum mismatch for migration 0004"):
        run_apply(monkeypatch, MIGRATIONS, connection)
    assert not any("DO $q24_verify$" in query for query, _ in connection.cursor_instance.executed)


@pytest.mark.parametrize("checker", ["migrate.py", "check-migration-order.py"])
@pytest.mark.parametrize("defect", ["missing", "empty", "gap", "duplicate", "filename", "tampered0005", "renamed0005"])
def test_offline_validators_reject_invalid_sources(tmp_path, checker, defect) -> None:
    directory = tmp_path / "migrations"
    if defect != "missing":
        directory.mkdir()
    if defect == "gap":
        (directory / "0002_only.sql").write_text("SELECT 1;")
    elif defect == "duplicate":
        (directory / "0001_one.sql").write_text("SELECT 1;")
        (directory / "0001_two.sql").write_text("SELECT 2;")
    elif defect == "filename":
        (directory / "invalid.sql").write_text("SELECT 1;")
    elif defect in {"tampered0005", "renamed0005"}:
        shutil.copytree(MIGRATIONS, directory, dirs_exist_ok=True)
        if defect == "tampered0005":
            with (directory / migrate.LEGACY_REWRITE_NAME).open("a") as stream:
                stream.write("\n-- unreviewed change\n")
        else:
            (directory / migrate.LEGACY_REWRITE_NAME).rename(directory / "0005_renamed.sql")
    command = [sys.executable, str(ROOT / "infrastructure/scripts" / checker), str(directory)]
    if checker == "migrate.py":
        command.append("--check")
    result = subprocess.run(command, capture_output=True, text=True, timeout=10)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "PASS" not in result.stdout


def test_execution_uses_checked_bytes_and_rejects_discovery_race(monkeypatch, tmp_path) -> None:
    directory = migration_dir(tmp_path)
    original = migrate.migration_files

    def change_after_discovery(path):
        rows = original(path)
        (path / "0002_second.sql").write_text("SELECT 'unreviewed';")
        return rows

    monkeypatch.setattr(migrate, "migration_files", change_after_discovery)
    connection = FakeConnection([])
    with pytest.raises(RuntimeError, match="changed during checksum validation"):
        run_apply(monkeypatch, directory, connection)
    assert not connection.cursor_instance.executed


def test_failed_transaction_does_not_report_applied_or_pass(monkeypatch, tmp_path, capsys) -> None:
    connection = FakeConnection([], fail_on="CREATE TABLE second")
    with pytest.raises(RuntimeError, match="synthetic SQL failure"):
        run_apply(monkeypatch, migration_dir(tmp_path), connection)
    output = capsys.readouterr().out
    assert ": applied" not in output
    assert "PASS" not in output


def test_database_error_redacts_driver_diagnostics(monkeypatch, tmp_path) -> None:
    class FailingDriver(FakePsycopg):
        def connect(self, _dsn):
            raise FakeDatabaseError("synthetic-private-driver-detail")

    monkeypatch.setitem(sys.modules, "psycopg", FailingDriver(FakeConnection([])))
    with pytest.raises(RuntimeError, match="SQLSTATE 23514") as error:
        migrate.apply(migration_dir(tmp_path), "postgresql://synthetic")
    assert "synthetic-private-driver-detail" not in str(error.value)


def historical_0005() -> bytes:
    """Reconstitute the Git blob, then prove byte identity before executing it.

    Keeping the four inverse replacements avoids duplicating the 27 KB source.
    The independently recorded Git SHA-256 makes fixture drift a hard failure.
    """
    sql = (MIGRATIONS / "0005_rewrite_legacy_jobs.sql").read_text()
    sql = sql.replace("(SELECT count(*) FROM jsonb_object_keys(target_payload))", "jsonb_object_length(target_payload)")
    sql = sql.replace("(SELECT count(*) FROM jsonb_object_keys(target_result -> 'output_refs'))", "jsonb_object_length(target_result -> 'output_refs')")
    sql = sql.replace("[A-Za-z0-9_.:/@?=&%+~,\\-]*$", "[A-Za-z0-9_.:/@?=&%+~,\\-]{0,511}$")
    source = sql.encode("utf-8")
    assert hashlib.sha256(source).hexdigest() == "d577b70fb1af2790851c0f42d50d2269e80da412405cff2dfde53d63bb873a03"
    return source


def test_historical_fixture_matches_inspected_git_blob() -> None:
    historical_0005()


def historical_0004() -> bytes:
    source = (MIGRATIONS / "0004_durable_jobs_contract.sql").read_text().replace(
        "CHECK (operation ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$');",
        "CHECK (length(operation) BETWEEN 1 AND 64);",
    ).encode("utf-8")
    assert hashlib.sha256(source).hexdigest() == "9ddcde2578d7c829a4efcba6db33fd37c7781b753f3676198a653f133436db8d"
    return source


def test_historical0004_fixture_and_decision_match_git_provenance() -> None:
    original = hashlib.sha256(historical_0004()).hexdigest()
    rows = migrate.migration_files(MIGRATIONS)
    applied = [(version, original if version == "0004" else digest, migrate.APPLICATION)
               for version, _path, digest in rows[:4]]
    assert migrate.validate_history(rows, applied)["0004"] == original
    for bad_version, bad_path, bad_digest, bad_recorded in [
        ("0005", Path(migrate.JOBS_CONTRACT_NAME), migrate.JOBS_CONTRACT_CURRENT, original),
        ("0004", Path("0004_other.sql"), migrate.JOBS_CONTRACT_CURRENT, original),
        ("0004", Path(migrate.JOBS_CONTRACT_NAME), "f" * 64, original),
        ("0004", Path(migrate.JOBS_CONTRACT_NAME), migrate.JOBS_CONTRACT_CURRENT, "f" * 64),
    ]:
        assert not migrate.compatible_checksum(bad_version, bad_path, bad_digest, bad_recorded)


@pytest.mark.parametrize("checker", ["migrate.py", "check-migration-order.py"])
@pytest.mark.parametrize("defect", ["missing-repair", "tampered-repair", "tampered0004", "renamed0004"])
def test_offline_historical0004_support_requires_pinned_artifacts(tmp_path, checker, defect) -> None:
    directory = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS, directory)
    if defect == "missing-repair":
        (directory / migrate.OPERATION_REPAIR_NAME).unlink()
    elif defect == "renamed0004":
        (directory / migrate.JOBS_CONTRACT_NAME).rename(directory / "0004_other.sql")
    else:
        path = directory / (migrate.OPERATION_REPAIR_NAME if defect == "tampered-repair" else migrate.JOBS_CONTRACT_NAME)
        with path.open("a") as stream:
            stream.write("\n-- unreviewed\n")
    command = [sys.executable, str(ROOT / "infrastructure/scripts" / checker), str(directory)]
    if checker == "migrate.py":
        command.append("--check")
    result = subprocess.run(command, capture_output=True, text=True, timeout=10)
    assert result.returncode == 2
    assert "PASS" not in result.stdout


@pytest.fixture(scope="module")
def postgres_cluster(tmp_path_factory):
    """Opt-in live tests always provision their own disposable PostgreSQL.

    No caller-provided DSN, existing database, network, or volume is accepted.
    The only port is dynamically assigned on loopback. Teardown verifies the
    unique ownership label before removing this container and its volumes.
    """
    if os.environ.get("RICK_MIGRATION_POSTGRES_TESTS") != "1":
        pytest.skip("set RICK_MIGRATION_POSTGRES_TESTS=1 for disposable Docker PostgreSQL")
    import psycopg

    assert shutil.which("docker"), "live tests explicitly requested but Docker is unavailable"
    run_id = "rick-q24-migration-" + uuid.uuid4().hex
    image = os.environ.get("RICK_MIGRATION_POSTGRES_IMAGE", "postgres:16-alpine")
    log_root = os.environ.get("RICK_MIGRATION_TEST_LOG_DIR")
    logs = (Path(log_root) if log_root else tmp_path_factory.mktemp("migration-logs")) / run_id
    logs.mkdir(parents=True, exist_ok=False)

    def docker(*args, check=True, input=None):
        command = ["docker", *args]
        result = subprocess.run(command, input=input, capture_output=True, timeout=45)
        record = {"command": command, "exit": result.returncode}
        with (logs / "docker-commands.jsonl").open("a") as stream:
            stream.write(json.dumps(record) + "\n")
        if check and result.returncode:
            pytest.fail(f"Docker command failed ({result.returncode}); see {logs}")
        return result

    docker("image", "inspect", image, "--format", "{{.Id}}")
    try:
        result = docker(
            "run", "--detach", "--rm", "--name", run_id,
            "--label", f"rick.q24.migration={run_id}",
            "--cpus", "1", "--memory", "512m", "--pids-limit", "256",
            "--tmpfs", "/var/lib/postgresql/data:rw,size=256m",
            "--publish", "127.0.0.1::5432",
            "--env", "POSTGRES_HOST_AUTH_METHOD=trust", image,
            "-c", f"cluster_name={run_id}",
            "-c", "shared_buffers=32MB", "-c", "max_connections=32",
        )
        container_id = result.stdout.decode().strip()
        address = docker("port", container_id, "5432/tcp").stdout.decode().strip()
        assert address.startswith("127.0.0.1:") and "\n" not in address
        port = int(address.rsplit(":", 1)[1])
        dsn = f"host=127.0.0.1 port={port} user=postgres dbname=postgres connect_timeout=2"
        deadline = time.monotonic() + 30
        while True:
            try:
                with psycopg.connect(dsn) as connection:
                    assert connection.execute("SHOW cluster_name").fetchone()[0] == run_id
                    version = connection.execute("SHOW server_version").fetchone()[0]
                break
            except psycopg.OperationalError:
                if time.monotonic() >= deadline:
                    pytest.fail(f"owned PostgreSQL did not become ready; see {logs}")
                time.sleep(0.2)
        resource = {
            "run_id": run_id, "container_id": container_id,
            "image": image, "server_version": version, "loopback_port": port,
            "image_id": docker("inspect", container_id, "--format", "{{.Image}}").stdout.decode().strip(),
            "memory_bytes": 536870912, "cpus": 1, "tmpfs_bytes": 268435456,
            "readiness_limit_seconds": 30, "command_limit_seconds": 45,
        }
        (logs / "resource.json").write_text(json.dumps(resource, indent=2) + "\n")
        yield {"dsn": dsn, "logs": logs, "container_id": container_id, "docker": docker}
    finally:
        observed = docker("inspect", run_id, "--format", '{{index .Config.Labels "rick.q24.migration"}}', check=False)
        if observed.returncode == 0:
            assert observed.stdout.decode().strip() == run_id, "refusing to remove resource without ownership label"
            output = docker("logs", run_id, check=False)
            (logs / "postgres.log").write_bytes(output.stdout + output.stderr)
            docker("rm", "--force", "--volumes", run_id)
        remaining = docker("ps", "--all", "--quiet", "--filter", f"label=rick.q24.migration={run_id}")
        assert not remaining.stdout.strip(), "owned PostgreSQL container survived teardown"
        (logs / "teardown.json").write_text(json.dumps({"run_id": run_id, "remaining_containers": 0}) + "\n")


@pytest.fixture
def postgres_db(postgres_cluster):
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    name = "q24_" + uuid.uuid4().hex
    with psycopg.connect(postgres_cluster["dsn"], autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    dsn = make_conninfo(postgres_cluster["dsn"], dbname=name, options="-c statement_timeout=10000 -c lock_timeout=5000")
    try:
        yield dsn
    finally:
        with psycopg.connect(postgres_cluster["dsn"], autocommit=True) as connection:
            connection.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def query(dsn, statement, params=()):
    import psycopg

    with psycopg.connect(dsn) as connection:
        cursor = connection.execute(statement, params)
        return cursor.fetchall() if cursor.description else []


def install_snapshot(dsn, through, *, start=1, original=False, original4=False):
    """Execute actual old/current SQL before recording its real digest.

    This fixture does not retrofit a checksum onto a differently executed SQL
    file. All DDL and ledger inserts share the historical transaction boundary.
    """
    import psycopg

    with psycopg.connect(dsn) as connection:
        for path in sorted(MIGRATIONS.glob("*.sql")):
            version = path.name[:4]
            if not start <= int(version) <= through:
                continue
            source = historical_0005() if original and version == "0005" else path.read_bytes()
            if original4 and version == "0004":
                source = historical_0004()
            connection.execute(source.decode("utf-8"))
            connection.execute(
                "INSERT INTO rick_schema_migrations(version,checksum,application) VALUES (%s,%s,%s)",
                (version, hashlib.sha256(source).hexdigest(), migrate.APPLICATION),
            )


def seed_scope(dsn):
    query(dsn, """
        INSERT INTO rick_tenants(tenant_id,display_name) VALUES ('tenant','Synthetic tenant');
        INSERT INTO rick_users(user_id,email) VALUES ('user','synthetic@example.invalid');
        INSERT INTO rick_memberships(tenant_id,user_id,workspace_id,role,authorized_collection_ids)
            VALUES ('tenant','user','workspace','VETERINARIAN','["collection"]');
        INSERT INTO rick_collections(tenant_id,workspace_id,collection_id,title,created_by)
            VALUES ('tenant','workspace','collection','Synthetic collection','user');
        INSERT INTO rick_collection_grants(tenant_id,workspace_id,collection_id,user_id,granted_by)
            VALUES ('tenant','workspace','collection','user','user');
        INSERT INTO rick_documents(document_id,tenant_id,workspace_id,collection_id,document_version,
            content_checksum,object_key,byte_size,title,display_filename,mime_type,status,
            parser_version,chunker_version,embedding_model,embedding_version,created_by)
            VALUES ('document','tenant','workspace','collection','v1','synthetic-checksum',
                'objects/synthetic','12','Synthetic','Guia clínico.pdf','application/pdf','published',
                'p1','c1','synthetic','e1','user');
    """)


def seed_job(dsn, job_id, *, status="queued", attempts=0, canonical=False, active=False, payload=None, result=None):
    from psycopg.types.json import Jsonb

    query(dsn, """
        INSERT INTO rick_ingestion_jobs(job_id,idempotency_key,tenant_id,workspace_id,collection_id,
            document_id,status,attempts,created_at,updated_at,available_at,payload,result,
            contract_state,lease_owner,lease_until)
        VALUES (%s,%s,'tenant','workspace','collection','document',%s,%s,
            '2026-01-01 00:00:00+00','2026-01-01 00:01:00+00','2026-01-01 00:00:00+00',
            %s,%s,%s,%s,CASE WHEN %s THEN NOW()+INTERVAL '1 hour' ELSE '2026-01-01 00:00:30+00'::timestamptz END)
    """, (
        job_id, job_id, status, attempts,
        Jsonb(payload if payload is not None else {"source_key": "objects/synthetic", "display_filename": "Guia clínico.pdf", "byte_size": "12"}),
        Jsonb(result) if result is not None else None, "QUEUED" if canonical else None,
        "worker-1:lease-1" if status in {"leased", "processing"} else None, active,
    ))


def snapshot(dsn):
    from psycopg import sql

    tables = query(dsn, "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
    data = {}
    for (table,) in tables:
        data[table] = query(dsn, sql.SQL("SELECT row_to_json(t)::text FROM {} t ORDER BY row_to_json(t)::text").format(sql.Identifier(table)))
    data["_triggers"] = query(dsn, "SELECT tgname,tgenabled,pg_get_triggerdef(oid) FROM pg_trigger WHERE NOT tgisinternal ORDER BY tgname")
    data["_constraints"] = query(dsn, """SELECT c.conrelid::regclass::text,c.conname,c.convalidated,pg_get_constraintdef(c.oid)
        FROM pg_constraint c JOIN pg_namespace n ON c.connamespace=n.oid
        WHERE n.nspname='public' ORDER BY c.conrelid::regclass::text,c.conname""")
    return data


def history(dsn):
    return query(dsn, "SELECT version,checksum,application,applied_at FROM rick_schema_migrations ORDER BY version")


def test_postgres_empty_install_and_repeat(postgres_db):
    assert migrate.apply(MIGRATIONS, postgres_db) == 0
    assert len(history(postgres_db)) == len(migrate.migration_files(MIGRATIONS))
    before = snapshot(postgres_db)
    assert migrate.apply(MIGRATIONS, postgres_db) == 0
    assert snapshot(postgres_db) == before


def test_postgres_0008_rejects_cross_scope_relations_and_keeps_valid_rows(postgres_db):
    import psycopg

    assert migrate.apply(MIGRATIONS, postgres_db) == 0
    seed_scope(postgres_db)
    query(postgres_db, """
        INSERT INTO rick_collections(tenant_id,workspace_id,collection_id,title,created_by)
        VALUES ('tenant','workspace','other','Other collection','user');
        INSERT INTO rick_memberships(tenant_id,user_id,workspace_id,role,authorized_collection_ids)
        VALUES ('tenant','user','other-workspace','VETERINARIAN','[]');
    """)
    query(postgres_db, """
        INSERT INTO rick_chunks(chunk_id,document_id,tenant_id,workspace_id,collection_id,
            chunk_index,text,checksum,embedding_version,index_version)
        VALUES ('valid-chunk','document','tenant','workspace','collection',0,'synthetic','hash','e1','i1')
    """)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        query(postgres_db, """
            INSERT INTO rick_chunks(chunk_id,document_id,tenant_id,workspace_id,collection_id,
                chunk_index,text,checksum,embedding_version,index_version)
            VALUES ('invalid-chunk','document','tenant','workspace','other',1,'synthetic','hash','e1','i1')
        """)
    seed_job(postgres_db, 'valid-job', canonical=True, payload={'source_key': 'objects/synthetic'})
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        query(postgres_db, "UPDATE rick_ingestion_jobs SET collection_id='other' WHERE job_id='valid-job'")
    query(postgres_db, """
        INSERT INTO rick_conversations(conversation_id,tenant_id,workspace_id,user_id,collection_id,title)
        VALUES ('valid-conversation','tenant','workspace','user','collection','Synthetic')
    """)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        query(postgres_db, """
            INSERT INTO rick_conversations(conversation_id,tenant_id,workspace_id,user_id,collection_id,title)
            VALUES ('invalid-conversation','tenant','other-workspace','user','collection','Synthetic')
        """)
    query(postgres_db, """
        INSERT INTO rick_messages(message_id,conversation_id,tenant_id,workspace_id,user_id,role,content)
        VALUES ('valid-message','valid-conversation','tenant','workspace','user','user','Synthetic')
    """)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        query(postgres_db, """
            INSERT INTO rick_messages(message_id,conversation_id,tenant_id,workspace_id,user_id,role,content)
            VALUES ('invalid-message','valid-conversation','tenant','other-workspace','user','user','Synthetic')
        """)
    assert query(postgres_db, 'SELECT COUNT(*) FROM rick_chunks') == [(1,)]
    assert query(postgres_db, 'SELECT COUNT(*) FROM rick_messages') == [(1,)]
    preflight = (ROOT / 'docs/operations/0008-scope-preflight.sql').read_text()
    assert dict(query(postgres_db, preflight)) == {
        'chunks_document_scope': 0,
        'jobs_document_scope': 0,
        'conversations_collection_scope': 0,
        'messages_conversation_scope': 0,
    }


@pytest.mark.parametrize(("defect", "constraint_sql"), [
    (
        "wrong-type",
        "ALTER TABLE rick_chunks ADD CONSTRAINT rick_chunks_document_scope_fkey "
        "CHECK (chunk_index >= 0)",
    ),
    (
        "wrong-definition",
        "ALTER TABLE rick_chunks ADD CONSTRAINT rick_chunks_document_scope_fkey "
        "FOREIGN KEY (document_id) REFERENCES rick_documents (document_id)",
    ),
    (
        "not-valid",
        "ALTER TABLE rick_chunks ADD CONSTRAINT rick_chunks_document_scope_fkey "
        "FOREIGN KEY (tenant_id, workspace_id, collection_id, document_id) "
        "REFERENCES rick_documents (tenant_id, workspace_id, collection_id, document_id) NOT VALID",
    ),
])
def test_postgres_0008_rejects_incompatible_same_name_constraints_without_advancing(
    postgres_db, defect, constraint_sql,
):
    install_snapshot(postgres_db, 7)
    query(postgres_db, constraint_sql)
    before = snapshot(postgres_db)
    before_history = history(postgres_db)

    with pytest.raises(RuntimeError, match="SQLSTATE P0001"):
        migrate.apply(MIGRATIONS, postgres_db)

    assert snapshot(postgres_db) == before
    assert history(postgres_db) == before_history
    assert [row[0] for row in history(postgres_db)] == [
        "0001", "0002", "0003", "0004", "0005", "0006", "0007",
    ]


def test_postgres_0008_rejects_incompatible_0004_prerequisite_without_advancing(postgres_db):
    # Seed the wrong same-name object before immutable migration 0004 runs.
    # Its legacy duplicate_object handler leaves it in place; 0008 must expose
    # that it is not the required validated foreign key.
    install_snapshot(postgres_db, 3)
    query(postgres_db, """
        ALTER TABLE rick_ingestion_jobs
        ADD CONSTRAINT rick_ingestion_jobs_document_scope_fkey
        CHECK (job_id IS NOT NULL)
    """)
    install_snapshot(postgres_db, 7, start=4)
    before = snapshot(postgres_db)
    before_history = history(postgres_db)

    with pytest.raises(RuntimeError, match="SQLSTATE P0001"):
        migrate.apply(MIGRATIONS, postgres_db)

    assert snapshot(postgres_db) == before
    assert history(postgres_db) == before_history
    assert [row[0] for row in history(postgres_db)] == [
        "0001", "0002", "0003", "0004", "0005", "0006", "0007",
    ]


def test_postgres_0008_rejects_existing_cross_scope_rows_without_history_update(postgres_db):
    install_snapshot(postgres_db, 7)
    seed_scope(postgres_db)
    query(postgres_db, """
        INSERT INTO rick_collections(tenant_id,workspace_id,collection_id,title,created_by)
        VALUES ('tenant','workspace','other','Other collection','user');
        INSERT INTO rick_chunks(chunk_id,document_id,tenant_id,workspace_id,collection_id,
            chunk_index,text,checksum,embedding_version,index_version)
        VALUES ('invalid-chunk','document','tenant','workspace','other',0,'synthetic','hash','e1','i1')
    """)
    before = snapshot(postgres_db)
    preflight = (ROOT / 'docs/operations/0008-scope-preflight.sql').read_text()
    assert dict(query(postgres_db, preflight))['chunks_document_scope'] == 1
    with pytest.raises(RuntimeError, match='SQLSTATE 23503'):
        migrate.apply(MIGRATIONS, postgres_db)
    assert snapshot(postgres_db) == before
    assert [row[0] for row in history(postgres_db)] == ['0001', '0002', '0003', '0004', '0005', '0006', '0007']


def preflight_cli(dsn, identifier="synthetic-pre0008"):
    return subprocess.run(
        [sys.executable, str(scope_preflight.__file__), "--snapshot-id", identifier],
        env={**os.environ, "RICK_PREFLIGHT_DATABASE_DSN": dsn},
        capture_output=True, text=True, timeout=25,
    )


def test_postgres_scope_preflight_clean_snapshot_is_read_only_and_repeatable(postgres_db, postgres_cluster):
    install_snapshot(postgres_db, 7)
    seed_scope(postgres_db)
    before = snapshot(postgres_db)
    for _ in range(2):
        result = preflight_cli(postgres_db)
        assert result.returncode == 0 and result.stderr == ""
        record = json.loads(result.stdout)
        assert record["status"] == "NO_CONFLICTS"
        assert record["snapshot_id"] == "synthetic-pre0008"
        assert record["transaction"] == {"read_only": True, "isolation_level": "repeatable read"}
        assert record["checks"] == dict.fromkeys(scope_preflight.CHECK_NAMES, 0)
        assert record["sql_sha256"] == hashlib.sha256(scope_preflight.SQL_PATH.read_bytes()).hexdigest()
        assert record["local_migration_sha256"] == hashlib.sha256(scope_preflight.MIGRATION_PATH.read_bytes()).hexdigest()
        assert "synthetic@example.invalid" not in result.stdout and postgres_db not in result.stdout
        assert snapshot(postgres_db) == before
        (postgres_cluster["logs"] / "scope-preflight-clean.json").write_text(result.stdout)
    assert len(history(postgres_db)) == 7


def test_postgres_scope_preflight_reports_all_four_conflicts_without_repair(postgres_db, postgres_cluster):
    install_snapshot(postgres_db, 7)
    seed_scope(postgres_db)
    query(postgres_db, """
        INSERT INTO rick_collections(tenant_id,workspace_id,collection_id,title,created_by)
        VALUES ('tenant','workspace','other','Other','user');
        INSERT INTO rick_memberships(tenant_id,user_id,workspace_id,role,authorized_collection_ids)
        VALUES ('tenant','user','other-workspace','VETERINARIAN','[]');
        INSERT INTO rick_chunks(chunk_id,document_id,tenant_id,workspace_id,collection_id,
            chunk_index,text,checksum,embedding_version,index_version)
        VALUES ('invalid-chunk','document','tenant','workspace','other',0,'PRIVATE ROW','hash','e1','i1');
        ALTER TABLE rick_ingestion_jobs DROP CONSTRAINT rick_ingestion_jobs_document_scope_fkey;
    """)
    seed_job(postgres_db, 'invalid-job', canonical=True)
    query(postgres_db, """
        UPDATE rick_ingestion_jobs SET collection_id='other' WHERE job_id='invalid-job';
        INSERT INTO rick_conversations(conversation_id,tenant_id,workspace_id,user_id,collection_id,title)
        VALUES ('invalid-conversation','tenant','other-workspace','user','collection','PRIVATE TITLE');
        INSERT INTO rick_messages(message_id,conversation_id,tenant_id,workspace_id,user_id,role,content)
        VALUES ('invalid-message','invalid-conversation','tenant','workspace','user','user','PRIVATE CONTENT');
    """)
    before = snapshot(postgres_db)
    result = preflight_cli(postgres_db)
    assert result.returncode == 1 and result.stderr == ""
    record = json.loads(result.stdout)
    assert record["status"] == "BLOCKED"
    assert record["checks"] == dict.fromkeys(scope_preflight.CHECK_NAMES, 1)
    assert "PRIVATE" not in result.stdout and postgres_db not in result.stdout
    assert snapshot(postgres_db) == before
    (postgres_cluster["logs"] / "scope-preflight-blocked.json").write_text(result.stdout)


def test_postgres_scope_preflight_cannot_write_even_with_privileged_connection(postgres_db, monkeypatch, tmp_path):
    install_snapshot(postgres_db, 7)
    seed_scope(postgres_db)
    source = tmp_path / 'attempted-write.sql'
    source.write_text("UPDATE rick_documents SET title='unexpected mutation';")
    monkeypatch.setattr(scope_preflight, 'SQL_PATH', source)
    before = snapshot(postgres_db)
    with pytest.raises(RuntimeError, match='SQLSTATE 25006'):
        scope_preflight.inspect_scope(postgres_db, 'synthetic-write-probe')
    assert snapshot(postgres_db) == before


def test_postgres_scope_preflight_missing_schema_is_error_not_zero_counts(postgres_db):
    result = preflight_cli(postgres_db)
    assert result.returncode == 2 and result.stdout == ""
    assert "SQLSTATE 42P01" in result.stderr and postgres_db not in result.stderr
    assert snapshot(postgres_db) == {"_triggers": [], "_constraints": []}


def test_postgres_scope_preflight_lock_wait_is_bounded_and_redacted(postgres_db):
    import psycopg

    install_snapshot(postgres_db, 7)
    before = snapshot(postgres_db)
    with psycopg.connect(postgres_db) as connection:
        connection.execute("LOCK TABLE rick_chunks IN ACCESS EXCLUSIVE MODE")
        started = time.monotonic()
        result = preflight_cli(postgres_db)
        elapsed = time.monotonic() - started
        assert result.returncode == 2 and result.stdout == ""
        assert "SQLSTATE 55P03" in result.stderr and postgres_db not in result.stderr
        assert 4 <= elapsed < 15
    assert snapshot(postgres_db) == before


def test_postgres_scope_preflight_make_command_uses_explicit_snapshot(postgres_db):
    install_snapshot(postgres_db, 7)
    result = subprocess.run(
        ["make", "ops-scope-preflight", f"PYTHON={sys.executable}"], cwd=ROOT,
        env={**os.environ, "RICK_PREFLIGHT_DATABASE_DSN": postgres_db,
             "RICK_PREFLIGHT_SNAPSHOT_ID": "synthetic-make-snapshot"},
        capture_output=True, text=True, timeout=25,
    )
    assert result.returncode == 0 and result.stderr == ""
    assert json.loads(result.stdout)["snapshot_id"] == "synthetic-make-snapshot"
    assert len(history(postgres_db)) == 7


def test_postgres_pre0005_preserves_data_attempts_projections_and_permissions(postgres_db):
    import base64
    import psycopg

    install_snapshot(postgres_db, 4)
    seed_scope(postgres_db)
    cases = [
        ("queued", "queued", 0, False, "QUEUED"),
        ("retry", "failed", 2, False, "QUEUED"),
        ("exhausted", "failed", 3, False, "DEAD_LETTER"),
        ("dead", "dead", 1, False, "DEAD_LETTER"),
        ("cancelled", "cancelled", 1, False, "CANCELLED"),
        ("published", "published", 2, False, "SUCCEEDED"),
        ("running", "processing", 1, True, "RUNNING"),
        ("expired", "leased", 1, False, "QUEUED"),
        ("queued-exhausted", "queued", 3, False, "DEAD_LETTER"),
    ]
    for job_id, status, attempts, active, _state in cases:
        seed_job(postgres_db, job_id, status=status, attempts=attempts, active=active)
    before = snapshot(postgres_db)
    old_history = history(postgres_db)
    assert migrate.apply(MIGRATIONS, postgres_db) == 0
    assert history(postgres_db)[:4] == old_history
    after = snapshot(postgres_db)
    for table in ("rick_tenants", "rick_users", "rick_memberships", "rick_collections", "rick_collection_grants"):
        assert after[table] == before[table]
    for job_id, _status, attempts, _active, state in cases:
        row = query(postgres_db, "SELECT contract_state,attempts,payload FROM rick_ingestion_jobs WHERE job_id=%s", (job_id,))[0]
        assert row[:2] == (state, attempts)
        assert base64.b64decode(row[2]["filename_ref"]).decode() == "Guia clínico.pdf"
        assert "display_filename" not in row[2]
        assert query(postgres_db, "SELECT count(*) FROM rick_ingestion_job_attempts WHERE job_id=%s", (job_id,))[0][0] == attempts
    for table in ("rick_ingestion_job_events", "rick_outbox", "rick_audit_events"):
        assert len(after[table]) == len(cases)
    assert query(postgres_db, "SELECT ingestion_version,object_ref,published_at FROM rick_documents")[0] == ("v1", "objects/synthetic", None)
    assert migrate.apply(MIGRATIONS, postgres_db) == 0
    assert snapshot(postgres_db) == after
    with pytest.raises(psycopg.Error):
        seed_job(postgres_db, "forbidden-legacy")
    with pytest.raises(psycopg.Error):
        query(postgres_db, "DELETE FROM rick_ingestion_job_attempts WHERE job_id='published'")
    assert snapshot(postgres_db) == after


@pytest.mark.parametrize("canonical_rows", [False, True])
def test_postgres_already_applied_old0005_retains_its_real_checksum(postgres_db, canonical_rows, capsys):
    install_snapshot(postgres_db, 4)
    seed_scope(postgres_db)
    if canonical_rows:
        seed_job(postgres_db, "canonical", canonical=True, payload={"source_key": "objects/synthetic"})
    install_snapshot(postgres_db, 5, start=5, original=True)
    previous = history(postgres_db)
    previous_jobs = snapshot(postgres_db)["rick_ingestion_jobs"]
    assert previous[-1][1] == migrate.LEGACY_REWRITE_ORIGINAL
    assert migrate.apply(MIGRATIONS, postgres_db) == 0
    assert "recognized historical checksum retained" in capsys.readouterr().out
    assert history(postgres_db)[:5] == previous
    # 0009 adds one nullable recovery timestamp. Preserve every pre-existing
    # field exactly and require the new field's declared default explicitly.
    assert [json.loads(row[0]) for row in snapshot(postgres_db)["rick_ingestion_jobs"]] == [
        {**json.loads(row[0]), "publication_recovery_at": None} for row in previous_jobs
    ]
    after = snapshot(postgres_db)
    assert migrate.apply(MIGRATIONS, postgres_db) == 0
    assert snapshot(postgres_db) == after


def test_postgres_old0005_reproduces_failure_with_legacy_rows(postgres_db):
    import psycopg

    install_snapshot(postgres_db, 4)
    seed_scope(postgres_db)
    seed_job(postgres_db, "legacy")
    before = snapshot(postgres_db)
    with pytest.raises(psycopg.errors.UndefinedFunction):
        install_snapshot(postgres_db, 5, start=5, original=True)
    assert snapshot(postgres_db) == before
    assert migrate.apply(MIGRATIONS, postgres_db) == 0
    assert query(postgres_db, "SELECT contract_state FROM rick_ingestion_jobs")[0][0] == "QUEUED"


def test_postgres_current_install_is_unchanged_on_restart(postgres_db):
    current_version = max(int(version) for version, _path, _digest in migrate.migration_files(MIGRATIONS))
    install_snapshot(postgres_db, current_version)
    seed_scope(postgres_db)
    seed_job(postgres_db, "canonical", canonical=True, payload={"source_key": "objects/synthetic"})
    before = snapshot(postgres_db)
    assert migrate.apply(MIGRATIONS, postgres_db) == 0
    assert snapshot(postgres_db) == before


@pytest.mark.parametrize("original", [False, True])
@pytest.mark.parametrize("defect", ["unknown-version", "gap", "checksum0005", "checksum0004", "application"])
def test_postgres_corrupt_history_never_reaches_pending_sql(postgres_db, original, defect):
    install_snapshot(postgres_db, 5, original=original)
    if defect == "unknown-version":
        query(postgres_db, "INSERT INTO rick_schema_migrations(version,checksum,application) VALUES ('9999',%s,%s)", ("f" * 64, migrate.APPLICATION))
    elif defect == "gap":
        query(postgres_db, "DELETE FROM rick_schema_migrations WHERE version='0002'")
    elif defect.startswith("checksum"):
        query(postgres_db, "UPDATE rick_schema_migrations SET checksum=%s WHERE version=%s", ("f" * 64, defect[-4:]))
    else:
        query(postgres_db, "UPDATE rick_schema_migrations SET application='unknown' WHERE version='0005'")
    before = snapshot(postgres_db)
    with pytest.raises(RuntimeError, match="unknown version|gap|checksum mismatch|application mismatch"):
        migrate.apply(MIGRATIONS, postgres_db)
    assert snapshot(postgres_db) == before
    assert not query(postgres_db, "SELECT 1 FROM rick_schema_migrations WHERE version='0006'")


@pytest.mark.parametrize("defect", ["missing", "empty"])
def test_postgres_existing_schema_without_history_is_not_adopted(postgres_db, defect):
    install_snapshot(postgres_db, 4)
    seed_scope(postgres_db)
    if defect == "missing":
        query(postgres_db, "DROP TABLE rick_schema_migrations")
    else:
        query(postgres_db, "DELETE FROM rick_schema_migrations")
    before = snapshot(postgres_db)
    with pytest.raises(RuntimeError, match="SQLSTATE P0001"):
        migrate.apply(MIGRATIONS, postgres_db)
    assert snapshot(postgres_db) == before


@pytest.mark.parametrize("original", [False, True])
@pytest.mark.parametrize("defect", ["disabled-guard", "legacy-row", "attempt-count"])
def test_postgres_recorded0005_requires_complete_canonical_state(postgres_db, original, defect):
    install_snapshot(postgres_db, 5, original=original)
    seed_scope(postgres_db)
    if defect in {"disabled-guard", "legacy-row"}:
        # Deliberately corrupt only this disposable fixture, never the runner.
        query(postgres_db, "ALTER TABLE rick_ingestion_jobs DISABLE TRIGGER rick_require_canonical_job_write_trg")
        if defect == "legacy-row":
            seed_job(postgres_db, "incomplete")
            query(postgres_db, "ALTER TABLE rick_ingestion_jobs ENABLE TRIGGER rick_require_canonical_job_write_trg")
    else:
        query(postgres_db, "ALTER TABLE rick_ingestion_jobs DISABLE TRIGGER rick_job_attempt_count_jobs_trg")
        seed_job(postgres_db, "incomplete", canonical=True, attempts=1, payload={})
        query(postgres_db, "ALTER TABLE rick_ingestion_jobs ENABLE TRIGGER rick_job_attempt_count_jobs_trg")
    before = snapshot(postgres_db)
    with pytest.raises(RuntimeError, match="SQLSTATE P0001"):
        migrate.apply(MIGRATIONS, postgres_db)
    assert snapshot(postgres_db) == before
    assert not query(postgres_db, "SELECT 1 FROM rick_schema_migrations WHERE version='0006'")


@pytest.mark.parametrize("defect", [
    "noop-canonical-guard", "noop-attempt-update", "noop-attempt-delete",
    "noop-attempt-count", "wrong-binding",
])
def test_postgres_recorded0005_rejects_changed_trigger_contract(postgres_db, defect):
    install_snapshot(postgres_db, 6)
    if defect == "noop-canonical-guard":
        query(postgres_db, """CREATE OR REPLACE FUNCTION rick_require_canonical_job_write()
            RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END; $$""")
    elif defect == "noop-attempt-update":
        query(postgres_db, """CREATE OR REPLACE FUNCTION rick_guard_job_attempt_update()
            RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END; $$""")
    elif defect == "noop-attempt-delete":
        query(postgres_db, """CREATE OR REPLACE FUNCTION rick_guard_job_attempt_delete()
            RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END; $$""")
    elif defect == "noop-attempt-count":
        query(postgres_db, """CREATE OR REPLACE FUNCTION rick_check_job_attempt_count()
            RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END; $$""")
    else:
        query(postgres_db, """CREATE FUNCTION rick_q24_noop_guard()
            RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END; $$""")
        query(postgres_db, "DROP TRIGGER rick_require_canonical_job_write_trg ON rick_ingestion_jobs")
        query(postgres_db, """CREATE TRIGGER rick_require_canonical_job_write_trg
            BEFORE INSERT OR UPDATE ON rick_ingestion_jobs
            FOR EACH ROW EXECUTE FUNCTION rick_q24_noop_guard()""")
    if defect == "wrong-binding":
        assert query(postgres_db, """SELECT t.tgenabled, t.tgfoid::regprocedure::text
            FROM pg_trigger t WHERE t.tgrelid='rick_ingestion_jobs'::regclass
              AND t.tgname='rick_require_canonical_job_write_trg'""") == [(
                  "O", "rick_q24_noop_guard()",
              )]
    before = snapshot(postgres_db)
    with pytest.raises(RuntimeError, match="SQLSTATE P0001|trigger function body changed"):
        migrate.apply(MIGRATIONS, postgres_db)
    assert snapshot(postgres_db) == before


def test_postgres_partial_legacy_attempts_are_not_silently_merged(postgres_db):
    install_snapshot(postgres_db, 4)
    seed_scope(postgres_db)
    seed_job(postgres_db, "partial", attempts=1)
    query(postgres_db, """INSERT INTO rick_ingestion_job_attempts
        (job_id,attempt_no,worker_id,state,started_at)
        VALUES ('partial',1,'worker','RUNNING','2026-01-01 00:00:00+00')""")
    before = snapshot(postgres_db)
    with pytest.raises(RuntimeError, match="SQLSTATE P0001"):
        migrate.apply(MIGRATIONS, postgres_db)
    assert snapshot(postgres_db) == before


@pytest.mark.parametrize("corrupt_literal", [False, True])
def test_postgres_recorded_guard_preserves_literal_semantics(postgres_db, corrupt_literal):
    import psycopg

    install_snapshot(postgres_db, 4)
    seed_scope(postgres_db)
    seed_job(postgres_db, "running", status="processing", attempts=1, active=True)
    install_snapshot(postgres_db, 8, start=5)
    completion = """UPDATE rick_ingestion_job_attempts
        SET state='SUCCEEDED', finished_at=NOW()
        WHERE job_id='running' AND attempt_no=1"""
    # The original installed guard allows completion. Roll back this control
    # so the identical RUNNING attempt is available for the negative probe.
    with psycopg.connect(postgres_db) as connection:
        assert connection.execute(completion).rowcount == 1
        connection.rollback()
    original = query(postgres_db, "SELECT prosrc FROM pg_proc WHERE oid='rick_guard_job_attempt_update()'::regprocedure")[0][0]
    body = original.replace("'RUNNING'", "'RUN NING'") if corrupt_literal else "\n" + original + "\n"
    query(postgres_db, "CREATE OR REPLACE FUNCTION rick_guard_job_attempt_update() "
          "RETURNS trigger LANGUAGE plpgsql AS $$" + body + "$$")
    if corrupt_literal:
        with pytest.raises(psycopg.errors.RaiseException, match="finished job attempts are immutable"):
            query(postgres_db, completion)
    before = snapshot(postgres_db)
    old_history = history(postgres_db)
    if corrupt_literal:
        with pytest.raises(RuntimeError, match="trigger function body changed"):
            migrate.apply(MIGRATIONS, postgres_db)
        assert snapshot(postgres_db) == before
        assert history(postgres_db) == old_history
    else:
        assert migrate.apply(MIGRATIONS, postgres_db) == 0
        assert history(postgres_db)[:8] == old_history
    assert query(postgres_db, "SELECT prosrc FROM pg_proc WHERE oid='rick_guard_job_attempt_update()'::regprocedure") == [(body,)]


@pytest.mark.parametrize(("payload", "accepted"), [
    ({"source_key": "a" * 512}, True),
    ({"source_key": "a" * 513}, False),
    ({f"field_{i}_ref": "value" for i in range(32)}, True),
    ({f"field_{i}_ref": "value" for i in range(33)}, False),
    ({"unexpected": "value"}, False),
    ({"source_key": 123}, False),
    ({"display_filename": "file.pdf", "filename_ref": "ZmlsZS5wZGY="}, False),
    (["not-an-object"], False),
])
def test_postgres_corrected_expressions_preserve_payload_bounds(postgres_db, payload, accepted):
    install_snapshot(postgres_db, 4)
    seed_scope(postgres_db)
    seed_job(postgres_db, "a-valid-first", attempts=1)
    seed_job(postgres_db, "z-boundary", payload=payload)
    before = snapshot(postgres_db)
    if accepted:
        assert migrate.apply(MIGRATIONS, postgres_db) == 0
        assert query(postgres_db, "SELECT payload FROM rick_ingestion_jobs WHERE job_id='z-boundary'")[0][0] == payload
    else:
        with pytest.raises(RuntimeError, match="database migration failed"):
            migrate.apply(MIGRATIONS, postgres_db)
        # The preceding valid row's rewrite, attempt and three projections
        # must all disappear when a subsequent row fails.
        assert snapshot(postgres_db) == before


@pytest.mark.parametrize(("refs", "accepted"), [
    ({"source_key": "a" * 512}, True),
    ({"source_key": "a" * 513}, False),
    ({f"field_{i}_ref": "value" for i in range(32)}, True),
    ({f"field_{i}_ref": "value" for i in range(33)}, False),
    ({"source_key": 123}, False),
])
def test_postgres_corrected_expressions_preserve_result_bounds(postgres_db, refs, accepted):
    install_snapshot(postgres_db, 4)
    seed_scope(postgres_db)
    result = {"output_refs": refs, "document_id": "document", "completed_at": 1767225630}
    seed_job(postgres_db, "published", status="published", result=result)
    before = snapshot(postgres_db)
    if accepted:
        assert migrate.apply(MIGRATIONS, postgres_db) == 0
        assert query(postgres_db, "SELECT result FROM rick_ingestion_jobs")[0][0] == result
    else:
        with pytest.raises(RuntimeError, match="database migration failed"):
            migrate.apply(MIGRATIONS, postgres_db)
        assert snapshot(postgres_db) == before


def test_postgres_later_sql_failure_rolls_back_and_backup_restores(postgres_db, postgres_cluster, tmp_path, capsys):
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    install_snapshot(postgres_db, 4)
    seed_scope(postgres_db)
    seed_job(postgres_db, "legacy", status="failed", attempts=1)
    before = snapshot(postgres_db)
    db_name = conninfo_to_dict(postgres_db)["dbname"]
    dump = postgres_cluster["docker"]("exec", postgres_cluster["container_id"], "pg_dump", "-U", "postgres", "-d", db_name, "-Fc", "--no-owner", "--no-acl").stdout
    backup = postgres_cluster["logs"] / "pre0005-synthetic.dump"
    backup.write_bytes(dump)
    (postgres_cluster["logs"] / "backup-sha256.txt").write_text(hashlib.sha256(dump).hexdigest() + "\n")
    broken = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS, broken)
    with (broken / "0006_document_lineage_contract.sql").open("a") as stream:
        stream.write("\nCREATE TABLE q24_failure_probe(id integer); SELECT 1/0;\n")
    with pytest.raises(RuntimeError, match="SQLSTATE 22012"):
        migrate.apply(broken, postgres_db)
    assert ": applied" not in capsys.readouterr().out
    assert snapshot(postgres_db) == before
    assert migrate.apply(MIGRATIONS, postgres_db) == 0
    assert query(postgres_db, "SELECT contract_state,attempts FROM rick_ingestion_jobs")[0] == ("QUEUED", 1)

    restored_name = "q24_restore_" + uuid.uuid4().hex
    with psycopg.connect(postgres_cluster["dsn"], autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(restored_name)))
    restored_dsn = make_conninfo(postgres_db, dbname=restored_name)
    try:
        postgres_cluster["docker"]("exec", "-i", postgres_cluster["container_id"], "pg_restore", "-U", "postgres", "-d", restored_name, "--exit-on-error", "--no-owner", "--no-acl", input=dump)
        assert snapshot(restored_dsn) == before
        assert migrate.apply(MIGRATIONS, restored_dsn) == 0
        after = snapshot(restored_dsn)
        assert migrate.apply(MIGRATIONS, restored_dsn) == 0
        assert snapshot(restored_dsn) == after
        (postgres_cluster["logs"] / "recovery.json").write_text(json.dumps({
            "sql_failure_rolled_back": True, "same_database_roll_forward": True,
            "pg_dump_restore_matches_source": True, "restored_upgrade_repeat_unchanged": True,
            "source_history_count": 4, "target_history_count": len(history(restored_dsn)),
        }, indent=2) + "\n")
    finally:
        with psycopg.connect(postgres_cluster["dsn"], autocommit=True) as connection:
            connection.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(restored_name)))


def test_postgres_deferred_commit_failure_rolls_back_without_success_log(postgres_db, tmp_path, capsys):
    directory = tmp_path / "migrations"
    directory.mkdir()
    path = directory / "0001_deferred.sql"
    source = """
        CREATE TABLE q24_parent(id integer PRIMARY KEY);
        CREATE TABLE q24_child(parent_id integer REFERENCES q24_parent(id) DEFERRABLE INITIALLY DEFERRED);
        INSERT INTO q24_child VALUES (1);
    """
    path.write_text(source)
    before = snapshot(postgres_db)
    with pytest.raises(RuntimeError, match="SQLSTATE 23503"):
        migrate.apply(directory, postgres_db)
    assert snapshot(postgres_db) == before
    assert "applied" not in capsys.readouterr().out
    path.write_text(source + "INSERT INTO q24_parent VALUES (1);")
    assert migrate.apply(directory, postgres_db) == 0
    assert query(postgres_db, "SELECT parent_id FROM q24_child") == [(1,)]


def test_rewrite_integrity_failure_rolls_back_before_later_sql(monkeypatch, capsys):
    previous = [
        (version, digest, migrate.APPLICATION)
        for version, _path, digest in migrate.migration_files(MIGRATIONS)
        if version <= "0004"
    ]
    connection = FakeConnection(list(previous), fail_on=(
        "SET CONSTRAINTS rick_job_attempt_count_jobs_trg, "
        "rick_job_attempt_count_attempts_trg IMMEDIATE"
    ))
    with pytest.raises(RuntimeError, match="synthetic SQL failure"):
        run_apply(monkeypatch, MIGRATIONS, connection)
    assert connection.history == previous
    assert connection.rollbacks == 1
    assert not any(
        "CREATE TABLE IF NOT EXISTS rick_publication_receipts" in sql
        for sql, _params in connection.cursor_instance.executed
    )
    assert "applied" not in capsys.readouterr().out


def test_postgres_unrelated_constraints_can_span_migration_files(postgres_db, tmp_path):
    directory = tmp_path / "migrations"
    directory.mkdir()
    (directory / "0001_deferred.sql").write_text("""
        CREATE TABLE q24_parent(id integer PRIMARY KEY);
        CREATE TABLE q24_child(parent_id integer REFERENCES q24_parent(id)
            DEFERRABLE INITIALLY DEFERRED);
        INSERT INTO q24_child VALUES (1);
    """)
    (directory / "0002_parent.sql").write_text("INSERT INTO q24_parent VALUES (1);")
    assert migrate.apply(directory, postgres_db) == 0
    assert query(postgres_db, "SELECT parent_id FROM q24_child") == [(1,)]


def test_postgres_two_empty_installers_serialize_before_bookkeeping(postgres_db):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    barrier = Barrier(2)

    def install():
        barrier.wait(timeout=5)
        return migrate.apply(MIGRATIONS, postgres_db)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(install) for _ in range(2)]
        assert [future.result(timeout=20) for future in futures] == [0, 0]
    assert len(history(postgres_db)) == len(migrate.migration_files(MIGRATIONS))


def test_postgres_tampered_source_fails_before_touching_old_history(postgres_db, tmp_path):
    install_snapshot(postgres_db, 5, original=True)
    before = snapshot(postgres_db)
    directory = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS, directory)
    with (directory / migrate.LEGACY_REWRITE_NAME).open("a") as stream:
        stream.write("\n-- unrecognized change\n")
    with pytest.raises(ValueError, match="unrecognized local artifact/checksum"):
        migrate.apply(directory, postgres_db)
    assert snapshot(postgres_db) == before


def test_postgres_cli_reports_only_committed_success(postgres_db):
    result = subprocess.run(
        [sys.executable, str(ROOT / "infrastructure/scripts/migrate.py"), str(MIGRATIONS), "--apply"],
        env={**os.environ, "RICK_EXTERNAL_DATABASE_DSN": postgres_db, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "migration execution: PASS" in result.stdout
    assert len(history(postgres_db)) == len(migrate.migration_files(MIGRATIONS))


def test_postgres_interrupted_backend_leaves_no_partial_migration(postgres_db, postgres_cluster, tmp_path):
    from psycopg.conninfo import make_conninfo

    install_snapshot(postgres_db, 4)
    seed_scope(postgres_db)
    seed_job(postgres_db, "interrupted", status="failed", attempts=1)
    before = snapshot(postgres_db)
    directory = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS, directory)
    with (directory / "0006_document_lineage_contract.sql").open("a") as stream:
        stream.write("\nSELECT pg_sleep(30);\n")
    application = "q24-interrupt-" + uuid.uuid4().hex
    dsn = make_conninfo(postgres_db, application_name=application, options="-c statement_timeout=45000 -c lock_timeout=5000")
    command = [sys.executable, str(ROOT / "infrastructure/scripts/migrate.py"), str(directory), "--apply"]
    process = subprocess.Popen(command, env={**os.environ, "RICK_EXTERNAL_DATABASE_DSN": dsn}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 10
        while True:
            backends = query(postgres_db, """SELECT pid FROM pg_stat_activity
                WHERE application_name=%s AND datname=current_database()
                  AND wait_event='PgSleep'""", (application,))
            if backends:
                assert len(backends) == 1
                break
            assert process.poll() is None, "migration exited before the interruption point"
            assert time.monotonic() < deadline, "migration never reached the interruption point"
            time.sleep(0.1)
        # This PID was observed in our new database with our unique application
        # name, after 0005 and 0006 SQL ran but before the transaction committed.
        assert query(postgres_db, "SELECT pg_terminate_backend(%s)", (backends[0][0],)) == [(True,)]
        stdout, stderr = process.communicate(timeout=15)
        assert process.returncode == 2
        assert "PASS" not in stdout and ": applied" not in stdout
        assert "database migration failed" in stderr
        (postgres_cluster["logs"] / "interrupted-cli.log").write_text(stdout + stderr)
        assert snapshot(postgres_db) == before
        assert migrate.apply(MIGRATIONS, postgres_db) == 0
        assert query(postgres_db, "SELECT contract_state,attempts FROM rick_ingestion_jobs")[0] == ("QUEUED", 1)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)


@pytest.mark.parametrize("state", ["pre0005", "old0005", "current0005", "old0005-and0006"])
def test_postgres_historical0004_gets_recorded_additive_guard(postgres_db, state):
    import psycopg

    install_snapshot(postgres_db, 4, original4=True)
    seed_scope(postgres_db)
    if state == "pre0005":
        seed_job(postgres_db, "legacy", status="failed", attempts=1)
    else:
        install_snapshot(postgres_db, 6 if state.endswith("and0006") else 5, start=5, original=state != "current0005")
        seed_job(postgres_db, "canonical", canonical=True, payload={})
    previous = history(postgres_db)
    assert previous[3][1] == migrate.JOBS_CONTRACT_ORIGINAL
    assert migrate.apply(MIGRATIONS, postgres_db) == 0
    assert history(postgres_db)[:len(previous)] == previous
    repair = query(postgres_db, "SELECT repair_id,source_version,source_checksum,repair_checksum,application FROM rick_schema_migration_repairs")
    assert repair == [(migrate.OPERATION_REPAIR_ID, "0004", migrate.JOBS_CONTRACT_ORIGINAL, migrate.OPERATION_REPAIR_SHA256, migrate.APPLICATION)]
    assert query(postgres_db, """SELECT count(*) FROM pg_constraint WHERE conrelid='rick_ingestion_jobs'::regclass
        AND conname IN ('rick_ingestion_jobs_operation_ck','rick_ingestion_jobs_operation_v2_ck')""") == [(2,)]
    before = snapshot(postgres_db)
    assert migrate.apply(MIGRATIONS, postgres_db) == 0
    assert snapshot(postgres_db) == before
    with pytest.raises(psycopg.errors.CheckViolation):
        query(postgres_db, "UPDATE rick_ingestion_jobs SET operation='contains space'")
    assert snapshot(postgres_db) == before


@pytest.mark.parametrize("canonical", [False, True])
def test_postgres_historical0004_invalid_operations_block_repair(postgres_db, canonical):
    install_snapshot(postgres_db, 4, original4=True)
    seed_scope(postgres_db)
    seed_job(postgres_db, "invalid", canonical=canonical, payload={})
    query(postgres_db, "UPDATE rick_ingestion_jobs SET operation='contains space'")
    before = snapshot(postgres_db)
    with pytest.raises(RuntimeError, match="SQLSTATE 23514"):
        migrate.apply(MIGRATIONS, postgres_db)
    assert snapshot(postgres_db) == before
    assert query(postgres_db, "SELECT to_regclass('rick_schema_migration_repairs')") == [(None,)]


def test_postgres_historical0004_repair_rolls_back_with_failed0005(postgres_db):
    from psycopg.types.json import Jsonb

    install_snapshot(postgres_db, 4, original4=True)
    seed_scope(postgres_db)
    seed_job(postgres_db, "invalid-payload", payload={"source_key": "x" * 513})
    before = snapshot(postgres_db)
    with pytest.raises(RuntimeError, match="database migration failed"):
        migrate.apply(MIGRATIONS, postgres_db)
    assert snapshot(postgres_db) == before
    query(postgres_db, "UPDATE rick_ingestion_jobs SET payload=%s", (Jsonb({"source_key": "objects/synthetic"}),))
    assert migrate.apply(MIGRATIONS, postgres_db) == 0
    assert len(query(postgres_db, "SELECT repair_id FROM rick_schema_migration_repairs")) == 1
    assert history(postgres_db)[3][1] == migrate.JOBS_CONTRACT_ORIGINAL


@pytest.mark.parametrize("defect", ["checksum", "unknown-repair", "missing-constraint", "weakened-constraint", "unvalidated-constraint", "source-history"])
def test_postgres_historical0004_repair_drift_fails_without_repairing_history(postgres_db, defect):
    install_snapshot(postgres_db, 4, original4=True)
    assert migrate.apply(MIGRATIONS, postgres_db) == 0
    if defect == "checksum":
        query(postgres_db, "UPDATE rick_schema_migration_repairs SET repair_checksum=%s", ("f" * 64,))
    elif defect == "unknown-repair":
        query(postgres_db, """INSERT INTO rick_schema_migration_repairs
            SELECT 'unknown',source_version,source_checksum,repair_checksum,application,applied_at
            FROM rick_schema_migration_repairs""")
    elif defect == "source-history":
        query(postgres_db, "UPDATE rick_schema_migrations SET checksum=%s WHERE version='0004'", (migrate.JOBS_CONTRACT_CURRENT,))
    else:
        query(postgres_db, "ALTER TABLE rick_ingestion_jobs DROP CONSTRAINT rick_ingestion_jobs_operation_v2_ck")
        if defect == "weakened-constraint":
            query(postgres_db, "ALTER TABLE rick_ingestion_jobs ADD CONSTRAINT rick_ingestion_jobs_operation_v2_ck CHECK (length(operation)>0)")
        elif defect == "unvalidated-constraint":
            query(postgres_db, """ALTER TABLE rick_ingestion_jobs ADD CONSTRAINT rick_ingestion_jobs_operation_v2_ck
                CHECK (operation ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$') NOT VALID""")
    before = snapshot(postgres_db)
    with pytest.raises(RuntimeError, match="migration repair history|recorded operation repair|SQLSTATE P0001"):
        migrate.apply(MIGRATIONS, postgres_db)
    assert snapshot(postgres_db) == before


def test_postgres_admin_mutation_outbox_projection_and_last_admin_serialization(postgres_db, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from types import SimpleNamespace

    for relative in (
        "apps/api/src",
        "apps/worker",
        "packages/authorization/src",
        "packages/contracts/src",
        "packages/identity/src",
        "packages/observability/src",
    ):
        monkeypatch.syspath_prepend(str(ROOT / relative))

    import psycopg
    from psycopg.conninfo import make_conninfo
    from admin_audit_outbox import PostgresAdminAuditReconciler
    from core.errors import ApiError
    from services.postgres_audit import PostgresAuditSink
    from services.postgres_identity import PostgresIdentityProvider

    migrate.apply(MIGRATIONS, postgres_db)
    with pytest.raises(psycopg.errors.CheckViolation):
        query(postgres_db, """
            INSERT INTO rick_outbox
                (event_id,tenant_id,aggregate_type,aggregate_id,event_type,payload)
            VALUES ('   ','tenant-a','rick_user','target','admin.audit.completion','{}'::jsonb)
        """)

    def seed_admin(tenant_id, user_id, email):
        query(postgres_db, "INSERT INTO rick_tenants(tenant_id,display_name) VALUES (%s,%s)", (tenant_id, tenant_id))
        query(postgres_db, "INSERT INTO rick_users(user_id,email) VALUES (%s,%s)", (user_id, email))
        query(postgres_db, """
            INSERT INTO rick_memberships(tenant_id,user_id,workspace_id,role,status)
            VALUES (%s,%s,'workspace','PLATFORM_ADMIN','active')
        """, (tenant_id, user_id))

    seed_admin("tenant-a", "admin-a", "admin-a@example.test")
    query(postgres_db, "INSERT INTO rick_tenants(tenant_id,display_name) VALUES ('tenant-b','tenant-b')")
    seed_admin("tenant-race", "race-a", "race-a@example.test")
    query(postgres_db, "INSERT INTO rick_users(user_id,email) VALUES ('race-b','race-b@example.test')")
    query(postgres_db, """
        INSERT INTO rick_memberships(tenant_id,user_id,workspace_id,role,status)
        VALUES ('tenant-race','race-b','workspace','PLATFORM_ADMIN','active')
    """)

    def actor(user_id, tenant_id):
        return SimpleNamespace(
            user_id=user_id,
            tenant_id=tenant_id,
            workspace_id="workspace",
            role="PLATFORM_ADMIN",
            canonical_role="PLATFORM_ADMIN",
            permissions=["users.manage", "audit.read"],
        )

    def connect():
        return psycopg.connect(postgres_db, connect_timeout=2)

    identity = PostgresIdentityProvider(connect, production_safe=True)
    admin = actor("admin-a", "tenant-a")
    assert identity.admin_target_in_scope(user_id="admin-a", tenant_id="tenant-a", workspace_id="workspace") is True
    assert identity.admin_target_in_scope(user_id="race-a", tenant_id="tenant-a", workspace_id="workspace") is False
    assert identity.admin_target_in_scope(user_id="admin-a", tenant_id="tenant-a", workspace_id="other-workspace") is False

    query(postgres_db, """
        INSERT INTO rick_users(user_id,email,password_hash)
        VALUES ('reset-sibling-only','reset-sibling-only@example.test','before-reset-hash')
    """)
    query(postgres_db, """
        INSERT INTO rick_memberships(tenant_id,user_id,workspace_id,role,status)
        VALUES ('tenant-a','reset-sibling-only','sibling-workspace','VETERINARIAN','active')
    """)
    query(postgres_db, """
        INSERT INTO rick_sessions
            (session_id,token_hash,tenant_id,user_id,workspace_id,authorization_snapshot,
             password_version,role_version,expires_at)
        VALUES ('reset-sibling-only-session','hash-reset-sibling-only','tenant-a','reset-sibling-only',
                'sibling-workspace','{"permissions":[]}',1,1,NOW()+INTERVAL '1 hour')
    """)
    sibling_account_before_reset = query(
        postgres_db,
        "SELECT password_hash,password_version FROM rick_users WHERE user_id='reset-sibling-only'",
    )
    sibling_outbox_before_reset = query(
        postgres_db,
        "SELECT count(*) FROM rick_outbox WHERE aggregate_id='reset-sibling-only' AND event_type='admin.audit.completion'",
    )
    with pytest.raises(ApiError) as sibling_reset_error:
        identity.admin_reset_password(
            actor=admin,
            user_id="reset-sibling-only",
            password="sibling-reset-password",
            request_id="request-sibling-workspace-reset",
        )
    assert sibling_reset_error.value.code == "forbidden"
    assert query(
        postgres_db,
        "SELECT password_hash,password_version FROM rick_users WHERE user_id='reset-sibling-only'",
    ) == sibling_account_before_reset
    assert query(
        postgres_db,
        "SELECT revoked_at FROM rick_sessions WHERE session_id='reset-sibling-only-session'",
    ) == [(None,)]
    assert query(
        postgres_db,
        "SELECT count(*) FROM rick_outbox WHERE aggregate_id='reset-sibling-only' AND event_type='admin.audit.completion'",
    ) == sibling_outbox_before_reset

    query(postgres_db, """
        CREATE FUNCTION reject_admin_audit_outbox() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.event_type = 'admin.audit.completion' THEN
                RAISE EXCEPTION 'synthetic admin audit rejection';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    query(postgres_db, """
        CREATE TRIGGER reject_admin_audit_outbox_trg
        BEFORE INSERT ON rick_outbox FOR EACH ROW EXECUTE FUNCTION reject_admin_audit_outbox()
    """)
    with pytest.raises(ApiError) as create_error:
        identity.admin_create_user(
            actor=admin,
            email="rolled-back@example.test",
            role="VETERINARIAN",
            tenant_id="tenant-a",
            password="private-create-password",
            request_id="request-failed-create",
        )
    assert create_error.value.code == "provider_unavailable"
    assert query(postgres_db, "SELECT count(*) FROM rick_users WHERE email='rolled-back@example.test'") == [(0,)]

    query(postgres_db, "DROP TRIGGER reject_admin_audit_outbox_trg ON rick_outbox")
    query(postgres_db, "DROP FUNCTION reject_admin_audit_outbox()")
    created_user, create_event_id = identity.admin_create_user(
        actor=admin,
        email="target@example.test",
        role="VETERINARIAN",
        tenant_id="tenant-a",
        password="private-create-password",
        request_id="request-create",
    )
    query(postgres_db, """
        INSERT INTO rick_memberships(tenant_id,user_id,workspace_id,role,status)
        VALUES ('tenant-b',%s,'default','VETERINARIAN','active')
    """, (created_user["user_id"],))
    initial_version = query(
        postgres_db,
        "SELECT password_version FROM rick_users WHERE user_id=%s",
        (created_user["user_id"],),
    )[0][0]
    role_version = query(
        postgres_db,
        "SELECT role_version FROM rick_users WHERE user_id=%s",
        (created_user["user_id"],),
    )[0][0]

    def insert_target_session(session_id, tenant_id, version, workspace_id="workspace"):
        query(postgres_db, """
            INSERT INTO rick_sessions
                (session_id,token_hash,tenant_id,user_id,workspace_id,authorization_snapshot,
                 password_version,role_version,expires_at)
            VALUES (%s,%s,%s,%s,%s,'{"permissions":[]}',%s,%s,NOW()+INTERVAL '1 hour')
        """, (session_id, f"hash-{session_id}", tenant_id, created_user["user_id"], workspace_id, version, role_version))

    insert_target_session("target-session-a-1", "tenant-a", initial_version)
    insert_target_session("target-session-b-1", "tenant-b", initial_version, "default")

    outbox_count = query(
        postgres_db,
        "SELECT count(*) FROM rick_outbox WHERE aggregate_id=%s AND event_type='admin.audit.completion'",
        (created_user["user_id"],),
    )[0][0]
    for index, membership_change in enumerate((
        {"role": "KNOWLEDGE_MANAGER"},
        {"authorized_collection_ids": ["collection-b"]},
        {"permission_overrides": {"add": ["users.manage"], "remove": []}},
    )):
        with pytest.raises(ApiError) as membership_error:
            identity.admin_update_user(
                actor=admin,
                user_id=created_user["user_id"],
                request_id=f"request-cross-tenant-membership-{index}",
                **membership_change,
            )
        assert membership_error.value.code == "forbidden"
    with pytest.raises(ApiError) as cross_tenant_email_error:
        identity.admin_update_user(
            actor=admin,
            user_id=created_user["user_id"],
            email="cross-tenant-update@example.test",
            request_id="request-cross-tenant-email",
        )
    assert cross_tenant_email_error.value.code == "forbidden"
    with pytest.raises(ApiError) as cross_tenant_reset_error:
        identity.admin_reset_password(
            actor=admin,
            user_id=created_user["user_id"],
            password="private-cross-tenant-reset",
            request_id="request-cross-tenant-reset",
        )
    assert cross_tenant_reset_error.value.code == "forbidden"
    assert query(postgres_db, "SELECT email,password_version FROM rick_users WHERE user_id=%s", (created_user["user_id"],)) == [
        ("target@example.test", initial_version),
    ]
    assert query(postgres_db, "SELECT role,authorized_collection_ids,permission_overrides FROM rick_memberships WHERE tenant_id='tenant-a' AND user_id=%s", (created_user["user_id"],)) == [
        ("VETERINARIAN", [], {"add": [], "remove": []}),
    ]
    assert query(
        postgres_db,
        "SELECT revoked_at FROM rick_sessions WHERE session_id IN ('target-session-a-1','target-session-b-1') ORDER BY session_id",
    ) == [(None,), (None,)]
    assert query(
        postgres_db,
        "SELECT count(*) FROM rick_outbox WHERE aggregate_id=%s AND event_type='admin.audit.completion'",
        (created_user["user_id"],),
    ) == [(outbox_count,)]
    query(postgres_db, "DELETE FROM rick_sessions WHERE session_id='target-session-b-1'")
    query(postgres_db, "DELETE FROM rick_memberships WHERE tenant_id='tenant-b' AND user_id=%s", (created_user["user_id"],))

    query(postgres_db, """
        CREATE FUNCTION reject_admin_audit_outbox() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.event_type = 'admin.audit.completion' THEN
                RAISE EXCEPTION 'synthetic admin audit rejection';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    query(postgres_db, """
        CREATE TRIGGER reject_admin_audit_outbox_trg
        BEFORE INSERT ON rick_outbox FOR EACH ROW EXECUTE FUNCTION reject_admin_audit_outbox()
    """)
    with pytest.raises(ApiError):
        identity.admin_update_user(
            actor=admin,
            user_id=created_user["user_id"],
            email="rolled-back-update@example.test",
            request_id="request-failed-update",
        )
    assert query(postgres_db, "SELECT email FROM rick_users WHERE user_id=%s", (created_user["user_id"],)) == [("target@example.test",)]
    with pytest.raises(ApiError):
        identity.admin_deactivate_user(
            actor=admin,
            user_id=created_user["user_id"],
            request_id="request-failed-deactivate",
        )
    assert query(postgres_db, """
        SELECT tenant_id,status FROM rick_memberships
        WHERE user_id=%s AND tenant_id IN ('tenant-a','tenant-b') ORDER BY tenant_id
    """, (created_user["user_id"],)) == [("tenant-a", "active")]
    assert query(postgres_db, "SELECT revoked_at FROM rick_sessions WHERE session_id='target-session-a-1'") == [(None,)]
    with pytest.raises(ApiError):
        identity.admin_reset_password(
            actor=admin,
            user_id=created_user["user_id"],
            password="private-reset-password",
            request_id="request-failed-reset",
        )
    assert query(postgres_db, "SELECT password_version FROM rick_users WHERE user_id=%s", (created_user["user_id"],)) == [(initial_version,)]
    assert query(postgres_db, "SELECT revoked_at FROM rick_sessions WHERE session_id='target-session-a-1'") == [(None,)]
    query(postgres_db, "DROP TRIGGER reject_admin_audit_outbox_trg ON rick_outbox")
    query(postgres_db, "DROP FUNCTION reject_admin_audit_outbox()")

    updated_user, update_event_id = identity.admin_update_user(
        actor=admin,
        user_id=created_user["user_id"],
        email="updated-target@example.test",
        request_id="request-update",
    )
    assert updated_user["email"] == "updated-target@example.test"
    reset_revoked, reset_event_id = identity.admin_reset_password(
        actor=admin,
        user_id=created_user["user_id"],
        password="private-reset-password",
        request_id="request-reset",
    )
    assert reset_revoked == 1
    reset_version = query(
        postgres_db,
        "SELECT password_version FROM rick_users WHERE user_id=%s",
        (created_user["user_id"],),
    )[0][0]
    assert reset_version == initial_version + 1
    assert all(
        revoked_at is not None
        for (revoked_at,) in query(
            postgres_db,
            "SELECT revoked_at FROM rick_sessions WHERE session_id='target-session-a-1'",
        )
    )

    recovery_token = identity.issue_password_reset(
        email="updated-target@example.test", tenant_id="tenant-a",
    )
    assert isinstance(recovery_token, str)
    inactive_membership_token = identity.issue_password_reset(
        email="updated-target@example.test", tenant_id="tenant-a",
    )
    assert isinstance(inactive_membership_token, str)

    query(postgres_db, """
        INSERT INTO rick_memberships(tenant_id,user_id,workspace_id,role,status)
        VALUES ('tenant-b',%s,'default','VETERINARIAN','active')
    """, (created_user["user_id"],))
    query(postgres_db, """
        INSERT INTO rick_memberships(tenant_id,user_id,workspace_id,role,status)
        VALUES ('tenant-a',%s,'sibling-workspace','VETERINARIAN','active')
    """, (created_user["user_id"],))
    insert_target_session("target-session-a-2", "tenant-a", reset_version, "workspace")
    insert_target_session("target-session-a-sibling", "tenant-a", reset_version, "sibling-workspace")
    insert_target_session("target-session-b-2", "tenant-b", reset_version, "default")
    cross_tenant_bearer = identity._sessions.create({
        "user_id": created_user["user_id"],
        "email": "updated-target@example.test",
        "role": "VETERINARIAN",
        "canonical_role": "VETERINARIAN",
        "permissions": [],
        "authorization_snapshot_version": 1,
        "authorization_state": "AUTHORITATIVE",
        "allowed_collection_ids": [],
        "tenant_id": "tenant-b",
        "workspace_id": "default",
        "password_version": reset_version,
        "role_version": role_version,
        "session_id": "target-session-b-recovery-bearer",
    })
    assert identity.validate_token(cross_tenant_bearer).authenticated is True
    same_tenant_workspace_bearer = identity._sessions.create({
        "user_id": created_user["user_id"],
        "email": "updated-target@example.test",
        "role": "VETERINARIAN",
        "canonical_role": "VETERINARIAN",
        "permissions": [],
        "authorization_snapshot_version": 1,
        "authorization_state": "AUTHORITATIVE",
        "allowed_collection_ids": [],
        "tenant_id": "tenant-a",
        "workspace_id": "workspace",
        "password_version": reset_version,
        "role_version": role_version,
        "session_id": "target-session-a-workspace-bearer",
    })
    same_tenant_sibling_bearer = identity._sessions.create({
        "user_id": created_user["user_id"],
        "email": "updated-target@example.test",
        "role": "VETERINARIAN",
        "canonical_role": "VETERINARIAN",
        "permissions": [],
        "authorization_snapshot_version": 1,
        "authorization_state": "AUTHORITATIVE",
        "allowed_collection_ids": [],
        "tenant_id": "tenant-a",
        "workspace_id": "sibling-workspace",
        "password_version": reset_version,
        "role_version": role_version,
        "session_id": "target-session-a-sibling-workspace-bearer",
    })
    assert identity.validate_token(same_tenant_workspace_bearer).authenticated is True
    assert identity.validate_token(same_tenant_sibling_bearer).authenticated is True
    global_account_before_deactivate = query(
        postgres_db,
        "SELECT email,status,password_hash,password_version,role_version FROM rick_users WHERE user_id=%s",
        (created_user["user_id"],),
    )
    original_locked_lookup = identity._users.get_by_id_for_tenant_workspace_for_update
    original_update_membership = identity._users.update_membership_status
    membership_lock_acquired = threading.Event()
    deactivation_update_started = threading.Event()
    deactivation_finished = threading.Event()
    allow_recovery_to_continue = threading.Event()

    def pause_recovery_after_membership_lock(user_id, tenant_id, workspace_id, *, connection):
        membership = original_locked_lookup(
            user_id, tenant_id, workspace_id, connection=connection,
        )
        membership_lock_acquired.set()
        if not allow_recovery_to_continue.wait(timeout=10):
            raise AssertionError("timed out waiting for concurrent workspace deactivation")
        return membership

    def signal_deactivation_update(*args, **kwargs):
        deactivation_update_started.set()
        return original_update_membership(*args, **kwargs)

    identity._users.get_by_id_for_tenant_workspace_for_update = pause_recovery_after_membership_lock
    identity._users.update_membership_status = signal_deactivation_update

    def consume_recovery_while_membership_is_locked():
        return identity.consume_password_reset(
            token=recovery_token, new_password="private-recovery-password",
        )

    def deactivate_after_recovery_lock():
        try:
            return identity.admin_deactivate_user(
                actor=admin,
                user_id=created_user["user_id"],
                request_id="request-deactivate",
            )
        finally:
            deactivation_finished.set()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            recovery_future = pool.submit(consume_recovery_while_membership_is_locked)
            deactivation_future = None
            try:
                assert membership_lock_acquired.wait(timeout=10), "recovery did not lock the active membership"
                deactivation_future = pool.submit(deactivate_after_recovery_lock)
                assert deactivation_update_started.wait(timeout=10), "deactivation did not reach the membership update"
                assert not deactivation_finished.wait(timeout=0.25), (
                    "deactivation passed the membership lock while recovery was uncommitted"
                )
            finally:
                allow_recovery_to_continue.set()
            recovery_revoked = recovery_future.result(timeout=10)
            assert deactivation_future is not None
            revoked, deactivate_event_id = deactivation_future.result(timeout=10)
    finally:
        allow_recovery_to_continue.set()
        identity._users.get_by_id_for_tenant_workspace_for_update = original_locked_lookup
        identity._users.update_membership_status = original_update_membership
    assert recovery_revoked == 6
    assert revoked == 0
    assert query(postgres_db, "SELECT status FROM rick_users WHERE user_id=%s", (created_user["user_id"],)) == [("active",)]
    global_account_after_recovery = query(
        postgres_db,
        "SELECT email,status,password_hash,password_version,role_version FROM rick_users WHERE user_id=%s",
        (created_user["user_id"],),
    )[0]
    previous_global_account = global_account_before_deactivate[0]
    assert global_account_after_recovery[:2] == previous_global_account[:2]
    assert global_account_after_recovery[2] != previous_global_account[2]
    assert global_account_after_recovery[3] == previous_global_account[3] + 1
    assert global_account_after_recovery[4] == previous_global_account[4]
    assert query(postgres_db, """
        SELECT tenant_id,workspace_id,status FROM rick_memberships
        WHERE user_id=%s AND tenant_id IN ('tenant-a','tenant-b') ORDER BY tenant_id,workspace_id
    """, (created_user["user_id"],)) == [
        ("tenant-a", "sibling-workspace", "active"),
        ("tenant-a", "workspace", "disabled"),
        ("tenant-b", "default", "active"),
    ]
    assert query(postgres_db, "SELECT revoked_at FROM rick_sessions WHERE session_id='target-session-a-2'")[0][0] is not None
    assert query(postgres_db, "SELECT revoke_reason FROM rick_sessions WHERE session_id='target-session-a-sibling'") == [("password_recovery",)]
    assert query(postgres_db, "SELECT revoke_reason FROM rick_sessions WHERE session_id='target-session-b-2'") == [("password_recovery",)]
    cross_tenant_session_after_recovery = query(postgres_db, """
        SELECT revoked_at,revoke_reason FROM rick_sessions
        WHERE session_id='target-session-b-recovery-bearer'
    """)[0]
    assert cross_tenant_session_after_recovery[0] is not None
    assert cross_tenant_session_after_recovery[1] == "password_recovery"
    assert identity.validate_token(cross_tenant_bearer).authenticated is False
    assert identity.validate_token(same_tenant_workspace_bearer).authenticated is False
    assert identity.validate_token(same_tenant_sibling_bearer).authenticated is False
    password_state_after_recovery = query(
        postgres_db,
        "SELECT password_hash,password_version FROM rick_users WHERE user_id=%s",
        (created_user["user_id"],),
    )
    session_state_after_recovery = query(
        postgres_db,
        "SELECT session_id,revoked_at,revoke_reason FROM rick_sessions WHERE user_id=%s ORDER BY session_id",
        (created_user["user_id"],),
    )
    with pytest.raises(ApiError):
        identity.consume_password_reset(
            token=recovery_token, new_password="replayed-recovery-password",
        )
    assert query(
        postgres_db,
        "SELECT password_hash,password_version FROM rick_users WHERE user_id=%s",
        (created_user["user_id"],),
    ) == password_state_after_recovery
    assert query(
        postgres_db,
        "SELECT session_id,revoked_at,revoke_reason FROM rick_sessions WHERE user_id=%s ORDER BY session_id",
        (created_user["user_id"],),
    ) == session_state_after_recovery

    inactive_token_hash = hashlib.sha256(inactive_membership_token.encode("utf-8")).hexdigest()
    with pytest.raises(ApiError):
        identity.consume_password_reset(
            token=inactive_membership_token,
            new_password="inactive-membership-password",
        )
    assert query(
        postgres_db,
        "SELECT password_hash,password_version FROM rick_users WHERE user_id=%s",
        (created_user["user_id"],),
    ) == password_state_after_recovery
    assert query(
        postgres_db,
        "SELECT consumed_at FROM rick_password_reset_tokens WHERE token_hash=%s",
        (inactive_token_hash,),
    ) == [(None,)]
    assert identity.get_admin_audit_status(actor=admin, event_id=create_event_id)["status"] == "pending"
    assert identity.get_admin_audit_status(actor=admin, event_id=update_event_id)["status"] == "pending"
    assert identity.get_admin_audit_status(actor=admin, event_id=reset_event_id)["status"] == "pending"
    assert identity.get_admin_audit_status(actor=admin, event_id=deactivate_event_id)["status"] == "pending"

    reconciler = PostgresAdminAuditReconciler(connect)
    assert reconciler.health_check() is True
    assert PostgresAdminAuditReconciler(connect).process_once() == 4
    assert identity.get_admin_audit_status(actor=admin, event_id=create_event_id)["status"] == "published"
    assert identity.get_admin_audit_status(actor=admin, event_id=update_event_id)["status"] == "published"
    assert identity.get_admin_audit_status(actor=admin, event_id=reset_event_id)["status"] == "published"
    assert identity.get_admin_audit_status(actor=admin, event_id=deactivate_event_id)["status"] == "published"
    assert query(postgres_db, "SELECT count(*) FROM rick_audit_events WHERE event_id IN (%s,%s,%s,%s)", (create_event_id, update_event_id, reset_event_id, deactivate_event_id)) == [(4,)]
    projected = PostgresAuditSink(connect).list(tenant_id="tenant-a")
    assert {event["action"] for event in projected} >= {
        "admin.user_created", "admin.user_updated", "admin.user_access_reset", "admin.user_deactivated"
    }

    # Repair an inconsistent state in which the global account is disabled
    # while the actor's exact workspace membership is still active.
    query(postgres_db, "UPDATE rick_users SET status='disabled' WHERE user_id=%s", (created_user["user_id"],))
    query(postgres_db, """
        UPDATE rick_memberships SET status='active'
        WHERE tenant_id='tenant-a' AND user_id=%s AND workspace_id='workspace'
    """, (created_user["user_id"],))
    insert_target_session("target-session-global-disabled", "tenant-a", reset_version + 1, "workspace")
    inactive_deactivation_revoked, inactive_deactivation_event_id = identity.admin_deactivate_user(
        actor=admin,
        user_id=created_user["user_id"],
        request_id="request-globally-disabled-membership",
    )
    assert inactive_deactivation_revoked == 1
    assert query(postgres_db, "SELECT status FROM rick_users WHERE user_id=%s", (created_user["user_id"],)) == [("disabled",)]
    assert query(postgres_db, """
        SELECT status FROM rick_memberships
        WHERE tenant_id='tenant-a' AND user_id=%s AND workspace_id='workspace'
    """, (created_user["user_id"],)) == [("disabled",)]
    assert query(postgres_db, "SELECT revoke_reason FROM rick_sessions WHERE session_id='target-session-global-disabled'") == [("user_disabled",)]
    assert identity.get_admin_audit_status(actor=admin, event_id=inactive_deactivation_event_id)["status"] == "pending"
    assert reconciler.process_once() == 1
    assert identity.get_admin_audit_status(actor=admin, event_id=inactive_deactivation_event_id)["status"] == "published"

    # Exercise the real API route with the PostgreSQL atomic provider, then
    # prove that its response refers to the durable completion event.
    from fastapi.testclient import TestClient
    from app import create_app
    from core.config import ApiSettings
    from dependencies.identity import get_current_session
    from dependencies.services import Providers
    from rick_contracts.security import SessionSnapshot
    from services.audit import InMemoryAuditSink

    api_settings = ApiSettings(
        environment="local", identity_mode="dev",
        cors_allowed_origins=("http://localhost:3000",), session_cookie_secure=False,
    )
    api_providers = Providers(
        settings=api_settings, identity=identity, audit_sink=InMemoryAuditSink(),
    )
    api = create_app(api_settings, api_providers)
    api_session = SessionSnapshot(
        authenticated=True, session_state="active", user_id="admin-a",
        email="admin-a@example.test", role="PLATFORM_ADMIN", canonical_role="PLATFORM_ADMIN",
        permissions=["users.manage", "audit.read"], tenant_id="tenant-a",
        workspace_id="workspace", session_id="admin-a-test-session",
    )
    api.dependency_overrides[get_current_session] = lambda: api_session
    with TestClient(api, raise_server_exceptions=False) as client:
        api_response = client.post("/api/v1/admin/users", json={
            "email": "api-route-user@example.test", "role": "VETERINARIAN",
            "tenant_id": "tenant-a", "password": "private-api-password",
        })
    assert api_response.status_code == 202, api_response.text
    api_body = api_response.json()
    assert api_body["audit_status"] == "pending"
    assert query(postgres_db, "SELECT email FROM rick_users WHERE user_id=%s", (api_body["user"]["user_id"],)) == [
        ("api-route-user@example.test",),
    ]
    assert query(
        postgres_db,
        "SELECT payload->>'action',tenant_id FROM rick_outbox WHERE event_id=%s",
        (api_body["audit_event_id"],),
    ) == [("admin.user_created", "tenant-a")]
    assert reconciler.process_once() == 1
    assert identity.get_admin_audit_status(actor=admin, event_id=api_body["audit_event_id"])["status"] == "published"

    # The legacy direct provider entry point must either have actor scope and
    # delegate to the atomic operation, or fail before opening a connection.
    with pytest.raises(ApiError) as direct_create_denied:
        identity.create_user(
            email="unscoped-direct-user@example.test", role="VETERINARIAN",
            tenant_id="tenant-a", password="private-direct-password",
        )
    assert direct_create_denied.value.code == "provider_unavailable"
    assert query(postgres_db, "SELECT count(*) FROM rick_users WHERE email=%s", ("unscoped-direct-user@example.test",)) == [(0,)]
    direct_user = identity.create_user(
        actor=admin, email="scoped-direct-user@example.test", role="VETERINARIAN",
        tenant_id="tenant-a", password="private-direct-password", request_id="request-direct-create",
    )
    direct_event_id, = query(
        postgres_db,
        "SELECT event_id FROM rick_outbox WHERE aggregate_id=%s AND event_type='admin.audit.completion'",
        (direct_user["user_id"],),
    )[0]
    assert query(
        postgres_db,
        "SELECT payload->>'action',payload->>'request_id' FROM rick_outbox WHERE event_id=%s",
        (direct_event_id,),
    ) == [("admin.user_created", "request-direct-create")]

    restart_event_id = "admin-audit-restart-resume-live"
    restart_payload = json.dumps({
        "action": "admin.user_updated", "actor_user_id": "admin-a",
        "target_type": "user", "target_id": created_user["user_id"],
        "tenant_id": "tenant-a", "workspace_id": "workspace",
        "request_id": "request-restart", "status": "completed",
    })
    query(postgres_db, """
        INSERT INTO rick_outbox(event_id,tenant_id,aggregate_type,aggregate_id,event_type,payload)
        VALUES (%s,'tenant-a','rick_user',%s,'admin.audit.completion',CAST(%s AS jsonb))
    """, (restart_event_id, created_user["user_id"], restart_payload))
    query(postgres_db, """
        CREATE FUNCTION delay_admin_audit_projection() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.event_id = 'admin-audit-restart-resume-live' THEN
                PERFORM pg_sleep(30);
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    query(postgres_db, """
        CREATE TRIGGER delay_admin_audit_projection_trg
        BEFORE INSERT ON rick_audit_events FOR EACH ROW EXECUTE FUNCTION delay_admin_audit_projection()
    """)
    worker_paths = (
        "apps/worker", "apps/api/src", "packages/contracts/src", "packages/authorization/src",
        "packages/identity/src", "packages/observability/src", "packages/knowledge/src",
        "packages/ingestion/src", "packages/retrieval/src", "packages/providers/src",
        "packages/locking/src", "packages/professor/src", "packages/evidence/src", "packages/decision/src",
    )
    worker_env = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": os.pathsep.join(str(ROOT / item) for item in worker_paths)
        + os.pathsep + os.environ.get("PYTHONPATH", ""),
    }
    worker_runtime_code = """
import sys
from threading import Event
from types import SimpleNamespace
import psycopg
from admin_audit_outbox import PostgresAdminAuditReconciler
from deployment_composition import DeploymentRuntime
class Worker:
    def start(self):
        return True
    def health_check(self):
        return True
    def run_forever(self):
        Event().wait()
    def shutdown(self, *, timeout):
        return True
dsn = sys.argv[1]
worker = Worker()
reconciler = PostgresAdminAuditReconciler(lambda: psycopg.connect(dsn, connect_timeout=2))
runtime = DeploymentRuntime(
    SimpleNamespace(worker=worker, health_checks={}),
    admin_audit_reconciler=reconciler,
    admin_audit_poll_interval=0.05,
)
if runtime.start() is not True:
    raise SystemExit(2)
print("runtime-started", flush=True)
runtime.run_forever()
"""
    crash_worker_app = "q24-audit-crash-" + uuid.uuid4().hex
    crash_worker_dsn = make_conninfo(
        postgres_db,
        application_name=crash_worker_app,
        options="-c statement_timeout=0 -c lock_timeout=5000",
    )
    crash_worker = subprocess.Popen(
        [sys.executable, "-c", worker_runtime_code, crash_worker_dsn],
        env=worker_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        wait_deadline = time.monotonic() + 10
        while True:
            sleeping = query(postgres_db, """
                SELECT pid FROM pg_stat_activity
                WHERE application_name=%s AND datname=current_database() AND wait_event='PgSleep'
            """, (crash_worker_app,))
            if sleeping:
                break
            if crash_worker.poll() is not None:
                stdout, stderr = crash_worker.communicate(timeout=5)
                pytest.fail(f"worker exited before projection crash point: {stdout} {stderr}")
            assert time.monotonic() < wait_deadline, "worker never reached the in-transaction projection point"
            time.sleep(0.05)
        assert query(postgres_db, "SELECT pg_terminate_backend(%s)", (sleeping[0][0],)) == [(True,)]
        failure_deadline = time.monotonic() + 10
        while True:
            attempts = query(
                postgres_db,
                "SELECT attempts FROM rick_outbox WHERE event_id=%s",
                (restart_event_id,),
            )[0][0]
            if attempts == 1:
                break
            if crash_worker.poll() is not None:
                stdout, stderr = crash_worker.communicate(timeout=5)
                pytest.fail(f"worker exited before recording the interrupted attempt: {stdout} {stderr}")
            assert time.monotonic() < failure_deadline, "interrupted projection did not record its bounded retry"
            time.sleep(0.05)
        crash_worker.kill()
        crash_stdout, crash_stderr = crash_worker.communicate(timeout=15)
        assert crash_worker.returncode is not None and crash_worker.returncode < 0, crash_stderr
        assert "runtime-started" in crash_stdout
    finally:
        if crash_worker.poll() is None:
            crash_worker.kill()
            crash_worker.communicate(timeout=5)
    query(postgres_db, "DROP TRIGGER delay_admin_audit_projection_trg ON rick_audit_events")
    query(postgres_db, "DROP FUNCTION delay_admin_audit_projection()")
    attempts, published_at = query(
        postgres_db,
        "SELECT attempts,published_at FROM rick_outbox WHERE event_id=%s",
        (restart_event_id,),
    )[0]
    assert attempts == 1 and published_at is None
    restarted_worker_app = "q24-audit-restart-" + uuid.uuid4().hex
    restarted_worker_dsn = make_conninfo(postgres_db, application_name=restarted_worker_app)
    restarted_worker = subprocess.Popen(
        [sys.executable, "-c", worker_runtime_code, restarted_worker_dsn],
        env=worker_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        wait_deadline = time.monotonic() + 15
        while True:
            published = query(
                postgres_db,
                "SELECT published_at FROM rick_outbox WHERE event_id=%s",
                (restart_event_id,),
            )[0][0]
            if published is not None:
                break
            if restarted_worker.poll() is not None:
                stdout, stderr = restarted_worker.communicate(timeout=5)
                pytest.fail(f"restarted deployment worker exited before recovery: {stdout} {stderr}")
            assert time.monotonic() < wait_deadline, "restarted deployment worker did not recover the outbox event"
            time.sleep(0.05)
    finally:
        if restarted_worker.poll() is None:
            restarted_worker.kill()
        restarted_stdout, restarted_stderr = restarted_worker.communicate(timeout=15)
    assert "runtime-started" in restarted_stdout, restarted_stderr
    assert query(postgres_db, "SELECT count(*) FROM rick_audit_events WHERE event_id=%s", (restart_event_id,)) == [(1,)]
    assert identity.get_admin_audit_status(actor=admin, event_id=restart_event_id)["status"] == "published"

    concurrent_event_id = "admin-audit-concurrent-live"
    concurrent_payload = json.dumps({
        "action": "admin.user_updated", "actor_user_id": "admin-a",
        "target_type": "user", "target_id": created_user["user_id"],
        "tenant_id": "tenant-a", "workspace_id": "workspace",
        "request_id": "request-concurrent", "status": "completed",
    })
    query(postgres_db, """
        INSERT INTO rick_outbox(event_id,tenant_id,aggregate_type,aggregate_id,event_type,payload)
        VALUES (%s,'tenant-a','rick_user',%s,'admin.audit.completion',CAST(%s AS jsonb))
    """, (concurrent_event_id, created_user["user_id"], concurrent_payload))
    query(postgres_db, """
        CREATE FUNCTION delay_admin_audit_projection() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.event_id = 'admin-audit-concurrent-live' THEN
                PERFORM pg_sleep(3);
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    query(postgres_db, """
        CREATE TRIGGER delay_admin_audit_projection_trg
        BEFORE INSERT ON rick_audit_events FOR EACH ROW EXECUTE FUNCTION delay_admin_audit_projection()
    """)
    concurrent_worker_app = "q24-audit-concurrent-a-" + uuid.uuid4().hex
    competing_worker_app = "q24-audit-concurrent-b-" + uuid.uuid4().hex
    concurrent_worker_dsn = make_conninfo(postgres_db, application_name=concurrent_worker_app)
    competing_worker_dsn = make_conninfo(postgres_db, application_name=competing_worker_app)
    concurrent_worker = PostgresAdminAuditReconciler(
        lambda: psycopg.connect(concurrent_worker_dsn, connect_timeout=2), batch_size=1
    )
    competing_worker = PostgresAdminAuditReconciler(
        lambda: psycopg.connect(competing_worker_dsn, connect_timeout=2), batch_size=1
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        active_worker = executor.submit(concurrent_worker.process_once)
        wait_deadline = time.monotonic() + 10
        while True:
            sleeping = query(postgres_db, """
                SELECT pid FROM pg_stat_activity
                WHERE application_name=%s AND datname=current_database() AND wait_event='PgSleep'
            """, (concurrent_worker_app,))
            if sleeping:
                break
            assert not active_worker.done(), "first consumer exited before locking the pending event"
            assert time.monotonic() < wait_deadline, "first consumer never held the pending row lock"
            time.sleep(0.05)
        assert competing_worker.process_once() == 0
        assert active_worker.result(timeout=10) == 1
    query(postgres_db, "DROP TRIGGER delay_admin_audit_projection_trg ON rick_audit_events")
    query(postgres_db, "DROP FUNCTION delay_admin_audit_projection()")
    assert query(postgres_db, "SELECT count(*) FROM rick_audit_events WHERE event_id=%s", (concurrent_event_id,)) == [(1,)]
    assert identity.get_admin_audit_status(actor=admin, event_id=concurrent_event_id)["status"] == "published"

    dead_event_id = "admin-audit-dead-letter-live"
    query(postgres_db, """
            INSERT INTO rick_outbox(event_id,tenant_id,aggregate_type,aggregate_id,event_type,payload)
            VALUES (%s,'tenant-a','rick_user','target','admin.audit.completion',
                    '{"action":"admin.user_updated","tenant_id":"other-tenant","workspace_id":"workspace","status":"completed"}'::jsonb)
    """, (dead_event_id,))
    bounded_reconciler = PostgresAdminAuditReconciler(connect, max_attempts=1)
    for retry_number in range(4):
        assert bounded_reconciler.process_once() == 0
        dead_status = identity.get_admin_audit_status(actor=admin, event_id=dead_event_id)
        assert dead_status["status"] == "dead_lettered"
        assert dead_status["manual_retry_count"] == retry_number
        foreign_workspace_actor = actor("admin-other", "tenant-a")
        foreign_workspace_actor.workspace_id = "other-workspace"
        assert identity.get_admin_audit_status(actor=foreign_workspace_actor, event_id=dead_event_id) is None
        if retry_number < 3:
            assert dead_status["can_retry"] is True
            assert identity.retry_admin_audit_event(actor=admin, event_id=dead_event_id) is True
            if retry_number == 0:
                assert identity.retry_admin_audit_event(actor=foreign_workspace_actor, event_id=dead_event_id) is False
        else:
            assert dead_status["can_retry"] is False
            assert identity.retry_admin_audit_event(actor=admin, event_id=dead_event_id) is False

    barrier = threading.Barrier(2)

    def deactivate_last_admin(admin_id):
        barrier.wait(timeout=5)
        try:
            identity.admin_deactivate_user(
                actor=actor(admin_id, "tenant-race"),
                user_id=admin_id,
                request_id=f"request-{admin_id}",
            )
            return "committed"
        except ApiError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(deactivate_last_admin, ("race-a", "race-b")))
    assert sorted(results) == ["committed", "conflict"]
    assert query(postgres_db, """
        SELECT count(*) FROM rick_memberships m JOIN rick_users u USING (user_id)
        WHERE m.tenant_id='tenant-race' AND m.role='PLATFORM_ADMIN'
          AND m.status='active' AND u.status='active'
    """) == [(1,)]
    assert PostgresAdminAuditReconciler(connect).process_once() == 1

    # Demoting the sole active administrator in workspace A must fail even
    # when workspace B in the same tenant still has another administrator.
    query(postgres_db, "INSERT INTO rick_tenants(tenant_id,display_name) VALUES ('tenant-demotion','tenant-demotion')")
    query(postgres_db, """
        INSERT INTO rick_users(user_id,email) VALUES
            ('demotion-manager','demotion-manager@example.test'),
            ('demotion-target','demotion-target@example.test'),
            ('demotion-admin-b','demotion-admin-b@example.test')
    """)
    query(postgres_db, """
        INSERT INTO rick_memberships(tenant_id,user_id,workspace_id,role,status)
        VALUES
            ('tenant-demotion','demotion-manager','workspace-a','VETERINARIAN','active'),
            ('tenant-demotion','demotion-target','workspace-a','PLATFORM_ADMIN','active'),
            ('tenant-demotion','demotion-target','workspace-b','VETERINARIAN','active'),
            ('tenant-demotion','demotion-admin-b','workspace-b','PLATFORM_ADMIN','active')
    """)
    workspace_manager = SimpleNamespace(
        user_id="demotion-manager", tenant_id="tenant-demotion", workspace_id="workspace-a",
        role="VETERINARIAN", canonical_role="VETERINARIAN", permissions=["users.manage"],
    )
    demotion_outbox_before = query(
        postgres_db,
        "SELECT count(*) FROM rick_outbox WHERE aggregate_id='demotion-target' AND event_type='admin.audit.completion'",
    )[0][0]
    with pytest.raises(ApiError) as workspace_demotion_error:
        identity.admin_update_user(
            actor=workspace_manager, user_id="demotion-target", role="VETERINARIAN",
            request_id="request-demote-last-workspace-admin",
        )
    assert workspace_demotion_error.value.code == "conflict"
    assert query(postgres_db, """
        SELECT workspace_id,role,status FROM rick_memberships
        WHERE tenant_id='tenant-demotion' AND user_id='demotion-target' ORDER BY workspace_id
    """) == [
        ("workspace-a", "PLATFORM_ADMIN", "active"),
        ("workspace-b", "VETERINARIAN", "active"),
    ]
    assert query(postgres_db, """
        SELECT count(*) FROM rick_memberships
        WHERE tenant_id='tenant-demotion' AND workspace_id='workspace-b'
          AND role='PLATFORM_ADMIN' AND status='active'
    """) == [(1,)]
    assert query(
        postgres_db,
        "SELECT count(*) FROM rick_outbox WHERE aggregate_id='demotion-target' AND event_type='admin.audit.completion'",
    ) == [(demotion_outbox_before,)]


@pytest.mark.parametrize("patch_kind", ["empty", "workspace_only"])
@pytest.mark.parametrize("lock_order", ["admin_first", "recovery_first"])
def test_postgres_sparse_admin_update_serializes_with_password_recovery(
    postgres_db, monkeypatch, patch_kind, lock_order,
):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from types import SimpleNamespace

    for relative in (
        "apps/api/src",
        "packages/authorization/src",
        "packages/contracts/src",
        "packages/identity/src",
        "packages/observability/src",
    ):
        monkeypatch.syspath_prepend(str(ROOT / relative))

    from rick_identity.passwords import hash_password, verify_password_hash
    from services.postgres_identity import PostgresIdentityProvider

    migrate.apply(MIGRATIONS, postgres_db)
    tenant_id = "tenant-sparse-recovery-race"
    admin_id = "admin-sparse-recovery-race"
    target_id = "target-sparse-recovery-race"
    target_email = "target-sparse-recovery-race@example.test"
    query(postgres_db, "INSERT INTO rick_tenants(tenant_id,display_name) VALUES (%s,%s)",
          (tenant_id, tenant_id))
    query(postgres_db, "INSERT INTO rick_users(user_id,email) VALUES (%s,%s)",
          (admin_id, "admin-sparse-recovery-race@example.test"))
    query(postgres_db, """
        INSERT INTO rick_memberships(tenant_id,user_id,workspace_id,role,status)
        VALUES (%s,%s,'workspace','PLATFORM_ADMIN','active')
    """, (tenant_id, admin_id))
    old_password_hash = hash_password("password-before-recovery")
    query(postgres_db, """
        INSERT INTO rick_users(user_id,email,password_hash,password_version)
        VALUES (%s,%s,%s,1)
    """, (target_id, target_email, old_password_hash))
    query(postgres_db, """
        INSERT INTO rick_memberships(tenant_id,user_id,workspace_id,role,status)
        VALUES (%s,%s,'workspace','VETERINARIAN','active')
    """, (tenant_id, target_id))

    def connect():
        import psycopg
        return psycopg.connect(postgres_db, connect_timeout=2)

    identity = PostgresIdentityProvider(connect, production_safe=True)
    admin = SimpleNamespace(
        user_id=admin_id, tenant_id=tenant_id, workspace_id="workspace",
        role="PLATFORM_ADMIN", canonical_role="PLATFORM_ADMIN", permissions=["users.manage"],
    )
    recovery_token = identity.issue_password_reset(email=target_email, tenant_id=tenant_id)
    assert isinstance(recovery_token, str)

    original_lookup = identity._users.get_by_id_for_tenant_workspace
    original_lock_user = identity._users.lock_user_for_update
    original_revoke_user = identity._sessions.revoke_user
    worker_role = threading.local()
    admin_read_paused = threading.Event()
    allow_admin_update_to_save = threading.Event()
    admin_lock_attempted = threading.Event()
    recovery_lock_attempted = threading.Event()
    recovery_holds_account_lock = threading.Event()
    allow_recovery_to_commit = threading.Event()
    admin_finished = threading.Event()
    recovery_finished = threading.Event()
    paused_once = threading.Event()

    def pause_after_admin_read(user_id, tenant, workspace, *, connection=None):
        row = original_lookup(user_id, tenant, workspace, connection=connection)
        if row is not None and lock_order == "admin_first" and not paused_once.is_set():
            paused_once.set()
            admin_read_paused.set()
            if not allow_admin_update_to_save.wait(timeout=10):
                raise AssertionError("timed out waiting to resume sparse admin update")
        return row

    def observe_account_lock(user_id, *, connection=None):
        if getattr(worker_role, "name", None) == "admin":
            admin_lock_attempted.set()
        elif getattr(worker_role, "name", None) == "recovery":
            recovery_lock_attempted.set()
        return original_lock_user(user_id, connection=connection)

    def pause_recovery_before_session_revocation(*args, **kwargs):
        if kwargs.get("reason") == "password_recovery":
            recovery_holds_account_lock.set()
            if not allow_recovery_to_commit.wait(timeout=10):
                raise AssertionError("timed out waiting to commit password recovery")
        return original_revoke_user(*args, **kwargs)

    identity._users.get_by_id_for_tenant_workspace = pause_after_admin_read
    identity._users.lock_user_for_update = observe_account_lock
    identity._sessions.revoke_user = pause_recovery_before_session_revocation

    def sparse_admin_patch():
        worker_role.name = "admin"
        try:
            return identity.admin_update_user(
                actor=admin,
                user_id=target_id,
                request_id=f"request-{patch_kind}-patch-{lock_order}",
                workspace_id="workspace" if patch_kind == "workspace_only" else None,
            )
        finally:
            admin_finished.set()

    def recover_password():
        worker_role.name = "recovery"
        try:
            return identity.consume_password_reset(
                token=recovery_token, new_password="password-after-recovery",
            )
        finally:
            recovery_finished.set()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            if lock_order == "admin_first":
                update_future = pool.submit(sparse_admin_patch)
                assert admin_read_paused.wait(timeout=10), "sparse admin PATCH did not read the target row"
                recovery_future = pool.submit(recover_password)
                assert recovery_lock_attempted.wait(timeout=10), "password recovery did not request the account lock"
                assert not recovery_finished.wait(timeout=1), (
                    "password recovery passed the account lock while the full-row admin update was paused"
                )
                allow_admin_update_to_save.set()
            else:
                recovery_future = pool.submit(recover_password)
                assert recovery_holds_account_lock.wait(timeout=10), (
                    "password recovery did not reach its account-locked commit boundary"
                )
                update_future = pool.submit(sparse_admin_patch)
                assert admin_lock_attempted.wait(timeout=10), "sparse admin PATCH did not request the account lock"
                assert not admin_finished.wait(timeout=1), (
                    "sparse admin PATCH passed the account lock while password recovery held it"
                )
                allow_recovery_to_commit.set()
            update_future.result(timeout=10)
            allow_recovery_to_commit.set()
            recovery_future.result(timeout=10)
    finally:
        allow_admin_update_to_save.set()
        allow_recovery_to_commit.set()
        identity._users.get_by_id_for_tenant_workspace = original_lookup
        identity._users.lock_user_for_update = original_lock_user
        identity._sessions.revoke_user = original_revoke_user

    recovered_hash, recovered_version = query(
        postgres_db,
        "SELECT password_hash,password_version FROM rick_users WHERE user_id=%s",
        (target_id,),
    )[0]
    assert recovered_version == 2
    assert verify_password_hash(recovered_hash, "password-after-recovery")
    assert not verify_password_hash(recovered_hash, "password-before-recovery")
    assert query(
        postgres_db,
        "SELECT workspace_id,role,status FROM rick_memberships WHERE tenant_id=%s AND user_id=%s",
        (tenant_id, target_id),
    ) == [("workspace", "VETERINARIAN", "active")]


def test_postgres_canonical_job_queue_live_claim_fencing_replay_and_retention(postgres_db, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    for relative in ("apps/worker", "packages/jobs/src"):
        monkeypatch.syspath_prepend(str(ROOT / relative))

    import psycopg
    from psycopg.conninfo import make_conninfo
    from rick_jobs import Job, JobFailure, JobResult, JobScope, JobState
    from postgres_jobs import (
        PostgresJobError,
        PostgresJobIdempotencyError,
        PostgresJobLeaseError,
        PostgresJobQueue,
    )

    migrate.apply(MIGRATIONS, postgres_db)
    seed_scope(postgres_db)
    scope = JobScope("tenant", "workspace", "collection")
    first_id = "a-q17-live-claim"
    second_id = "b-q17-live-claim"
    locker_app = "q17-job-locker-" + uuid.uuid4().hex
    competitor_app = "q17-job-competitor-" + uuid.uuid4().hex
    plain_app = "q17-job-plain-" + uuid.uuid4().hex

    def connect(application_name, lock_timeout="5000ms"):
        dsn = make_conninfo(
            postgres_db,
            application_name=application_name,
            options=f"-c statement_timeout=8000 -c lock_timeout={lock_timeout}",
        )
        return lambda: psycopg.connect(dsn, connect_timeout=2)

    queue_a = PostgresJobQueue(connect(locker_app), max_attempts=2, lease_seconds=1.0, backoff_seconds=0.0)
    queue_b = PostgresJobQueue(connect(competitor_app, "500ms"), max_attempts=2, lease_seconds=1.0, backoff_seconds=0.0)
    queue_plain = PostgresJobQueue(connect(plain_app), max_attempts=2, lease_seconds=1.0, backoff_seconds=0.0)

    def new_job(job_id, key, *, max_attempts=2):
        return Job.create(
            job_id=job_id,
            tenant_id=scope.tenant_id,
            workspace_id=scope.workspace_id,
            collection_id=scope.collection_id,
            operation="ingest",
            idempotency_key=key,
            payload={"source_key": f"objects/{job_id}.txt"},
            now=time.time(),
            max_attempts=max_attempts,
        )

    first = new_job(first_id, "idem-q17-first", max_attempts=3)
    second = new_job(second_id, "idem-q17-second", max_attempts=1)
    first_queued = queue_a.enqueue(first, expected_version=0)
    second_queued = queue_b.enqueue(second, expected_version=0)
    assert first_queued.state is JobState.QUEUED
    assert second_queued.state is JobState.QUEUED
    replayed = queue_plain.create_or_replay(first, expected_version=0)
    assert replayed.job_id == first_queued.job_id
    assert replayed.version == first_queued.version
    with pytest.raises(PostgresJobIdempotencyError):
        queue_plain.create_or_replay(
            new_job("different-q17-job", "idem-q17-first"), expected_version=0,
        )
    assert query(
        postgres_db,
        "SELECT count(*) FROM rick_ingestion_job_events WHERE job_id=%s AND event_type='created'",
        (first_id,),
    ) == [(1,)]

    # Hold the first real row lock inside PostgreSQL while a second consumer
    # claims the next job. The competing claim must skip the locked row.
    query(postgres_db, f"""
        CREATE FUNCTION q17_delay_job_claim() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF current_setting('application_name') = '{locker_app}'
               AND NEW.contract_state = 'RUNNING' THEN
                PERFORM pg_sleep(0.75);
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    query(postgres_db, """
        CREATE TRIGGER q17_delay_job_claim_trg
        BEFORE UPDATE ON rick_ingestion_jobs
        FOR EACH ROW EXECUTE FUNCTION q17_delay_job_claim()
    """)
    first_claim_future = None
    first_claim = ()
    second_claim = ()
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            first_claim_future = executor.submit(
                queue_a.claim,
                worker_id="worker-q17-a",
                scope=scope,
                expected_versions={},
                limit=1,
                now=time.time(),
            )
            wait_deadline = time.monotonic() + 8
            while True:
                sleeping = query(
                    postgres_db,
                    """SELECT pid FROM pg_stat_activity
                       WHERE application_name=%s AND datname=current_database()
                         AND wait_event='PgSleep'""",
                    (locker_app,),
                )
                if sleeping:
                    break
                assert not first_claim_future.done(), "first consumer exited before the locked-row window"
                assert time.monotonic() < wait_deadline, "first consumer did not reach the PostgreSQL lock window"
                time.sleep(0.02)
            second_claim = queue_b.claim(
                worker_id="worker-q17-b",
                scope=scope,
                expected_versions={},
                limit=1,
                now=time.time(),
            )
            assert len(second_claim) == 1
            first_claim = first_claim_future.result(timeout=5)
    finally:
        if first_claim_future is not None and not first_claim_future.done():
            first_claim_future.cancel()
        query(postgres_db, "DROP TRIGGER IF EXISTS q17_delay_job_claim_trg ON rick_ingestion_jobs")
        query(postgres_db, "DROP FUNCTION IF EXISTS q17_delay_job_claim()")

    assert len(first_claim) == 1
    first_running, stale_lease = first_claim[0]
    second_running, second_lease = second_claim[0]
    assert first_running.job_id != second_running.job_id
    second_succeeded = queue_b.acknowledge(
        second_lease,
        JobResult(output_refs={"object_key": "objects/q17-second-result"}, completed_at=time.time()),
        now=time.time(),
        expected_version=second_running.version,
    )
    assert second_succeeded.state is JobState.SUCCEEDED

    # A new connection recovers an expired attempt, and the old owner cannot
    # acknowledge the replacement lease or mutate its durable version.
    time.sleep(1.05)
    recovered_claim = queue_b.claim(
        worker_id="worker-q17-recovery",
        scope=scope,
        expected_versions={},
        limit=1,
        now=time.time(),
    )
    assert len(recovered_claim) == 1
    retried, current_lease = recovered_claim[0]
    assert retried.job_id == first_running.job_id
    assert retried.attempt_count == 2
    with pytest.raises(PostgresJobLeaseError):
        queue_a.acknowledge(
            stale_lease,
            JobResult(output_refs={}, completed_at=time.time()),
            now=time.time(),
            expected_version=first_running.version,
        )
    retried_after_failure = queue_b.fail(
        current_lease,
        JobFailure("provider_timeout", "provider timed out", True, 2, time.time()),
        now=time.time(),
        expected_version=retried.version,
    )
    assert retried_after_failure.state is JobState.QUEUED
    third_claim = queue_b.claim(
        worker_id="worker-q17-dead-letter",
        scope=scope,
        expected_versions={},
        limit=1,
        now=time.time(),
    )
    assert len(third_claim) == 1
    dead_running, dead_lease = third_claim[0]
    assert dead_running.job_id == first_running.job_id
    assert dead_running.attempt_count == 3
    dead = queue_b.fail(
        dead_lease,
        JobFailure("schema_invalid", "invalid job schema", False, 3, time.time()),
        now=time.time(),
        expected_version=dead_running.version,
    )
    assert dead.state is JobState.DEAD_LETTER
    assert len(dead.attempts) == 3
    assert [(attempt.state, attempt.worker_id) for attempt in dead.attempts] == [
        (JobState.FAILED, "worker-q17-a"),
        (JobState.FAILED, "worker-q17-recovery"),
        (JobState.FAILED, "worker-q17-dead-letter"),
    ]
    assert [job.job_id for job in queue_plain.list_dead_letters(scope=scope)] == [dead.job_id]
    requeued = queue_plain.replay_dead_letter(
        dead.job_id,
        tenant_id=scope.tenant_id,
        workspace_id=scope.workspace_id,
        collection_id=scope.collection_id,
        replay_job_id="q17-live-replay",
        replay_idempotency_key="idem-q17-live-replay",
        now=time.time(),
        expected_version=dead.version,
    )
    assert requeued.state is JobState.QUEUED
    assert queue_b.get_by_idempotency(
        tenant_id=scope.tenant_id,
        workspace_id=scope.workspace_id,
        collection_id=scope.collection_id,
        idempotency_key="idem-q17-live-replay",
    ).job_id == requeued.job_id
    cancelled_replay = queue_plain.cancel(
        requeued.job_id,
        tenant_id=scope.tenant_id,
        workspace_id=scope.workspace_id,
        collection_id=scope.collection_id,
        now=time.time(),
        expected_version=requeued.version,
    )
    assert cancelled_replay.state is JobState.CANCELLED

    # A fault after the row/attempt update but before audit/outbox projection
    # must roll back the entire acknowledgement transaction.
    rollback_job = new_job("q17-live-rollback", "idem-q17-live-rollback")
    queued_rollback = queue_plain.enqueue(rollback_job, expected_version=0)
    rollback_running, rollback_lease = queue_plain.claim(
        worker_id="worker-q17-rollback",
        scope=scope,
        expected_versions={queued_rollback.job_id: queued_rollback.version},
        now=time.time(),
    )[0]

    def fail_before_projection(point):
        if point == "before_publish":
            raise RuntimeError("controlled local rollback point")

    failing_queue = PostgresJobQueue(
        connect(plain_app),
        max_attempts=2,
        lease_seconds=1.0,
        backoff_seconds=0.0,
        fault_injector=fail_before_projection,
    )
    with pytest.raises(PostgresJobError) as rollback_error:
        failing_queue.acknowledge(
            rollback_lease,
            JobResult(output_refs={"object_key": "objects/rollback-result"}, completed_at=time.time()),
            now=time.time(),
            expected_version=rollback_running.version,
        )
    assert rollback_error.value.code == "queue_unavailable"
    durable_state = query(
        postgres_db,
        "SELECT contract_state,version FROM rick_ingestion_jobs WHERE job_id=%s",
        (rollback_job.job_id,),
    )
    assert durable_state == [("RUNNING", rollback_running.version)]
    assert query(
        postgres_db,
        "SELECT state FROM rick_ingestion_job_attempts WHERE job_id=%s ORDER BY attempt_no",
        (rollback_job.job_id,),
    ) == [("RUNNING",)]
    assert query(
        postgres_db,
        "SELECT count(*) FROM rick_outbox WHERE aggregate_id=%s AND event_type='jobs.acknowledged'",
        (rollback_job.job_id,),
    ) == [(0,)]
    rollback_succeeded = queue_plain.acknowledge(
        rollback_lease,
        JobResult(output_refs={"object_key": "objects/rollback-result"}, completed_at=time.time()),
        now=time.time(),
        expected_version=rollback_running.version,
    )
    assert rollback_succeeded.state is JobState.SUCCEEDED

    # Retention deletes the terminal job rows but keeps the durable audit and
    # outbox projections that record the deletion.
    cutoff = time.time() + 10
    assert queue_plain.prune_terminal(scope=scope, older_than=cutoff, limit=10) == 4
    assert query(
        postgres_db,
        "SELECT count(*) FROM rick_ingestion_jobs WHERE job_id IN (%s,%s,%s,%s)",
        (first_running.job_id, second_running.job_id, rollback_job.job_id, requeued.job_id),
    ) == [(0,)]
    assert query(
        postgres_db,
        "SELECT count(*) FROM rick_outbox WHERE aggregate_type='job' AND event_type='jobs.retention_pruned' AND aggregate_id IN (%s,%s,%s,%s)",
        (first_running.job_id, second_running.job_id, rollback_job.job_id, requeued.job_id),
    ) == [(4,)]
    assert query(
        postgres_db,
        "SELECT count(*) FROM rick_audit_events WHERE action='jobs.retention_pruned' AND target_id IN (%s,%s,%s,%s)",
        (first_running.job_id, second_running.job_id, rollback_job.job_id, requeued.job_id),
    ) == [(4,)]
