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
import signal
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
    "docs/prompts/phase-3-triple-aaa-closure-2026-09-09.txt",
    "docs/reports/current-triple-aaa-gap-audit.md",
    "docs/reports/current-triple-aaa-quality-bar-v1.json",
    "docs/reports/rick-intelligence-triple-aaa-final-promotion.md",
    "docs/plans/phase-3-triple-aaa-closure.md",
    "apps/api/pyproject.toml",
    "apps/api/README.md",
    "apps/api/src/app.py",
    "apps/api/src/core/rate_limit.py",
    "apps/api/src/routes/auth.py",
    "apps/api/src/routes/chat.py",
    "apps/api/src/routes/compatibility_openai.py",
    "apps/api/src/services/external_composition.py",
    "apps/api/src/services/professor_backend.py",
    "apps/api/tests/test_evidence_decision_gate.py",
    "apps/api/tests/test_app_lifecycle.py",
    "apps/api/tests/test_external_composition.py",
    "apps/api/tests/test_rate_limit.py",
    "apps/web/app/globals.css",
    "apps/web/components/app-shell.tsx",
    "apps/web/components/session-provider.tsx",
    "apps/web/components/chat/chat-workspace.module.css",
    "apps/web/tests/session-ordering.spec.ts",
    "docker-compose.dev.yml",
    "docker-compose.staging.yml",
    "docs/architecture/release-integrity.md",
    "docs/architecture/api-kernel.md",
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
    "packages/locking/src/rick_locking/rate_limit.py",
    "packages/locking/src/rick_locking/redis.py",
    "scripts/phase11/check_adversarial_corpus.py",
    "scripts/phase11/check_compose.py",
    "scripts/phase11/runner.py",
    "scripts/phase11/test_compose_lifecycle.py",
    "scripts/phase11/object_qdrant_runtime_gate.py",
    "scripts/phase11/provider_runtime_gate.py",
    "scripts/phase11/golden_runtime_gate.py",
    "scripts/phase11/tenant_evidence_runtime_gate.py",
    "scripts/phase11/observability_runtime_gate.py",
    "scripts/phase11/frontend_supply_runtime_gate.py",
    "scripts/phase11/restore_runtime_gate.py",
    "scripts/phase11/file_security_runtime_gate.py",
    "scripts/phase11/postgres_runtime_gate.py",
    "scripts/state_of_art/run_phase3_postgres.py",
    "scripts/state_of_art/run_phase3_object_qdrant.py",
    "scripts/state_of_art/run_phase3_provider.py",
    "scripts/state_of_art/run_phase3_golden_runtime.py",
    "scripts/state_of_art/run_phase3_tenant_evidence.py",
    "scripts/state_of_art/run_phase3_observability.py",
    "scripts/state_of_art/run_phase3_frontend_supply.py",
    "scripts/state_of_art/run_phase3_restore.py",
    "scripts/state_of_art/run_phase3_file_security.py",
    "scripts/state_of_art/run_phase3_operational.py",
    "scripts/state_of_art/tests/test_phase3_postgres_runtime.py",
    "scripts/phase11/multi_worker_runtime_gate.py",
    "scripts/state_of_art/run_phase3_multi_worker.py",
    "scripts/state_of_art/tests/test_multi_worker_runtime.py",
    "scripts/phase11/redis_runtime_gate.py",
    "scripts/phase11/redis_multi_replica_runtime_gate.py",
    "scripts/state_of_art/run_phase3_redis_multi_replica.py",
    "scripts/state_of_art/tests/test_redis_multi_replica_runtime.py",
    "scripts/state_of_art/triple_aaa_verify.py",
    "scripts/state_of_art/promotion_engine.py",
    "scripts/state_of_art/packet_seal.py",
    "scripts/state_of_art/tests/test_promotion_engine.py",
    "scripts/state_of_art/tests/test_packet_seal.py",
    "scripts/state_of_art/tests/test_generate_release_evidence.py",
    "scripts/state_of_art/validate_quality_bar.py",
    "tests/security/rag_adversarial/corpus.jsonl",
    "scripts/state_of_art/release_integrity.py",
    "scripts/state_of_art/release_manifest.py",
    "scripts/state_of_art/generate_release_evidence.py",
    "scripts/state_of_art/ci_lane_evidence.py",
    "scripts/state_of_art/phase3_evidence.py",
    "scripts/state_of_art/generate_phase3_evidence.py",
    "scripts/state_of_art/phase3_lane.py",
    "scripts/state_of_art/phase3_runtime_adapter.py",
    "scripts/state_of_art/tests/test_phase3_evidence.py",
    "scripts/state_of_art/tests/test_ci_lane_evidence.py",
    "scripts/state_of_art/tests/test_phase3_lane.py",
    "scripts/state_of_art/tests/test_object_qdrant_runtime.py",
    "scripts/state_of_art/tests/test_provider_runtime.py",
    "scripts/state_of_art/tests/test_golden_runtime.py",
    "scripts/state_of_art/tests/test_tenant_evidence_runtime.py",
    "scripts/state_of_art/tests/test_observability_runtime.py",
    "scripts/state_of_art/tests/test_frontend_supply_runtime.py",
    "scripts/state_of_art/tests/test_restore_runtime.py",
    "scripts/state_of_art/tests/test_file_security_runtime.py",
)
RUNTIME_GATE_ARTIFACTS = {
    "multi-worker": ".runtime/phase-3/multi-worker-runtime-evidence.json",
    "multi-tenant": ".runtime/phase-3/tenant-evidence-runtime-evidence.json",
    # The mandatory release gate is the multi-replica Redis contract.  The
    # single-node envelope remains available as a diagnostic, but must never
    # satisfy the release gate on its own.
    "redis": ".runtime/phase-3/redis-multi-replica-runtime-evidence.json",
    "redis-multi-replica": ".runtime/phase-3/redis-multi-replica-runtime-evidence.json",
    "postgresql": ".runtime/phase-3/postgres-runtime-evidence.json",
    "qdrant": ".runtime/phase-3/object-qdrant-runtime-evidence.json",
    "object-storage": ".runtime/phase-3/object-qdrant-runtime-evidence.json",
    "ingestion-e2e": ".runtime/phase-3/golden-ingestion-runtime-evidence.json",
    "evidence": ".runtime/phase-3/tenant-evidence-runtime-evidence.json",
    "citation": ".runtime/phase-3/golden-ingestion-runtime-evidence.json",
    "decision": ".runtime/phase-3/golden-ingestion-runtime-evidence.json",
    "observability": ".runtime/phase-3/observability-runtime-evidence.json",
    "restore": ".runtime/phase-3/restore-runtime-evidence.json",
    "dr": ".runtime/phase-3/restore-runtime-evidence.json",
    "file-security": ".runtime/phase-3/file-security-runtime-evidence.json",
    "chaos": ".runtime/phase-3/chaos-runtime-evidence.json",
    "soak": ".runtime/phase-3/soak-runtime-evidence.json",
    "performance": ".runtime/phase-3/performance-runtime-evidence.json",
    "frontend-e2e": ".runtime/phase-3/frontend-supply-runtime-evidence.json",
    "accessibility": ".runtime/phase-3/frontend-supply-runtime-evidence.json",
    "visual": ".runtime/phase-3/frontend-supply-runtime-evidence.json",
    "supply-chain": ".runtime/phase-3/supply-chain-runtime-evidence.json",
    "provider": ".runtime/phase-3/provider-runtime-evidence.json",
}
CI_GATE_ARTIFACTS = {
    # These are local CI gates only.  They never replace the named live
    # runtime envelopes above, and their envelope explicitly carries the
    # LOCAL_CI_ONLY promotion scope.
    "architecture": ".runtime/ci/architecture.json",
    "contracts": ".runtime/ci/contracts.json",
    "security": ".runtime/ci/security.json",
    "unit": ".runtime/ci/unit.json",
    "supply-chain": ".runtime/ci/supply-chain.json",
}


