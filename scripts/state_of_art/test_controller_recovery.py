"""Recovery must retain history and reject known-bad controller snapshots."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("archive_controller", ROOT / "scripts/state_of_art/archive_controller.py")
archive_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(archive_module)
CHECKER = ROOT / "scripts/control_plane/vendor/engineering_framework/scripts/check_state.py"


def copy_recorded_artifacts(root):
    """Keep snapshot fixtures complete when canonical evidence gains a file.

    Resolve real recorded artifacts, never create placeholders that could turn
    a broken source reference into a passing fixture.
    """
    records = [json.loads(line) for line in (ROOT / ".agent/verification.jsonl").read_text().splitlines() if line]
    for relative in {reference.split("#", 1)[0] for record in records for reference in record["artifacts"]}:
        source = archive_module.scoped_path(ROOT, relative)
        if not source.is_file() or source.is_symlink():
            raise ValueError(f"fixture evidence must resolve to an existing regular file: {relative}")
        target = archive_module.scoped_path(root, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


class ArchiveTests(unittest.TestCase):
    def fixture(self, root):
        for name in ("state.json", "backlog.json", "execution-log.jsonl", "verification.jsonl", "PLANS.md"):
            path = root / ".agent" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("historical bytes\n")
        gate = root / ".agent/gates/history.json"
        gate.parent.mkdir()
        gate.write_text('{"decision":"BLOCKED"}\n')

    def test_archive_retry_and_recovery_preserve_exact_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            first = archive_module.archive(root)
            self.assertEqual(archive_module.archive(root), first)
            self.assertEqual(archive_module.verify(root), 6)
            original = root / ".agent/gates/history.json"
            original.unlink()  # Synthetic fixture only; exercise restoration.
            self.assertEqual(archive_module.verify(root), 6)
            shutil.copy2(root / ".agent/legacy-v1/gates/history.json", original)
            self.assertEqual(archive_module.digest(original), first["files"][-1]["sha256"])

    def test_archive_refuses_changed_source_or_corrupt_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            archive_module.archive(root)
            (root / ".agent/state.json").write_text("new state")
            with self.assertRaises(ValueError):
                archive_module.archive(root)
            (root / ".agent/legacy-v1/state.json").write_text("corrupt archive")
            with self.assertRaises(ValueError):
                archive_module.verify(root)

    def test_partial_copy_retry_completes_without_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            target = root / ".agent/legacy-v1/state.json"
            target.parent.mkdir(parents=True)
            shutil.copy2(root / ".agent/state.json", target)
            archive_module.archive(root)
            self.assertEqual(archive_module.verify(root), 6)


    def test_manifest_cannot_hide_an_archived_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            manifest = archive_module.archive(root)
            manifest["files"].pop()
            (root / ".agent/legacy-v1/manifest.json").write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                archive_module.verify(root)

    def test_manifest_duplicate_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            archive_module.archive(root)
            manifest_path = root / ".agent/legacy-v1/manifest.json"
            manifest = manifest_path.read_text()
            manifest_path.write_text(
                manifest.replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1')
            )
            with self.assertRaises(ValueError):
                archive_module.verify(root)

    def test_symlink_archive_parent_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            destination = root / "outside"
            destination.mkdir()
            (root / ".agent/legacy-v1").symlink_to(destination, target_is_directory=True)
            with self.assertRaises(ValueError):
                archive_module.archive(root)
            self.assertEqual(list(destination.iterdir()), [])


class CanonicalControllerTests(unittest.TestCase):
    def test_real_cli_rejects_null_objects_and_schema_downgrades(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in (".agent", "docs", "scripts/control_plane/vendor", ".gauntlet-state-of-art",
                             ".gauntlet", ".orchestrate", ".orchestrate-state-of-art", ".review-control-history"):
                shutil.copytree(ROOT / relative, root / relative)
            for relative in ("cvg-master-rag-v2/AGENTS.md", "docs/architecture/controller-recovery.md",
                             "docs/ci/check_control_plane.py", "scripts/state_of_art/archive_controller.py",
                             "scripts/state_of_art/review_control_views.py"):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, target)
            copy_recorded_artifacts(root)
            subprocess.run(["git", "init", "--quiet", str(root)], check=True)
            subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                            "commit", "--allow-empty", "--quiet", "-m", "fixture"], cwd=root, check=True)
            # A copied run belongs to its original absolute workspace. Create
            # a genuinely new, empty-evidence fixture run instead of weakening
            # the manager's repository identity check.
            (root / ".gauntlet").rename(root / "imported-review-run")
            initialized = subprocess.run([
                sys.executable, str(root / "scripts/control_plane/vendor/gauntlet_loop/gauntlet_state.py"),
                "init", "--repo", str(root), "--goal-file", str(root / ".gauntlet-state-of-art/goal.txt"),
                "--bar-manifest", str(root / ".gauntlet-state-of-art/bar.canonical.json"),
                "--run-id", "isolated-cli-fixture",
            ], cwd=root, capture_output=True, text=True, timeout=20)
            self.assertEqual(initialized.returncode, 0, initialized.stdout + initialized.stderr)
            shutil.copy2(ROOT / ".gauntlet/state.md", root / ".gauntlet/state.md")

            def check():
                return subprocess.run([sys.executable, str(root / "docs/ci/check_control_plane.py")],
                                      cwd=root, capture_output=True, text=True, timeout=20)

            baseline = check()
            self.assertEqual(baseline.returncode, 0, baseline.stdout + baseline.stderr)
            state_path, backlog_path = root / ".agent/state.json", root / ".agent/backlog.json"
            original_state, original_backlog = state_path.read_text(), backlog_path.read_text()
            state_path.write_text("null")
            backlog_path.write_text("null")
            self.assertNotEqual(check().returncode, 0)
            for value in (None, [], "invalid", {}, {"schema_version": 1},
                          {"schema_version": 3}, {"schema_version": True}, {"schema_version": 2.0}):
                for path in (state_path, backlog_path):
                    state_path.write_text(original_state)
                    backlog_path.write_text(original_backlog)
                    path.write_text(json.dumps(value))
                    result = check()
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertNotIn("Control-plane check OK", result.stdout)
            state_path.write_text(original_state)
            backlog_path.write_text(original_backlog)
            (root / ".agent/legacy-v1/state.json").write_text("corrupt")
            self.assertNotEqual(check().returncode, 0)

    def test_current_snapshot_passes_and_known_bad_pointer_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / ".agent", root / ".agent")
            shutil.copytree(ROOT / "docs", root / "docs")
            shutil.copytree(ROOT / ".gauntlet-state-of-art/reports", root / ".gauntlet-state-of-art/reports")
            child = root / "cvg-master-rag-v2/AGENTS.md"
            child.parent.mkdir()
            shutil.copy2(ROOT / "cvg-master-rag-v2/AGENTS.md", child)
            copy_recorded_artifacts(root)
            def check():
                return subprocess.run([sys.executable, str(CHECKER), str(root), "--quiet"],
                                      capture_output=True, text=True, timeout=20)
            good = check()
            self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
            path = root / ".agent/state.json"
            state = json.loads(path.read_text())
            state["active_action_id"] = state["active_task"] + ":WRONG"
            path.write_text(json.dumps(state))
            bad = check()
            self.assertNotEqual(bad.returncode, 0)
            self.assertIn("RESULT FAIL", bad.stdout)


if __name__ == "__main__":
    unittest.main()
