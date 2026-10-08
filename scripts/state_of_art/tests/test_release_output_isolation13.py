"""Current release output must never replace restored historical controls."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts.state_of_art import generate_release_evidence as generator
from scripts.state_of_art import release_integrity as integrity
from scripts.state_of_art import triple_aaa_verify as packet
from scripts.state_of_art import verify_sealed_promotion as sealed


CURRENT = ".runtime/release/release-evidence.json"
HISTORY = "docs/progress/release-evidence.json"
EVIDENCE_DIR = Path("/tmp/rick-production-20261004/release-output13")


def setUpModule() -> None:
    # Fresh checkouts (CI) never created this incident scratch directory.
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)


class ReleaseOutputIsolationTests(unittest.TestCase):
    def test_canonical_defaults_and_explicit_consumers_agree(self):
        from scripts.state_of_art.release_evidence_paths import CURRENT_RELEASE_EVIDENCE
        self.assertEqual(CURRENT_RELEASE_EVIDENCE, CURRENT)
        for module in (generator, integrity, packet, sealed):
            self.assertEqual(module.CURRENT_RELEASE_EVIDENCE, CURRENT_RELEASE_EVIDENCE)
        self.assertEqual(generator.DEFAULT_OUTPUT, CURRENT)
        self.assertEqual(integrity.DEFAULT_EVIDENCE, (CURRENT,))
        self.assertEqual(generator._parse_args([]).output, CURRENT)
        self.assertEqual(integrity._parse_args([]).evidence_paths, [CURRENT])
        self.assertEqual(packet.RELEASE_EVIDENCE_ARTIFACT, CURRENT)
        self.assertEqual(packet._release_gate().command[-1], CURRENT)
        for name in ("quality.yml", "state-of-art-quality.yml"):
            workflow = (generator.ROOT / ".github/workflows" / name).read_text()
            self.assertIn("--evidence " + CURRENT, workflow)
            self.assertNotIn(HISTORY, workflow)

    def test_missing_current_default_rejects_even_with_history(self):
        with tempfile.TemporaryDirectory(dir=EVIDENCE_DIR) as directory:
            root = Path(directory)
            history = root / HISTORY
            history.parent.mkdir(parents=True)
            history.write_text('{"commit_binding":{"artifact_set_sha256":"historical"}}')
            checkout = dict(available=True, head="a" * 40, tree="b" * 40,
                            fingerprint="c" * 64, status="CLEAN", errors=[])
            def command(name, *args, **kwargs):
                return dict(name=name, classification=integrity.PASS, required=True)
            with patch.object(integrity, "capture_checkout", return_value=checkout), \
                 patch.object(integrity, "_command_result", side_effect=command):
                result = integrity.run_gate(root)
            self.assertNotEqual(result["classification"], integrity.PASS)
            evidence = result["evidence"][0]
            self.assertEqual(evidence["reason"], "required release evidence file is absent")
            self.assertIn("MISSING_EVIDENCE_REJECTED", evidence["rejection_codes"])
            with patch.object(packet, "ROOT", root):
                self.assertIsNone(packet._manifest_artifact_hash())
            self.assertIsNone(sealed._manifest_artifact_hash(root))

    def test_digest_readers_use_current_when_history_also_exists(self):
        with tempfile.TemporaryDirectory(dir=EVIDENCE_DIR) as directory:
            root = Path(directory)
            for name, digest in ((HISTORY, "old"), (CURRENT, "new")):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"commit_binding": {"artifact_set_sha256": digest}}))
            with patch.object(packet, "ROOT", root):
                self.assertEqual(packet._manifest_artifact_hash(), "new")
            self.assertEqual(sealed._manifest_artifact_hash(root), "new")

    def test_reserved_aliases_reject_before_any_generation_or_mutation(self):
        with tempfile.TemporaryDirectory(dir=EVIDENCE_DIR) as directory:
            root = Path(directory)
            history = root / HISTORY
            history.parent.mkdir(parents=True)
            authentic = b"authentic historical fixture\n"
            history.write_bytes(authentic)
            alias = root / "alias.json"
            alias.symlink_to(history)
            hardlink = root / "hardlink.json"
            hardlink.hardlink_to(history)
            aliases = (HISTORY, "./" + HISTORY, "docs/progress/../progress/release-evidence.json",
                       str(history), "alias.json", "hardlink.json")
            for output in aliases:
                with self.subTest(output=output), patch.object(generator, "ROOT", root), \
                     patch.object(generator, "generate_manifest", side_effect=AssertionError("generation must not run")) as generate:
                    before = sorted(str(p.relative_to(root)) for p in root.rglob("*"))
                    with self.assertRaisesRegex(ValueError, "historical"):
                        generator.main(["--output", output])
                    generate.assert_not_called()
                    self.assertEqual(history.read_bytes(), authentic)
                    self.assertEqual(sorted(str(p.relative_to(root)) for p in root.rglob("*")), before)

    def test_library_reserved_output_rejects_before_checkout_or_gates(self):
        with tempfile.TemporaryDirectory(dir=EVIDENCE_DIR) as directory, \
             patch.object(generator, "capture_checkout", side_effect=AssertionError("checkout must not run")) as capture:
            with self.assertRaisesRegex(ValueError, "historical"):
                generator.generate_manifest(Path(directory), output=HISTORY)
            capture.assert_not_called()

    def test_custom_output_api_preserved(self):
        with tempfile.TemporaryDirectory(dir=EVIDENCE_DIR) as directory:
            root = Path(directory)
            manifest = SimpleNamespace(status="FAIL", manifest_id="diagnostic", to_dict=lambda: {"status": "FAIL"})
            with patch.object(generator, "ROOT", root), patch.object(generator, "generate_manifest", return_value=manifest) as generate:
                self.assertEqual(generator.main(["--output", "custom/current.json"]), 0)
            self.assertEqual(generate.call_args.kwargs["output"], "custom/current.json")
            self.assertEqual(json.loads((root / "custom/current.json").read_text()), {"status": "FAIL"})

    def test_direct_script_imports(self):
        for name in ("generate_release_evidence", "release_integrity", "triple_aaa_verify", "verify_sealed_promotion"):
            with self.subTest(script=name):
                result = subprocess.run([sys.executable, "-B", str(generator.ROOT / "scripts/state_of_art" / (name + ".py")), "--help"],
                                        cwd=EVIDENCE_DIR, capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
