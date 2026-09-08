from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


DOCKER_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = DOCKER_ROOT / "release-manifest.json"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECK = _load_module("rec33_check_release", DOCKER_ROOT / "check_release.py")


class ReleaseStaticTests(unittest.TestCase):
    def test_prepared_packet_passes_without_external_tools(self) -> None:
        self.assertEqual(CHECK.validate_release(MANIFEST_PATH, mode="prepared"), [])

    def test_candidate_mode_requires_external_evidence(self) -> None:
        errors = CHECK.validate_release(MANIFEST_PATH, mode="candidate")
        self.assertTrue(errors)
        self.assertTrue(any("CANDIDATE" in error for error in errors))
        self.assertTrue(any("source_revision" in error for error in errors))

    def test_complete_candidate_shape_passes_static_checks(self) -> None:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        manifest["status"] = "CANDIDATE"
        manifest["source_revision"] = {"value": "abcdef1234567", "status": "CAPTURED"}
        manifest["build"]["status"] = "PASS"
        for base in manifest["base_images"]:
            base["ref"] = f"{base['argument'].lower()}:3.12@sha256:{'a' * 64}"
            base["status"] = "CAPTURED"
        for image in manifest["images"]:
            digest = f"sha256:{'b' * 64}"
            image["build_status"] = "PASS"
            image["image_ref"] = f"registry.example/rick-intelligence/{image['service']}@{digest}"
            image["digest"] = digest
            image["digest_status"] = "PASS"
            image["scan"].update(
                {
                    "status": "PASS",
                    "report": f"evidence/{image['service']}-trivy.json",
                    "critical": 0,
                    "high": 0,
                    "sbom": f"evidence/{image['service']}-sbom.json",
                }
            )
            image["signature"].update(
                {
                    "status": "PASS",
                    "bundle": f"evidence/{image['service']}-cosign.json",
                    "identity": "release-builder@example.invalid",
                    "issuer": "https://issuer.example.invalid",
                }
            )
        manifest["rollout"]["canary"] = {"status": "PASS", "evidence": "evidence/canary.json"}
        manifest["rollout"]["rollback"] = {
            "status": "PASS",
            "evidence": "evidence/rollback.json",
            "previous_release_digest": f"sha256:{'c' * 64}",
            "migration_compatibility": "PASS",
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(manifest, handle)
            handle.flush()
            self.assertEqual(CHECK.validate_release(Path(handle.name), mode="candidate"), [])

    def test_prepared_packet_rejects_pass_claims_without_external_evidence(self) -> None:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        manifest["images"][0]["scan"]["status"] = "PASS"
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
            json.dump(manifest, handle)
            handle.flush()
            errors = CHECK.validate_release(Path(handle.name), mode="prepared")
        self.assertTrue(any("scan.status is invalid" in error for error in errors))

    def test_prepared_packet_rejects_pass_claims_in_every_external_status(self) -> None:
        mutations = {
            "build.status": lambda manifest: manifest["build"].__setitem__("status", "PASS"),
            "source_revision.status": lambda manifest: manifest["source_revision"].__setitem__("status", "PASS"),
            "base_images[0].status": lambda manifest: manifest["base_images"][0].__setitem__("status", "PASS"),
            "images[0].build_status": lambda manifest: manifest["images"][0].__setitem__("build_status", "PASS"),
            "images[0].digest_status": lambda manifest: manifest["images"][0].__setitem__("digest_status", "PASS"),
            "images[0].scan.status": lambda manifest: manifest["images"][0]["scan"].__setitem__("status", "PASS"),
            "images[0].signature.status": lambda manifest: manifest["images"][0]["signature"].__setitem__("status", "PASS"),
            "rollout.canary.status": lambda manifest: manifest["rollout"]["canary"].__setitem__("status", "PASS"),
            "rollout.rollback.status": lambda manifest: manifest["rollout"]["rollback"].__setitem__("status", "PASS"),
            "rollout.rollback.migration_compatibility": lambda manifest: manifest["rollout"]["rollback"].__setitem__(
                "migration_compatibility", "PASS"
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
                mutate(manifest)
                with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as handle:
                    json.dump(manifest, handle)
                    handle.flush()
                    errors = CHECK.validate_release(Path(handle.name), mode="prepared")
                self.assertTrue(any(label in error for error in errors), errors)

    def test_dockerfiles_have_reviewable_runtime_contracts(self) -> None:
        expected = {
            "api.Dockerfile": ("PYTHON_IMAGE", "10001:10001", "8000"),
            "worker.Dockerfile": ("PYTHON_IMAGE", "10001:10001", "RICK_WORKER_COMPOSITION"),
            "web.Dockerfile": ("NODE_BUILD_IMAGE", "10001:10001", "3000"),
        }
        for name, markers in expected.items():
            text = (DOCKER_ROOT / name).read_text(encoding="utf-8")
            self.assertIn(f"ARG {markers[0]}", text)
            self.assertIn(f"USER {markers[1]}", text)
            self.assertIn("HEALTHCHECK", text)
            self.assertIn(markers[2], text)
            self.assertNotRegex(text, r"(?im)^\s*(?:ENV|ARG).*?(?:PASSWORD|SECRET|API_KEY|TOKEN|DSN)")
            self.assertNotRegex(text, r"(?i)(?:\.env|\.pem|\.key|credentials|secrets)")
        for name in ("api.Dockerfile", "worker.Dockerfile"):
            text = (DOCKER_ROOT / name).read_text(encoding="utf-8")
            self.assertIn("/opt/rick/packages/storage/src", text)
            self.assertIn("COPY packages/storage/src /opt/rick/packages/storage/src", text)

    def test_manifest_marks_external_claims_as_not_run(self) -> None:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "PREPARED_NOT_RUN")
        self.assertEqual(manifest["build"]["status"], "NOT_RUN")
        self.assertTrue(all(item["digest_status"] == "NOT_RUN" for item in manifest["images"]))
        self.assertTrue(all(item["scan"]["status"] == "NOT_RUN" for item in manifest["images"]))
        self.assertTrue(all(item["signature"]["status"] == "NOT_RUN" for item in manifest["images"]))
        self.assertEqual(manifest["rollout"]["canary"]["status"], "NOT_RUN")
        self.assertEqual(manifest["rollout"]["rollback"]["status"], "NOT_RUN")
        self.assertFalse(manifest["secrets"]["baked_into_image"])
        self.assertTrue(manifest["secrets"]["runtime_injected"])


if __name__ == "__main__":
    unittest.main()
