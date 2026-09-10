#!/usr/bin/env python3
"""Typed, dependency-free release-evidence manifest primitives.

The release manifest is deliberately data-only.  It binds every gate to one
commit and one deterministic set of artifact hashes; the integrity checker is
responsible for checking those hashes against the checkout before promotion.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal


SHA1_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
MANIFEST_SCHEMA = "state-of-art-release-evidence.v2"
REQUIRED_GATES = (
    "architecture",
    "security",
    "contracts",
    "unit",
    "integration",
    "multi-worker",
    "multi-tenant",
    "redis",
    "postgresql",
    "qdrant",
    "object-storage",
    "ingestion-e2e",
    "evidence",
    "citation",
    "decision",
    "observability",
    "dr",
    "restore",
    "chaos",
    "soak",
    "performance",
    "frontend-e2e",
    "accessibility",
    "visual",
    "supply-chain",
    "release-integrity",
    "independent-reviews",
)
GateStatus = Literal["PASS", "FAIL", "BLOCKED_EXTERNAL", "NOT_RUN", "STALE", "INVALID"]
ManifestStatus = Literal["PASS", "FAIL", "BLOCKED_EXTERNAL", "NOT_RUN"]


class ManifestValidationError(ValueError):
    """Raised when a JSON object cannot be represented by the typed schema."""

    def __init__(self, errors: Sequence[str]):
        self.errors = tuple(errors)
        super().__init__("; ".join(self.errors))


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestValidationError((f"{field} must be a non-empty string",))
    return value.strip()


def _hash(value: Any, field: str) -> str:
    candidate = _text(value, field).lower()
    if candidate.startswith("sha256:"):
        candidate = candidate[7:]
    if not SHA256_RE.fullmatch(candidate):
        raise ManifestValidationError((f"{field} must be a SHA-256 hex digest",))
    return candidate


def _sha1(value: Any, field: str) -> str:
    candidate = _text(value, field).lower()
    if not SHA1_RE.fullmatch(candidate):
        raise ManifestValidationError((f"{field} must be a full Git commit SHA",))
    return candidate


def _string_list(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ManifestValidationError((f"{field} must be a list of strings",))
    values: list[str] = []
    errors: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            errors.append(f"{field}[{index}] must be a non-empty string")
        else:
            values.append(item.strip())
    if errors:
        raise ManifestValidationError(errors)
    return tuple(values)


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ManifestValidationError((f"{field} must be an object",))
    return value


def _exit_status(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ManifestValidationError((f"{field} must be a non-negative integer or null",))
    return value


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass(frozen=True)
class ArtifactFingerprint:
    path: str
    sha256: str
    role: str

    @classmethod
    def from_mapping(cls, value: Any, *, field: str = "artifact") -> "ArtifactFingerprint":
        item = _mapping(value, field)
        return cls(
            path=_text(item.get("path"), f"{field}.path"),
            sha256=_hash(item.get("sha256"), f"{field}.sha256"),
            role=_text(item.get("role", "release-artifact"), f"{field}.role"),
        )

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "role": self.role, "sha256": self.sha256}


@dataclass(frozen=True)
class EvidenceRef:
    path: str
    sha256: str
    description: str

    @classmethod
    def from_mapping(cls, value: Any, *, field: str = "evidence") -> "EvidenceRef":
        item = _mapping(value, field)
        return cls(
            path=_text(item.get("path"), f"{field}.path"),
            sha256=_hash(item.get("sha256"), f"{field}.sha256"),
            description=_text(item.get("description", "gate evidence"), f"{field}.description"),
        )

    def to_dict(self) -> dict[str, str]:
        return {"description": self.description, "path": self.path, "sha256": self.sha256}


@dataclass(frozen=True)
class ReviewerRef:
    reviewer_id: str
    kind: str
    name: str
    independent: bool

    @classmethod
    def from_mapping(cls, value: Any, *, field: str = "reviewer") -> "ReviewerRef":
        item = _mapping(value, field)
        reviewer_id = _text(item.get("reviewer_id", item.get("id")), f"{field}.reviewer_id")
        name = _text(item.get("name"), f"{field}.name")
        if name.lower() in {"tbd", "todo", "unknown", "anonymous", "fabricated"}:
            raise ManifestValidationError((f"{field}.name cannot be a placeholder",))
        kind = _text(item.get("kind"), f"{field}.kind").lower()
        independent = item.get("independent")
        if not isinstance(independent, bool):
            raise ManifestValidationError((f"{field}.independent must be boolean",))
        return cls(reviewer_id=reviewer_id, kind=kind, name=name, independent=independent)

    def to_dict(self) -> dict[str, object]:
        return {
            "independent": self.independent,
            "kind": self.kind,
            "name": self.name,
            "reviewer_id": self.reviewer_id,
        }


@dataclass(frozen=True)
class CommitBinding:
    commit_sha: str
    tree_sha: str
    checkout_fingerprint: str
    artifact_set_sha256: str
    clean_worktree: bool

    @classmethod
    def from_mapping(cls, value: Any, *, field: str = "commit_binding") -> "CommitBinding":
        item = _mapping(value, field)
        tree_sha = _sha1(item.get("tree_sha"), f"{field}.tree_sha")
        clean_worktree = item.get("clean_worktree")
        if not isinstance(clean_worktree, bool):
            raise ManifestValidationError((f"{field}.clean_worktree must be boolean",))
        return cls(
            commit_sha=_sha1(item.get("commit_sha"), f"{field}.commit_sha"),
            tree_sha=tree_sha,
            checkout_fingerprint=_hash(item.get("checkout_fingerprint"), f"{field}.checkout_fingerprint"),
            artifact_set_sha256=_hash(item.get("artifact_set_sha256"), f"{field}.artifact_set_sha256"),
            clean_worktree=clean_worktree,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "artifact_set_sha256": self.artifact_set_sha256,
            "checkout_fingerprint": self.checkout_fingerprint,
            "clean_worktree": self.clean_worktree,
            "commit_sha": self.commit_sha,
            "tree_sha": self.tree_sha,
        }


@dataclass(frozen=True)
class GateResult:
    gate_id: str
    commit_sha: str
    tree_sha: str
    artifact_hash: str
    command: tuple[str, ...]
    procedure: str
    environment: str
    timestamp: str
    exit_status: int | None
    result: GateStatus
    limitations: tuple[str, ...]
    reviewer: ReviewerRef
    evidence_paths: tuple[EvidenceRef, ...]

    @classmethod
    def from_mapping(cls, value: Any, *, field: str = "gate") -> "GateResult":
        item = _mapping(value, field)
        if "exit_status" not in item:
            raise ManifestValidationError((f"{field}.exit_status is required",))
        command = _string_list(item.get("command"), f"{field}.command")
        limitations = _string_list(item.get("limitations", ()), f"{field}.limitations")
        evidence = item.get("evidence_paths", item.get("evidence_path"))
        if not isinstance(evidence, Sequence) or isinstance(evidence, (str, bytes, bytearray)):
            raise ManifestValidationError((f"{field}.evidence_paths must be a list",))
        evidence_paths = tuple(
            EvidenceRef.from_mapping(entry, field=f"{field}.evidence_paths[{index}]")
            for index, entry in enumerate(evidence)
        )
        raw_result = item.get("result", item.get("status"))
        result = _text(raw_result, f"{field}.result").upper()
        raw_status = item.get("status")
        if raw_status is not None and _text(raw_status, f"{field}.status").upper() != result:
            raise ManifestValidationError((f"{field}.status and {field}.result disagree",))
        allowed = {"PASS", "FAIL", "BLOCKED_EXTERNAL", "NOT_RUN", "STALE", "INVALID"}
        if result not in allowed:
            raise ManifestValidationError((f"{field}.result has unsupported value {result!r}",))
        return cls(
            gate_id=_text(item.get("gate_id"), f"{field}.gate_id"),
            commit_sha=_sha1(item.get("commit_sha"), f"{field}.commit_sha"),
            tree_sha=_sha1(item.get("tree_sha"), f"{field}.tree_sha"),
            artifact_hash=_hash(item.get("artifact_hash"), f"{field}.artifact_hash"),
            command=command,
            procedure=_text(item.get("procedure"), f"{field}.procedure"),
            environment=_text(item.get("environment"), f"{field}.environment"),
            timestamp=_text(item.get("timestamp"), f"{field}.timestamp"),
            exit_status=_exit_status(item.get("exit_status"), f"{field}.exit_status"),
            result=result,  # type: ignore[arg-type]
            limitations=limitations,
            reviewer=ReviewerRef.from_mapping(item.get("reviewer"), field=f"{field}.reviewer"),
            evidence_paths=evidence_paths,
        )

    def to_dict(self) -> dict[str, object]:
        evidence = [item.to_dict() for item in self.evidence_paths]
        return {
            "artifact_hash": self.artifact_hash,
            "command": list(self.command),
            "commit_sha": self.commit_sha,
            "tree_sha": self.tree_sha,
            "environment": self.environment,
            "evidence_path": evidence,
            "evidence_paths": evidence,
            "gate_id": self.gate_id,
            "limitations": list(self.limitations),
            "procedure": self.procedure,
            "result": self.result,
            "status": self.result,
            "exit_status": self.exit_status,
            "reviewer": self.reviewer.to_dict(),
            "timestamp": self.timestamp,
        }


def artifact_set_digest(artifacts: Sequence[ArtifactFingerprint]) -> str:
    canonical = [item.to_dict() for item in sorted(artifacts, key=lambda item: (item.path, item.role))]
    return sha256(_canonical(canonical)).hexdigest()


@dataclass(frozen=True)
class ReleaseEvidenceManifest:
    schema_version: str
    manifest_id: str
    generated_at: str
    status: ManifestStatus
    commit_binding: CommitBinding
    artifacts: tuple[ArtifactFingerprint, ...]
    gates: tuple[GateResult, ...]
    reviewers: tuple[ReviewerRef, ...]
    limitations: tuple[str, ...]

    @classmethod
    def from_mapping(cls, value: Any) -> "ReleaseEvidenceManifest":
        item = _mapping(value, "manifest")
        errors: list[str] = []

        def parse_one(field: str, factory: Any, raw: Any) -> Any:
            try:
                return factory(raw, field=field)
            except ManifestValidationError as exc:
                errors.extend(exc.errors)
                return None

        schema_version = item.get("schema_version")
        if schema_version != MANIFEST_SCHEMA:
            errors.append(f"manifest.schema_version must be {MANIFEST_SCHEMA!r}")
        manifest_id = item.get("manifest_id")
        generated_at = item.get("generated_at")
        status = item.get("status")
        try:
            manifest_id = _text(manifest_id, "manifest.manifest_id")
        except ManifestValidationError as exc:
            errors.extend(exc.errors)
            manifest_id = ""
        try:
            generated_at = _text(generated_at, "manifest.generated_at")
        except ManifestValidationError as exc:
            errors.extend(exc.errors)
            generated_at = ""
        if not isinstance(status, str) or status.upper() not in {"PASS", "FAIL", "BLOCKED_EXTERNAL", "NOT_RUN"}:
            errors.append("manifest.status must be PASS, FAIL, BLOCKED_EXTERNAL or NOT_RUN")
            status = "NOT_RUN"
        else:
            status = status.upper()

        binding = parse_one("manifest.commit_binding", CommitBinding.from_mapping, item.get("commit_binding"))

        artifacts_raw = item.get("artifacts")
        artifacts: list[ArtifactFingerprint] = []
        if not isinstance(artifacts_raw, Sequence) or isinstance(artifacts_raw, (str, bytes, bytearray)):
            errors.append("manifest.artifacts must be a list")
        else:
            for index, raw in enumerate(artifacts_raw):
                parsed = parse_one(f"manifest.artifacts[{index}]", ArtifactFingerprint.from_mapping, raw)
                if parsed is not None:
                    artifacts.append(parsed)

        gates_raw = item.get("gates")
        gates: list[GateResult] = []
        if not isinstance(gates_raw, Sequence) or isinstance(gates_raw, (str, bytes, bytearray)):
            errors.append("manifest.gates must be a list")
        else:
            for index, raw in enumerate(gates_raw):
                parsed = parse_one(f"manifest.gates[{index}]", GateResult.from_mapping, raw)
                if parsed is not None:
                    gates.append(parsed)

        reviewers_raw = item.get("reviewers")
        reviewers: list[ReviewerRef] = []
        if not isinstance(reviewers_raw, Sequence) or isinstance(reviewers_raw, (str, bytes, bytearray)):
            errors.append("manifest.reviewers must be a list")
        else:
            for index, raw in enumerate(reviewers_raw):
                parsed = parse_one(f"manifest.reviewers[{index}]", ReviewerRef.from_mapping, raw)
                if parsed is not None:
                    reviewers.append(parsed)

        try:
            limitations = _string_list(item.get("limitations", ()), "manifest.limitations")
        except ManifestValidationError as exc:
            errors.extend(exc.errors)
            limitations = ()

        if errors:
            raise ManifestValidationError(errors)
        return cls(
            schema_version=MANIFEST_SCHEMA,
            manifest_id=manifest_id,
            generated_at=generated_at,
            status=status,  # type: ignore[arg-type]
            commit_binding=binding,
            artifacts=tuple(artifacts),
            gates=tuple(gates),
            reviewers=tuple(reviewers),
            limitations=limitations,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "artifacts": [item.to_dict() for item in self.artifacts],
            "commit_binding": self.commit_binding.to_dict(),
            "generated_at": self.generated_at,
            "gates": [item.to_dict() for item in self.gates],
            "limitations": list(self.limitations),
            "manifest_id": self.manifest_id,
            "reviewers": [item.to_dict() for item in self.reviewers],
            "schema_version": self.schema_version,
            "status": self.status,
        }

    def structural_errors(self) -> list[str]:
        errors: list[str] = []
        if not self.artifacts:
            errors.append("manifest must contain at least one artifact fingerprint")
        if not self.gates:
            errors.append("manifest must contain at least one gate result")
        present_gate_ids = {item.gate_id for item in self.gates}
        missing_gate_ids = [gate_id for gate_id in REQUIRED_GATES if gate_id not in present_gate_ids]
        if missing_gate_ids:
            errors.append(
                "manifest is missing mandatory gate results: " + ", ".join(missing_gate_ids)
            )
        if not self.reviewers:
            errors.append("manifest must contain at least one reviewer reference")
        if len({item.path for item in self.artifacts}) != len(self.artifacts):
            errors.append("artifact paths must be unique")
        if len({item.gate_id for item in self.gates}) != len(self.gates):
            errors.append("gate IDs must be unique")
        if len({item.reviewer_id for item in self.reviewers}) != len(self.reviewers):
            errors.append("reviewer IDs must be unique")
        expected_artifact_set = artifact_set_digest(self.artifacts)
        if self.commit_binding.artifact_set_sha256 != expected_artifact_set:
            errors.append("commit binding artifact_set_sha256 does not match artifact fingerprints")
        reviewers = {item.reviewer_id for item in self.reviewers}
        for gate in self.gates:
            if gate.commit_sha != self.commit_binding.commit_sha:
                errors.append(f"gate {gate.gate_id} is bound to the wrong commit")
            if gate.tree_sha != self.commit_binding.tree_sha:
                errors.append(f"gate {gate.gate_id} is bound to the wrong tree")
            if gate.reviewer.reviewer_id not in reviewers:
                errors.append(f"gate {gate.gate_id} references an undeclared reviewer")
            if gate.gate_id in {"independent-reviews", "final-go-no-go"} and gate.result == "PASS" and not gate.reviewer.independent:
                errors.append(
                    f"gate {gate.gate_id} PASS requires an independent reviewer; self-promotion is rejected"
                )
            if gate.artifact_hash != self.commit_binding.artifact_set_sha256:
                errors.append(f"gate {gate.gate_id} is bound to the wrong artifact hash")
            if not gate.command:
                errors.append(f"gate {gate.gate_id} has no command")
            if not gate.evidence_paths:
                errors.append(f"gate {gate.gate_id} has no evidence paths")
            if gate.result == "PASS" and gate.exit_status != 0:
                errors.append(f"gate {gate.gate_id} is PASS but exit_status is not zero")
            if gate.result != "PASS" and gate.exit_status == 0:
                errors.append(f"gate {gate.gate_id} is {gate.result} but exit_status is zero")
            if gate.result != "PASS" and not gate.limitations:
                errors.append(f"gate {gate.gate_id} must document limitations when result is {gate.result}")
        if self.status != "PASS" and all(item.result == "PASS" for item in self.gates):
            errors.append(f"manifest status is {self.status} even though every gate is PASS")
        return errors
