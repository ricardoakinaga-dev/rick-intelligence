#!/usr/bin/env python3
"""Generate a deterministic, commit-bound release-evidence manifest.

The output is intentionally ignored by Git.  CI creates it after checkout,
then the release-integrity gate validates it against the exact clean checkout.
This avoids a cryptographic self-reference while keeping missing evidence
fail-closed.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Sequence

try:
    from scripts.state_of_art.release_integrity import capture_checkout
    from scripts.state_of_art.release_manifest import (
        ArtifactFingerprint,
        CommitBinding,
        EvidenceRef,
        GateResult,
        REQUIRED_GATES,
        ReleaseEvidenceManifest,
        ReviewerRef,
        artifact_set_digest,
    )
except ImportError:  # pragma: no cover - direct script execution fallback.
    from release_integrity import capture_checkout
    from release_manifest import (
        ArtifactFingerprint,
        CommitBinding,
        EvidenceRef,
        GateResult,
        REQUIRED_GATES,
        ReleaseEvidenceManifest,
        ReviewerRef,
        artifact_set_digest,
    )


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = "docs/progress/release-evidence.json"
DEFAULT_ARTIFACTS = (
    ".github/workflows/state-of-art-quality.yml",
    ".github/workflows/quality.yml",
    "Makefile",
    "README.md",
    "docs/prompts/state-of-art-triple-aaa-2026-09-09.txt",
    "docs/prompts/phase-3-runtime-evidence-production-promotion-2026-09-09.txt",
    "apps/api/pyproject.toml",
    "apps/api/src/app.py",
    "apps/api/src/services/external_composition.py",
    "apps/api/src/services/professor_backend.py",
    "apps/api/tests/test_evidence_decision_gate.py",
    "apps/web/app/globals.css",
    "apps/web/components/app-shell.tsx",
    "apps/web/components/session-provider.tsx",
    "apps/web/components/chat/chat-workspace.module.css",
    "apps/web/tests/session-ordering.spec.ts",
    "docker-compose.dev.yml",
    "docker-compose.staging.yml",
    "docs/architecture/release-integrity.md",
    "docs/plans/phase-2-production-intelligence-runtime.md",
    "docs/plans/phase-3-runtime-evidence-production-promotion.md",
    ".agent/plans/phase-3-runtime-evidence-production-promotion.md",
    "docs/reports/phase-3-runtime-evidence-current-audit.md",
    "docs/reports/phase-2-current-gap-audit.md",
    "docs/reports/phase-2-release-integrity-implementation-2026-09-09.md",
    "docs/reports/phase-2-canonical-compose-2026-09-09.md",
    "docs/reports/phase-2-postgres-runtime-gate-2026-09-09.md",
    "docs/reports/phase-2-redis-runtime-gate-2026-09-09.md",
    "docs/reports/phase-2-object-qdrant-runtime-gate-2026-09-09.md",
    "docs/reports/external-evidence-blockers.md",
    "docs/reports/state-of-art-triple-aaa-final-audit.md",
    "docs/progress/phase-2-final-report.md",
    "infrastructure/compose/otel-collector-config.yaml",
    "infrastructure/compose/prometheus.yml",
    "infrastructure/compose/README.md",
    "infrastructure/compose/.env.dev.example",
    "infrastructure/compose/.env.staging.example",
    "docs/operations/deployment.md",
    "infrastructure/docker/api.Dockerfile",
    "infrastructure/docker/worker.Dockerfile",
    "infrastructure/migrations/0006_document_lineage_contract.sql",
    "packages/evidence/src/rick_evidence/validator.py",
    "packages/knowledge/src/rick_knowledge/models.py",
    "packages/knowledge/src/rick_knowledge/payload.py",
    "packages/knowledge/src/rick_knowledge/postgres_store.py",
    "packages/knowledge/src/rick_knowledge/sqlite_store.py",
    "packages/locking/pyproject.toml",
    "scripts/phase11/check_adversarial_corpus.py",
    "scripts/phase11/check_compose.py",
    "scripts/phase11/runner.py",
    "scripts/phase11/test_compose_lifecycle.py",
    "scripts/phase11/object_qdrant_runtime_gate.py",
    "scripts/phase11/postgres_runtime_gate.py",
    "scripts/state_of_art/run_phase3_postgres.py",
    "scripts/state_of_art/tests/test_phase3_postgres_runtime.py",
    "scripts/phase11/redis_runtime_gate.py",
    "scripts/state_of_art/triple_aaa_verify.py",
    "tests/security/rag_adversarial/corpus.jsonl",
    "scripts/state_of_art/release_integrity.py",
    "scripts/state_of_art/release_manifest.py",
    "scripts/state_of_art/generate_release_evidence.py",
    "scripts/state_of_art/phase3_evidence.py",
    "scripts/state_of_art/generate_phase3_evidence.py",
    "scripts/state_of_art/phase3_lane.py",
    "scripts/state_of_art/tests/test_phase3_evidence.py",
)
def _run(root: Path, command: Sequence[str]) -> tuple[str, int | None, str]:
    try:
        completed = subprocess.run(
            list(command),
            cwd=root,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "NOT_RUN", None, type(exc).__name__
    if completed.returncode == 0:
        return "PASS", completed.returncode, "command returned zero"
    return "FAIL", completed.returncode, "command did not return zero"


def _commit_timestamp(root: Path) -> str:
    source_date_epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if source_date_epoch:
        try:
            return datetime.fromtimestamp(int(source_date_epoch), tz=timezone.utc).isoformat()
        except ValueError:
            pass
    try:
        completed = subprocess.run(
            ["git", "show", "-s", "--format=%cI", "HEAD"],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        value = completed.stdout.strip()
        if value:
            return value
    except (OSError, subprocess.CalledProcessError):
        pass
    return datetime.now(timezone.utc).isoformat()


def _file_hash(root: Path, relative: str) -> str:
    digest = sha256()
    with (root / relative).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _evidence_ref(root: Path, relative: str, description: str) -> EvidenceRef:
    return EvidenceRef(path=relative, sha256=_file_hash(root, relative), description=description)


def generate_manifest(
    root: Path = ROOT,
    *,
    output: str = DEFAULT_OUTPUT,
    environment: str = "local-hermetic",
    artifact_paths: Sequence[str] = DEFAULT_ARTIFACTS,
) -> ReleaseEvidenceManifest:
    root = root.resolve()
    checkout = capture_checkout(root)
    artifacts: list[ArtifactFingerprint] = []
    for relative in artifact_paths:
        path = root / relative
        if not path.is_file():
            raise FileNotFoundError(f"artifact path does not exist: {relative}")
        artifacts.append(
            ArtifactFingerprint(path=relative, sha256=_file_hash(root, relative), role="release-source")
        )
    artifact_hash = artifact_set_digest(artifacts)
    reviewer = ReviewerRef(
        reviewer_id="automated-release-integrity",
        kind="automated",
        name="release-integrity-generator",
        independent=False,
    )
    timestamp = _commit_timestamp(root)
    audit_path = "docs/reports/phase-3-runtime-evidence-current-audit.md"
    release_evidence = (
        _evidence_ref(root, "docs/architecture/release-integrity.md", "release integrity policy"),
        _evidence_ref(root, audit_path, "current candidate gap audit"),
    )
    diff_result, diff_code, diff_reason = _run(root, ("git", "diff", "--check"))
    validate_result, validate_code, validate_reason = _run(root, ("make", "validate"))
    local_result = "PASS" if diff_result == "PASS" and validate_result == "PASS" and checkout["status"] == "CLEAN" else "FAIL"
    local_limitations: tuple[str, ...] = () if local_result == "PASS" else (
        f"git diff --check: {diff_result} ({diff_reason})",
        f"make validate: {validate_result} ({validate_reason})",
        f"checkout status: {checkout['status']}",
    )
    gates: list[GateResult] = [
        GateResult(
            gate_id="release-integrity",
            commit_sha=checkout["head"],
            artifact_hash=artifact_hash,
            command=("git", "diff", "--check", "&&", "make", "validate"),
            environment=environment,
            timestamp=timestamp,
            result=local_result,  # type: ignore[arg-type]
            limitations=local_limitations,
            reviewer=reviewer,
            evidence_paths=release_evidence,
        )
    ]
    for gate_id in REQUIRED_GATES:
        if gate_id == "release-integrity":
            continue
        gates.append(
            GateResult(
                gate_id=gate_id,
                commit_sha=checkout["head"],
                artifact_hash=artifact_hash,
                command=("gate", gate_id),
                environment=environment,
                timestamp=timestamp,
                result="BLOCKED_EXTERNAL",
                limitations=("required runtime or independent evidence was not executed in this environment",),
                reviewer=reviewer,
                evidence_paths=(
                    _evidence_ref(root, audit_path, "current gap audit records the unresolved gate"),
                ),
            )
        )
    status = "PASS"
    if any(gate.result == "FAIL" for gate in gates):
        status = "FAIL"
    elif any(gate.result != "PASS" for gate in gates):
        status = "BLOCKED_EXTERNAL"
    limitations = (
        "Generated from the exact checkout; blocked gates are preserved and cannot be promoted as PASS.",
    )
    if checkout["status"] != "CLEAN":
        limitations += ("The checkout is dirty; this manifest is diagnostic until generated from a clean candidate.",)
    return ReleaseEvidenceManifest(
        schema_version="state-of-art-release-evidence.v2",
        manifest_id=f"release-{checkout['head'][:12]}",
        generated_at=timestamp,
        status=status,  # type: ignore[arg-type]
        commit_binding=CommitBinding(
            commit_sha=checkout["head"],
            tree_sha=checkout["tree"],
            checkout_fingerprint=checkout["fingerprint"],
            artifact_set_sha256=artifact_hash,
            clean_worktree=checkout["status"] == "CLEAN",
        ),
        artifacts=tuple(artifacts),
        gates=tuple(gates),
        reviewers=(reviewer,),
        limitations=limitations,
    )


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="ignored JSON output path inside the checkout")
    parser.add_argument("--environment", default="local-hermetic")
    parser.add_argument("--artifact", action="append", dest="artifacts", help="artifact path to hash; repeatable")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    manifest = generate_manifest(
        ROOT,
        output=args.output,
        environment=args.environment,
        artifact_paths=tuple(args.artifacts or DEFAULT_ARTIFACTS),
    )
    output = (ROOT / args.output).resolve()
    output.relative_to(ROOT.resolve())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": args.output, "status": manifest.status, "manifest_id": manifest.manifest_id}, sort_keys=True))
    # Generation is not the promotion gate.  It must leave a truthful
    # non-PASS manifest behind so the verifier can reject it fail-closed.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
