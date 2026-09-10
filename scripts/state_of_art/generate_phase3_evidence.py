#!/usr/bin/env python3
"""Generate the current fail-closed Phase 3 capability evidence matrix."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

try:
    from scripts.state_of_art.phase3_evidence import (
        MATRIX_SCHEMA,
        RUNTIME_EVIDENCE_STATUSES,
        build_capability,
        evaluate_matrix,
        parse_matrix,
    )
    from scripts.state_of_art.phase3_runtime_adapter import redact_runtime_value
    from scripts.state_of_art.release_integrity import capture_checkout
except ImportError:  # pragma: no cover - direct script execution fallback.
    from phase3_evidence import MATRIX_SCHEMA, RUNTIME_EVIDENCE_STATUSES, build_capability, evaluate_matrix, parse_matrix
    from phase3_runtime_adapter import redact_runtime_value
    from release_integrity import capture_checkout


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ".runtime/phase-3/capability-matrix.json"
PROMPT_PATH = "docs/prompts/phase-3-triple-aaa-closure-2026-09-09.txt"
AUDIT_PATH = "docs/reports/current-triple-aaa-gap-audit.md"
PUBLIC_PLAN_PATH = "docs/plans/phase-3-triple-aaa-closure.md"
EXECP_PLAN_PATH = ".agent/plans/phase-3-runtime-evidence-production-promotion.md"
QUALITY_BAR_PATH = "docs/reports/current-triple-aaa-quality-bar-v1.json"
FINAL_REPORT_PATH = "docs/reports/rick-intelligence-triple-aaa-final-promotion.md"
LOCAL_CHECK_DIR = ".runtime/phase-3/local-checks"


def _redacted_tail(value: str) -> str:
    """Keep local-check diagnostics useful without persisting secrets."""

    return str(redact_runtime_value(value))[-4000:]


def _file_hash(root: Path, path: str) -> str:
    digest = hashlib.sha256()
    with (root / path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _common_artifacts() -> list[tuple[str, str]]:
    return [
        (PROMPT_PATH, "exact supplied Phase 3 prompt copy"),
        (AUDIT_PATH, "current Phase 3 entry audit"),
        (PUBLIC_PLAN_PATH, "public Phase 3 execution plan"),
        (EXECP_PLAN_PATH, "living engineering ExecPlan"),
        (QUALITY_BAR_PATH, "frozen Triple AAA quality bar"),
        (FINAL_REPORT_PATH, "current diagnostic promotion report"),
    ]


def _reviewer() -> dict[str, Any]:
    return {
        "id": "codex-lead-local",
        "kind": "lead-local",
        "name": "Codex lead local verification",
        "independent": False,
    }


def _capability_definitions() -> tuple[dict[str, Any], ...]:
    common = _common_artifacts()
    return (
        {
            "capability_id": "P0-01",
            "title": "Control plane and canonical local CI lanes",
            "priority": "P0",
            "status": "LOCAL_VERIFIED",
            "code_tests": [".github/workflows/quality.yml", "Makefile", "docs/ci/check_control_plane.py"],
            "artifacts": common + [(".github/workflows/quality.yml", "canonical quality workflow"), ("Makefile", "canonical local commands")],
            "local_checks": (("make validate", ("make", "validate")),),
            "limitations": "Local controls and static lanes pass, but remote CI and live runtime execution are not proven.",
            "next_action": "Add explicit Phase 3 lane artifacts and obtain a current remote CI run.",
        },
        {
            "capability_id": "P0-02",
            "title": "Commit-bound release evidence",
            "priority": "P0",
            "status": "PARTIAL",
            "code_tests": ["scripts/state_of_art/release_integrity.py", "scripts/state_of_art/release_manifest.py", "scripts/state_of_art/tests/test_release_manifest.py"],
            "artifacts": common + [("scripts/state_of_art/release_integrity.py", "release integrity verifier"), ("scripts/state_of_art/release_manifest.py", "typed release manifest")],
            "limitations": "The release manifest is fail-closed but not a complete clean Triple AAA promotion packet.",
            "next_action": "Complete Phase 3 manifest binding and explicit negative rejection tests.",
        },
        {
            "capability_id": "P0-03",
            "title": "Disposable lab lifecycle and readiness",
            "priority": "P0",
            "status": "LOCAL_VERIFIED",
            "code_tests": ["scripts/phase11/runner.py", "scripts/phase11/test_compose_lifecycle.py", "scripts/phase11/check_compose.py", "docker-compose.dev.yml", "docker-compose.staging.yml"],
            "artifacts": common + [("scripts/phase11/runner.py", "readiness-aware Compose lifecycle launcher"), ("scripts/phase11/test_compose_lifecycle.py", "hermetic lifecycle contract tests"), ("docker-compose.dev.yml", "development service topology"), ("docker-compose.staging.yml", "staging service topology")],
            "local_checks": (
                ("make compose-static", ("make", "compose-static")),
                ("Compose lifecycle contract tests", (sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "scripts/phase11/test_compose_lifecycle.py")),
            ),
            "limitations": "Configuration validation, local-only scoping, health wait flags, worker A/B topology and bounded diagnostics are locally verified; Docker daemon readiness and endpoint observations remain BLOCKED_EXTERNAL.",
            "next_action": "Run make up and make down against the approved disposable daemon, retain health/log evidence and do not upgrade this row without live readiness.",
        },
        {
            "capability_id": "P0-04",
            "title": "PostgreSQL migrations, locking and durable queue",
            "priority": "P0",
            "status": "BLOCKED_EXTERNAL",
            "code_tests": ["infrastructure/migrations/0004_durable_jobs_contract.sql", "apps/worker/postgres_jobs.py", "scripts/phase11/postgres_runtime_gate.py", "scripts/state_of_art/run_phase3_postgres.py"],
            "artifacts": common + [("scripts/phase11/postgres_runtime_gate.py", "PostgreSQL runtime gate"), ("scripts/state_of_art/run_phase3_postgres.py", "Phase 3 commit-bound PostgreSQL evidence adapter")],
            "runtime_evidence": [(".runtime/phase-3/postgres-runtime-evidence.json", "PostgreSQL runtime evidence envelope")],
            "limitations": "No live PostgreSQL DSN or client runtime is available for migration, lock, concurrency or crash evidence; the Phase 3 adapter remains a blocked diagnostic.",
            "next_action": "Execute the disposable Postgres migration/concurrency/recovery matrix and bind the resulting envelope to an independent review.",
        },
        {
            "capability_id": "P0-05",
            "title": "Two workers, fencing and crash recovery",
            "priority": "P0",
            "status": "BLOCKED_EXTERNAL",
            "code_tests": ["apps/worker/runtime.py", "apps/worker/canonical_queue.py", "apps/worker/tests/test_runtime.py", "scripts/phase11/multi_worker_runtime_gate.py", "scripts/state_of_art/tests/test_multi_worker_runtime.py"],
            "artifacts": common + [("apps/worker/runtime.py", "real worker runtime"), ("apps/worker/canonical_queue.py", "canonical queue"), ("scripts/phase11/multi_worker_runtime_gate.py", "two-process worker fencing gate")],
            "runtime_evidence": [(".runtime/phase-3/multi-worker-runtime-evidence.json", "two-process worker runtime evidence envelope")],
            "limitations": "No approved disposable PostgreSQL DSN is available for two-process ownership, heartbeat, crash/reclaim or stale-fence runtime observation.",
            "next_action": "Run make phase3-multi-worker-runtime against the approved disposable PostgreSQL runtime.",
        },
        {
            "capability_id": "P0-06",
            "title": "Redis multi-replica lease and rate-limit behavior",
            "priority": "P0",
            "status": "BLOCKED_EXTERNAL",
            "code_tests": ["apps/api/src/core/rate_limit.py", "apps/api/src/routes/auth.py", "apps/api/src/routes/chat.py", "apps/api/src/routes/compatibility_openai.py", "apps/api/src/app.py", "apps/api/src/services/external_composition.py", "apps/api/tests/test_app_lifecycle.py", "apps/api/tests/test_external_composition.py", "apps/api/tests/test_rate_limit.py", "scripts/phase11/redis_runtime_gate.py", "scripts/phase11/redis_multi_replica_runtime_gate.py", "scripts/state_of_art/run_phase3_redis.py", "scripts/state_of_art/run_phase3_redis_multi_replica.py", "packages/locking/pyproject.toml", "packages/locking/src/rick_locking/rate_limit.py", "packages/locking/src/rick_locking/redis.py", "Makefile"],
            "artifacts": common + [("apps/api/src/core/rate_limit.py", "API rate-limit adapter"), ("apps/api/src/routes/auth.py", "auth rate-limit HTTP boundary"), ("apps/api/src/routes/chat.py", "chat and compatibility rate-limit HTTP boundary"), ("apps/api/src/routes/compatibility_openai.py", "compatibility rate-limit HTTP boundary"), ("apps/api/src/app.py", "production admission gate"), ("apps/api/src/services/external_composition.py", "Redis client/capability binding"), ("scripts/phase11/redis_runtime_gate.py", "Redis lease/runtime gate"), ("scripts/phase11/redis_multi_replica_runtime_gate.py", "two-process canonical API HTTP Redis multi-replica gate"), ("scripts/state_of_art/run_phase3_redis.py", "Phase 3 commit-bound Redis evidence adapter"), ("scripts/state_of_art/run_phase3_redis_multi_replica.py", "Phase 3 commit-bound multi-replica Redis evidence adapter")],
            "runtime_evidence": [(".runtime/phase-3/redis-multi-replica-runtime-evidence.json", "two-process Redis multi-replica runtime evidence envelope")],
            "limitations": "No live Redis endpoint or two-process canonical API run is available; the gate remains fail-closed until an approved endpoint and driver are supplied.",
            "next_action": "Execute two canonical apps/api replicas against the same Redis, then run TTL, fencing, rate-limit and unavailable-broker cases.",
        },
        {
            "capability_id": "P0-07",
            "title": "S3-compatible object and Qdrant vector lifecycle",
            "priority": "P0",
            "status": "BLOCKED_EXTERNAL",
            "code_tests": ["scripts/phase11/object_qdrant_runtime_gate.py", "scripts/state_of_art/run_phase3_object_qdrant.py", "packages/storage/pyproject.toml", "packages/knowledge/src/rick_knowledge/models.py"],
            "artifacts": common + [("scripts/phase11/object_qdrant_runtime_gate.py", "object/vector runtime gate"), ("scripts/state_of_art/run_phase3_object_qdrant.py", "Phase 3 commit-bound object/vector evidence adapter")],
            "runtime_evidence": [(".runtime/phase-3/object-qdrant-runtime-evidence.json", "object/vector runtime evidence envelope")],
            "limitations": "No live object-store or Qdrant lifecycle, checksum, delete, restore or tenant filter evidence exists.",
            "next_action": "Run live object/vector lifecycle and restore/consistency negatives.",
        },
        {
            "capability_id": "P0-08",
            "title": "Golden ingestion, idempotency and lineage",
            "priority": "P0",
            "status": "BLOCKED_EXTERNAL",
            "code_tests": ["apps/worker/external_ingestion.py", "apps/api/src/services/postgres_ingestion.py", "infrastructure/migrations/0006_document_lineage_contract.sql"],
            "artifacts": common + [("apps/worker/external_ingestion.py", "external ingestion bridge"), ("infrastructure/migrations/0006_document_lineage_contract.sql", "lineage contract")],
            "limitations": "No approved golden document has traversed real upload, parse, chunk, embed, index and query services.",
            "next_action": "Run golden ingestion, crash/replay, idempotency and lineage closure.",
        },
        {
            "capability_id": "P1-01",
            "title": "Evidence authority and mandatory negative security",
            "priority": "P1",
            "status": "PARTIAL",
            "code_tests": ["packages/evidence/src/rick_evidence/validator.py", "packages/decision/src/rick_decision", "scripts/phase11/check_adversarial_corpus.py"],
            "artifacts": common + [("packages/evidence/src/rick_evidence/validator.py", "evidence validator"), ("scripts/phase11/check_adversarial_corpus.py", "adversarial corpus checker")],
            "limitations": "Local authority and adversarial checks exist, but live artifact, cross-tenant and stale-version closure is open.",
            "next_action": "Execute forged, cross-tenant, stale-version, wrong-checksum and unknown-chunk runtime cases.",
        },
        {
            "capability_id": "P1-02",
            "title": "Approved real or OpenAI-compatible provider",
            "priority": "P1",
            "status": "BLOCKED_EXTERNAL",
            "code_tests": ["packages/providers/pyproject.toml", "apps/api/src/services/professor_backend.py", "docs/evaluation/packs/rec22-local-v1/manifest.json"],
            "artifacts": common + [("apps/api/src/services/professor_backend.py", "provider boundary"), ("docs/evaluation/packs/rec22-local-v1/manifest.json", "offline evaluation pack")],
            "limitations": "No approved provider endpoint, credentials, budget or corpus authority is available.",
            "next_action": "Obtain D03/D04 and run the redacted provider, budget, citation and cancellation matrix.",
        },
        {
            "capability_id": "P1-03",
            "title": "Multi-tenancy and adversarial RAG",
            "priority": "P1",
            "status": "PARTIAL",
            "code_tests": ["docs/evaluation/packs/rec22-local-v1/manifest.json", "scripts/state_of_art/evaluate_pack.py", "scripts/state_of_art/evaluate_retrieval.py"],
            "artifacts": common + [("docs/evaluation/packs/rec22-local-v1/manifest.json", "synthetic offline pack"), ("scripts/state_of_art/evaluate_retrieval.py", "retrieval evaluator")],
            "limitations": "Synthetic offline ACL/citation evidence does not prove live multi-tenant retrieval against an approved corpus.",
            "next_action": "Run live isolation, ACL, prompt-injection, poisoned-document and stale-index tests.",
        },
        {
            "capability_id": "P1-04",
            "title": "Distributed OTel, redaction, metrics and SLO",
            "priority": "P1",
            "status": "PARTIAL",
            "code_tests": ["infrastructure/compose/otel-collector-config.yaml", "infrastructure/compose/prometheus.yml", "docs/operations/slo.md"],
            "artifacts": common + [("infrastructure/compose/otel-collector-config.yaml", "OTel collector configuration"), ("docs/operations/slo.md", "SLO contract")],
            "limitations": "Local telemetry seams and static configs exist; distributed export, alert delivery and soak evidence are not run.",
            "next_action": "Exercise trace propagation, redaction, metrics cardinality, alerts and SLOs.",
        },
        {
            "capability_id": "P1-05",
            "title": "DR, restore, chaos, soak and performance",
            "priority": "P1",
            "status": "NOT_RUN",
            "code_tests": ["infrastructure/scripts/backup-restore-check.py", "infrastructure/scripts/backup_restore.py", "docs/operations/release-readiness.md"],
            "artifacts": common + [("docs/operations/release-readiness.md", "release/restore readiness contract")],
            "limitations": "No real backup/restore, RPO/RTO, chaos, soak or load run is available in this environment.",
            "next_action": "Define budgets and execute the disposable DR/resilience matrix.",
        },
        {
            "capability_id": "P1-06",
            "title": "Frontend runtime, accessibility and visual QA",
            "priority": "P1",
            "status": "PARTIAL",
            "code_tests": ["apps/web/package.json", "apps/web/playwright.config.ts", "docs/operations/slo.md"],
            "artifacts": common + [("apps/web/package.json", "frontend scripts"), ("apps/web/playwright.config.ts", "browser harness")],
            "limitations": "Static lint/type/build and historical local browser evidence exist; no fresh Phase 3 independent runtime review is bound.",
            "next_action": "Run 375/768/1440 browser, accessibility and independent visual review gates.",
        },
        {
            "capability_id": "P1-07",
            "title": "Supply chain and deployment hardening",
            "priority": "P1",
            "status": "PARTIAL",
            "code_tests": [".github/workflows/quality.yml", "infrastructure/docker/api.Dockerfile", "infrastructure/docker/worker.Dockerfile"],
            "artifacts": common + [(".github/workflows/quality.yml", "supply-chain CI lane"), ("infrastructure/docker/api.Dockerfile", "API image")],
            "limitations": "Partial dependency audits and pinned workflows exist; SBOM, signed provenance and full image hardening are open.",
            "next_action": "Add scanners, SBOM, signatures, immutable digests and container hardening evidence.",
        },
        {
            "capability_id": "P1-08",
            "title": "Independent reviews and human promotion decision",
            "priority": "P1",
            "status": "NOT_RUN",
            "code_tests": ["docs/reports/current-triple-aaa-gap-audit.md", "docs/plans/phase-3-triple-aaa-closure.md"],
            "artifacts": common + [(AUDIT_PATH, "current audit")],
            "limitations": "Historical scoped reviews do not constitute a fresh Phase 3 packet review or human Go/No-Go.",
            "next_action": "Commission independent reviews and bind the human deployment/rollback decision.",
        },
        {
            "capability_id": "P2-01",
            "title": "Advanced retrieval and calibration feature flags",
            "priority": "P2",
            "status": "NOT_RUN",
            "code_tests": ["packages/retrieval/pyproject.toml", "scripts/state_of_art/evaluate_retrieval.py", PUBLIC_PLAN_PATH],
            "artifacts": common + [("scripts/state_of_art/evaluate_retrieval.py", "retrieval evaluation")],
            "limitations": "Advanced retrieval is intentionally not promoted before baseline runtime, citation and release closure.",
            "next_action": "Enable only after all required P0/P1 runtime evidence is current.",
        },
    )


def build_matrix(root: Path, *, environment: str = "local-hermetic") -> dict[str, Any]:
    checkout = capture_checkout(root)
    prompt = root / PROMPT_PATH
    capabilities: list[dict[str, Any]] = []
    reviewer = _reviewer()
    observed_at = datetime.now(timezone.utc).isoformat()
    for definition in _capability_definitions():
        status = definition["status"]
        artifact_paths = list(definition["artifacts"])
        runtime_paths: list[tuple[str, str]] = []
        local_checks = tuple(definition.get("local_checks", ()))
        check_results: list[dict[str, Any]] = []
        runtime_observation: dict[str, Any] | None = None
        for runtime_path, runtime_description in definition.get("runtime_evidence", ()):
            runtime_target = root / runtime_path
            if not runtime_target.is_file():
                continue
            runtime_paths.append((runtime_path, runtime_description))
            try:
                runtime_observation = json.loads(runtime_target.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                runtime_observation = None
            if isinstance(runtime_observation, dict) and runtime_observation.get("status") in {
                "PASS",
                "VERIFIED_RUNTIME",
                "PROMOTABLE",
            }:
                if status == "BLOCKED_EXTERNAL":
                    status = "PARTIAL"
                break
        if local_checks:
            for label, command in local_checks:
                try:
                    completed = subprocess.run(
                        list(command),
                        cwd=root,
                        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        check=False,
                        timeout=600,
                    )
                    check_results.append(
                        {
                            "label": label,
                            "command": list(command),
                            "exit_status": completed.returncode,
                            "stdout": _redacted_tail(completed.stdout or ""),
                            "stderr": _redacted_tail(completed.stderr or ""),
                        }
                    )
                except (OSError, subprocess.TimeoutExpired) as exc:
                    check_results.append(
                        {
                            "label": label,
                            "command": list(command),
                            "exit_status": None,
                            "error": type(exc).__name__,
                        }
                    )
            check_path = f"{LOCAL_CHECK_DIR}/{definition['capability_id']}.json"
            check_target = root / check_path
            check_target.parent.mkdir(parents=True, exist_ok=True)
            check_target.write_text(
                json.dumps(
                    {
                        "schema_version": "state-of-art-local-check.v1",
                        "capability_id": definition["capability_id"],
                        "observed_at": observed_at,
                        "checks": check_results,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            check_target.chmod(0o600)
            artifact_paths.append((check_path, "executed local check record"))
            if status == "LOCAL_VERIFIED" and not all(item.get("exit_status") == 0 for item in check_results):
                status = "FAILED"
        if local_checks:
            procedure = "executed local checks: " + ", ".join(label for label, _command in local_checks)
            failed = [item for item in check_results if item.get("exit_status") != 0]
            exit_status = 0 if not failed else next(
                (item.get("exit_status") for item in failed if isinstance(item.get("exit_status"), int)),
                1,
            )
        elif status in {"BLOCKED_EXTERNAL", "NOT_RUN", "PARTIAL"}:
            exit_status = None
            procedure = "runtime procedure not executed because the capability remains outside the local evidence boundary"
        elif status == "FAILED":
            exit_status = 1
            procedure = "local capability procedure executed and failed"
        else:
            exit_status = 0
            procedure = "local structural, static or hermetic verification procedure"
        limitations = definition["limitations"]
        if runtime_paths:
            runtime_status = runtime_observation.get("status") if isinstance(runtime_observation, dict) else None
            if runtime_status in RUNTIME_EVIDENCE_STATUSES:
                raw_exit_status = runtime_observation.get("exit_status")
                exit_status = raw_exit_status if type(raw_exit_status) is int and raw_exit_status >= 0 else None
                procedure = (
                    "attached runtime evidence envelope observation; independent review is required before promotion"
                )
            else:
                procedure = "attached runtime evidence path could not be parsed as a valid envelope"
                exit_status = None
            limitations += " Runtime evidence is attached only as a commit-bound observation; independent review is required for runtime promotion."
        if local_checks and status == "FAILED":
            limitations += " One or more required local checks returned non-zero; the row is not locally verified."
        capabilities.append(
            build_capability(
                root,
                capability_id=definition["capability_id"],
                title=definition["title"],
                priority=definition["priority"],
                status=status,
                code_tests=definition["code_tests"],
                artifact_paths=artifact_paths,
                commit_sha=checkout["head"],
                environment=environment,
                reviewer=reviewer,
                limitations=limitations,
                next_action=definition["next_action"],
                runtime_paths=runtime_paths,
                procedure=procedure,
                exit_status=exit_status,
                observed_at=observed_at,
            )
        )
    return {
        "schema_version": MATRIX_SCHEMA,
        "generated_at": observed_at,
        "environment": environment,
        "source_prompt": PROMPT_PATH,
        "source_prompt_sha256": _file_hash(root, PROMPT_PATH),
        "candidate": {
            "commit_sha": checkout["head"],
            "tree_sha": checkout["tree"],
            "checkout_fingerprint": checkout["fingerprint"],
            "clean_worktree": checkout["status"] == "CLEAN",
        },
        "capabilities": capabilities,
    }


def write_matrix(root: Path, output: str, *, environment: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    matrix = build_matrix(root, environment=environment)
    parse_matrix(matrix, require_complete=True)
    path, path_error = _safe_output_path(root, output)
    if path_error or path is None:
        raise ValueError(path_error or "invalid output path")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(matrix, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    result = evaluate_matrix(path, capture_checkout(root), root=root)
    return path, matrix, result


def _safe_output_path(root: Path, raw_path: str) -> tuple[Path | None, str | None]:
    candidate = (root / raw_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None, "output path must remain inside the repository root"
    return candidate, None


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--environment", default="local-hermetic")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    parser.add_argument("--verify", action="store_true", help="verify an existing matrix instead of regenerating it")
    parser.add_argument("--require-promotable", action="store_true", help="return non-zero unless every capability is promotable")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    root = args.root.resolve()
    path, path_error = _safe_output_path(root, args.output)
    if path_error or path is None:
        print(json.dumps({"classification": "FAILED", "reason": path_error}, ensure_ascii=False))
        return 1
    if args.verify:
        if not path.is_file():
            result = {"classification": "NOT_RUN", "reason": "matrix file is absent", "rejection_codes": ["MISSING_EVIDENCE_REJECTED"]}
        else:
            result = evaluate_matrix(path, capture_checkout(root), root=root)
    else:
        try:
            path, _, result = write_matrix(root, args.output, environment=args.environment)
        except (OSError, ValueError, KeyError) as exc:
            print(json.dumps({"classification": "FAILED", "reason": str(exc)}, ensure_ascii=False))
            return 1
    print(json.dumps({"output": str(path.relative_to(root)), **result}, ensure_ascii=False, sort_keys=True, indent=2))
    if args.verify and result.get("classification") == "BLOCKED_EXTERNAL":
        return 2
    if args.verify and result.get("classification") in {"FAILED", "NOT_RUN"}:
        return 1
    if args.require_promotable and result.get("classification") == "BLOCKED_EXTERNAL":
        return 2
    if args.require_promotable and result.get("classification") != "PROMOTABLE":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
