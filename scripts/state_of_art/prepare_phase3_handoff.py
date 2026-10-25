#!/usr/bin/env python3
"""Prepare an unsigned diagnostic handoff; never issue review or release approval.

Reads existing evidence, verifies referenced raw hashes, and records why each
lane still needs work. Does not run gates or overwrite canonical control inputs.
The source manifest includes untracked nonignored files so a dirty worktree can
be reviewed precisely, while remaining ineligible for commit-bound release.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.state_of_art.json_boundary import load_json
from scripts.state_of_art.release_integrity import capture_checkout

SCHEMA = "phase3-preparation-handoff.v1"
EVIDENCE = {
    "postgres": ".runtime/phase-3/prd26-postgres-runtime-evidence.json",
    "multi-worker": ".runtime/phase-3/multi-worker-runtime-evidence.json",
    "redis": ".runtime/phase-3/redis-runtime-evidence.json",
    "redis-multi-replica": ".runtime/phase-3/redis-multi-replica-runtime-evidence.json",
    "object-qdrant": ".runtime/phase-3/object-qdrant-runtime-evidence.json",
    "golden": ".runtime/phase-3/golden-ingestion-runtime-evidence.json",
    "tenant-evidence": ".runtime/phase-3/tenant-evidence-runtime-evidence.json",
    "provider": ".runtime/phase-3/provider-runtime-evidence.json",
    "observability": ".runtime/phase-3/observability-runtime-evidence.json",
    "restore": ".runtime/phase-3/restore-runtime-evidence.json",
    "file-security": ".runtime/phase-3/file-security-runtime-evidence.json",
    "frontend-supply": ".runtime/phase-3/frontend-supply-runtime-evidence.json",
    "performance": ".runtime/phase-3/performance-runtime-evidence.json",
    "chaos": ".runtime/phase-3/chaos-runtime-evidence.json",
    "soak": ".runtime/phase-3/soak-runtime-evidence.json",
}
LOCAL_OBSERVATIONS = (
    ".runtime/phase-3/local-closure/product-probe.json",
    ".runtime/phase-3/local-closure/frontend-supply.json",
    ".runtime/phase-3/local-closure/observability.json",
    ".runtime/phase-3/formal-local/tenant-current.json",
    ".runtime/phase-3/formal-local/tenant-contention.json",
    ".runtime/phase-3/formal-local/golden-current.json",
    ".runtime/phase-3/formal-local/distributed.json",
    ".runtime/phase-3/formal-local/frontend-supply.json",
    ".runtime/phase-3/formal-local/tenant-contention-current.json",
    ".runtime/phase-3/operational-local/performance-current.json",
    ".runtime/phase-3/operational-local/soak-current.json",
    ".runtime/phase-3/chaos-local/current.json",
    ".runtime/phase-3/frontend-local/current.json",
    ".runtime/phase-3/observability-local/current.json",
    ".runtime/phase-3/supply-local/current.json",
)
VERIFICATION_ARTIFACTS = tuple(
    f".runtime/phase-3/formal-local/{name}.log" for name in (
        "regression-final", "retrieval-preparation-final", "final-boundaries", "lifecycle-final",
        "validate-final", "compose-final", "typecheck-final", "handoff-final",
        "operational-regression-final", "web-contract-tests", "chat-read-regression",
        "worker-exit-regression", "causal-network-final", "lane-browser-regression",
    )
)
CURRENT_LOCAL = {
    "golden": ".runtime/phase-3/formal-local/golden-current.json",
    "tenant-contention": ".runtime/phase-3/formal-local/tenant-contention-current.json",
    "performance": ".runtime/phase-3/operational-local/performance-current.json",
    "soak": ".runtime/phase-3/operational-local/soak-current.json",
    "chaos": ".runtime/phase-3/chaos-local/current.json",
    "frontend": ".runtime/phase-3/frontend-local/current.json",
    "observability": ".runtime/phase-3/observability-local/current.json",
    "supply": ".runtime/phase-3/supply-local/current.json",
}


def safe_file(root: Path, raw: str) -> Path:
    if not isinstance(raw, str) or not raw:
        raise ValueError("unsafe_artifact_path")
    path = Path(raw)
    if not raw or path.is_absolute() or ".." in path.parts:
        raise ValueError("unsafe_artifact_path")
    target = root
    for part in path.parts:
        target /= part
        if target.is_symlink():
            raise ValueError("symlink_artifact_rejected")
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("unsafe_artifact_path")
    return target


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_manifest(root: Path) -> list[dict]:
    proc = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                          cwd=root, capture_output=True, check=True)
    manifest = []
    for raw in sorted(set(proc.stdout.decode().strip("\0").split("\0")) - {""}):
        path = safe_file(root, raw)
        manifest.append({"path": raw, "sha256": sha256(path) if path.is_file() else None})
    return manifest


def inspect_evidence(root: Path, raw: str, checkout: dict, *, now=None) -> dict:
    """Diagnostic projection only; the canonical verifier still owns acceptance."""
    row = {"path": raw, "observed_status": "NOT_RUN", "issues": []}
    try:
        path = safe_file(root, raw)
        if not path.is_file():
            row["issues"].append("missing_evidence")
            return row
        row["sha256"] = sha256(path)
        payload = load_json(path)
        if not isinstance(payload, dict):
            raise ValueError("nonobject_evidence")
        row["observed_status"] = payload.get("status", "INVALID")
        row["production_safe"] = payload.get("production_safe") is True
        row["independent"] = (isinstance(payload.get("reviewer"), dict)
                              and payload["reviewer"].get("independent") is True)
        if payload.get("schema_version") != "state-of-art-runtime-evidence.v1":
            row["issues"].append("not_runtime_envelope")
        if payload.get("status") != "PASS" or type(payload.get("exit_status")) is not int or payload.get("exit_status") != 0:
            row["issues"].append("runtime_not_pass")
        for field, expected in (("commit_sha", checkout.get("head")),
                                ("tree_sha", checkout.get("tree")),
                                ("checkout_fingerprint", checkout.get("fingerprint"))):
            if not expected or payload.get(field) != expected:
                row["issues"].append(f"{field}_mismatch")
        if payload.get("clean_worktree") is not True or checkout.get("status") != "CLEAN":
            row["issues"].append("clean_candidate_required")
        observed = datetime.fromisoformat(str(payload.get("observed_at", "")).replace("Z", "+00:00"))
        if observed.tzinfo is None:
            raise ValueError("timestamp_without_timezone")
        age = ((now or datetime.now(timezone.utc)) - observed).total_seconds()
        if age > 86400 or age < -300:
            row["issues"].append("stale_evidence")
        artifacts = payload.get("raw_artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            row["issues"].append("raw_artifacts_missing")
        else:
            for ref in artifacts:
                if not isinstance(ref, dict):
                    raise ValueError("invalid_artifact_ref")
                target = safe_file(root, ref.get("path", ""))
                if not target.is_file() or sha256(target) != ref.get("sha256"):
                    row["issues"].append("raw_artifact_hash_mismatch")
        preflight = payload.get("preflight")
        if not isinstance(preflight, dict) or preflight.get("status") != "PASS":
            row["issues"].append("preflight_not_pass")
        else:
            preflight_file = safe_file(root, payload.get("preflight_path", ""))
            if not preflight_file.is_file() or sha256(preflight_file) != payload.get("preflight_sha256"):
                row["issues"].append("preflight_hash_mismatch")
        if not row["production_safe"]:
            row["issues"].append("production_profile_required")
        if not row["independent"]:
            row["issues"].append("independent_review_required")
    except (OSError, ValueError, TypeError, KeyError):
        row["issues"].append("invalid_or_unsafe_evidence")
    row["issues"] = sorted(set(row["issues"]))
    return row


def prepare(root: Path, *, evidence=None) -> dict:
    checkout = capture_checkout(root)
    sources = source_manifest(root)
    digest = hashlib.sha256(json.dumps(sources, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    rows = {name: inspect_evidence(root, path, checkout) for name, path in (EVIDENCE if evidence is None else evidence).items()}
    local = []
    for raw in LOCAL_OBSERVATIONS:
        path = safe_file(root, raw)
        if path.is_file():
            try:
                observation = load_json(path)
                if not isinstance(observation, dict):
                    raise ValueError("nonobject_observation")
                record = {"path": raw, "sha256": sha256(path),
                              "observed_status": observation.get("status", "INVALID"),
                              "release_acceptance": False}
                run_id = observation.get("run_id") or observation.get("runtime_run_id")
                if isinstance(run_id, str) and run_id.isalnum() and len(run_id) <= 64:
                    record["run_id"] = run_id
                    record["raw_observations"] = []
                    for name in ("tenant-observations", "golden-observations"):
                        extra = f".runtime/phase-3/formal-local/{run_id}/{name}.json"
                        source = safe_file(root, extra)
                        if source.is_file():
                            record["raw_observations"].append({"path": extra, "sha256": sha256(source)})
                refs = observation.get("raw_artifacts", [])
                if isinstance(refs, list):
                    record["raw_artifacts"] = []
                    for ref in refs:
                        if not isinstance(ref, dict):
                            raise ValueError("invalid_artifact_ref")
                        source = safe_file(root, ref.get("path", ""))
                        artifact_digest = sha256(source) if source.is_file() else None
                        record["raw_artifacts"].append({"path": ref["path"], "sha256": artifact_digest,
                            "hash_matches": artifact_digest is not None and artifact_digest == ref.get("sha256")})
                local.append(record)
            except (ValueError, OSError):
                local.append({"path": raw, "observed_status": "INVALID", "release_acceptance": False})
    return {
        "schema_version": SCHEMA, "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PREPARED_NO_GO", "promotable": False, "signed": False,
        "human_decision": "PENDING", "independent_review": "PENDING",
        "checkout": {field: checkout.get(field) for field in ("head", "tree", "status", "fingerprint")},
        "source_manifest_sha256": digest, "source_manifest": sources, "evidence": rows,
        "local_observations": local,
        "current_local_results": {name: next((record for record in local if record["path"] == path),
            {"path": path, "observed_status": "NOT_RUN", "release_acceptance": False}) for name, path in CURRENT_LOCAL.items()},
        "verification_artifacts": [{"path": path, "sha256": sha256(safe_file(root, path))}
            for path in VERIFICATION_ARTIFACTS if safe_file(root, path).is_file()],
        "remaining_work": [
            {"id": "tenant-timing", "required": "Review the bounded four-actor local experiment and preserved failures; approve and execute the production contention workload and timing policy."},
            {"id": "golden-evaluation", "required": "Approved claim-support evaluator/corpus and observed decision/response; the provider fixture cannot approve model quality."},
            {"id": "observability", "required": "Supply an approved semantic claim-support observation; review local trace/metric/alert evidence and ratify production SLOs, timers and delivery destinations."},
            {"id": "frontend", "required": "Review local states, accessibility and native zoom evidence; bind the final production frontend and immutable images/SBOMs to trusted CI, vulnerability scans, provenance and signatures."},
        ],
        "required_inputs": [
            {"id": "approved-evaluation", "owner": "knowledge/model evaluation authority",
             "required": "Approved corpus, claim-support evaluator, exact hashes and acceptance criteria; structural citation validation is insufficient."},
            {"id": "production-profile", "owner": "operations/security",
             "required": "Reviewed TLS/auth profile, secret-store references and trusted certificates; rerun every gate."},
            {"id": "operational-budgets", "owner": "operations",
             "required": "Approved performance workload, chaos window, soak durations, SLO/RPO/RTO and stop limits."},
            {"id": "remote-supply-chain", "owner": "release/security",
             "required": "Remote CI for the exact SHA; immutable images, SBOM, scan, provenance and signatures."},
            {"id": "independent-reviews", "owner": "independent reviewers",
             "required": "Current review ledger bound to the candidate; builder self-review is not independent."},
            {"id": "human-go", "owner": "release authority",
             "required": "Explicit GO/NO-GO for the exact sealed packet, rollback owner and monitoring window."},
        ],
        "limitations": [
            "Preparation only, not the canonical verifier or a sealed release packet.",
            "Envelope metadata is untrusted; full semantic acceptance belongs to phase3_evidence/release_integrity.",
            "Regenerate after any source/artifact change. Fresh local evidence cannot confer release authority.",
            "Local runtime observations are diagnostics on the source manifest, not commit-bound production envelopes.",
        ],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=".runtime/phase-3/local-closure/production-handoff.json")
    args = parser.parse_args(argv)
    output = safe_file(ROOT, args.output)
    # Preparation may only write into its own ignored workspace; never a
    # canonical control input, source file, signed packet or evidence envelope.
    allowed = ROOT / ".runtime/phase-3/local-closure"
    if not output.is_relative_to(allowed) or output.name != "production-handoff.json":
        parser.error("output must be named production-handoff.json under .runtime/phase-3/local-closure")
    payload = prepare(ROOT)
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    archive = output.with_name(f"production-handoff-{digest[:16]}.json")
    if not archive.exists():
        archive.write_text(encoded, encoding="utf-8")
    output.write_text(encoded, encoding="utf-8")
    print(json.dumps({"status": payload["status"], "lanes": len(payload["evidence"]),
                      "source_files": len(payload["source_manifest"]), "output": args.output}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
