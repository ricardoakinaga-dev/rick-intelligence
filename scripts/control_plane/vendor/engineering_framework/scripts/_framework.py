#!/usr/bin/env python3
"""Shared standard-library primitives for engineering-framework validators.

All command-line tools use the same result contract:

* ``RESULT PASS``: all required checks passed, exit code 0.
* ``RESULT WARN``: required checks passed with explicit limitations, exit code 0.
* ``RESULT FAIL``: at least one required check failed, exit code 1.

The module deliberately contains mechanics, not framework policy. Normative enums,
required fields, transitions, and manifests are loaded from
``references/contracts.json``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Iterator, Mapping, Sequence
from urllib.parse import unquote, urlsplit


RESULT_LEVELS = ("PASS", "WARN", "FAIL")
EXIT_BY_RESULT = {"PASS": 0, "WARN": 0, "FAIL": 1}

IGNORED_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    ".venv",
    "venv",
    "node_modules",
    "build",
    "dist",
}
IGNORED_FILE_SUFFIXES = {".pyc", ".pyo", ".swp", ".tmp"}
OFFICIAL_EXTERNAL_HOSTS = {
    "developers.openai.com",
    "learn.chatgpt.com",
    "github.com",
    "openai.com",
    "platform.openai.com",
}
# Opaque integrity/version guard only. The digest carries no enum or workflow
# semantics; references/contracts.json remains the sole normative contract.
SUPPORTED_CONTRACT_FINGERPRINT = "9fe3e3e4b374c115f3a4a148ef40680d359f6798dec01e489f97a29e4a54b6ea"

CLASSIFICATION_ENUMS = {
    "project_profile": "project_profile",
    "work_mode": "work_mode",
    "lifecycle_stage": "lifecycle_stage",
    "activity": "activity",
    "engineering_tier": "engineering_tier",
    "risk_level": "risk_level",
    "blast_radius": "blast_radius",
    "work_status": "work_status",
}


@dataclass(frozen=True)
class Finding:
    level: str
    code: str
    message: str
    path: str | None = None

    def render(self) -> str:
        location = f" ({self.path})" if self.path else ""
        return f"[{self.level}] {self.code}: {self.message}{location}"


@dataclass
class Report:
    """Accumulates deterministic findings and computes one CLI result."""

    findings: list[Finding] = field(default_factory=list)

    def add(self, level: str, code: str, message: str, path: os.PathLike[str] | str | None = None) -> None:
        if level not in RESULT_LEVELS:
            raise ValueError(f"unsupported finding level: {level}")
        self.findings.append(Finding(level, code, message, str(path) if path is not None else None))

    def pass_(self, code: str, message: str, path: os.PathLike[str] | str | None = None) -> None:
        self.add("PASS", code, message, path)

    def warn(self, code: str, message: str, path: os.PathLike[str] | str | None = None) -> None:
        self.add("WARN", code, message, path)

    def fail(self, code: str, message: str, path: os.PathLike[str] | str | None = None) -> None:
        self.add("FAIL", code, message, path)

    def extend(self, other: "Report", prefix: str | None = None) -> None:
        for finding in other.findings:
            code = f"{prefix}.{finding.code}" if prefix else finding.code
            self.findings.append(Finding(finding.level, code, finding.message, finding.path))

    @property
    def result(self) -> str:
        if any(item.level == "FAIL" for item in self.findings):
            return "FAIL"
        if any(item.level == "WARN" for item in self.findings):
            return "WARN"
        return "PASS"

    @property
    def exit_code(self) -> int:
        return EXIT_BY_RESULT[self.result]

    def render(self, include_passes: bool = True) -> str:
        items = self.findings if include_passes else [item for item in self.findings if item.level != "PASS"]
        lines = [item.render() for item in items]
        counts = {level: sum(item.level == level for item in self.findings) for level in RESULT_LEVELS}
        lines.append(
            f"RESULT {self.result} "
            f"(pass={counts['PASS']} warn={counts['WARN']} fail={counts['FAIL']})"
        )
        return "\n".join(lines)


def emit(report: Report, *, include_passes: bool = True) -> int:
    """Print a report and return its stable exit code."""

    print(report.render(include_passes=include_passes))
    return report.exit_code


def script_root(script_file: str) -> Path:
    """Return the skill root from a script path, independent of the caller CWD."""

    return Path(script_file).resolve().parent.parent


def resolve_root(value: str | os.PathLike[str] | None, script_file: str) -> Path:
    candidate = Path(value).expanduser() if value is not None else script_root(script_file)
    candidate = candidate.resolve()
    if not candidate.is_dir():
        raise ValueError(f"root is not a directory: {candidate}")
    return candidate


def safe_relative_path(root: Path, value: str, *, field_name: str = "path") -> Path:
    """Resolve a repository-relative path without allowing traversal outside root."""

    raw = Path(value)
    if raw.is_absolute():
        raise ValueError(f"{field_name} must be relative: {value}")
    resolved = (root / raw).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"{field_name} escapes root: {value}") from exc
    return resolved


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle, object_pairs_hook=_unique_json_object)


def load_json_object(path: Path) -> dict[str, Any]:
    value = load_json(path)
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, 1):
            if not raw.strip():
                continue
            try:
                value = json.loads(raw, object_pairs_hook=_unique_json_object)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at {path}:{line_number}: {exc.msg}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"expected object at {path}:{line_number}")
            records.append(value)
    return records


def load_contracts(root: Path) -> dict[str, Any]:
    path = root / "references" / "contracts.json"
    if not path.is_file():
        raise ValueError(f"missing canonical contracts: {path}")
    value = load_json_object(path)
    fingerprint = hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if fingerprint != SUPPORTED_CONTRACT_FINGERPRINT:
        raise ValueError(
            "canonical contracts do not match the supported contract fingerprint; "
            "migrate the contract and validator together"
        )
    for key in (
        "framework",
        "enums",
        "mode_composition",
        "status_transitions",
        "lifecycle_transitions",
        "semantic_gates",
        "gate_required_criteria",
        "gate_criteria_allow_extensions",
        "gate_required_fields",
        "gate_criterion_required_fields",
        "gate_condition_required_fields",
        "authority_record_required_fields",
        "authority_evidence_record_required_fields",
        "authority_evidence_field_enums",
        "override_required_fields",
        "gate_field_enums",
        "gate_invariants",
        "gate_history_invariants",
        "override_invariants",
        "context_pack_fields",
        "runtime_state_schema_version",
        "backlog_schema_version",
        "runtime_state_required_fields",
        "runtime_state_nonempty_string_fields",
        "runtime_state_nullable_string_fields",
        "runtime_state_string_list_fields",
        "backlog_item_required_fields",
        "backlog_item_nonempty_string_fields",
        "next_action_required_fields",
        "next_action_nonempty_string_fields",
        "next_action_field_enums",
        "next_action_invariants",
        "execution_log_action_binding",
        "execution_log_required_fields",
        "execution_log_nonempty_string_fields",
        "execution_correction_required_fields",
        "verification_record_required_fields",
        "verification_record_field_enums",
        "verification_invariants",
        "eval_scenario_required_fields",
        "traceability_schema_version",
        "traceability_review_check_required_fields",
        "review_record_required_fields",
        "review_record_field_enums",
        "review_invariants",
        "tier_obligations",
        "execplan_invariants",
        "review_degradation_rules",
        "runtime_gate_rules",
        "runtime_classification_rules",
        "runtime_reconciliation_rules",
        "human_stop_triggers",
        "release_gate_invariants",
        "reference_manifest",
        "template_manifest",
    ):
        if key not in value:
            raise ValueError(f"contracts missing key: {key}")

    def require_object(name: str) -> dict[str, Any]:
        item = value[name]
        if not isinstance(item, dict):
            raise ValueError(f"contracts.{name} must be an object")
        return item

    missing_value = object()

    def require_string_list(
        name: str,
        item: Any = missing_value,
        *,
        allow_empty: bool = False,
        allow_blank: bool = False,
    ) -> list[str]:
        candidate = value[name] if item is missing_value else item
        if (
            not isinstance(candidate, list)
            or (not allow_empty and not candidate)
            or not all(
                isinstance(entry, str) and (allow_blank or bool(entry.strip()))
                for entry in candidate
            )
            or len(candidate) != len(set(candidate))
        ):
            qualifier = "a unique string list" if allow_empty else "a non-empty unique string list"
            raise ValueError(f"contracts.{name} must be {qualifier}")
        return candidate

    framework = require_object("framework")
    for field in ("name", "version"):
        if not isinstance(framework.get(field), str) or not framework[field].strip():
            raise ValueError(f"contracts.framework.{field} must be a non-empty string")
    if (
        not isinstance(framework.get("contract_version"), int)
        or isinstance(framework.get("contract_version"), bool)
        or framework["contract_version"] < 1
    ):
        raise ValueError("contracts.framework.contract_version must be a positive integer")

    required_enums = {
        "project_profile", "work_mode", "lifecycle_stage", "activity",
        "engineering_tier", "risk_level", "blast_radius", "work_status",
        "evidence_status", "claim_type", "confidence", "gate_criterion_status",
        "gate_status", "verification_status", "authority_state", "authority_subject_type", "condition_status",
        "override_status", "procedure_status", "evidence_kind", "evidence_freshness",
        "event_type", "review_independence", "next_action_kind",
    }
    enums = require_object("enums")
    if not required_enums.issubset(enums):
        raise ValueError(f"contracts.enums missing keys: {', '.join(sorted(required_enums - set(enums)))}")
    for name, entries in enums.items():
        require_string_list(f"enums.{name}", entries)

    list_sections = (
        "semantic_gates",
        "gate_required_fields",
        "gate_criterion_required_fields",
        "gate_condition_required_fields",
        "authority_record_required_fields",
        "authority_evidence_record_required_fields",
        "override_required_fields",
        "context_pack_fields",
        "runtime_state_required_fields",
        "runtime_state_nonempty_string_fields",
        "runtime_state_nullable_string_fields",
        "runtime_state_string_list_fields",
        "backlog_item_required_fields",
        "backlog_item_nonempty_string_fields",
        "next_action_required_fields",
        "next_action_nonempty_string_fields",
        "execution_log_required_fields",
        "execution_log_nonempty_string_fields",
        "execution_correction_required_fields",
        "verification_record_required_fields",
        "eval_scenario_required_fields",
        "traceability_review_check_required_fields",
        "review_record_required_fields",
        "human_stop_triggers",
        "reference_manifest",
        "template_manifest",
    )
    for name in list_sections:
        require_string_list(name)
    if value["traceability_schema_version"] != 2:
        raise ValueError("contracts.traceability_schema_version must be 2")
    review_field_enums = require_object("review_record_field_enums")
    expected_review_enum_fields = {
        "procedure_status": "procedure_status",
        "result": "verification_status",
        "freshness": "evidence_freshness",
        "independence": "review_independence",
    }
    if review_field_enums != expected_review_enum_fields:
        raise ValueError("contracts.review_record_field_enums must bind every typed review field")
    next_action_fields = set(value["next_action_required_fields"])
    expected_action_fields = {"id", "kind", "summary", "target", "completion_signal"}
    if next_action_fields != expected_action_fields:
        raise ValueError("contracts.next_action_required_fields must define the canonical action object")
    if set(value["next_action_nonempty_string_fields"]) != expected_action_fields:
        raise ValueError("contracts.next_action_nonempty_string_fields must cover every action field")
    next_action_field_enums = require_object("next_action_field_enums")
    if next_action_field_enums != {"kind": "next_action_kind"}:
        raise ValueError("contracts.next_action_field_enums must bind kind to next_action_kind")
    next_action_invariants = require_object("next_action_invariants")
    if next_action_invariants.get("allow_extensions") is not False:
        raise ValueError("contracts.next_action_invariants.allow_extensions must be false")
    for field in (
        "single_object_only",
        "id_must_be_task_scoped",
        "ids_must_be_unique",
        "text_fields_must_be_single_line",
        "active_task_requires_action_pointer",
        "inactive_state_forbids_action_pointer",
        "active_state_pointer_must_match_active_backlog_action",
    ):
        if next_action_invariants.get(field) is not True:
            raise ValueError(f"contracts.next_action_invariants.{field} must be true")
    action_suffix_pattern = next_action_invariants.get("id_suffix_pattern")
    if not isinstance(action_suffix_pattern, str) or not action_suffix_pattern.strip():
        raise ValueError("contracts.next_action_invariants.id_suffix_pattern must be non-empty")
    try:
        re.compile(f"^(?:{action_suffix_pattern})$")
    except re.error as exc:
        raise ValueError("contracts.next_action_invariants.id_suffix_pattern must compile") from exc
    boundary_characters = next_action_invariants.get("id_token_boundary_character_class")
    if not isinstance(boundary_characters, str) or not boundary_characters.strip():
        raise ValueError(
            "contracts.next_action_invariants.id_token_boundary_character_class must be non-empty"
        )
    try:
        re.compile(f"[{boundary_characters}]")
    except re.error as exc:
        raise ValueError(
            "contracts.next_action_invariants.id_token_boundary_character_class must compile"
        ) from exc
    boundary_categories = require_string_list(
        "next_action_invariants.id_token_boundary_unicode_categories",
        next_action_invariants.get("id_token_boundary_unicode_categories"),
    )
    if set(boundary_categories) != {"Mc", "Me", "Mn"}:
        raise ValueError(
            "contracts.next_action_invariants.id_token_boundary_unicode_categories must cover combining marks"
        )
    boundary_codepoints = require_string_list(
        "next_action_invariants.id_token_boundary_codepoints",
        next_action_invariants.get("id_token_boundary_codepoints"),
    )
    if set(boundary_codepoints) != {"\u200c", "\u200d"} or not all(
        len(item) == 1 for item in boundary_codepoints
    ):
        raise ValueError(
            "contracts.next_action_invariants.id_token_boundary_codepoints must cover one-code-point ZWNJ and ZWJ"
        )
    terminal_allowed = next_action_invariants.get("terminal_allowed_kinds")
    if not isinstance(terminal_allowed, dict) or set(terminal_allowed) != {"DONE", "CANCELLED"}:
        raise ValueError("contracts.next_action_invariants.terminal_allowed_kinds must cover DONE and CANCELLED")
    for status, kinds in terminal_allowed.items():
        entries = require_string_list(f"next_action_invariants.terminal_allowed_kinds.{status}", kinds)
        if set(entries) - set(enums["next_action_kind"]):
            raise ValueError("contracts.next_action_invariants.terminal_allowed_kinds contains unknown kinds")
    forbidden_active_kinds = require_string_list(
        "next_action_invariants.active_forbidden_kinds",
        next_action_invariants.get("active_forbidden_kinds"),
    )
    if set(forbidden_active_kinds) - set(enums["next_action_kind"]):
        raise ValueError("contracts.next_action_invariants.active_forbidden_kinds contains unknown kinds")
    release_invariants = require_object("release_gate_invariants")
    expected_release_fields = {
        "default_decision_paths",
        "explicit_decisions_replace_defaults",
        "doctor_required_result",
        "required_state_values",
        "empty_state_list_fields",
        "terminal_backlog_statuses",
        "require_clean_git_worktree",
        "require_exact_git_toplevel",
        "tag_prefix",
        "require_version_tag_at_head",
        "required_test_modules",
        "minimum_unit_tests",
        "unittest_discovery_start",
        "unit_runner_protocol",
        "unit_suite_timeout_seconds",
        "unit_runner_supported_platforms",
        "forbid_skipped_tests",
        "product_manifest_source",
        "product_manifest_include_modes",
        "product_manifest_forbid_symlinks",
        "comparison_roots_optional",
        "require_out_of_band_gate_digest",
        "require_out_of_band_manifest_digest",
        "trusted_digest_algorithm",
        "trusted_digest_source",
        "external_publication_not_proven",
    }
    if set(release_invariants) != expected_release_fields:
        raise ValueError("contracts.release_gate_invariants must define the exact release boundary")
    default_decisions = require_string_list(
        "release_gate_invariants.default_decision_paths",
        release_invariants.get("default_decision_paths"),
    )
    required_test_modules = require_string_list(
        "release_gate_invariants.required_test_modules",
        release_invariants.get("required_test_modules"),
    )
    empty_state_fields = require_string_list(
        "release_gate_invariants.empty_state_list_fields",
        release_invariants.get("empty_state_list_fields"),
    )
    terminal_backlog_statuses = require_string_list(
        "release_gate_invariants.terminal_backlog_statuses",
        release_invariants.get("terminal_backlog_statuses"),
    )
    for field, paths in (
        ("default_decision_paths", default_decisions),
        ("required_test_modules", required_test_modules),
    ):
        if any(Path(path).is_absolute() or ".." in Path(path).parts for path in paths):
            raise ValueError(
                f"contracts.release_gate_invariants.{field} must contain safe relative paths"
            )
    if any(
        not path.startswith("tests/test_") or not path.endswith(".py")
        for path in required_test_modules
    ):
        raise ValueError(
            "contracts.release_gate_invariants.required_test_modules must name tests/test_*.py files"
        )
    if set(empty_state_fields) - set(value["runtime_state_string_list_fields"]):
        raise ValueError(
            "contracts.release_gate_invariants.empty_state_list_fields must name runtime string-list fields"
        )
    if set(terminal_backlog_statuses) != {"DONE", "CANCELLED"}:
        raise ValueError(
            "contracts.release_gate_invariants.terminal_backlog_statuses must be DONE and CANCELLED"
        )
    required_state_values = release_invariants.get("required_state_values")
    if not isinstance(required_state_values, dict) or required_state_values != {
        "status": "DONE",
        "verification_state": "PASS",
        "active_task": None,
        "active_action_id": None,
    }:
        raise ValueError(
            "contracts.release_gate_invariants.required_state_values must define the terminal release state"
        )
    for field in (
        "explicit_decisions_replace_defaults",
        "require_clean_git_worktree",
        "require_exact_git_toplevel",
        "require_version_tag_at_head",
        "forbid_skipped_tests",
        "product_manifest_include_modes",
        "product_manifest_forbid_symlinks",
        "comparison_roots_optional",
        "require_out_of_band_gate_digest",
        "require_out_of_band_manifest_digest",
        "external_publication_not_proven",
    ):
        if release_invariants.get(field) is not True:
            raise ValueError(f"contracts.release_gate_invariants.{field} must be true")
    if release_invariants.get("doctor_required_result") != "PASS":
        raise ValueError("contracts.release_gate_invariants.doctor_required_result must be PASS")
    if release_invariants.get("product_manifest_source") != "git_index_paths_and_worktree_bytes":
        raise ValueError(
            "contracts.release_gate_invariants.product_manifest_source must bind Git-index paths to worktree bytes"
        )
    if release_invariants.get("trusted_digest_algorithm") != "SHA256":
        raise ValueError("contracts.release_gate_invariants.trusted_digest_algorithm must be SHA256")
    if release_invariants.get("trusted_digest_source") != "OUT_OF_BAND_RELEASE_AUTHORITY":
        raise ValueError(
            "contracts.release_gate_invariants.trusted_digest_source must be OUT_OF_BAND_RELEASE_AUTHORITY"
        )
    tag_prefix = release_invariants.get("tag_prefix")
    if not isinstance(tag_prefix, str) or not tag_prefix.strip():
        raise ValueError("contracts.release_gate_invariants.tag_prefix must be non-empty")
    if release_invariants.get("unittest_discovery_start") != "tests":
        raise ValueError("contracts.release_gate_invariants.unittest_discovery_start must be tests")
    unit_runner_protocol = release_invariants.get("unit_runner_protocol")
    if not isinstance(unit_runner_protocol, str) or not unit_runner_protocol.strip():
        raise ValueError("contracts.release_gate_invariants.unit_runner_protocol must be non-empty")
    unit_suite_timeout = release_invariants.get("unit_suite_timeout_seconds")
    if (
        not isinstance(unit_suite_timeout, int)
        or isinstance(unit_suite_timeout, bool)
        or unit_suite_timeout < 1
        or unit_suite_timeout > 3600
    ):
        raise ValueError(
            "contracts.release_gate_invariants.unit_suite_timeout_seconds must be an integer from 1 through 3600"
        )
    supported_platforms = release_invariants.get("unit_runner_supported_platforms")
    if supported_platforms != ["linux"]:
        raise ValueError(
            "contracts.release_gate_invariants.unit_runner_supported_platforms must be exactly ['linux']"
        )
    minimum_unit_tests = release_invariants.get("minimum_unit_tests")
    if (
        not isinstance(minimum_unit_tests, int)
        or isinstance(minimum_unit_tests, bool)
        or minimum_unit_tests < 1
    ):
        raise ValueError("contracts.release_gate_invariants.minimum_unit_tests must be positive")
    review_invariants = require_object("review_invariants")
    if not isinstance(review_invariants.get("ledger_path"), str) or not review_invariants["ledger_path"].strip():
        raise ValueError("contracts.review_invariants.ledger_path must be non-empty")
    for field in (
        "target_requires_exact_fragment",
        "subject_must_include_requirement_id",
        "source_refs_must_exactly_cover_evidence_targets",
        "independent_reviewer_must_not_be_producer",
        "evidence_refs_must_resolve",
        "ledger_is_append_ordered",
        "latest_record_owns_review_status",
        "latest_record_owns_subject_status",
        "supersedes_must_reference_prior_same_review_id",
    ):
        if review_invariants.get(field) is not True:
            raise ValueError(f"contracts.review_invariants.{field} must be true")
    mandatory_contract_fields = {
        "gate_condition_required_fields": {"due_at"},
        "authority_evidence_record_required_fields": {"subject_type", "subject_id"},
        "override_required_fields": {"expires_at"},
    }
    for section, required_fields in mandatory_contract_fields.items():
        missing_fields = required_fields - set(value[section])
        if missing_fields:
            raise ValueError(
                f"contracts.{section} missing safety fields: {', '.join(sorted(missing_fields))}"
            )
    for name in ("runtime_state_schema_version", "backlog_schema_version"):
        if not isinstance(value[name], int) or isinstance(value[name], bool) or value[name] < 1:
            raise ValueError(f"contracts.{name} must be a positive integer")

    gate_criteria = require_object("gate_required_criteria")
    if set(gate_criteria) != set(value["semantic_gates"]):
        raise ValueError("contracts.gate_required_criteria keys must exactly match semantic_gates")
    all_criterion_ids: list[str] = []
    for gate_id, criterion_ids in gate_criteria.items():
        all_criterion_ids.extend(
            require_string_list(f"gate_required_criteria.{gate_id}", criterion_ids)
        )
    if len(all_criterion_ids) != len(set(all_criterion_ids)):
        raise ValueError("contracts.gate_required_criteria IDs must be globally unique")
    if not isinstance(value["gate_criteria_allow_extensions"], bool):
        raise ValueError("contracts.gate_criteria_allow_extensions must be boolean")

    for section, enum_name in (
        ("status_transitions", "work_status"),
        ("lifecycle_transitions", "lifecycle_stage"),
    ):
        transitions = require_object(section)
        expected_keys = set(enums[enum_name])
        if set(transitions) != expected_keys:
            raise ValueError(f"contracts.{section} keys must exactly match enums.{enum_name}")
        for source, targets in transitions.items():
            entries = require_string_list(f"{section}.{source}", targets, allow_empty=True)
            invalid = sorted(set(entries) - expected_keys)
            if invalid:
                raise ValueError(f"contracts.{section}.{source} has unknown targets: {', '.join(invalid)}")

    composition = require_object("mode_composition")
    for field in ("primary_field", "overlay_field", "value_enum"):
        if not isinstance(composition.get(field), str) or not composition[field].strip():
            raise ValueError(f"contracts.mode_composition.{field} must be a non-empty string")
    if composition["value_enum"] not in enums:
        raise ValueError("contracts.mode_composition.value_enum must name a canonical enum")
    require_string_list(
        "mode_composition.forbidden_overlay_values",
        composition.get("forbidden_overlay_values"),
        allow_empty=True,
    )
    if not isinstance(composition.get("rules"), dict) or not isinstance(composition.get("example"), dict):
        raise ValueError("contracts.mode_composition rules and example must be objects")

    object_sections = (
        "gate_field_enums",
        "gate_invariants",
        "gate_history_invariants",
        "override_invariants",
        "verification_record_field_enums",
        "authority_evidence_field_enums",
        "verification_invariants",
        "execution_log_action_binding",
        "execplan_invariants",
        "review_degradation_rules",
        "runtime_gate_rules",
        "runtime_classification_rules",
        "runtime_reconciliation_rules",
    )
    objects = {name: require_object(name) for name in object_sections}
    for section in (
        "gate_field_enums",
        "verification_record_field_enums",
        "authority_evidence_field_enums",
    ):
        for field, enum_name in objects[section].items():
            if (
                not isinstance(field, str)
                or not field.strip()
                or not isinstance(enum_name, str)
                or enum_name not in enums
            ):
                raise ValueError(f"contracts.{section} must map non-empty field names to canonical enum names")
    required_field_enum_keys = {
        "gate_field_enums": {
            "decision", "confidence", "residual_risk", "criteria.status",
            "criteria.confidence", "conditions.status", "conditions.residual_risk",
            "conditions.authority_state", "authority.state", "override.status",
            "override.risk_level", "override.residual_risk",
        },
        "verification_record_field_enums": {
            "result", "procedure_status", "evidence_kind", "freshness",
        },
        "authority_evidence_field_enums": {"status", "subject_type"},
    }
    for section, required_fields in required_field_enum_keys.items():
        if not required_fields.issubset(objects[section]):
            raise ValueError(
                f"contracts.{section} missing field bindings: "
                f"{', '.join(sorted(required_fields - set(objects[section])))}"
            )

    tier_obligations = require_object("tier_obligations")
    tier_names = set(enums["engineering_tier"])
    if set(tier_obligations) != tier_names:
        raise ValueError("contracts.tier_obligations keys must exactly match enums.engineering_tier")
    for tier, obligations in tier_obligations.items():
        if not isinstance(obligations, dict):
            raise ValueError(f"contracts.tier_obligations.{tier} must be an object")
        if not isinstance(obligations.get("minimum_review"), str) or not obligations["minimum_review"].strip():
            raise ValueError(f"contracts.tier_obligations.{tier}.minimum_review must be a non-empty string")
        require_string_list(
            f"tier_obligations.{tier}.minimum_evidence",
            obligations.get("minimum_evidence"),
        )
        for field, item in obligations.items():
            if field not in {"minimum_review", "minimum_evidence"} and not isinstance(item, bool):
                raise ValueError(f"contracts.tier_obligations.{tier}.{field} must be boolean")

    invariant_lists = {
        "gate_invariants": (
            "pass_decisions",
            "required_criterion_pass_statuses",
            "blocking_criterion_statuses",
            "open_condition_forbidden_residual_risks",
            "passing_gate_forbidden_residual_risks",
            "passing_gate_residual_risk_requiring_confirmed_authority",
            "criterion_nonempty_fields",
            "gates_requiring_typed_verification_evidence",
            "confirmed_authority_placeholder_values",
            "terminal_condition_statuses_requiring_evidence",
        ),
        "override_invariants": (
            "eligible_active_types",
            "entry_authorizing_types",
            "entry_authorizing_gate_decisions",
            "entry_authorizing_criterion_statuses",
            "active_forbidden_residual_risks",
            "active_forbidden_risk_levels",
            "active_risk_levels_requiring_confirmed_authority",
            "terminal_override_statuses_requiring_evidence",
        ),
        "verification_invariants": (
            "pass_allowed_evidence_kinds",
            "pass_evidence_kinds_requiring_zero_exit_status",
            "pass_evidence_kinds_allowing_null_exit_status",
        ),
        "execplan_invariants": ("required_sections",),
        "runtime_gate_rules": (
            "tiers_requiring_stage_entry_gate",
            "activities_requiring_entry_gate",
            "required_entry_gate_decisions",
            "passing_verification_state_required_gate_ids",
            "risk_severity_order",
        ),
        "runtime_reconciliation_rules": (
            "active_backlog_statuses",
            "statuses_requiring_declared_transition",
        ),
        "runtime_classification_rules": ("unknown_axis_safe_activities",),
    }
    for section, fields in invariant_lists.items():
        for field in fields:
            require_string_list(
                f"{section}.{field}",
                objects[section].get(field),
                allow_blank=(section, field)
                == ("gate_invariants", "confirmed_authority_placeholder_values"),
            )

    constrained_lists = {
        ("gate_invariants", "pass_decisions"): set(enums["gate_status"]),
        ("gate_invariants", "required_criterion_pass_statuses"): set(enums["gate_criterion_status"]),
        ("gate_invariants", "blocking_criterion_statuses"): set(enums["gate_criterion_status"]),
        ("gate_invariants", "open_condition_forbidden_residual_risks"): set(enums["risk_level"]),
        ("gate_invariants", "passing_gate_forbidden_residual_risks"): set(enums["risk_level"]),
        ("gate_invariants", "passing_gate_residual_risk_requiring_confirmed_authority"): set(enums["risk_level"]),
        ("gate_invariants", "criterion_nonempty_fields"): set(value["gate_criterion_required_fields"]),
        ("gate_invariants", "gates_requiring_typed_verification_evidence"): set(value["semantic_gates"]),
        ("gate_invariants", "terminal_condition_statuses_requiring_evidence"): set(enums["condition_status"]),
        ("override_invariants", "eligible_active_types"): set(enums["work_mode"]),
        ("override_invariants", "entry_authorizing_types"): set(enums["work_mode"]),
        ("override_invariants", "entry_authorizing_gate_decisions"): set(enums["gate_status"]),
        ("override_invariants", "entry_authorizing_criterion_statuses"): set(enums["gate_criterion_status"]),
        ("override_invariants", "active_forbidden_residual_risks"): set(enums["risk_level"]),
        ("override_invariants", "active_forbidden_risk_levels"): set(enums["risk_level"]),
        ("override_invariants", "active_risk_levels_requiring_confirmed_authority"): set(enums["risk_level"]),
        ("override_invariants", "terminal_override_statuses_requiring_evidence"): set(enums["override_status"]),
        ("verification_invariants", "pass_allowed_evidence_kinds"): set(enums["evidence_kind"]),
        ("verification_invariants", "pass_evidence_kinds_requiring_zero_exit_status"): set(enums["evidence_kind"]),
        ("verification_invariants", "pass_evidence_kinds_allowing_null_exit_status"): set(enums["evidence_kind"]),
        ("runtime_gate_rules", "tiers_requiring_stage_entry_gate"): set(enums["engineering_tier"]),
        ("runtime_gate_rules", "activities_requiring_entry_gate"): set(enums["activity"]),
        ("runtime_gate_rules", "required_entry_gate_decisions"): set(enums["gate_status"]),
        ("runtime_gate_rules", "passing_verification_state_required_gate_ids"): set(value["semantic_gates"]),
        ("runtime_gate_rules", "risk_severity_order"): set(enums["risk_level"]),
        ("runtime_reconciliation_rules", "active_backlog_statuses"): set(enums["work_status"]),
        ("runtime_reconciliation_rules", "statuses_requiring_declared_transition"): set(enums["work_status"]),
        ("runtime_classification_rules", "unknown_axis_safe_activities"): set(enums["activity"]),
    }
    for (section, field), allowed_values in constrained_lists.items():
        entries = objects[section][field]
        invalid = sorted(set(entries) - allowed_values)
        if invalid:
            raise ValueError(
                f"contracts.{section}.{field} contains unknown values: {', '.join(invalid)}"
            )

    verification_rules = objects["verification_invariants"]
    pass_kinds = set(verification_rules["pass_allowed_evidence_kinds"])
    zero_exit_kinds = set(verification_rules["pass_evidence_kinds_requiring_zero_exit_status"])
    null_exit_kinds = set(verification_rules["pass_evidence_kinds_allowing_null_exit_status"])
    if zero_exit_kinds & null_exit_kinds:
        raise ValueError(
            "contracts.verification_invariants PASS exit-status evidence-kind lists must be disjoint"
        )
    if zero_exit_kinds | null_exit_kinds != pass_kinds:
        raise ValueError(
            "contracts.verification_invariants PASS exit-status evidence-kind lists must exactly partition pass_allowed_evidence_kinds"
        )
    if "COMMAND" not in zero_exit_kinds:
        raise ValueError(
            "contracts.verification_invariants COMMAND PASS evidence must require exit_status=0"
        )

    execplan_rules = objects["execplan_invariants"]
    for field in (
        "required_path_prefix",
        "required_path_suffix",
        "current_action_marker_prefix",
        "current_action_marker_suffix",
    ):
        if not isinstance(execplan_rules.get(field), str) or not execplan_rules[field].strip():
            raise ValueError(f"contracts.execplan_invariants.{field} must be non-empty")
    if Path(execplan_rules["required_path_prefix"]).is_absolute():
        raise ValueError("contracts.execplan_invariants.required_path_prefix must be relative")
    if execplan_rules.get("forbid_unresolved_template_tokens") is not True:
        raise ValueError("contracts.execplan_invariants.forbid_unresolved_template_tokens must be true")
    minimum_body = execplan_rules.get("minimum_section_body_characters")
    if not isinstance(minimum_body, int) or isinstance(minimum_body, bool) or minimum_body < 1:
        raise ValueError("contracts.execplan_invariants.minimum_section_body_characters must be positive")
    for field in (
        "required_section_headings_visible_only",
        "required_section_headings_unique",
        "progress_requires_timestamped_checkbox",
        "milestones_require_level_three_heading",
        "concrete_steps_require_numbered_list",
        "concrete_steps_numbered_list_uses_visible_scanner",
        "current_action_marker_required",
        "first_concrete_step_requires_action_id",
        "first_concrete_step_requires_canonical_index",
        "visible_markdown_excludes_html_comments",
        "visible_markdown_excludes_fenced_code",
        "first_concrete_step_body_ends_at_next_ordered_item",
        "first_concrete_step_body_includes_nested_items",
        "first_concrete_step_must_match_marker",
        "first_concrete_step_forbids_other_action_ids",
        "inactive_state_allows_historical_action_references",
    ):
        if execplan_rules.get(field) is not True:
            raise ValueError(f"contracts.execplan_invariants.{field} must be true")
    if execplan_rules.get("first_concrete_step_canonical_delimiter") != ".":
        raise ValueError(
            "contracts.execplan_invariants.first_concrete_step_canonical_delimiter must be '.'"
        )
    ordered_delimiters = require_string_list(
        "execplan_invariants.ordered_list_delimiters",
        execplan_rules.get("ordered_list_delimiters"),
    )
    if set(ordered_delimiters) != {".", ")"}:
        raise ValueError(
            "contracts.execplan_invariants.ordered_list_delimiters must cover '.' and ')'"
        )
    for field, expected in (
        ("ordered_list_max_leading_spaces", 3),
        ("ordered_list_max_digits", 9),
    ):
        if execplan_rules.get(field) != expected:
            raise ValueError(f"contracts.execplan_invariants.{field} must be {expected}")

    log_action_rules = objects["execution_log_action_binding"]
    if log_action_rules.get("field") != "active_action_id":
        raise ValueError("contracts.execution_log_action_binding.field must be active_action_id")
    for field in (
        "tail_requires_field",
        "tail_must_match_state",
        "tail_task_must_match_active_task",
        "inactive_tail_requires_null",
    ):
        if log_action_rules.get(field) is not True:
            raise ValueError(f"contracts.execution_log_action_binding.{field} must be true")
    authoritative_log_fields = require_string_list(
        "execution_log_action_binding.tail_authoritative_text_fields",
        log_action_rules.get("tail_authoritative_text_fields"),
    )
    if set(authoritative_log_fields) - set(value["execution_log_nonempty_string_fields"]):
        raise ValueError(
            "contracts.execution_log_action_binding.tail_authoritative_text_fields must name "
            "required non-empty execution fields"
        )

    invalid_overlay_values = sorted(
        set(composition["forbidden_overlay_values"]) - set(enums["work_mode"])
    )
    if invalid_overlay_values:
        raise ValueError(
            "contracts.mode_composition.forbidden_overlay_values contains unknown values: "
            + ", ".join(invalid_overlay_values)
        )

    invalidating_event_types = require_string_list(
        "runtime_reconciliation_rules.verification_invalidating_event_types",
        objects["runtime_reconciliation_rules"].get("verification_invalidating_event_types"),
    )
    unknown_invalidators = sorted(set(invalidating_event_types) - set(enums["event_type"]))
    if unknown_invalidators:
        raise ValueError(
            "contracts.runtime_reconciliation_rules.verification_invalidating_event_types "
            f"contains unknown event types: {', '.join(unknown_invalidators)}"
        )

    reconciliation = objects["runtime_reconciliation_rules"]
    for field in (
        "active_task_status_must_match_state",
        "declared_log_transitions_must_match_current_records",
        "done_requires_cited_current_pass_verification",
        "done_forbids_latest_nonpass_verification",
        "done_requires_complete_transition",
        "done_complete_must_not_predate_cited_pass",
        "done_state_requires_verification_pass",
        "done_state_forbids_blockers",
        "done_state_forbids_pending_human_approval",
        "correction_requires_latest_task_transition",
        "control_ledgers_must_not_postdate_state",
    ):
        if reconciliation.get(field) is not True:
            raise ValueError(f"contracts.runtime_reconciliation_rules.{field} must be true")
    expected_transition_statuses = set(enums["work_status"]) - {"TODO", "UNKNOWN"}
    if set(reconciliation["statuses_requiring_declared_transition"]) != expected_transition_statuses:
        raise ValueError(
            "contracts.runtime_reconciliation_rules.statuses_requiring_declared_transition "
            "must include every non-initial work status except UNKNOWN"
        )
    if (
        reconciliation.get("done_complete_status_from") != "VERIFY"
        or reconciliation.get("done_complete_status_to") != "DONE"
    ):
        raise ValueError(
            "contracts.runtime_reconciliation_rules DONE completion must be VERIFY -> DONE"
        )
    for field in (
        "correction_event_type",
        "correction_target_field",
        "correction_effective_type_field",
        "correction_reason_field",
    ):
        if not isinstance(reconciliation.get(field), str) or not reconciliation[field].strip():
            raise ValueError(f"contracts.runtime_reconciliation_rules.{field} must be non-empty")
    if reconciliation["correction_event_type"] not in enums["event_type"]:
        raise ValueError("contracts.runtime_reconciliation_rules.correction_event_type must be canonical")

    mandatory_true_flags = {
        "gate_invariants": (
            "open_conditions_require_future_due_at",
            "confirmed_authority_requires_latest_subject_decision",
            "terminal_nonresolution_conditions_remain_blocking",
            "saved_gate_requires_nonempty_revalidation_triggers",
        ),
        "override_invariants": (
            "active_requires_future_expires_at",
            "active_type_must_match_runtime_mode",
            "active_expiry_rechecked_against_state",
            "terminal_nonresolution_overrides_remain_blocking",
            "entry_requires_deferred_criterion",
            "entry_requires_nonempty_evidence_refs",
            "entry_requires_confirmed_authority",
            "entry_requires_override_event_after_gate_decision",
            "active_requires_bound_override_event",
        ),
        "runtime_gate_rules": (
            "due_open_conditions_reopen_current_gate",
            "confirmed_authority_must_remain_current",
            "referenced_and_obligation_gates_require_bound_events",
            "gate_event_must_be_strictly_later",
            "gate_reopen_requires_new_superseding_record",
            "legacy_gate_requires_superseding_record",
            "referenced_applicable_gate_decision_governs_all_tiers",
            "current_applicable_gate_cannot_be_hidden_by_pointer",
            "referenced_gate_residual_risk_cannot_exceed_runtime_risk",
            "active_obligation_risk_cannot_exceed_runtime_risk",
        ),
        "gate_history_invariants": (
            "condition_and_override_ids_are_stable_within_scope",
            "condition_and_override_updates_require_later_timestamp",
        ),
        "verification_invariants": (
            "applicable_evidence_requires_task_binding",
            "ledger_is_append_ordered",
            "latest_record_owns_effective_freshness",
            "later_nonpass_invalidates_prior_pass",
        ),
    }
    for section, fields in mandatory_true_flags.items():
        for field in fields:
            if objects[section].get(field) is not True:
                raise ValueError(f"contracts.{section}.{field} must be true")

    override_rules = objects["override_invariants"]
    for field in (
        "override_event_type",
        "override_event_id_field",
        "override_event_fingerprint_field",
        "override_event_required_result",
    ):
        if not isinstance(override_rules.get(field), str) or not override_rules[field].strip():
            raise ValueError(f"contracts.override_invariants.{field} must be non-empty")
    if override_rules["override_event_type"] not in enums["event_type"]:
        raise ValueError("contracts.override_invariants.override_event_type must be canonical")

    authority_states = objects["gate_invariants"].get("authority_states_by_required")
    if not isinstance(authority_states, dict) or set(authority_states) != {"false", "true"}:
        raise ValueError("contracts.gate_invariants.authority_states_by_required must map false and true")
    for required, states in authority_states.items():
        entries = require_string_list(f"gate_invariants.authority_states_by_required.{required}", states)
        invalid = sorted(set(entries) - set(enums["authority_state"]))
        if invalid:
            raise ValueError(
                "contracts.gate_invariants.authority_states_by_required contains unknown states: "
                + ", ".join(invalid)
            )
    runtime_gate = objects["runtime_gate_rules"]
    if runtime_gate["risk_severity_order"] != ["LOW", "MEDIUM", "HIGH", "CRITICAL"]:
        raise ValueError(
            "contracts.runtime_gate_rules.risk_severity_order must be LOW, MEDIUM, HIGH, CRITICAL"
        )
    if not isinstance(runtime_gate.get("stage_entry_gates"), dict) or not runtime_gate["stage_entry_gates"]:
        raise ValueError("contracts.runtime_gate_rules.stage_entry_gates must be a non-empty object")
    for stage, gate in runtime_gate["stage_entry_gates"].items():
        if stage not in enums["lifecycle_stage"] or gate not in value["semantic_gates"]:
            raise ValueError("contracts.runtime_gate_rules.stage_entry_gates contains an unknown stage or gate")
    for field in (
        "record_ref_field",
        "verification_ledger_path",
        "authority_ledger_path",
        "gate_event_source_field",
        "gate_event_record_id_field",
        "gate_event_decision_field",
        "gate_event_fingerprint_field",
        "legacy_gate_recovery_event_type",
        "legacy_gate_recovery_state_field",
        "legacy_gate_recovery_state_value",
        "legacy_gate_event_id_field",
        "gate_reopen_event_type",
    ):
        if not isinstance(runtime_gate.get(field), str) or not runtime_gate[field].strip():
            raise ValueError(f"contracts.runtime_gate_rules.{field} must be a non-empty string")
    legacy_missing = require_string_list(
        "runtime_gate_rules.legacy_gate_allowed_missing_fields",
        runtime_gate.get("legacy_gate_allowed_missing_fields"),
    )
    if set(legacy_missing) - set(value["gate_required_fields"]):
        raise ValueError(
            "contracts.runtime_gate_rules.legacy_gate_allowed_missing_fields must name gate fields"
        )
    if runtime_gate["legacy_gate_recovery_event_type"] not in enums["event_type"]:
        raise ValueError(
            "contracts.runtime_gate_rules.legacy_gate_recovery_event_type must be canonical"
        )
    gate_lifecycle_types = require_string_list(
        "runtime_gate_rules.gate_lifecycle_event_types",
        runtime_gate.get("gate_lifecycle_event_types"),
    )
    if set(gate_lifecycle_types) - set(enums["event_type"]):
        raise ValueError("contracts.runtime_gate_rules.gate_lifecycle_event_types must be canonical")
    if runtime_gate["gate_reopen_event_type"] not in gate_lifecycle_types:
        raise ValueError("contracts.runtime_gate_rules.gate_reopen_event_type must be a lifecycle event")
    gate_event_types = runtime_gate.get("gate_event_types_by_decision")
    if not isinstance(gate_event_types, dict) or set(gate_event_types) != set(enums["gate_status"]):
        raise ValueError(
            "contracts.runtime_gate_rules.gate_event_types_by_decision must map every gate_status"
        )
    for decision, event_types in gate_event_types.items():
        entries = require_string_list(
            f"runtime_gate_rules.gate_event_types_by_decision.{decision}", event_types
        )
        if set(entries) - set(enums["event_type"]):
            raise ValueError(
                "contracts.runtime_gate_rules.gate_event_types_by_decision contains an unknown event type"
            )
    gate_event_results = runtime_gate.get("gate_event_results_by_decision")
    if not isinstance(gate_event_results, dict) or set(gate_event_results) != set(enums["gate_status"]):
        raise ValueError(
            "contracts.runtime_gate_rules.gate_event_results_by_decision must map every gate_status"
        )
    for decision, results in gate_event_results.items():
        require_string_list(
            f"runtime_gate_rules.gate_event_results_by_decision.{decision}", results
        )

    runtime_classification = objects["runtime_classification_rules"]
    for field in (
        "unknown_classification_forbids_material_activity",
        "unknown_status_requires_no_active_task",
    ):
        if runtime_classification.get(field) is not True:
            raise ValueError(f"contracts.runtime_classification_rules.{field} must be true")
    tier_values = enums["engineering_tier"]
    for field, enum_name in (
        ("minimum_tier_by_risk", "risk_level"),
        ("minimum_tier_by_blast_radius", "blast_radius"),
    ):
        mapping = runtime_classification.get(field)
        if not isinstance(mapping, dict) or set(mapping) != set(enums[enum_name]):
            raise ValueError(
                f"contracts.runtime_classification_rules.{field} must map every canonical {enum_name}"
            )
        if any(value not in tier_values for value in mapping.values()):
            raise ValueError(
                f"contracts.runtime_classification_rules.{field} contains an unknown engineering tier"
            )
    allowed_stages = runtime_classification.get("activity_allowed_stages")
    if not isinstance(allowed_stages, dict) or not allowed_stages:
        raise ValueError(
            "contracts.runtime_classification_rules.activity_allowed_stages must be a non-empty object"
        )
    for activity, stages in allowed_stages.items():
        if activity not in enums["activity"]:
            raise ValueError(
                "contracts.runtime_classification_rules.activity_allowed_stages contains an unknown activity"
            )
        entries = require_string_list(
            f"runtime_classification_rules.activity_allowed_stages.{activity}", stages
        )
        if set(entries) - set(enums["lifecycle_stage"]):
            raise ValueError(
                "contracts.runtime_classification_rules.activity_allowed_stages contains an unknown lifecycle stage"
            )
    activity_gates = runtime_classification.get("activity_entry_gates")
    if not isinstance(activity_gates, dict) or not activity_gates:
        raise ValueError(
            "contracts.runtime_classification_rules.activity_entry_gates must be a non-empty object"
        )
    for activity, gate in activity_gates.items():
        if activity not in allowed_stages or gate not in value["semantic_gates"]:
            raise ValueError(
                "contracts.runtime_classification_rules.activity_entry_gates contains an unknown activity or gate"
            )
    return value


def is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def require_fields(value: Mapping[str, Any], fields: Sequence[str]) -> list[str]:
    return [name for name in fields if name not in value]


def enum_values(contracts: Mapping[str, Any], name: str) -> set[str]:
    enums = contracts.get("enums", {})
    values = enums.get(name, []) if isinstance(enums, Mapping) else []
    return {str(value) for value in values}


def classification_invariant_violations(
    classification: Mapping[str, Any], contracts: Mapping[str, Any]
) -> list[str]:
    """Return canonical cross-axis violations for a plain classification mapping."""

    violations: list[str] = []
    rules = contracts.get("runtime_classification_rules", {})
    tier_order = list(contracts.get("enums", {}).get("engineering_tier", []))
    tier = classification.get("engineering_tier")
    if isinstance(tier, str) and tier in tier_order and tier != "UNKNOWN":
        selected_rank = tier_order.index(tier)
        for axis, mapping_field in (
            ("risk_level", "minimum_tier_by_risk"),
            ("blast_radius", "minimum_tier_by_blast_radius"),
        ):
            value = classification.get(axis)
            mapping = rules.get(mapping_field, {})
            minimum = (
                mapping.get(value)
                if isinstance(mapping, Mapping) and isinstance(value, str)
                else None
            )
            if isinstance(minimum, str) and minimum in tier_order and selected_rank < tier_order.index(minimum):
                violations.append(
                    f"{axis}={value} requires engineering_tier {minimum} or higher, not {tier}"
                )

    activity = classification.get("activity")
    stage = classification.get("lifecycle_stage")
    allowed_by_activity = rules.get("activity_allowed_stages", {})
    allowed_stages = (
        allowed_by_activity.get(activity)
        if isinstance(activity, str) and isinstance(allowed_by_activity, Mapping)
        else None
    )
    if isinstance(allowed_stages, list) and isinstance(stage, str) and stage not in allowed_stages:
        violations.append(
            f"activity={activity} requires lifecycle_stage in {allowed_stages}, not {stage}"
        )
    unknown_axes = [
        axis
        for axis in (
            "project_profile",
            "work_mode",
            "work_mode_overlays",
            "lifecycle_stage",
            "activity",
            "engineering_tier",
            "risk_level",
            "blast_radius",
        )
        if classification.get(axis) == "UNKNOWN"
    ]
    safe_activities = set(rules.get("unknown_axis_safe_activities", []))
    if (
        unknown_axes
        and rules.get("unknown_classification_forbids_material_activity")
        and (not isinstance(activity, str) or activity not in safe_activities)
    ):
        violations.append(
            f"unresolved axes {unknown_axes} forbid material activity {activity!r}"
        )
    return violations


def parse_iso8601(value: Any) -> datetime | None:
    if not is_nonempty_string(value):
        return None
    text = str(value)
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def parse_scalar(value: str) -> Any:
    stripped = value.strip()
    if stripped.startswith(("[", "{")):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON collection value: {value!r}") from exc
    lowered = stripped.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none"}:
        return None
    if re.fullmatch(r"-?\d+", stripped):
        return int(stripped)
    return stripped


def assign_dotted(target: dict[str, Any], dotted_key: str, value: Any) -> None:
    if not dotted_key or any(not part for part in dotted_key.split(".")):
        raise ValueError(f"invalid dotted key: {dotted_key!r}")
    cursor = target
    parts = dotted_key.split(".")
    for part in parts[:-1]:
        existing = cursor.setdefault(part, {})
        if not isinstance(existing, dict):
            raise ValueError(f"key collides with scalar: {dotted_key}")
        cursor = existing
    cursor[parts[-1]] = value


def dotted_get(source: Mapping[str, Any], dotted_key: str, default: Any = None) -> Any:
    cursor: Any = source
    for part in dotted_key.split("."):
        if not isinstance(cursor, Mapping) or part not in cursor:
            return default
        cursor = cursor[part]
    return cursor


def parse_frontmatter(path: Path) -> dict[str, str]:
    """Parse the simple top-level scalar fields used by SKILL.md frontmatter.

    This is intentionally not a general YAML parser. It rejects nested or
    collection values for required top-level metadata instead of silently
    accepting syntax it cannot validate with the standard library.
    """

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("missing opening YAML frontmatter delimiter")
    try:
        end = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration as exc:
        raise ValueError("missing closing YAML frontmatter delimiter") from exc
    result: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#") or line[:1].isspace():
            continue
        match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)", line)
        if not match:
            raise ValueError(f"unsupported frontmatter line: {line!r}")
        key, raw = match.groups()
        value = raw.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        result[key] = value
    return result


def iter_files(root: Path, suffixes: set[str] | None = None) -> Iterator[Path]:
    """Yield repository files while excluding metadata, caches, and build output."""

    for current, directories, files in os.walk(root):
        directories[:] = sorted(name for name in directories if name not in IGNORED_DIR_NAMES)
        for filename in sorted(files):
            path = Path(current) / filename
            if path.suffix in IGNORED_FILE_SUFFIXES:
                continue
            if suffixes is not None and path.suffix.lower() not in suffixes:
                continue
            yield path


MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
HTML_HREF_RE = re.compile(r"\bhref=[\"']([^\"']+)[\"']", re.IGNORECASE)


def markdown_links(text: str) -> Iterator[str]:
    for match in MARKDOWN_LINK_RE.finditer(text):
        raw = match.group(1).strip()
        if raw.startswith("<") and raw.endswith(">"):
            raw = raw[1:-1]
        elif " " in raw and not raw.startswith(("http://", "https://")):
            raw = raw.split(" ", 1)[0]
        yield raw
    for match in HTML_HREF_RE.finditer(text):
        yield match.group(1).strip()


def markdown_anchor(text: str) -> str:
    value = text.strip().lower()
    value = re.sub(r"[`*_~]", "", value)
    value = re.sub(r"[^\w\- ]", "", value, flags=re.UNICODE)
    value = re.sub(r"\s+", "-", value)
    return value.strip("-")


def markdown_anchors(path: Path) -> set[str]:
    anchors: set[str] = set()
    duplicates: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        if not match:
            continue
        base = markdown_anchor(match.group(1))
        if not base:
            continue
        count = duplicates.get(base, 0)
        anchors.add(base if count == 0 else f"{base}-{count}")
        duplicates[base] = count + 1
    return anchors


def classify_link(link: str) -> tuple[str, str, str]:
    """Return (kind, path, fragment) for a Markdown link."""

    parsed = urlsplit(link)
    if parsed.scheme in {"http", "https"}:
        host = (parsed.hostname or "").lower()
        return ("official-external" if host in OFFICIAL_EXTERNAL_HOSTS else "external", link, parsed.fragment)
    if parsed.scheme or link.startswith("//"):
        return ("external", link, parsed.fragment)
    return ("internal", unquote(parsed.path), unquote(parsed.fragment))


def unique_duplicates(values: Iterable[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def relative_display(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def cli_failure(code: str, message: str) -> int:
    report = Report()
    report.fail(code, message)
    return emit(report)


def main_guard(function: Any) -> None:
    """Run a CLI main while converting broken pipes into conventional success."""

    try:
        raise SystemExit(function())
    except BrokenPipeError:
        try:
            sys.stdout.close()
        finally:
            raise SystemExit(0)
