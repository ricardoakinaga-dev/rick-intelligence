import importlib.util
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location(
    "backup_restore", Path(__file__).parents[1] / "backup_restore.py"
)
backup_restore = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(backup_restore)


NOW = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)


def test_create_verify_restore_and_reconcile(tmp_path: Path) -> None:
    source = tmp_path / "exports"
    source.mkdir()
    (source / "db.json").write_text('{"rows": 2}\n', encoding="utf-8")
    (source / "audit.log").write_text("event-a\nevent-b\n", encoding="utf-8")
    backups = tmp_path / "backups"

    manifest = backup_restore.create_backup(
        {"postgres": source},
        backups,
        backup_id="release-001",
        operator="operator-1",
        restore_target="/srv/restore/release-001",
        created_at=NOW,
    )

    assert manifest["status"] == "PASS"
    verified = backup_restore.verify_backup(backups / "release-001")
    assert verified["file_count"] == 2
    assert verified["component_summary"]["postgres"]["byte_count"] > 0

    target = tmp_path / "restored"
    dry_run = backup_restore.restore_backup(backups / "release-001", target, dry_run=True)
    assert dry_run["status"] == "DRY_RUN"
    assert not target.exists()
    restored = backup_restore.restore_backup(backups / "release-001", target)
    assert restored["status"] == "PASS"
    assert (target / "postgres" / "db.json").read_text(encoding="utf-8") == '{"rows": 2}\n'

    observed = verified["component_summary"]
    assert backup_restore.reconcile_backup(backups / "release-001", observed)["status"] == "PASS"
    mismatch = {"postgres": {**observed["postgres"], "file_count": 99}}
    assert backup_restore.reconcile_backup(backups / "release-001", mismatch)["status"] == "MISMATCH"


def test_verify_rejects_tampering_and_restore_requires_empty_target(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("original", encoding="utf-8")
    backup_root = tmp_path / "backups"
    backup_restore.create_backup(
        {"object_store": source}, backup_root, backup_id="b1", operator="ops", restore_target="target", created_at=NOW
    )
    target = tmp_path / "non-empty"
    target.mkdir()
    (target / "keep").write_text("do not overwrite", encoding="utf-8")
    with pytest.raises(backup_restore.BackupError, match="empty"):
        backup_restore.restore_backup(backup_root / "b1", target)

    payload = backup_root / "b1" / "payload" / "object_store" / "source.txt"
    payload.write_text("tampered", encoding="utf-8")
    with pytest.raises(backup_restore.BackupError):
        backup_restore.verify_backup(backup_root / "b1")


def test_purge_defaults_to_dry_run_and_keeps_latest(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.write_text("x", encoding="utf-8")
    root = tmp_path / "backups"
    for backup_id, created_at in (
        ("old", NOW - timedelta(days=30)),
        ("new", NOW - timedelta(days=1)),
    ):
        backup_restore.create_backup(
            {"audit": source}, root, backup_id=backup_id, operator="ops", restore_target="target", created_at=created_at
        )

    preview = backup_restore.purge_backups(root, retention_days=7, keep_latest=1, now=NOW)
    assert preview["status"] == "DRY_RUN"
    assert (root / "old").exists()
    applied = backup_restore.purge_backups(root, retention_days=7, keep_latest=1, dry_run=False, now=NOW)
    assert applied["status"] == "PASS"
    assert not (root / "old").exists()
    assert (root / "new").exists()


def test_backup_rejects_overlap_and_symlink_sources(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "file").write_text("x", encoding="utf-8")
    with pytest.raises(backup_restore.BackupError, match="separate"):
        backup_restore.create_backup(
            {"component": source}, source, backup_id="b", operator="ops", restore_target="target"
        )
    link = tmp_path / "link"
    link.symlink_to(source / "file")
    with pytest.raises(backup_restore.BackupError):
        backup_restore.create_backup(
            {"component": link}, tmp_path / "backups", backup_id="b", operator="ops", restore_target="target"
        )


def test_semantic_reconciliation_requires_acl_scope_and_relations(tmp_path: Path) -> None:
    source = tmp_path / "exports"
    source.mkdir()
    (source / "snapshot.json").write_text('{"rows": 2}\n', encoding="utf-8")
    metadata = {
        "postgres": {
            "record_count": 2,
            "acl_sha256": "a" * 64,
            "relation_checksums": {"conversation_messages": "b" * 64},
            "scope": {"tenant_ids": ["tenant-a"], "workspace_ids": ["workspace-a"]},
        }
    }
    root = tmp_path / "backups"
    backup_restore.create_backup(
        {"postgres": source},
        root,
        backup_id="semantic-1",
        operator="ops",
        restore_target="target",
        created_at=NOW,
        component_metadata=metadata,
    )
    verified = backup_restore.verify_backup(root / "semantic-1")
    observed = {
        "postgres": {
            **verified["component_summary"]["postgres"],
            "semantic": metadata["postgres"],
        }
    }
    assert backup_restore.reconcile_backup(
        root / "semantic-1",
        observed,
        required_components=("postgres",),
        expected_scope={"tenant_ids": ["tenant-a"], "workspace_ids": ["workspace-a"]},
    )["status"] == "PASS"

    missing_semantic = {"postgres": verified["component_summary"]["postgres"]}
    mismatch = backup_restore.reconcile_backup(root / "semantic-1", missing_semantic)
    assert mismatch["status"] == "MISMATCH"
    assert any("semantic metadata" in difference["reason"] for difference in mismatch["differences"])


def test_semantic_metadata_is_bounded_and_validated(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("x", encoding="utf-8")
    with pytest.raises(backup_restore.BackupError, match="acl_sha256"):
        backup_restore.create_backup(
            {"audit": source},
            tmp_path / "backups",
            backup_id="bad-semantic",
            operator="ops",
            restore_target="target",
            component_metadata={"audit": {"acl_sha256": "not-a-checksum"}},
        )