def _run(root: Path, command: Sequence[str]) -> tuple[str, int | None, str]:
    try:
        process = subprocess.Popen(
            list(command),
            cwd=root,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except OSError as exc:
        return "NOT_RUN", None, type(exc).__name__
    try:
        stdout, stderr = process.communicate(timeout=120)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        return "NOT_RUN", None, "TimeoutExpired: process group was terminated"
    del stdout, stderr
    if process.returncode == 0:
        return "PASS", process.returncode, "command returned zero"
    return "FAIL", process.returncode, "command did not return zero"


def _execution_timestamp(_root: Path) -> str:
    """Timestamp the observation, not the commit that happened to trigger it."""

    return datetime.now(timezone.utc).isoformat()


def _file_hash(root: Path, relative: str) -> str:
    digest = sha256()
    with (root / relative).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _evidence_ref(root: Path, relative: str, description: str) -> EvidenceRef:
    return EvidenceRef(path=relative, sha256=_file_hash(root, relative), description=description)


def _runtime_result(
    root: Path,
    gate_id: str,
    audit_path: str,
    reviewer: ReviewerRef,
    *,
    commit_sha: str,
    tree_sha: str,
    artifact_hash: str,
    timestamp: str,
    supplemental_ci_relative: str | None = None,
) -> GateResult:
    """Aggregate an observed runtime envelope or preserve a real NOT_RUN state."""

    relative = RUNTIME_GATE_ARTIFACTS.get(gate_id)
    evidence_paths: tuple[EvidenceRef, ...]
    command: tuple[str, ...]
    procedure: str
    result = "NOT_RUN"
    exit_status: int | None = None
    limitations = "No current runtime artifact was supplied for this mandatory gate."
    if relative is not None and (root / relative).is_file():
        evidence_paths = (_evidence_ref(root, relative, f"runtime envelope for {gate_id}"),)
        command = ("runtime-envelope", relative)
        procedure = f"validate the supplied runtime envelope for {gate_id} against this checkout"
        try:
            raw = json.loads((root / relative).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            raw = None
        if isinstance(raw, dict):
            observed = str(raw.get("status", "")).upper()
            if observed in {"PASS", "BLOCKED_EXTERNAL", "FAIL", "NOT_RUN"}:
                result = observed
                raw_exit = raw.get("exit_status")
                exit_status = raw_exit if type(raw_exit) is int and raw_exit >= 0 else {
                    "PASS": 0,
                    "BLOCKED_EXTERNAL": 2,
                    "FAIL": 1,
                    "NOT_RUN": None,
                }[observed]
                limitations = str(raw.get("limitations") or raw.get("reason") or "runtime envelope was supplied")
            else:
                result = "INVALID"
                exit_status = 1
                limitations = "runtime envelope has no supported gate status"
        else:
            result = "INVALID"
            exit_status = 1
            limitations = "runtime envelope is not a JSON object"
    else:
        evidence_paths = (_evidence_ref(root, audit_path, f"current audit for missing {gate_id} evidence"),)
        command = ("runtime-envelope", relative if relative and (root / relative).is_file() else gate_id)
        procedure = f"await the approved runtime procedure for {gate_id}; no artifact is claimed"
    if supplemental_ci_relative and relative is not None and (root / relative).is_file():
        ci_path = root / supplemental_ci_relative
        if ci_path.is_file():
            evidence_paths = evidence_paths + (
                _evidence_ref(root, supplemental_ci_relative, f"same-run CI supplement for {gate_id}"),
            )
            try:
                ci_raw = json.loads(ci_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                ci_raw = None
            ci_result = "INVALID"
            ci_exit_status: int | None = 1
            if isinstance(ci_raw, dict) and ci_raw.get("schema_version") == "state-of-art-ci-evidence.v1":
                observed_ci = str(ci_raw.get("status", "")).upper()
                expected_ci_exit = {"PASS": 0, "FAIL": 1, "NOT_RUN": None}
                raw_ci_exit = ci_raw.get("exit_status")
                expected_exit = expected_ci_exit.get(observed_ci)
                exit_shape_valid = (
                    type(raw_ci_exit) is int and raw_ci_exit >= 0
                    if expected_exit is not None
                    else raw_ci_exit is None
                )
                if observed_ci in expected_ci_exit and exit_shape_valid and raw_ci_exit == expected_exit:
                    ci_result = observed_ci
                    ci_exit_status = raw_ci_exit
            severity = {"PASS": 0, "NOT_RUN": 1, "BLOCKED_EXTERNAL": 2, "FAIL": 3, "INVALID": 4}
            if severity[ci_result] > severity.get(result, severity["INVALID"]):
                result = ci_result
                exit_status = ci_exit_status
            if ci_result != "PASS":
                limitations = f"{limitations}; same-run CI supplement: {ci_result}"
    return GateResult(
        gate_id=gate_id,
        commit_sha=commit_sha,
        tree_sha=tree_sha,
        artifact_hash=artifact_hash,
        command=command,
        procedure=procedure,
        environment="runtime-artifact-or-not-run",
        timestamp=timestamp,
        exit_status=exit_status,
        result=result,  # type: ignore[arg-type]
        limitations=(limitations,),
        reviewer=reviewer,
        evidence_paths=evidence_paths,
    )


def _ci_result(
    root: Path,
    gate_id: str,
    audit_path: str,
    reviewer: ReviewerRef,
    *,
    commit_sha: str,
    tree_sha: str,
    artifact_hash: str,
    timestamp: str,
) -> GateResult:
    """Aggregate one same-run local CI envelope without upgrading runtime."""

    relative = CI_GATE_ARTIFACTS[gate_id]
    evidence_paths: tuple[EvidenceRef, ...]
    command: tuple[str, ...]
    procedure: str
    result = "NOT_RUN"
    exit_status: int | None = None
    limitations = "No current same-run CI envelope was supplied for this local gate."
    path = root / relative
    if path.is_file():
        evidence_paths = (_evidence_ref(root, relative, f"same-run CI envelope for {gate_id}"),)
        command = ("ci-envelope", relative)
        procedure = f"validate the supplied same-run CI envelope for {gate_id} against this checkout"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            raw = None
        if isinstance(raw, dict) and raw.get("schema_version") == "state-of-art-ci-evidence.v1":
            observed = str(raw.get("status", "")).upper()
            raw_exit = raw.get("exit_status")
            expected_exit = {"PASS": 0, "FAIL": 1, "NOT_RUN": None}
            if observed in expected_exit and (
                (type(raw_exit) is int and raw_exit >= 0) or raw_exit is None
            ) and raw_exit == expected_exit[observed]:
                result = observed
                exit_status = raw_exit
                raw_limitations = raw.get("limitations")
                if isinstance(raw_limitations, list):
                    limitations = "; ".join(str(item) for item in raw_limitations if str(item).strip())
                elif raw_limitations:
                    limitations = str(raw_limitations)
            else:
                result = "INVALID"
                exit_status = 1
                limitations = "CI envelope has an unsupported status or contradictory exit_status"
        else:
            result = "INVALID"
            exit_status = 1
            limitations = "CI envelope has an unsupported schema or is not a JSON object"
    else:
        evidence_paths = (_evidence_ref(root, audit_path, f"current audit for missing {gate_id} CI evidence"),)
        command = ("ci-envelope", gate_id)
        procedure = f"await the same-run CI procedure for {gate_id}; no envelope is claimed"
    return GateResult(
        gate_id=gate_id,
        commit_sha=commit_sha,
        tree_sha=tree_sha,
        artifact_hash=artifact_hash,
        command=command,
        procedure=procedure,
        environment="same-run-ci-envelope-or-not-run",
        timestamp=timestamp,
        exit_status=exit_status,
        result=result,  # type: ignore[arg-type]
        limitations=(limitations or "CI envelope limitations were not supplied",),
        reviewer=reviewer,
        evidence_paths=evidence_paths,
    )


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
    timestamp = _execution_timestamp(root)
    audit_path = "docs/reports/current-triple-aaa-gap-audit.md"
    release_evidence = (
        _evidence_ref(root, "docs/architecture/release-integrity.md", "release integrity policy"),
        _evidence_ref(root, audit_path, "current candidate gap audit"),
        _evidence_ref(root, "docs/reports/current-triple-aaa-quality-bar-v1.json", "frozen quality bar"),
        _evidence_ref(root, "docs/plans/phase-3-triple-aaa-closure.md", "active closure plan"),
        _evidence_ref(root, "docs/reports/rick-intelligence-triple-aaa-final-promotion.md", "current diagnostic promotion report"),
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
            tree_sha=checkout["tree"],
            artifact_hash=artifact_hash,
            command=("git", "diff", "--check", "&&", "make", "validate"),
            procedure="run git diff --check and make validate against the exact checkout",
            environment=environment,
            timestamp=timestamp,
            exit_status=0 if local_result == "PASS" else 1,
            result=local_result,  # type: ignore[arg-type]
            limitations=local_limitations,
            reviewer=reviewer,
            evidence_paths=release_evidence,
        )
    ]
    for gate_id in REQUIRED_GATES:
        if gate_id == "release-integrity":
            continue
        if gate_id in CI_GATE_ARTIFACTS and gate_id != "supply-chain":
            gates.append(
                _ci_result(
                    root,
                    gate_id,
                    audit_path,
                    reviewer,
                    commit_sha=checkout["head"],
                    tree_sha=checkout["tree"],
                    artifact_hash=artifact_hash,
                    timestamp=timestamp,
                )
            )
        else:
            gates.append(
                _runtime_result(
                    root,
                    gate_id,
                    audit_path,
                    reviewer,
                    commit_sha=checkout["head"],
                    tree_sha=checkout["tree"],
                    artifact_hash=artifact_hash,
                    timestamp=timestamp,
                    supplemental_ci_relative=CI_GATE_ARTIFACTS.get(gate_id),
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
