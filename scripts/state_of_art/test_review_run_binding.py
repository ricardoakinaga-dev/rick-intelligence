"""Final acceptance cannot replay a prior run, even with the same artifact."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts/control_plane/vendor/gauntlet_loop/gauntlet_state.py"
spec = importlib.util.spec_from_file_location("bound_gauntlet", HELPER)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
BAR = json.loads((ROOT / ".gauntlet/bar.json").read_text())
CAPABILITIES = json.loads((ROOT / ".gauntlet-state-of-art/capabilities.json").read_text())


def packet(run_id="current-run", stamp="2026-09-05T12:00:00Z", digest="a" * 64):
    evidence = dict(run_id=run_id, status="PASS", executed=True,
                    artifact_fingerprint=digest, command="synthetic fixture only",
                    environment="isolated test", outcome="PASS", started_at=stamp,
                    ended_at=stamp, producer="fixture", raw_result_sha256="b" * 64)
    return dict(run_id=run_id,
                criteria_results=[dict(evidence, id=item["id"]) for item in BAR["criteria"]],
                integrated_verification=dict(evidence), limitations=[], resource_stop=False,
                final_critic=dict(run_id=run_id, started_at=stamp, ended_at=stamp,
                                 critic_id="fresh-fixture", mechanism="test fixture",
                                 largest_gap="none in fixture", pre_fingerprint=digest,
                                 post_fingerprint=digest, decision="APPROVE", independence="I1",
                                 mutation_clean=True, sealed_packet=True, fork_turns="none"))


class FinalBindingTests(unittest.TestCase):
    def validate(self, value, **overrides):
        context = dict(run_id="current-run", evidence_not_before="2026-09-05T11:00:00Z",
                       validated_at="2026-09-05T13:00:00Z")
        context.update(overrides)
        return helper.validate_final(value, BAR, "a" * 64, "PASS", set(),
                                     CAPABILITIES, "execute", **context)

    def test_current_packet_passes_existing_and_binding_rules(self):
        self.assertEqual(self.validate(packet()), [])

    def test_each_evidence_boundary_rejects_foreign_and_missing_run(self):
        for name in ("root", "criterion", "integrated_verification", "final_critic"):
            for foreign in (None, "prior-run"):
                with self.subTest(name=name, run=foreign):
                    value = packet()
                    item = value if name == "root" else (value["criteria_results"][0]
                           if name == "criterion" else value[name])
                    item["run_id"] = foreign
                    self.assertTrue(self.validate(value))

    def test_old_future_naive_malformed_and_reversed_times_are_rejected(self):
        for name in ("criterion", "integrated_verification", "final_critic"):
            for stamp in ("2000-01-01T00:00:00Z", "2999-01-01T00:00:00Z",
                          "2026-09-05T12:00:00", "not-a-time", None):
                with self.subTest(name=name, stamp=stamp):
                    value = packet()
                    item = value["criteria_results"][0] if name == "criterion" else value[name]
                    item["started_at"] = stamp
                    self.assertTrue(self.validate(value))
            value = packet()
            item = value["criteria_results"][0] if name == "criterion" else value[name]
            item["ended_at"] = "2026-09-05T11:59:00Z"
            self.assertTrue(self.validate(value))

    def test_rebaseline_invalidates_earlier_evidence_and_bad_epoch_fails_closed(self):
        self.assertTrue(self.validate(packet(), evidence_not_before="2026-09-05T12:30:00Z"))
        self.assertTrue(self.validate(packet(), evidence_not_before="bad"))
        self.assertTrue(self.validate(packet(), validated_at="2999-01-01T00:00:00Z"))

    def test_critic_cannot_precede_evidence(self):
        value = packet()
        value["final_critic"].update(started_at="2026-09-05T11:30:00Z", ended_at="2026-09-05T11:31:00Z")
        self.assertTrue(self.validate(value))

    def test_real_finish_and_persisted_validation_enforce_run_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "repo"
            root.mkdir()
            def run(*args):
                return subprocess.run([sys.executable, str(HELPER), *args],
                    env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", GIT_OPTIONAL_LOCKS="0"),
                    text=True, capture_output=True, timeout=15)
            result = run("init", "--repo", str(root), "--goal", "isolated fixture",
                "--run-id", "current-run", "--bar-manifest", str(ROOT / ".gauntlet/bar.json"),
                "--capabilities", str(ROOT / ".gauntlet-state-of-art/capabilities.json"),
                "--budget", str(ROOT / ".gauntlet-state-of-art/budget.json"))
            self.assertEqual(result.returncode, 0, result.stderr)
            for phase in ("CRITIQUE", "FINAL_GAUNTLET"):
                result = run("progress", "--repo", str(root), "--phase", phase,
                             "--current-gap", "fixture", "--next-action", "fixture")
                self.assertEqual(result.returncode, 0, result.stderr)
            state_path = root / ".gauntlet/state.json"
            state = json.loads(state_path.read_text())
            candidate = base / "verification.json"
            current = packet(stamp=helper.utc_now(), digest=state["artifact_fingerprint"]["digest"])
            finish_args = ("finish", "--repo", str(root), "--verdict", "PASS", "--reason",
                           "synthetic test only", "--next-gap", "none", "--verification", str(candidate))
            for invalid in (packet("prior-run", "2000-01-01T00:00:00Z", state["artifact_fingerprint"]["digest"]),
                            packet("current-run", "2000-01-01T00:00:00Z", state["artifact_fingerprint"]["digest"])):
                candidate.write_text(json.dumps(invalid))
                result = run(*finish_args)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertEqual(json.loads(state_path.read_text())["status"], "ACTIVE")
            candidate.write_text(json.dumps(current))
            result = run(*finish_args)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(run("validate", "--repo", str(root), "--check-drift").returncode, 0)
            # Rebuild the authenticated event too: mere hash mismatch must not
            # be the reason that replay is rejected on persisted validation.
            state = json.loads(state_path.read_text())
            state["stop"]["verification"]["final_critic"]["run_id"] = "prior-run"
            history_path = root / ".gauntlet/history.jsonl"
            history = helper.load_jsonl(history_path)
            history.pop()
            helper.append_history(history, dict(event="finish", **state["stop"]))
            history_path.write_text(helper.jsonl_text(history))
            state_path.write_text(json.dumps(state))
            result = run("validate", "--repo", str(root))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("run_id", result.stdout)


if __name__ == "__main__":
    unittest.main()
