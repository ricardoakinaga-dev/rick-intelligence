"""Derived views and schema recovery must not weaken the original bar."""
import importlib.util
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/state_of_art"))
spec = importlib.util.spec_from_file_location("review_control_views", ROOT / "scripts/state_of_art/review_control_views.py")
views = importlib.util.module_from_spec(spec)
spec.loader.exec_module(views)


class ReviewControlTests(unittest.TestCase):
    def test_derived_view_reader_rejects_duplicate_state_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".agent").mkdir()
            (root / ".agent/state.json").write_text(
                '{"state_revision":1,"state_revision":2}', encoding="utf-8"
            )
            (root / ".agent/backlog.json").write_text('{"items":[]}', encoding="utf-8")
            with self.assertRaises(ValueError):
                views.expected_views(root)

    def test_current_views_are_derived_and_history_preserved(self):
        self.assertEqual(views.verify_history(ROOT), 11)
        views.verify_bar(ROOT)
        for relative, expected in views.expected_views(ROOT).items():
            self.assertEqual((ROOT / relative).read_text(), expected)

    def test_bar_rejects_weakened_target_even_if_both_copies_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in (".gauntlet", ".gauntlet-state-of-art"):
                shutil.copytree(ROOT / relative, root / relative)
            for relative in (".gauntlet/bar.json", ".gauntlet-state-of-art/bar.canonical.json"):
                path = root / relative
                value = json.loads(path.read_text())
                value["criteria"][0]["required"] = False
                path.write_text(json.dumps(value))
            with self.assertRaises(ValueError):
                views.verify_bar(root)

    def test_history_corruption_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / ".review-control-history", root / ".review-control-history")
            (root / ".review-control-history/phase16-orchestrate/state.json").write_text("corrupt")
            with self.assertRaises(ValueError):
                views.verify_history(root)

    def test_changed_run_goal_is_rejected_even_with_consistent_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in (".gauntlet", ".gauntlet-state-of-art"):
                shutil.copytree(ROOT / relative, root / relative)
            path = root / ".gauntlet/state.json"
            state = json.loads(path.read_text())
            state["goal"] = {"text": "smaller task", "sha256": hashlib.sha256(b"smaller task").hexdigest()}
            path.write_text(json.dumps(state))
            with self.assertRaises(ValueError):
                views.verify_bar(root)

    def test_cli_rejects_a_stale_derived_view(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in (".agent", ".gauntlet", ".gauntlet-state-of-art", ".orchestrate",
                             ".orchestrate-state-of-art", ".review-control-history"):
                shutil.copytree(ROOT / relative, root / relative)
            path = root / ".orchestrate/state.json"
            view = json.loads(path.read_text())
            view["source_revision"] += 1
            path.write_text(json.dumps(view))
            result = subprocess.run([sys.executable, str(ROOT / "scripts/state_of_art/review_control_views.py"),
                                     "--root", str(root)], capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("stale derived view", result.stdout)


if __name__ == "__main__":
    unittest.main()
