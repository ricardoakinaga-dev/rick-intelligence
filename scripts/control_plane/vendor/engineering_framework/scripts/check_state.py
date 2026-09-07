#!/usr/bin/env python3
"""Validate canonical runtime state, backlog, log, and verification records.

The checker validates canonical required fields/enums, backlog transitions when
events declare ``status_from``/``status_to``, dependency integrity, append-log
ordering, evidence claims, and reconciliation signals between the four stores.
It never rewrites inconsistent state.

Result contract: ``RESULT PASS|WARN|FAIL``. PASS/WARN exit 0; FAIL exits 1.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from typing import Any, Mapping

try:
    from ._framework import (
        Report,
        classification_invariant_violations,
        classify_link,
        enum_values,
        emit,
        is_nonempty_string,
        load_contracts,
        load_json,
        load_json_object,
        load_jsonl,
        markdown_anchors,
        parse_iso8601,
        require_fields,
        resolve_root,
        safe_relative_path,
        unique_duplicates,
    )
except ImportError:
    from _framework import (
        Report,
        classification_invariant_violations,
        classify_link,
        enum_values,
        emit,
        is_nonempty_string,
        load_contracts,
        load_json,
        load_json_object,
        load_jsonl,
        markdown_anchors,
        parse_iso8601,
        require_fields,
        resolve_root,
        safe_relative_path,
        unique_duplicates,
    )


STATE_ENUM_FIELDS = {
    "project_profile": "project_profile",
    "work_mode": "work_mode",
    "lifecycle_stage": "lifecycle_stage",
    "active_activity": "activity",
    "engineering_tier": "engineering_tier",
    "risk_level": "risk_level",
    "blast_radius": "blast_radius",
    "status": "work_status",
    "verification_state": "verification_status",
}
BACKLOG_ENUM_FIELDS = {"stage": "lifecycle_stage", "status": "work_status"}
FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]


def _check_evidence_ref(
    root: Path,
    value: Any,
    report: Report,
    *,
    code: str,
    field: str,
    allow_directory: bool = False,
) -> None:
    """Validate an evidence reference without dereferencing external records."""

    if not is_nonempty_string(value):
        report.fail(code, f"{field} must be a non-empty repository path or external URI")
        return
    kind, target_text, fragment = classify_link(str(value))
    if kind != "internal":
        return
    if not target_text:
        report.fail(code, f"{field} internal reference must include a path")
        return
    try:
        target = safe_relative_path(root, target_text, field_name=field)
    except ValueError as exc:
        report.fail(code, str(exc))
        return
    exists = target.exists() if allow_directory else target.is_file()
    if not exists:
        expected = "path" if allow_directory else "file"
        report.fail(code, f"{field} does not resolve to an existing {expected}: {value}")
        return
    if fragment and target.is_file():
        try:
            if target.suffix.lower() == ".md":
                matched = fragment in markdown_anchors(target)
            elif target.suffix.lower() == ".jsonl":
                records = load_jsonl(target)
                matched = any(
                    fragment in {str(record.get(key)) for key in ("id", "event_id", "record_id")}
                    for record in records
                )
            elif target.suffix.lower() == ".json":
                payload = load_json(target)

                def contains_id(node: Any) -> bool:
                    if isinstance(node, Mapping):
                        if fragment in {str(node.get(key)) for key in ("id", "event_id", "record_id")}:
                            return True
                        return any(contains_id(item) for item in node.values())
                    if isinstance(node, list):
                        return any(contains_id(item) for item in node)
                    return False

                matched = contains_id(payload)
            else:
                matched = False
        except (OSError, UnicodeError, ValueError):
            matched = False
        if not matched:
            report.fail(code, f"{field} fragment does not resolve inside evidence target: {value}")


def _check_evidence_refs(
    root: Path,
    value: Any,
    report: Report,
    *,
    code: str,
    field: str,
    allow_directory: bool = False,
) -> None:
    if not isinstance(value, list):
        report.fail(code, f"{field} must be a list")
        return
    for index, reference in enumerate(value):
        _check_evidence_ref(
            root,
            reference,
            report,
            code=code,
            field=f"{field}[{index}]",
            allow_directory=allow_directory,
        )


def _read_artifacts(root: Path, report: Report) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[dict[str, Any]] | None, list[dict[str, Any]] | None]:
    state_path = root / ".agent" / "state.json"
    backlog_path = root / ".agent" / "backlog.json"
    log_path = root / ".agent" / "execution-log.jsonl"
    verification_path = root / ".agent" / "verification.jsonl"
    loaded: list[Any] = []
    for code, path, loader in (
        ("STATE_JSON", state_path, load_json_object),
        ("BACKLOG_JSON", backlog_path, load_json_object),
        ("EXECUTION_LOG", log_path, load_jsonl),
        ("VERIFICATION_LOG", verification_path, load_jsonl),
    ):
        if not path.is_file():
            report.fail(code, "canonical artifact is missing", path.relative_to(root))
            loaded.append(None)
            continue
        try:
            loaded.append(loader(path))
            report.pass_(code, "artifact parses", path.relative_to(root))
        except (OSError, UnicodeError, ValueError) as exc:
            report.fail(code, str(exc), path.relative_to(root))
            loaded.append(None)
    return loaded[0], loaded[1], loaded[2], loaded[3]


def _check_enum(report: Report, contracts: Mapping[str, Any], value: Any, enum_name: str, code: str, field: str) -> None:
    allowed = enum_values(contracts, enum_name)
    if not isinstance(value, str) or value not in allowed:
        report.fail(code, f"{field}={value!r} is not in canonical {enum_name}: {sorted(allowed)}")


def _check_mode_composition(state: Mapping[str, Any], contracts: Mapping[str, Any], report: Report) -> None:
    composition = contracts.get("mode_composition", {})
    primary_field = composition.get("primary_field", "work_mode")
    overlay_field = composition.get("overlay_field", "work_mode_overlays")
    primary = state.get(primary_field)
    overlays = state.get(overlay_field)
    if not isinstance(overlays, list) or not all(isinstance(item, str) for item in overlays):
        report.fail("STATE_MODE_COMPOSITION", f"{overlay_field} must be a string list")
        return
    allowed = enum_values(contracts, str(composition.get("value_enum", "work_mode")))
    invalid = sorted(set(overlays) - allowed)
    if invalid:
        report.fail("STATE_MODE_COMPOSITION", f"invalid overlays: {invalid}")
    if len(overlays) != len(set(overlays)):
        report.fail("STATE_MODE_COMPOSITION", "work_mode_overlays must be unique")
    if primary in overlays:
        report.fail("STATE_MODE_COMPOSITION", "primary work_mode must not repeat as an overlay")
    forbidden = set(composition.get("forbidden_overlay_values", [])) & set(overlays)
    if forbidden:
        report.fail("STATE_MODE_COMPOSITION", f"non-operative overlays are forbidden: {sorted(forbidden)}")


def _same_task_action_suffixes(
    text: str,
    *,
    task_id: str,
    rules: Mapping[str, Any],
) -> set[str]:
    """Return boundary-delimited canonical action suffixes for exactly one task."""

    suffix_pattern = rules.get("id_suffix_pattern", r"[A-Z][A-Z0-9._-]*")
    boundary_characters = rules.get(
        "id_token_boundary_character_class", r"A-Za-z0-9._-"
    )
    boundary_categories = rules.get("id_token_boundary_unicode_categories", [])
    boundary_codepoints = rules.get("id_token_boundary_codepoints", [])
    if (
        not isinstance(suffix_pattern, str)
        or not isinstance(boundary_characters, str)
        or not isinstance(boundary_categories, list)
        or not all(isinstance(item, str) for item in boundary_categories)
        or not isinstance(boundary_codepoints, list)
        or not all(isinstance(item, str) and len(item) == 1 for item in boundary_codepoints)
    ):
        return set()
    boundary_pattern = re.compile(rf"[{boundary_characters}]")

    def continues_token(character: str) -> bool:
        return bool(
            boundary_pattern.fullmatch(character)
            or unicodedata.category(character) in boundary_categories
            or character in boundary_codepoints
        )

    suffixes: set[str] = set()
    for match in re.finditer(rf"{re.escape(task_id)}:({suffix_pattern})", text):
        if match.start() > 0 and continues_token(text[match.start() - 1]):
            continue
        if match.end() < len(text) and continues_token(text[match.end()]):
            continue
        suffixes.add(match.group(1))
    return suffixes


def _without_html_comments(line: str, in_comment: bool) -> tuple[str, bool]:
    """Remove HTML comment spans from one line while retaining visible text."""

    visible: list[str] = []
    cursor = 0
    while cursor < len(line):
        if in_comment:
            end = line.find("-->", cursor)
            if end < 0:
                return "".join(visible), True
            cursor = end + 3
            in_comment = False
            continue
        start = line.find("<!--", cursor)
        if start < 0:
            visible.append(line[cursor:])
            break
        visible.append(line[cursor:start])
        cursor = start + 4
        in_comment = True
    return "".join(visible), in_comment


def _visible_markdown_lines(
    markdown: str,
    rules: Mapping[str, Any],
) -> list[str]:
    """Return visible lines after bounded HTML-comment and fence exclusion."""

    max_spaces = rules.get("ordered_list_max_leading_spaces", 3)
    if not isinstance(max_spaces, int) or isinstance(max_spaces, bool):
        return []
    fence_pattern = re.compile(rf"^ {{0,{max_spaces}}}(`{{3,}}|~{{3,}})")
    visible_lines: list[str] = []
    in_comment = False
    fence_character: str | None = None
    fence_length = 0
    for raw_line in markdown.splitlines():
        if fence_character is not None:
            closing = re.compile(
                rf"^ {{0,{max_spaces}}}{re.escape(fence_character)}"
                rf"{{{fence_length},}}[ \t]*$"
            )
            if closing.fullmatch(raw_line):
                fence_character = None
                fence_length = 0
            continue
        if not in_comment:
            raw_fence = fence_pattern.match(raw_line)
            if raw_fence is not None:
                fence_character = raw_fence.group(1)[0]
                fence_length = len(raw_fence.group(1))
                continue
        visible_line, in_comment = _without_html_comments(raw_line, in_comment)
        fence = fence_pattern.match(visible_line)
        if fence is not None:
            fence_character = fence.group(1)[0]
            fence_length = len(fence.group(1))
            continue
        visible_lines.append(visible_line)
    return visible_lines


def _visible_execplan_sections(
    markdown: str,
    rules: Mapping[str, Any],
) -> tuple[dict[str, list[str]], dict[str, int]]:
    """Extract visible level-two sections and retain heading multiplicity."""

    sections: dict[str, list[str]] = {}
    heading_counts: dict[str, int] = {}
    current_section: str | None = None
    for line in _visible_markdown_lines(markdown, rules):
        if line.startswith("## ") and line[3:].strip():
            current_section = line[3:].strip()
            heading_counts[current_section] = heading_counts.get(current_section, 0) + 1
            sections.setdefault(current_section, [])
        elif current_section is not None:
            sections[current_section].append(line)
    return sections, heading_counts


def _first_visible_markdown_ordered_item(
    markdown: str,
    rules: Mapping[str, Any],
) -> tuple[str, str, str, str] | None:
    """Find the first visible ordered item and its body through the next item."""

    max_spaces = rules.get("ordered_list_max_leading_spaces", 3)
    max_digits = rules.get("ordered_list_max_digits", 9)
    delimiters = rules.get("ordered_list_delimiters", [".", ")"])
    if (
        not isinstance(max_spaces, int)
        or isinstance(max_spaces, bool)
        or not isinstance(max_digits, int)
        or isinstance(max_digits, bool)
        or not isinstance(delimiters, list)
        or not all(isinstance(item, str) and len(item) == 1 for item in delimiters)
    ):
        return None
    delimiter_class = re.escape("".join(delimiters))
    item_pattern = re.compile(
        rf"^( {{0,{max_spaces}}})([0-9]{{1,{max_digits}}})([{delimiter_class}])[ \t]+(.*)$"
    )
    visible_lines = _visible_markdown_lines(markdown, rules)
    for index, visible_line in enumerate(visible_lines):
        item = item_pattern.match(visible_line)
        if item is not None:
            item_indent = len(item.group(1))
            body_lines = [item.group(4)]
            for continuation in visible_lines[index + 1 :]:
                next_item = item_pattern.match(continuation)
                if next_item is not None and len(next_item.group(1)) <= item_indent:
                    break
                body_lines.append(continuation)
            return (
                item.group(2),
                item.group(3),
                item.group(4),
                "\n".join(body_lines),
            )
    return None


def _visible_execplan_action_markers(
    markdown: str,
    *,
    prefix: str,
    suffix: str,
    rules: Mapping[str, Any],
) -> list[str]:
    """Find exact action marker lines outside outer comments and fenced code."""

    max_spaces = rules.get("ordered_list_max_leading_spaces", 3)
    if not isinstance(max_spaces, int) or isinstance(max_spaces, bool):
        return []
    marker_pattern = re.compile(
        rf"^{re.escape(prefix)}([^\r\n]+){re.escape(suffix)}$"
    )
    fence_pattern = re.compile(rf"^ {{0,{max_spaces}}}(`{{3,}}|~{{3,}})")
    markers: list[str] = []
    in_comment = False
    fence_character: str | None = None
    fence_length = 0
    for raw_line in markdown.splitlines():
        if fence_character is not None:
            closing = re.compile(
                rf"^ {{0,{max_spaces}}}{re.escape(fence_character)}{{{fence_length},}}[ \t]*$"
            )
            if closing.fullmatch(raw_line):
                fence_character = None
                fence_length = 0
            continue
        if in_comment:
            _, in_comment = _without_html_comments(raw_line, True)
            continue
        marker = marker_pattern.fullmatch(raw_line)
        if marker is not None:
            markers.append(marker.group(1))
            continue
        raw_fence = fence_pattern.match(raw_line)
        if raw_fence is not None:
            fence_character = raw_fence.group(1)[0]
            fence_length = len(raw_fence.group(1))
            continue
        visible_line, in_comment = _without_html_comments(raw_line, False)
        fence = fence_pattern.match(visible_line)
        if fence is not None:
            fence_character = fence.group(1)[0]
            fence_length = len(fence.group(1))
    return markers


def _validate_next_action(
    value: Any,
    *,
    task_id: str,
    status: Any,
    contracts: Mapping[str, Any],
    report: Report,
) -> str | None:
    """Validate one backlog-owned action without interpreting natural language."""

    prefix = f"{task_id}.next_action"
    rules = contracts.get("next_action_invariants", {})
    if not isinstance(value, Mapping):
        report.fail("BACKLOG_ACTION", f"{prefix} must be one structured action object")
        return None
    required = set(contracts.get("next_action_required_fields", []))
    missing = sorted(required - set(value))
    if missing:
        report.fail("BACKLOG_ACTION", f"{prefix} is missing {', '.join(missing)}")
    if rules.get("allow_extensions") is False:
        extra = sorted(set(value) - required)
        if extra:
            report.fail("BACKLOG_ACTION", f"{prefix} has unsupported fields: {', '.join(extra)}")
    for field in contracts.get("next_action_nonempty_string_fields", []):
        candidate = value.get(field)
        if not is_nonempty_string(candidate):
            report.fail("BACKLOG_ACTION", f"{prefix}.{field} must be a non-empty string")
        elif rules.get("text_fields_must_be_single_line") and ("\n" in candidate or "\r" in candidate):
            report.fail("BACKLOG_ACTION", f"{prefix}.{field} must be a single line")
    for field, enum_name in contracts.get("next_action_field_enums", {}).items():
        if field in value:
            _check_enum(
                report,
                contracts,
                value[field],
                str(enum_name),
                "BACKLOG_ACTION",
                f"{prefix}.{field}",
            )
    action_id = value.get("id")
    if is_nonempty_string(action_id) and rules.get("id_must_be_task_scoped"):
        action_suffix = action_id[len(task_id) + 1 :] if action_id.startswith(f"{task_id}:") else ""
        suffix_pattern = rules.get("id_suffix_pattern", r"[A-Z][A-Z0-9._-]*")
        if (
            not action_suffix
            or not isinstance(suffix_pattern, str)
            or re.fullmatch(suffix_pattern, action_suffix) is None
        ):
            report.fail(
                "BACKLOG_ACTION",
                f"{prefix}.id must be scoped as {task_id}:<STABLE-ID>",
            )
    allowed_by_status = rules.get("terminal_allowed_kinds", {})
    allowed_kinds = (
        allowed_by_status.get(status)
        if isinstance(allowed_by_status, Mapping) and isinstance(status, str)
        else None
    )
    if isinstance(allowed_kinds, list) and value.get("kind") not in allowed_kinds:
        report.fail(
            "BACKLOG_ACTION",
            f"{prefix}.kind must be one of {allowed_kinds} when status={status}",
        )
    active_statuses = set(contracts.get("runtime_reconciliation_rules", {}).get("active_backlog_statuses", []))
    forbidden_active_kinds = set(rules.get("active_forbidden_kinds", []))
    kind = value.get("kind")
    if (
        isinstance(status, str)
        and status in active_statuses
        and isinstance(kind, str)
        and kind in forbidden_active_kinds
    ):
        report.fail(
            "BACKLOG_ACTION",
            f"{prefix}.kind={kind} cannot drive active work",
        )
    return str(action_id) if is_nonempty_string(action_id) else None


def _check_state(root: Path, state: Mapping[str, Any], contracts: Mapping[str, Any], report: Report) -> None:
    missing = require_fields(state, contracts["runtime_state_required_fields"])
    if missing:
        report.fail("STATE_FIELDS", f"missing required fields: {', '.join(missing)}")
    else:
        report.pass_("STATE_FIELDS", "all canonical runtime fields are present")
    schema_version = state.get("schema_version")
    supported_schema = contracts.get("runtime_state_schema_version")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != supported_schema
    ):
        report.fail("STATE_SCHEMA", f"schema_version must equal supported version {supported_schema}")
    for field in contracts.get("runtime_state_nonempty_string_fields", []):
        if not is_nonempty_string(state.get(field)):
            report.fail("STATE_VALUE", f"{field} must be a non-empty string")
    for field in contracts.get("runtime_state_nullable_string_fields", []):
        value = state.get(field)
        if value is not None and not is_nonempty_string(value):
            report.fail("STATE_VALUE", f"{field} must be null or a non-empty string")
    for field in contracts.get("runtime_state_string_list_fields", []):
        value = state.get(field)
        if (
            not isinstance(value, list)
            or not all(is_nonempty_string(item) for item in value)
            or len(value) != len(set(value))
        ):
            report.fail("STATE_COLLECTION", f"{field} must be a unique list of non-empty strings")
    for field, enum_name in STATE_ENUM_FIELDS.items():
        if field in state:
            _check_enum(report, contracts, state[field], enum_name, "STATE_ENUM", field)
    _check_mode_composition(state, contracts, report)
    _check_runtime_classification(state, contracts, report)
    if state.get("next_gate") not in contracts.get("semantic_gates", []):
        report.fail("STATE_GATE", f"unknown next_gate: {state.get('next_gate')!r}")
    action_rules = contracts.get("next_action_invariants", {})
    active_task = state.get("active_task")
    active_action_id = state.get("active_action_id")
    if (
        action_rules.get("active_task_requires_action_pointer")
        and is_nonempty_string(active_task)
        and not is_nonempty_string(active_action_id)
    ):
        report.fail("STATE_ACTION", "an active_task requires a non-empty active_action_id")
    if (
        action_rules.get("inactive_state_forbids_action_pointer")
        and active_task is None
        and active_action_id is not None
    ):
        report.fail("STATE_ACTION", "active_action_id must be null when active_task is null")
    if (
        action_rules.get("id_must_be_task_scoped")
        and is_nonempty_string(active_task)
        and is_nonempty_string(active_action_id)
        and not active_action_id.startswith(f"{active_task}:")
    ):
        report.fail("STATE_ACTION", f"active_action_id must be scoped to active_task {active_task}")
    if (
        not isinstance(state.get("state_revision"), int)
        or isinstance(state.get("state_revision"), bool)
        or state.get("state_revision", 0) < 1
    ):
        report.fail("STATE_REVISION", "state_revision must be a positive integer")
    if parse_iso8601(state.get("updated_at")) is None:
        report.fail("STATE_TIMESTAMP", "updated_at must be ISO-8601 with timezone")
    for field in ("active_execplan",):
        value = state.get(field)
        if is_nonempty_string(value):
            try:
                target = safe_relative_path(root, value, field_name=field)
            except ValueError as exc:
                report.fail("STATE_REFERENCE", str(exc))
            else:
                if not target.is_file():
                    report.fail("STATE_REFERENCE", f"{field} target does not exist: {value}")
    if state.get("status") == "BLOCKED" and not state.get("blocked_by"):
        report.fail(
            "STATE_BLOCKER",
            "status=BLOCKED requires at least one concrete blocked_by reason or dependency",
        )
    reconciliation_rules = contracts.get("runtime_reconciliation_rules", {})
    if state.get("status") == "DONE":
        if reconciliation_rules.get("done_state_forbids_blockers") and state.get("blocked_by"):
            report.fail("STATE_DONE_PENDING", "status=DONE forbids unresolved blocked_by entries")
        if (
            reconciliation_rules.get("done_state_forbids_pending_human_approval")
            and state.get("human_approval_required")
        ):
            report.fail(
                "STATE_DONE_PENDING",
                "status=DONE forbids pending human_approval_required entries",
            )
    tier = state.get("engineering_tier")
    tier_rules = contracts.get("tier_obligations", {}).get(tier, {}) if isinstance(tier, str) else {}
    if (
        (isinstance(tier_rules, Mapping) and tier_rules.get("execplan") is True)
        or is_nonempty_string(state.get("active_execplan"))
    ):
        active_execplan = state.get("active_execplan")
        if not is_nonempty_string(active_execplan):
            report.fail("STATE_EXECPLAN_REQUIRED", f"{tier} requires a resolvable active_execplan")
        else:
            execplan_rules = contracts.get("execplan_invariants", {})
            normalized = Path(str(active_execplan)).as_posix()
            prefix = str(execplan_rules.get("required_path_prefix", ".agent/plans/"))
            suffix = str(execplan_rules.get("required_path_suffix", ".md"))
            if not normalized.startswith(prefix) or not normalized.endswith(suffix):
                report.fail(
                    "STATE_EXECPLAN_REQUIRED",
                    f"{tier} active_execplan must match {prefix}*{suffix}",
                )
            else:
                try:
                    plan_path = safe_relative_path(root, normalized, field_name="active_execplan")
                    plan_text = plan_path.read_text(encoding="utf-8")
                except (OSError, UnicodeError, ValueError) as exc:
                    report.fail("STATE_EXECPLAN_REQUIRED", f"cannot inspect active ExecPlan: {exc}")
                else:
                    section_lines, heading_counts = _visible_execplan_sections(
                        plan_text,
                        execplan_rules,
                    )
                    headings = set(section_lines)
                    missing_sections = [
                        section
                        for section in execplan_rules.get("required_sections", [])
                        if section not in headings
                    ]
                    if missing_sections:
                        report.fail(
                            "STATE_EXECPLAN_REQUIRED",
                            "active ExecPlan is missing required sections: "
                            + ", ".join(missing_sections),
                        )
                    if execplan_rules.get("required_section_headings_unique"):
                        duplicate_sections = sorted(
                            section
                            for section in execplan_rules.get("required_sections", [])
                            if heading_counts.get(section, 0) > 1
                        )
                        if duplicate_sections:
                            report.fail(
                                "STATE_EXECPLAN_REQUIRED",
                                "active ExecPlan has duplicate visible required sections: "
                                + ", ".join(duplicate_sections),
                            )
                    minimum_body = execplan_rules.get("minimum_section_body_characters", 1)
                    empty_sections = [
                        section
                        for section in execplan_rules.get("required_sections", [])
                        if section in section_lines
                        and len("\n".join(section_lines[section]).strip()) < minimum_body
                    ]
                    if empty_sections:
                        report.fail(
                            "STATE_EXECPLAN_REQUIRED",
                            "active ExecPlan has empty or non-substantive sections: "
                            + ", ".join(empty_sections),
                        )
                    progress = "\n".join(section_lines.get("Progress", []))
                    if (
                        execplan_rules.get("progress_requires_timestamped_checkbox")
                        and not re.search(
                            r"(?m)^-\s+\[(?: |x|X|~)\]\s+\([^\n)]*\d{4}-\d{2}-\d{2}[^\n)]*\)\s+\S",
                            progress,
                        )
                    ):
                        report.fail(
                            "STATE_EXECPLAN_REQUIRED",
                            "active ExecPlan Progress requires a timestamped checkbox entry",
                        )
                    milestones = "\n".join(section_lines.get("Milestones", []))
                    if (
                        execplan_rules.get("milestones_require_level_three_heading")
                        and not re.search(r"(?m)^###\s+\S", milestones)
                    ):
                        report.fail(
                            "STATE_EXECPLAN_REQUIRED",
                            "active ExecPlan Milestones requires at least one named milestone",
                        )
                    concrete_steps = "\n".join(section_lines.get("Concrete Steps", []))
                    first_step_item = _first_visible_markdown_ordered_item(
                        concrete_steps,
                        execplan_rules,
                    )
                    if (
                        execplan_rules.get("concrete_steps_require_numbered_list")
                        and first_step_item is None
                    ):
                        report.fail(
                            "STATE_EXECPLAN_REQUIRED",
                            "active ExecPlan Concrete Steps requires at least one visible ordered step",
                        )
                    marker_prefix = str(execplan_rules.get("current_action_marker_prefix", ""))
                    marker_suffix = str(execplan_rules.get("current_action_marker_suffix", ""))
                    action_markers = _visible_execplan_action_markers(
                        plan_text,
                        prefix=marker_prefix,
                        suffix=marker_suffix,
                        rules=execplan_rules,
                    )
                    expected_action = (
                        str(state.get("active_action_id"))
                        if is_nonempty_string(state.get("active_action_id"))
                        else "NONE"
                    )
                    has_active_task = is_nonempty_string(state.get("active_task"))
                    if (
                        has_active_task
                        and execplan_rules.get("current_action_marker_required")
                        and action_markers != [expected_action]
                    ):
                        report.fail(
                            "STATE_EXECPLAN_ACTION",
                            "active ExecPlan must contain exactly one current-action marker matching "
                            f"state.active_action_id ({expected_action})",
                        )
                    first_step_index = first_step_item[0] if first_step_item else None
                    first_step_delimiter = first_step_item[1] if first_step_item else None
                    first_step_line = first_step_item[2] if first_step_item else ""
                    first_step_body = first_step_item[3] if first_step_item else ""
                    if (
                        has_active_task
                        and execplan_rules.get("first_concrete_step_requires_canonical_index")
                        and (
                            first_step_index != "1"
                            or first_step_delimiter
                            != execplan_rules.get("first_concrete_step_canonical_delimiter")
                        )
                    ):
                        report.fail(
                            "STATE_EXECPLAN_ACTION",
                            "active ExecPlan first visible ordered item must use canonical marker 1.",
                        )
                    step_action_match = re.match(r"^\[([^\]\r\n]+)\]\s+\S", first_step_line)
                    step_action = step_action_match.group(1) if step_action_match else None
                    if (
                        has_active_task
                        and execplan_rules.get("first_concrete_step_requires_action_id")
                        and step_action is None
                    ):
                        report.fail(
                            "STATE_EXECPLAN_ACTION",
                            "active ExecPlan first Concrete Step must start with [<active_action_id>]",
                        )
                    if (
                        has_active_task
                        and execplan_rules.get("first_concrete_step_must_match_marker")
                        and step_action is not None
                        and step_action != expected_action
                    ):
                        report.fail(
                            "STATE_EXECPLAN_ACTION",
                            "active ExecPlan first Concrete Step action ID must match "
                            f"state.active_action_id ({expected_action})",
                        )
                    if (
                        execplan_rules.get("first_concrete_step_forbids_other_action_ids")
                        and is_nonempty_string(state.get("active_task"))
                    ):
                        mentioned = _same_task_action_suffixes(
                            first_step_body,
                            task_id=str(state["active_task"]),
                            rules=contracts.get("next_action_invariants", {}),
                        )
                        expected_suffix = expected_action.removeprefix(
                            f"{state['active_task']}:"
                        )
                        if mentioned - {expected_suffix}:
                            report.fail(
                                "STATE_EXECPLAN_ACTION",
                                "active ExecPlan first Concrete Step references a different "
                                "action ID for the active task",
                            )
                    if (
                        execplan_rules.get("forbid_unresolved_template_tokens")
                        and ("{{" in plan_text or "}}" in plan_text)
                    ):
                        report.fail(
                            "STATE_EXECPLAN_REQUIRED",
                            "active ExecPlan contains unresolved template tokens",
                        )
    refs = state.get("instruction_scope_refs", [])
    if isinstance(refs, list):
        for value in refs:
            if not isinstance(value, str):
                report.fail("STATE_REFERENCE", "instruction_scope_refs entries must be strings")
                continue
            try:
                target = safe_relative_path(root, value, field_name="instruction_scope_refs")
            except ValueError as exc:
                report.fail("STATE_REFERENCE", str(exc))
                continue
            if not target.is_file():
                report.fail("STATE_REFERENCE", f"instruction scope target does not exist: {value}")


def _check_runtime_classification(
    state: Mapping[str, Any], contracts: Mapping[str, Any], report: Report
) -> None:
    plain = dict(state)
    plain["activity"] = state.get("active_activity")
    for violation in classification_invariant_violations(plain, contracts):
        code = (
            "STATE_ACTIVITY_STAGE"
            if violation.startswith("activity=")
            else "STATE_UNKNOWN_CLASSIFICATION"
            if violation.startswith("unresolved axes")
            else "STATE_TIER_FLOOR"
        )
        report.fail(code, violation)
    rules = contracts.get("runtime_classification_rules", {})
    if (
        state.get("status") == "UNKNOWN"
        and rules.get("unknown_status_requires_no_active_task")
        and state.get("active_task") is not None
    ):
        report.fail(
            "STATE_UNKNOWN_STATUS",
            "status=UNKNOWN requires active_task=null until recovery resolves task status",
        )


def _dependency_cycles(items: Mapping[str, Mapping[str, Any]]) -> list[list[str]]:
    visiting: set[str] = set()
    visited: set[str] = set()
    cycles: list[list[str]] = []

    def visit(identifier: str, stack: list[str]) -> None:
        if identifier in visiting:
            index = stack.index(identifier)
            cycles.append(stack[index:] + [identifier])
            return
        if identifier in visited:
            return
        visiting.add(identifier)
        stack.append(identifier)
        dependencies = items[identifier].get("dependencies", [])
        if not isinstance(dependencies, list):
            dependencies = []
        for dependency in dependencies:
            if is_nonempty_string(dependency) and dependency in items:
                visit(dependency, stack)
        stack.pop()
        visiting.remove(identifier)
        visited.add(identifier)

    for identifier in items:
        visit(identifier, [])
    return cycles


def _check_backlog(
    root: Path,
    backlog: Mapping[str, Any],
    verification: list[Mapping[str, Any]],
    contracts: Mapping[str, Any],
    report: Report,
) -> dict[str, Mapping[str, Any]]:
    raw_items = backlog.get("items")
    if not isinstance(raw_items, list):
        report.fail("BACKLOG_ITEMS", "items must be a list")
        return {}
    schema_version = backlog.get("schema_version")
    supported_schema = contracts.get("backlog_schema_version")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != supported_schema
    ):
        report.fail("BACKLOG_SCHEMA", f"schema_version must equal supported version {supported_schema}")
    identifiers = [
        str(item["id"])
        for item in raw_items
        if isinstance(item, Mapping) and is_nonempty_string(item.get("id"))
    ]
    duplicates = unique_duplicates(identifiers)
    if duplicates:
        report.fail("BACKLOG_DUPLICATE_ID", f"duplicate item IDs: {', '.join(sorted(duplicates))}")
    items: dict[str, Mapping[str, Any]] = {}
    action_ids: list[str] = []
    for index, item in enumerate(raw_items):
        if not isinstance(item, Mapping):
            report.fail("BACKLOG_ITEM", f"item {index} must be an object")
            continue
        missing = require_fields(item, contracts["backlog_item_required_fields"])
        identifier = item.get("id", f"index-{index}")
        if missing:
            report.fail("BACKLOG_FIELDS", f"{identifier}: missing {', '.join(missing)}")
        for field in contracts.get("backlog_item_nonempty_string_fields", []):
            if not is_nonempty_string(item.get(field)):
                report.fail("BACKLOG_VALUE", f"{identifier}.{field} must be a non-empty string")
        if is_nonempty_string(item.get("id")):
            action_id = _validate_next_action(
                item.get("next_action"),
                task_id=str(item["id"]),
                status=item.get("status"),
                contracts=contracts,
                report=report,
            )
            if action_id is not None:
                action_ids.append(action_id)
        if is_nonempty_string(item.get("id")):
            items[str(item["id"])] = item
        for field, enum_name in BACKLOG_ENUM_FIELDS.items():
            if field in item:
                _check_enum(report, contracts, item[field], enum_name, "BACKLOG_ENUM", f"{identifier}.{field}")
        for field in ("dependencies", "evidence_refs"):
            if field in item and (
                not isinstance(item[field], list)
                or not all(is_nonempty_string(value) for value in item[field])
            ):
                report.fail("BACKLOG_COLLECTION", f"{identifier}.{field} must be a list")
        _check_evidence_refs(
            root,
            item.get("evidence_refs"),
            report,
            code="BACKLOG_EVIDENCE_REF",
            field=f"{identifier}.evidence_refs",
            allow_directory=True,
        )
        if item.get("status") == "DONE" and not item.get("evidence_refs"):
            report.fail("BACKLOG_DONE_EVIDENCE", f"{identifier}: DONE item has no evidence_refs")
        if item.get("status") == "DONE":
            reconciliation_rules = contracts.get("runtime_reconciliation_rules", {})
            ledger_path = str(
                contracts.get("runtime_gate_rules", {}).get(
                    "verification_ledger_path", ".agent/verification.jsonl"
                )
            )
            refs = item.get("evidence_refs") if isinstance(item.get("evidence_refs"), list) else []
            cited_ids = {
                fragment
                for reference_value in refs
                if isinstance(reference_value, str)
                for kind, target, fragment in [classify_link(reference_value)]
                if kind == "internal" and Path(target).as_posix() == ledger_path and fragment
            }
            task_records = [
                record
                for record in verification
                if isinstance(record, Mapping) and record.get("task") == identifier
            ]
            latest_task_records = [
                record
                for (task, _), record in _latest_verification_by_stream(verification).items()
                if task == identifier
            ]
            latest_ids = {
                str(record["id"])
                for record in latest_task_records
                if is_nonempty_string(record.get("id"))
            }
            cited_pass_records = [
                record
                for record in task_records
                if (
                record.get("id") in cited_ids
                and record.get("id") in latest_ids
                and _verification_record_is_qualifying_pass(record)
                )
            ]
            cited_pass = bool(cited_pass_records)
            if reconciliation_rules.get("done_requires_cited_current_pass_verification") and not cited_pass:
                report.fail(
                    "BACKLOG_DONE_VERIFICATION",
                    f"{identifier}: DONE requires an exact {ledger_path}#VER-ID CURRENT PASS for this task",
                )
            if (
                reconciliation_rules.get("done_forbids_latest_nonpass_verification")
                and any(
                    not _verification_record_is_qualifying_pass(record)
                    for record in latest_task_records
                )
            ):
                report.fail(
                    "BACKLOG_DONE_VERIFICATION",
                    f"{identifier}: DONE is incompatible with a latest applicable non-PASS verification",
                )
    for identifier, item in items.items():
        dependencies = item.get("dependencies", [])
        if not isinstance(dependencies, list):
            continue
        for dependency in dependencies:
            if not is_nonempty_string(dependency):
                continue
            if dependency not in items:
                report.fail("BACKLOG_DEPENDENCY", f"{identifier}: unknown dependency {dependency}")
            elif (
                isinstance(item.get("status"), str)
                and item.get("status") in {"IN_PROGRESS", "VERIFY", "DONE"}
                and items[dependency].get("status") != "DONE"
            ):
                report.fail("BACKLOG_DEPENDENCY", f"{identifier}: active/completed item depends on non-DONE {dependency}")
    for cycle in _dependency_cycles(items):
        report.fail("BACKLOG_CYCLE", "dependency cycle: " + " -> ".join(cycle))
    if contracts.get("next_action_invariants", {}).get("ids_must_be_unique"):
        duplicate_actions = unique_duplicates(action_ids)
        if duplicate_actions:
            report.fail(
                "BACKLOG_ACTION",
                f"duplicate next_action IDs: {', '.join(sorted(duplicate_actions))}",
            )
    if not any(item.level == "FAIL" and item.code.startswith("BACKLOG") for item in report.findings):
        report.pass_("BACKLOG_CONTRACT", f"validated {len(items)} backlog item(s)")
    return items


def _check_log(
    records: list[Mapping[str, Any]],
    items: Mapping[str, Mapping[str, Any]],
    contracts: Mapping[str, Any],
    report: Report,
) -> None:
    identifiers: list[str] = []
    previous_time = None
    event_types = enum_values(contracts, "event_type")
    transitions = contracts.get("status_transitions", {})
    lifecycle_transitions = contracts.get("lifecycle_transitions", {})
    previous_status_by_task: dict[str, str] = {}
    previous_lifecycle: str | None = None
    gate_rules = contracts.get("runtime_gate_rules", {})
    recovery_type = gate_rules.get("legacy_gate_recovery_event_type")
    recovery_state_field = str(
        gate_rules.get("legacy_gate_recovery_state_field", "prehistory_state")
    )
    recovery_state_value = gate_rules.get("legacy_gate_recovery_state_value")
    legacy_event_id_field = str(gate_rules.get("legacy_gate_event_id_field", "legacy_event_id"))
    recovered_legacy_events = {
        str(event[legacy_event_id_field])
        for event in records
        if (
            event.get("type") == recovery_type
            and event.get(recovery_state_field) == recovery_state_value
            and is_nonempty_string(event.get(legacy_event_id_field))
        )
    }
    reconciliation_rules = contracts.get("runtime_reconciliation_rules", {})
    correction_type = reconciliation_rules.get("correction_event_type", "CORRECTION")
    correction_target_field = str(
        reconciliation_rules.get("correction_target_field", "corrects_event_id")
    )
    correction_effective_type_field = str(
        reconciliation_rules.get("correction_effective_type_field", "corrected_event_type")
    )
    correction_reason_field = str(
        reconciliation_rules.get("correction_reason_field", "correction_reason")
    )
    seen_by_id: dict[str, tuple[int, Mapping[str, Any]]] = {}
    latest_transition_by_task: dict[str, str] = {}
    corrected_by: dict[str, Mapping[str, Any]] = {}
    lifecycle_types = set(gate_rules.get("gate_lifecycle_event_types", []))
    override_event_type = contracts.get("override_invariants", {}).get(
        "override_event_type", "OVERRIDE"
    )
    noncorrectable_types = lifecycle_types | {override_event_type}
    for index, event in enumerate(records, 1):
        identifier = event.get("event_id")
        task = event.get("task")
        if event.get("type") == correction_type:
            missing_correction = require_fields(
                event, contracts.get("execution_correction_required_fields", [])
            )
            if missing_correction:
                report.fail(
                    "LOG_CORRECTION",
                    f"{identifier or index}: correction missing {', '.join(missing_correction)}",
                )
                continue
            target_id = event.get(correction_target_field)
            target_entry = seen_by_id.get(str(target_id)) if is_nonempty_string(target_id) else None
            effective_type = event.get(correction_effective_type_field)
            valid = True
            if target_entry is None:
                report.fail("LOG_CORRECTION", f"{identifier or index}: correction target must be an earlier event")
                valid = False
            elif target_entry[1].get("task") != task:
                report.fail("LOG_CORRECTION", f"{identifier or index}: correction target must have the same task")
                valid = False
            elif target_entry[1].get("status_from") is None or target_entry[1].get("status_to") is None:
                report.fail("LOG_CORRECTION", f"{identifier or index}: correction target has no status transition")
                valid = False
            if not is_nonempty_string(event.get(correction_reason_field)):
                report.fail("LOG_CORRECTION", f"{identifier or index}: correction_reason must be non-empty")
                valid = False
            if (
                not isinstance(effective_type, str)
                or effective_type not in event_types
                or effective_type == correction_type
                or effective_type in noncorrectable_types
            ):
                report.fail("LOG_CORRECTION", f"{identifier or index}: corrected_event_type is invalid")
                valid = False
            if (
                target_entry is not None
                and target_entry[1].get("type") in noncorrectable_types
            ):
                report.fail(
                    "LOG_CORRECTION",
                    f"{identifier or index}: gate lifecycle and override activation events cannot be corrected; append a governing closure/reopen record",
                )
                valid = False
            if (
                reconciliation_rules.get("correction_requires_latest_task_transition")
                and is_nonempty_string(task)
                and latest_transition_by_task.get(str(task)) != target_id
            ):
                report.fail("LOG_CORRECTION", f"{identifier or index}: correction must target the latest task transition")
                valid = False
            if target_id in corrected_by:
                report.fail("LOG_CORRECTION", f"{identifier or index}: target already has a correction")
                valid = False
            before = event.get("status_from")
            after = event.get("status_to")
            if (
                not isinstance(before, str)
                or not isinstance(after, str)
                or after not in transitions.get(before, [])
            ):
                report.fail("LOG_CORRECTION", f"{identifier or index}: corrected transition is invalid")
                valid = False
            if valid:
                corrected_by[str(target_id)] = event
        elif (
            is_nonempty_string(task)
            and event.get("status_from") is not None
            and event.get("status_to") is not None
            and is_nonempty_string(identifier)
        ):
            latest_transition_by_task[str(task)] = str(identifier)
        if is_nonempty_string(identifier):
            seen_by_id.setdefault(str(identifier), (index, event))
    for index, event in enumerate(records, 1):
        identifier = event.get("event_id")
        missing = require_fields(event, contracts.get("execution_log_required_fields", []))
        if missing:
            report.fail("LOG_FIELDS", f"record {index} missing required fields: {', '.join(missing)}")
        for field in contracts.get("execution_log_nonempty_string_fields", []):
            if not is_nonempty_string(event.get(field)):
                report.fail("LOG_VALUE", f"{identifier or index}.{field} must be a non-empty string")
        if not is_nonempty_string(identifier):
            report.fail("LOG_EVENT_ID", f"record {index} has no event_id")
        else:
            identifiers.append(str(identifier))
        event_type = event.get("type")
        if not isinstance(event_type, str) or event_type not in event_types:
            report.fail("LOG_EVENT_TYPE", f"{identifier or index}: invalid type {event_type!r}")
        gate_fields = (
            str(gate_rules.get("gate_event_source_field", "gate_ref")),
            str(gate_rules.get("gate_event_record_id_field", "gate_record_id")),
            str(gate_rules.get("gate_event_decision_field", "gate_decision")),
            str(gate_rules.get("gate_event_fingerprint_field", "gate_fingerprint")),
        )
        has_gate_binding = any(field in event for field in gate_fields)
        if (event_type in lifecycle_types or has_gate_binding) and not (
            event_type in lifecycle_types
            and not has_gate_binding
            and identifier in recovered_legacy_events
        ):
            missing_gate_fields = [
                field for field in gate_fields if not is_nonempty_string(event.get(field))
            ]
            if missing_gate_fields:
                report.fail(
                    "LOG_GATE_BINDING",
                    f"{identifier or index}: gate lifecycle binding missing {', '.join(missing_gate_fields)}",
                )
        override_rules = contracts.get("override_invariants", {})
        if event_type == override_rules.get("override_event_type", "OVERRIDE"):
            override_fields = (
                str(override_rules.get("override_event_id_field", "override_id")),
                str(override_rules.get("override_event_fingerprint_field", "override_fingerprint")),
            )
            missing_override_fields = [
                field for field in override_fields if not is_nonempty_string(event.get(field))
            ]
            if missing_override_fields:
                report.fail(
                    "LOG_OVERRIDE_BINDING",
                    f"{identifier or index}: override event missing {', '.join(missing_override_fields)}",
                )
        timestamp = parse_iso8601(event.get("timestamp"))
        if timestamp is None:
            report.fail("LOG_TIMESTAMP", f"{identifier or index}: timestamp must include timezone")
        elif previous_time is not None and timestamp < previous_time:
            report.fail("LOG_ORDER", f"{identifier or index}: timestamp precedes previous append record")
        if timestamp is not None:
            previous_time = timestamp
        task = event.get("task")
        if is_nonempty_string(task) and task not in items:
            report.fail("LOG_TASK_REF", f"{identifier or index}: unknown task {task}")
        log_action_rules = contracts.get("execution_log_action_binding", {})
        log_action_field = str(log_action_rules.get("field", "active_action_id"))
        if log_action_field in event and event.get(log_action_field) is not None:
            event_action_id = event.get(log_action_field)
            if not is_nonempty_string(event_action_id):
                report.fail(
                    "LOG_ACTION",
                    f"{identifier or index}.{log_action_field} must be a non-empty string or null",
                )
            elif is_nonempty_string(task):
                suffix_pattern = contracts.get("next_action_invariants", {}).get(
                    "id_suffix_pattern", r"[A-Z][A-Z0-9._-]*"
                )
                action_suffix = (
                    event_action_id[len(str(task)) + 1 :]
                    if event_action_id.startswith(f"{task}:")
                    else ""
                )
                if (
                    not action_suffix
                    or not isinstance(suffix_pattern, str)
                    or re.fullmatch(suffix_pattern, action_suffix) is None
                ):
                    report.fail(
                        "LOG_ACTION",
                        f"{identifier or index}.{log_action_field} must be scoped as "
                        f"{task}:<STABLE-ID>",
                    )
        effective_event = corrected_by.get(str(identifier), event)
        before = None if event_type == correction_type else effective_event.get("status_from")
        after = None if event_type == correction_type else effective_event.get("status_to")
        if (before is None) != (after is None):
            report.fail("LOG_TRANSITION", f"{identifier or index}: status_from and status_to must appear together")
        elif before is not None:
            if not isinstance(before, str) or not isinstance(after, str):
                report.fail("LOG_TRANSITION", f"{identifier or index}: transition values must be strings")
                continue
            allowed = transitions.get(before)
            if not isinstance(allowed, list) or after not in allowed:
                report.fail("LOG_TRANSITION", f"{identifier or index}: invalid transition {before} -> {after}")
            if is_nonempty_string(task):
                previous_status = previous_status_by_task.get(str(task))
                if previous_status is not None and before != previous_status:
                    report.fail(
                        "LOG_TRANSITION_CONTINUITY",
                        f"{identifier or index}: {task} transition starts at {before}, "
                        f"but the prior declared transition ended at {previous_status}",
                    )
                previous_status_by_task[str(task)] = after
        lifecycle_before = event.get("lifecycle_from")
        lifecycle_after = event.get("lifecycle_to")
        if (lifecycle_before is None) != (lifecycle_after is None):
            report.fail("LOG_LIFECYCLE_TRANSITION", f"{identifier or index}: lifecycle_from and lifecycle_to must appear together")
        elif lifecycle_before is not None:
            if not isinstance(lifecycle_before, str) or not isinstance(lifecycle_after, str):
                report.fail(
                    "LOG_LIFECYCLE_TRANSITION",
                    f"{identifier or index}: lifecycle transition values must be strings",
                )
                continue
            allowed = lifecycle_transitions.get(lifecycle_before)
            if not isinstance(allowed, list) or lifecycle_after not in allowed:
                report.fail(
                    "LOG_LIFECYCLE_TRANSITION",
                    f"{identifier or index}: invalid lifecycle transition {lifecycle_before} -> {lifecycle_after}",
                )
            if previous_lifecycle is not None and lifecycle_before != previous_lifecycle:
                report.fail(
                    "LOG_LIFECYCLE_CONTINUITY",
                    f"{identifier or index}: lifecycle transition starts at {lifecycle_before}, "
                    f"but the prior declared transition ended at {previous_lifecycle}",
                )
            previous_lifecycle = lifecycle_after
    duplicates = unique_duplicates(identifiers)
    if duplicates:
        report.fail("LOG_DUPLICATE_ID", f"duplicate event IDs: {', '.join(sorted(duplicates))}")
    if not any(item.level == "FAIL" and item.code.startswith("LOG") for item in report.findings):
        report.pass_("LOG_CONTRACT", f"validated {len(records)} append-oriented event(s)")


def _enum_field(
    report: Report,
    contracts: Mapping[str, Any],
    value: Any,
    enum_name: str | None,
    code: str,
    field: str,
) -> None:
    if not enum_name:
        return
    _check_enum(report, contracts, value, enum_name, code, field)


def _check_authority(
    root: Path,
    authority: Any,
    contracts: Mapping[str, Any],
    report: Report,
    *,
    prefix: str,
    pass_decision: bool,
    must_confirm: bool = False,
    expected_scope: Any = None,
    expected_scope_ref: Any = None,
    expected_subject_type: Any = None,
    expected_subject_id: Any = None,
    not_after: Any = None,
    valid_through: Any = None,
) -> None:
    if not isinstance(authority, Mapping):
        report.fail("GATE_AUTHORITY", f"{prefix} must be an object")
        return
    missing = require_fields(authority, contracts.get("authority_record_required_fields", []))
    if missing:
        report.fail("GATE_AUTHORITY", f"{prefix} missing fields: {', '.join(missing)}")
        return
    _enum_field(report, contracts, authority.get("state"), "authority_state", "GATE_AUTHORITY", f"{prefix}.state")
    required = authority.get("required")
    if not isinstance(required, bool):
        report.fail("GATE_AUTHORITY", f"{prefix}.required must be boolean")
    for field in ("actor", "scope", "decision", "evidence_ref", "expires_or_revalidates"):
        if not is_nonempty_string(authority.get(field)):
            report.fail("GATE_AUTHORITY", f"{prefix}.{field} must be a non-empty string")
    if is_nonempty_string(expected_scope) and authority.get("scope") != expected_scope:
        report.fail(
            "GATE_AUTHORITY_SCOPE",
            f"{prefix}.scope must exactly match the governed scope {expected_scope!r}",
        )
    _check_evidence_ref(
        root,
        authority.get("evidence_ref"),
        report,
        code="GATE_AUTHORITY_EVIDENCE",
        field=f"{prefix}.evidence_ref",
    )
    allowed_by_required = contracts.get("gate_invariants", {}).get("authority_states_by_required", {})
    if isinstance(required, bool) and isinstance(allowed_by_required, Mapping):
        allowed_states = allowed_by_required.get(str(required).lower(), [])
        if authority.get("state") not in allowed_states:
            report.fail(
                "GATE_AUTHORITY",
                f"{prefix}.state={authority.get('state')!r} is invalid when required={required}",
            )
    if pass_decision and (required or must_confirm):
        if authority.get("state") != "CONFIRMED":
            report.fail("GATE_AUTHORITY", f"{prefix}: required authority must be CONFIRMED for a passing decision")
    if authority.get("state") == "CONFIRMED":
        placeholders = {
            str(value).strip().upper()
            for value in contracts.get("gate_invariants", {}).get(
                "confirmed_authority_placeholder_values",
                ["", "TBD", "PENDING", "UNKNOWN", "NONE", "NOT_REQUIRED"],
            )
        }
        actor = str(authority.get("actor", "")).strip().upper()
        evidence_ref = str(authority.get("evidence_ref", "")).strip().upper()
        if actor in placeholders or evidence_ref in placeholders:
            report.fail("GATE_AUTHORITY", f"{prefix}: confirmed authority requires a concrete actor and evidence_ref")
        ledger_path = str(
            contracts.get("runtime_gate_rules", {}).get(
                "authority_ledger_path", ".agent/authority.jsonl"
            )
        )
        kind, target, fragment = classify_link(str(authority.get("evidence_ref", "")))
        if kind != "internal" or Path(target).as_posix() != ledger_path or not fragment:
            report.fail(
                "GATE_AUTHORITY_EVIDENCE",
                f"{prefix}: CONFIRMED requires an exact {ledger_path}#AUTH-ID reference",
            )
            return
        try:
            records = load_jsonl(root / ledger_path)
        except (OSError, UnicodeError, ValueError) as exc:
            report.fail("GATE_AUTHORITY_EVIDENCE", f"{prefix}: cannot load authority ledger: {exc}")
            return
        ids: list[str] = []
        prior_ledger_time = None
        prior_subject_time: dict[tuple[str, str], Any] = {}
        required_typed_fields = contracts.get("authority_evidence_record_required_fields", [])
        subject_enum = contracts.get("authority_evidence_field_enums", {}).get("subject_type")
        status_enum = contracts.get("authority_evidence_field_enums", {}).get("status")
        for index, candidate in enumerate(records, 1):
            missing_candidate = require_fields(candidate, required_typed_fields)
            if missing_candidate:
                report.fail(
                    "GATE_AUTHORITY_EVIDENCE",
                    f"{prefix}: authority ledger record {index} missing {', '.join(missing_candidate)}",
                )
                continue
            candidate_id = candidate.get("id")
            if not is_nonempty_string(candidate_id):
                report.fail(
                    "GATE_AUTHORITY_EVIDENCE",
                    f"{prefix}: authority ledger record {index} has no non-empty id",
                )
            else:
                ids.append(str(candidate_id))
            candidate_time = parse_iso8601(candidate.get("timestamp"))
            if candidate_time is None:
                report.fail(
                    "GATE_AUTHORITY_EVIDENCE",
                    f"{prefix}: authority ledger record {candidate_id or index} timestamp must be zoned",
                )
            elif prior_ledger_time is not None and candidate_time < prior_ledger_time:
                report.fail(
                    "GATE_AUTHORITY_EVIDENCE",
                    f"{prefix}: authority ledger must be append-ordered by timestamp",
                )
            if candidate_time is not None:
                prior_ledger_time = candidate_time
            _enum_field(
                report,
                contracts,
                candidate.get("status"),
                status_enum,
                "GATE_AUTHORITY_EVIDENCE",
                f"{prefix}.ledger[{index}].status",
            )
            _enum_field(
                report,
                contracts,
                candidate.get("subject_type"),
                subject_enum,
                "GATE_AUTHORITY_EVIDENCE",
                f"{prefix}.ledger[{index}].subject_type",
            )
            subject_key = (str(candidate.get("subject_type")), str(candidate.get("subject_id")))
            if candidate_time is not None:
                prior = prior_subject_time.get(subject_key)
                if prior is not None and candidate_time <= prior:
                    report.fail(
                        "GATE_AUTHORITY_EVIDENCE",
                        f"{prefix}: authority decisions for one subject require strictly increasing timestamps",
                    )
                prior_subject_time[subject_key] = candidate_time
            expires_at_value = candidate.get("expires_at")
            if expires_at_value is not None and parse_iso8601(expires_at_value) is None:
                report.fail(
                    "GATE_AUTHORITY_EVIDENCE",
                    f"{prefix}: authority ledger record {candidate_id or index} expires_at must be null or zoned",
                )
        duplicate_ids = unique_duplicates(ids)
        if duplicate_ids:
            report.fail(
                "GATE_AUTHORITY_EVIDENCE",
                f"{prefix}: duplicate authority record IDs {sorted(duplicate_ids)}",
            )
        if ids.count(fragment) != 1:
            report.fail(
                "GATE_AUTHORITY_EVIDENCE",
                f"{prefix}: authority record {fragment!r} must resolve exactly once",
            )
            return
        typed = next(item for item in records if item.get("id") == fragment)
        missing_typed = require_fields(
            typed, contracts.get("authority_evidence_record_required_fields", [])
        )
        if missing_typed:
            report.fail(
                "GATE_AUTHORITY_EVIDENCE",
                f"{prefix}: authority record missing {', '.join(missing_typed)}",
            )
            return
        for field in (
            "id",
            "actor",
            "scope",
            "scope_ref",
            "subject_type",
            "subject_id",
            "decision",
            "evidence",
            "limitations",
        ):
            if not is_nonempty_string(typed.get(field)):
                report.fail(
                    "GATE_AUTHORITY_EVIDENCE",
                    f"{prefix}: authority record {field} must be non-empty",
                )
        _enum_field(
            report,
            contracts,
            typed.get("status"),
            contracts.get("authority_evidence_field_enums", {}).get("status"),
            "GATE_AUTHORITY_EVIDENCE",
            f"{prefix}.evidence.status",
        )
        _enum_field(
            report,
            contracts,
            typed.get("subject_type"),
            contracts.get("authority_evidence_field_enums", {}).get("subject_type"),
            "GATE_AUTHORITY_EVIDENCE",
            f"{prefix}.evidence.subject_type",
        )
        if typed.get("status") != "CONFIRMED":
            report.fail("GATE_AUTHORITY_EVIDENCE", f"{prefix}: authority evidence status must be CONFIRMED")
        expected_values = {
            "actor": authority.get("actor"),
            "scope": expected_scope,
            "scope_ref": expected_scope_ref,
            "subject_type": expected_subject_type,
            "subject_id": expected_subject_id,
            "decision": authority.get("decision"),
        }
        for field, expected in expected_values.items():
            if typed.get(field) != expected:
                report.fail(
                    "GATE_AUTHORITY_EVIDENCE",
                    f"{prefix}: authority evidence {field} does not match the governed record",
                )
        evidence_time = parse_iso8601(typed.get("timestamp"))
        decision_time = parse_iso8601(not_after)
        if evidence_time is None or decision_time is None or evidence_time > decision_time:
            report.fail(
                "GATE_AUTHORITY_EVIDENCE",
                f"{prefix}: authority evidence timestamp must be zoned and no later than the governed decision",
            )
        validity_time = decision_time if valid_through is None else parse_iso8601(valid_through)
        if validity_time is None:
            report.fail(
                "GATE_AUTHORITY_EVIDENCE",
                f"{prefix}: authority validity cutoff must include a timezone",
            )
        applicable_subject_records = [
            candidate
            for candidate in records
            if (
                candidate.get("subject_type") == expected_subject_type
                and candidate.get("subject_id") == expected_subject_id
                and (candidate_time := parse_iso8601(candidate.get("timestamp"))) is not None
                and validity_time is not None
                and candidate_time <= validity_time
            )
        ]
        if applicable_subject_records and applicable_subject_records[-1].get("id") != fragment:
            report.fail(
                "GATE_AUTHORITY_EVIDENCE",
                f"{prefix}: cited authority is not the latest applicable decision for this subject",
            )
        expires_at = typed.get("expires_at")
        if expires_at is not None:
            expiry_time = parse_iso8601(expires_at)
            if expiry_time is None or validity_time is None or expiry_time <= validity_time:
                report.fail(
                    "GATE_AUTHORITY_EVIDENCE",
                    f"{prefix}: expires_at must be null or a zoned time after the current governed use",
                )


def _check_authority_ledger(
    root: Path, contracts: Mapping[str, Any], report: Report
) -> list[Mapping[str, Any]]:
    """Validate the authority ledger even when no gate currently cites it."""

    ledger_path = str(
        contracts.get("runtime_gate_rules", {}).get(
            "authority_ledger_path", ".agent/authority.jsonl"
        )
    )
    path = root / ledger_path
    if not path.exists():
        return []
    try:
        records = load_jsonl(path)
    except (OSError, UnicodeError, ValueError) as exc:
        report.fail("AUTHORITY_LEDGER", str(exc), ledger_path)
        return []
    required = contracts.get("authority_evidence_record_required_fields", [])
    field_enums = contracts.get("authority_evidence_field_enums", {})
    identifiers: list[str] = []
    previous_time = None
    previous_subject_time: dict[tuple[str, str], Any] = {}
    for index, record in enumerate(records, 1):
        identifier = record.get("id")
        missing = require_fields(record, required)
        if missing:
            report.fail(
                "AUTHORITY_LEDGER_FIELDS",
                f"record {index} missing {', '.join(missing)}",
            )
        for field in (
            "id",
            "actor",
            "scope",
            "scope_ref",
            "subject_type",
            "subject_id",
            "decision",
            "evidence",
            "limitations",
        ):
            if not is_nonempty_string(record.get(field)):
                report.fail(
                    "AUTHORITY_LEDGER_VALUE",
                    f"{identifier or index}.{field} must be a non-empty string",
                )
        if is_nonempty_string(identifier):
            identifiers.append(str(identifier))
        _enum_field(
            report,
            contracts,
            record.get("status"),
            field_enums.get("status"),
            "AUTHORITY_LEDGER_ENUM",
            f"{identifier or index}.status",
        )
        _enum_field(
            report,
            contracts,
            record.get("subject_type"),
            field_enums.get("subject_type"),
            "AUTHORITY_LEDGER_ENUM",
            f"{identifier or index}.subject_type",
        )
        timestamp = parse_iso8601(record.get("timestamp"))
        if timestamp is None:
            report.fail(
                "AUTHORITY_LEDGER_TIME",
                f"{identifier or index}.timestamp must include a timezone",
            )
        elif previous_time is not None and timestamp < previous_time:
            report.fail(
                "AUTHORITY_LEDGER_ORDER",
                f"{identifier or index}: authority ledger must be append-ordered",
            )
        if timestamp is not None:
            previous_time = timestamp
            subject_key = (str(record.get("subject_type")), str(record.get("subject_id")))
            prior = previous_subject_time.get(subject_key)
            if prior is not None and timestamp <= prior:
                report.fail(
                    "AUTHORITY_LEDGER_ORDER",
                    f"{identifier or index}: one subject requires strictly increasing decision timestamps",
                )
            previous_subject_time[subject_key] = timestamp
        expires_at = record.get("expires_at")
        expiry_time = parse_iso8601(expires_at) if expires_at is not None else None
        if expires_at is not None and expiry_time is None:
            report.fail(
                "AUTHORITY_LEDGER_TIME",
                f"{identifier or index}.expires_at must be null or include a timezone",
            )
        elif timestamp is not None and expiry_time is not None and expiry_time <= timestamp:
            report.fail(
                "AUTHORITY_LEDGER_TIME",
                f"{identifier or index}.expires_at must be later than its decision timestamp",
            )
    duplicates = unique_duplicates(identifiers)
    if duplicates:
        report.fail(
            "AUTHORITY_LEDGER_ID",
            f"duplicate authority record IDs: {', '.join(sorted(duplicates))}",
        )
    if not any(
        item.level == "FAIL" and item.code.startswith("AUTHORITY_LEDGER")
        for item in report.findings
    ):
        report.pass_("AUTHORITY_LEDGER", f"validated {len(records)} authority decision record(s)")
    return records


def _verification_stream_key(record: Mapping[str, Any]) -> tuple[str, str] | None:
    task = record.get("task")
    scope = record.get("scope")
    if not is_nonempty_string(task) or not is_nonempty_string(scope):
        return None
    return str(task), str(scope)


def _verification_record_is_qualifying_pass(record: Mapping[str, Any]) -> bool:
    return (
        record.get("result") == "PASS"
        and record.get("freshness") == "CURRENT"
        and record.get("procedure_status") == "EXECUTED"
        and parse_iso8601(record.get("timestamp")) is not None
        and parse_iso8601(record.get("observed_at")) is not None
    )


def _latest_verification_by_stream(
    records: list[Mapping[str, Any]],
    *,
    cutoff: Any = None,
) -> dict[tuple[str, str], Mapping[str, Any]]:
    latest: dict[tuple[str, str], Mapping[str, Any]] = {}
    for record in records:
        key = _verification_stream_key(record)
        timestamp = parse_iso8601(record.get("timestamp"))
        if key is None or timestamp is None:
            continue
        if cutoff is not None and timestamp > cutoff:
            continue
        latest[key] = record
    return latest


def _verification_record_supports_gate(
    record: Mapping[str, Any] | None,
    verification: list[Mapping[str, Any]],
    gate: Mapping[str, Any],
    log: list[Mapping[str, Any]],
    contracts: Mapping[str, Any],
    *,
    current_through: Any = None,
) -> bool:
    if record is None:
        return False
    observed_at = parse_iso8601(record.get("observed_at"))
    record_time = parse_iso8601(record.get("timestamp"))
    gate_time = parse_iso8601(gate.get("timestamp"))
    if (
        not _verification_record_is_qualifying_pass(record)
        or record.get("task") != gate.get("scope_ref")
        or record.get("scope") != gate.get("scope")
        or observed_at is None
        or record_time is None
        or gate_time is None
        or observed_at > record_time
        or record_time > gate_time
    ):
        return False
    invalidating_types = set(
        contracts.get("runtime_reconciliation_rules", {}).get(
            "verification_invalidating_event_types", []
        )
    )
    task = record.get("task")
    cutoff = current_through if current_through is not None else gate_time
    if not hasattr(cutoff, "tzinfo") or cutoff < gate_time:
        return False
    stream_key = _verification_stream_key(record)
    if stream_key is None:
        return False
    latest = _latest_verification_by_stream(verification, cutoff=cutoff).get(stream_key)
    if latest is None or latest.get("id") != record.get("id"):
        return False
    return not any(
        event.get("task") == task
        and (
            event.get("type") in invalidating_types
            or event.get("result") != "PASS"
        )
        and (event_time := parse_iso8601(event.get("timestamp"))) is not None
        and observed_at <= event_time <= cutoff
        for event in log
    )


def validate_gate_record(
    record: Any,
    contracts: Mapping[str, Any],
    report: Report,
    *,
    root: Path,
    source: str = "gate",
) -> None:
    """Validate one nested gate decision against canonical machine invariants."""

    if not isinstance(record, Mapping):
        report.fail("GATE_RECORD", f"{source} must be an object")
        return
    missing = require_fields(record, contracts.get("gate_required_fields", []))
    if missing:
        report.fail("GATE_FIELDS", f"{source} missing fields: {', '.join(missing)}")
        return
    if not is_nonempty_string(record.get("record_id")):
        report.fail("GATE_RECORD_ID", f"{source}.record_id must be non-empty")
    if parse_iso8601(record.get("timestamp")) is None:
        report.fail("GATE_TIMESTAMP", f"{source}.timestamp must be ISO-8601 with timezone")
    if not is_nonempty_string(record.get("scope")):
        report.fail("GATE_SCOPE", f"{source}.scope must be non-empty")
    if not is_nonempty_string(record.get("scope_ref")):
        report.fail("GATE_SCOPE", f"{source}.scope_ref must be a non-empty stable task/backlog ID")
    if not isinstance(record.get("version"), int) or isinstance(record.get("version"), bool) or record.get("version", 0) < 1:
        report.fail("GATE_VERSION", f"{source}.version must be a positive integer")
    if record.get("supersedes") is not None and not is_nonempty_string(record.get("supersedes")):
        report.fail("GATE_SUPERSEDES", f"{source}.supersedes must be null or a non-empty record ID")
    for field in ("evidence", "gaps", "conditions", "revalidation_triggers"):
        if not isinstance(record.get(field), list):
            report.fail("GATE_COLLECTION", f"{source}.{field} must be a list")
    for field in ("gaps", "revalidation_triggers"):
        values = record.get(field)
        if isinstance(values, list) and not all(is_nonempty_string(value) for value in values):
            report.fail("GATE_COLLECTION", f"{source}.{field} entries must be non-empty strings")
    if not is_nonempty_string(record.get("next_action")):
        report.fail("GATE_NEXT_ACTION", f"{source}.next_action must be non-empty")
    gate_id = record.get("gate_id")
    if gate_id not in contracts.get("semantic_gates", []):
        report.fail("GATE_ID", f"{source}: unknown semantic gate {gate_id!r}")
    field_enums = contracts.get("gate_field_enums", {})
    for field in ("decision", "confidence", "residual_risk"):
        _enum_field(report, contracts, record.get(field), field_enums.get(field), "GATE_ENUM", f"{source}.{field}")
    decision = record.get("decision")
    invariants = contracts.get("gate_invariants", {})
    if (
        invariants.get("saved_gate_requires_nonempty_revalidation_triggers")
        and isinstance(record.get("revalidation_triggers"), list)
        and not record.get("revalidation_triggers")
    ):
        report.fail(
            "GATE_REVALIDATION",
            f"{source}.revalidation_triggers must name at least one concrete invalidation trigger",
        )
    pass_decisions = set(invariants.get("pass_decisions", []))
    passing = isinstance(decision, str) and decision in pass_decisions
    typed_evidence_required = (
        passing
        and isinstance(gate_id, str)
        and gate_id in set(invariants.get("gates_requiring_typed_verification_evidence", []))
    )
    typed_records_by_id: dict[str, Mapping[str, Any]] = {}
    typed_records: list[Mapping[str, Any]] = []
    gate_log: list[Mapping[str, Any]] = []
    if typed_evidence_required:
        ledger_path = str(
            contracts.get("runtime_gate_rules", {}).get(
                "verification_ledger_path", ".agent/verification.jsonl"
            )
        )
        try:
            typed_records = load_jsonl(root / ledger_path)
            gate_log = load_jsonl(root / ".agent/execution-log.jsonl")
        except (OSError, UnicodeError, ValueError) as exc:
            report.fail(
                "GATE_CRITERION_TYPED_EVIDENCE",
                f"{source}: cannot load typed verification/log evidence: {exc}",
            )
        else:
            typed_records_by_id = {
                str(item["id"]): item
                for item in typed_records
                if isinstance(item, Mapping) and is_nonempty_string(item.get("id"))
            }
    if passing and isinstance(record.get("gaps"), list) and record.get("gaps"):
        report.fail(
            "GATE_GAPS",
            f"{source}: passing gates require gaps=[]; non-blocking follow-up belongs in typed conditions",
        )
    criteria = record.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        report.fail("GATE_CRITERIA", f"{source}.criteria must be a non-empty list")
        criteria = []
    criterion_ids: list[str] = []
    for index, criterion in enumerate(criteria):
        label = f"{source}.criteria[{index}]"
        if not isinstance(criterion, Mapping):
            report.fail("GATE_CRITERION", f"{label} must be an object")
            continue
        missing = require_fields(criterion, contracts.get("gate_criterion_required_fields", []))
        if missing:
            report.fail("GATE_CRITERION", f"{label} missing fields: {', '.join(missing)}")
            continue
        identifier = criterion.get("id")
        if is_nonempty_string(identifier):
            criterion_ids.append(str(identifier))
        for field in invariants.get("criterion_nonempty_fields", ["id", "description"]):
            if not is_nonempty_string(criterion.get(field)):
                report.fail("GATE_CRITERION", f"{label}.{field} must be a non-empty string")
        _enum_field(
            report,
            contracts,
            criterion.get("status"),
            field_enums.get("criteria.status"),
            "GATE_CRITERION_ENUM",
            f"{label}.status",
        )
        _enum_field(
            report,
            contracts,
            criterion.get("confidence"),
            field_enums.get("criteria.confidence"),
            "GATE_CRITERION_ENUM",
            f"{label}.confidence",
        )
        if criterion.get("required") is not True and criterion.get("required") is not False:
            report.fail("GATE_CRITERION", f"{label}.required must be boolean")
        criterion_status = criterion.get("status")
        if (
            passing
            and criterion.get("required") is True
            and (
                not isinstance(criterion_status, str)
                or criterion_status not in set(invariants.get("required_criterion_pass_statuses", ["PASS"]))
            )
        ):
            report.fail("GATE_REQUIRED_FAILURE", f"{label}: passing gate has non-PASS required criterion")
        evidence_refs = criterion.get("evidence_refs")
        _check_evidence_refs(
            root,
            evidence_refs,
            report,
            code="GATE_CRITERION_EVIDENCE",
            field=f"{label}.evidence_refs",
        )
        if criterion.get("status") == "PASS" and (not isinstance(evidence_refs, list) or not evidence_refs):
            report.fail("GATE_CRITERION_EVIDENCE", f"{label}: PASS requires evidence_refs")
        if typed_evidence_required and criterion.get("status") == "PASS":
            ledger_path = str(
                contracts.get("runtime_gate_rules", {}).get(
                    "verification_ledger_path", ".agent/verification.jsonl"
                )
            )
            cited_ids = {
                fragment
                for reference_value in evidence_refs or []
                if isinstance(reference_value, str)
                for kind, target, fragment in [classify_link(reference_value)]
                if kind == "internal" and Path(target).as_posix() == ledger_path and fragment
            }
            if not any(
                _verification_record_supports_gate(
                    typed_records_by_id.get(identifier), typed_records, record, gate_log, contracts
                )
                for identifier in cited_ids
            ):
                report.fail(
                    "GATE_CRITERION_TYPED_EVIDENCE",
                    f"{label}: PASS requires an exact CURRENT PASS/EXECUTED {ledger_path}#VER-ID "
                    "with matching scope, valid timestamps, and no later invalidating event",
                )
        if criterion.get("status") == "NOT_APPLICABLE" and not str(criterion.get("limitations", "")).strip():
            report.fail("GATE_CRITERION_NA", f"{label}: NOT_APPLICABLE requires a rationale in limitations")
    duplicates = unique_duplicates(criterion_ids)
    if duplicates:
        report.fail("GATE_CRITERION_ID", f"{source}: duplicate criterion IDs {sorted(duplicates)}")
    required_criteria_by_gate = contracts.get("gate_required_criteria", {})
    required_criteria = (
        set(required_criteria_by_gate.get(gate_id, []))
        if isinstance(required_criteria_by_gate, Mapping) and isinstance(gate_id, str)
        else set()
    )
    presented_criteria = set(criterion_ids)
    missing_criteria = sorted(required_criteria - presented_criteria)
    if missing_criteria:
        report.fail(
            "GATE_CRITERIA_COVERAGE",
            f"{source}: {gate_id} is missing canonical criteria {missing_criteria}",
        )
    if contracts.get("gate_criteria_allow_extensions") is False:
        unknown_criteria = sorted(presented_criteria - required_criteria)
        if unknown_criteria:
            report.fail(
                "GATE_CRITERIA_COVERAGE",
                f"{source}: {gate_id} has non-canonical criteria {unknown_criteria}",
            )
    for index, criterion in enumerate(criteria):
        if (
            isinstance(criterion, Mapping)
            and criterion.get("id") in required_criteria
            and criterion.get("required") is not True
        ):
            report.fail(
                "GATE_CRITERIA_COVERAGE",
                f"{source}.criteria[{index}]: canonical gate criteria must set required=true",
            )

    conditions = record.get("conditions")
    if not isinstance(conditions, list):
        report.fail("GATE_CONDITION", f"{source}.conditions must be a list")
        conditions = []
    open_conditions = 0
    condition_ids: list[str] = []
    for index, condition in enumerate(conditions):
        label = f"{source}.conditions[{index}]"
        if not isinstance(condition, Mapping):
            report.fail("GATE_CONDITION", f"{label} must be an object")
            continue
        missing = require_fields(condition, contracts.get("gate_condition_required_fields", []))
        if missing:
            report.fail("GATE_CONDITION", f"{label} missing fields: {', '.join(missing)}")
            continue
        if is_nonempty_string(condition.get("id")):
            condition_ids.append(str(condition["id"]))
        else:
            report.fail("GATE_CONDITION", f"{label}.id must be a non-empty string")
        for field, key in (
            ("status", "conditions.status"),
            ("residual_risk", "conditions.residual_risk"),
            ("authority_state", "conditions.authority_state"),
        ):
            _enum_field(report, contracts, condition.get(field), field_enums.get(key), "GATE_CONDITION_ENUM", f"{label}.{field}")
        if not isinstance(condition.get("non_blocking"), bool):
            report.fail("GATE_CONDITION", f"{label}.non_blocking must be a boolean")
        if condition.get("status") == "OPEN":
            open_conditions += 1
            due_time = parse_iso8601(condition.get("due_at"))
            gate_time = parse_iso8601(record.get("timestamp"))
            if due_time is None or gate_time is None or due_time <= gate_time:
                report.fail(
                    "GATE_CONDITION_EXPIRY",
                    f"{label}.due_at must be a zoned time after the gate decision",
                )
            if passing and condition.get("non_blocking") is not True:
                report.fail(
                    "GATE_CONDITION_BLOCKING",
                    f"{label}: every OPEN condition on a passing gate must set non_blocking=true",
                )
            forbidden_risks = set(invariants.get("open_condition_forbidden_residual_risks", []))
            if (
                passing
                and isinstance(condition.get("residual_risk"), str)
                and condition.get("residual_risk") in forbidden_risks
            ):
                report.fail(
                    "GATE_CONDITION_RISK",
                    f"{label}: OPEN condition residual risk {condition.get('residual_risk')} forbids a passing gate",
                )
            if passing and condition.get("authority_state") in {"DENIED", "EXPIRED", "UNKNOWN"}:
                report.fail(
                    "GATE_CONDITION_AUTHORITY",
                    f"{label}: OPEN condition has non-permissive authority state {condition.get('authority_state')}",
                )
        elif condition.get("due_at") is not None and parse_iso8601(condition.get("due_at")) is None:
            report.fail(
                "GATE_CONDITION_EXPIRY",
                f"{label}.due_at must be null or an ISO-8601 time with timezone",
            )
        evidence_refs = condition.get("evidence_refs")
        _check_evidence_refs(
            root,
            evidence_refs,
            report,
            code="GATE_CONDITION_EVIDENCE",
            field=f"{label}.evidence_refs",
        )
        terminal_evidence_statuses = set(
            invariants.get(
                "terminal_condition_statuses_requiring_evidence",
                ["SATISFIED", "EXPIRED", "CANCELLED"],
            )
        )
        if condition.get("status") in terminal_evidence_statuses:
            if not isinstance(evidence_refs, list) or not evidence_refs:
                report.fail(
                    "GATE_CONDITION_EVIDENCE",
                    f"{label}: {condition.get('status')} requires resolved evidence_refs",
                )
        if condition.get("status") == "SATISFIED":
            if condition.get("authority_state") not in {"NOT_REQUIRED", "CONFIRMED"}:
                report.fail(
                    "GATE_CONDITION_AUTHORITY",
                    f"{label}: SATISFIED cannot retain unresolved authority",
                )
        if passing and condition.get("status") in {"EXPIRED", "CANCELLED"}:
            report.fail(
                "GATE_CONDITION_INVARIANT",
                f"{label}: {condition.get('status')} cannot be carried by a passing gate record",
            )
        for field in ("description", "impact", "owner", "due_or_trigger", "verification_method"):
            if not is_nonempty_string(condition.get(field)):
                report.fail("GATE_CONDITION", f"{label}.{field} must be a non-empty string")
        if condition.get("authority_state") == "CONFIRMED":
            gate_authority = record.get("authority")
            if (
                not isinstance(gate_authority, Mapping)
                or gate_authority.get("required") is not True
                or gate_authority.get("state") != "CONFIRMED"
            ):
                report.fail(
                    "GATE_CONDITION_AUTHORITY",
                    f"{label}: CONFIRMED must bind to the gate's required, confirmed authority record",
                )
    duplicates = unique_duplicates(condition_ids)
    if duplicates:
        report.fail("GATE_CONDITION_ID", f"{source}: duplicate condition IDs {sorted(duplicates)}")
    if decision == "PASS" and open_conditions:
        report.fail("GATE_CONDITION_INVARIANT", f"{source}: PASS forbids OPEN conditions")
    if decision == "PASS_WITH_CONDITIONS" and not open_conditions:
        report.fail("GATE_CONDITION_INVARIANT", f"{source}: PASS_WITH_CONDITIONS requires an OPEN condition")

    forbidden_passing_risks = set(
        invariants.get("passing_gate_forbidden_residual_risks", [])
    )
    if passing and record.get("residual_risk") in forbidden_passing_risks:
        report.fail(
            "GATE_RESIDUAL_RISK",
            f"{source}: passing decision cannot accept residual risk {record.get('residual_risk')!r}",
        )

    authority_risks = set(invariants.get("passing_gate_residual_risk_requiring_confirmed_authority", []))
    _check_authority(
        root,
        record.get("authority"),
        contracts,
        report,
        prefix=f"{source}.authority",
        pass_decision=passing,
        must_confirm=(
            passing
            and isinstance(record.get("residual_risk"), str)
            and record.get("residual_risk") in authority_risks
        ),
        expected_scope=record.get("scope"),
        expected_scope_ref=record.get("scope_ref"),
        expected_subject_type="GATE",
        expected_subject_id=record.get("record_id"),
        not_after=record.get("timestamp"),
    )
    evidence = record.get("evidence")
    _check_evidence_refs(
        root,
        evidence,
        report,
        code="GATE_EVIDENCE",
        field=f"{source}.evidence",
    )
    if passing and (not isinstance(evidence, list) or not evidence):
        report.fail("GATE_EVIDENCE", f"{source}: passing decision requires gate evidence")

    override = record.get("override")
    if override is not None:
        if not isinstance(override, Mapping):
            report.fail("GATE_OVERRIDE", f"{source}.override must be an object")
        else:
            missing = require_fields(override, contracts.get("override_required_fields", []))
            if missing:
                report.fail("GATE_OVERRIDE", f"{source}.override missing fields: {', '.join(missing)}")
            _enum_field(
                report,
                contracts,
                override.get("status"),
                field_enums.get("override.status"),
                "GATE_OVERRIDE_ENUM",
                f"{source}.override.status",
            )
            _enum_field(
                report,
                contracts,
                override.get("risk_level"),
                field_enums.get("override.risk_level"),
                "GATE_OVERRIDE_ENUM",
                f"{source}.override.risk_level",
            )
            _enum_field(
                report,
                contracts,
                override.get("residual_risk"),
                field_enums.get("override.residual_risk"),
                "GATE_OVERRIDE_ENUM",
                f"{source}.override.residual_risk",
            )
            if (
                not isinstance(override.get("type"), str)
                or override.get("type") not in enum_values(contracts, "work_mode")
            ):
                report.fail("GATE_OVERRIDE", f"{source}.override.type is not a canonical work_mode")
            for field in ("reduced_gates", "compensating_controls", "follow_up"):
                values = override.get(field)
                if (
                    not isinstance(values, list)
                    or not all(is_nonempty_string(item) for item in values)
                    or len(values) != len(set(values))
                ):
                    report.fail(
                        "GATE_OVERRIDE",
                        f"{source}.override.{field} must be a unique string list",
                    )
            if not is_nonempty_string(override.get("override_id")):
                report.fail("GATE_OVERRIDE", f"{source}.override.override_id must be non-empty")
            if override.get("scope") != record.get("scope"):
                report.fail(
                    "GATE_OVERRIDE_BINDING",
                    f"{source}.override.scope must match the governed gate scope in every status",
                )
            if override.get("scope_ref") != record.get("scope_ref"):
                report.fail(
                    "GATE_OVERRIDE_BINDING",
                    f"{source}.override.scope_ref must match the governed gate scope_ref in every status",
                )
            override_evidence = override.get("evidence_refs")
            _check_evidence_refs(
                root,
                override_evidence,
                report,
                code="GATE_OVERRIDE_EVIDENCE",
                field=f"{source}.override.evidence_refs",
            )
            terminal_override_statuses = set(
                contracts.get("override_invariants", {}).get(
                    "terminal_override_statuses_requiring_evidence", []
                )
            )
            if (
                override.get("status") in terminal_override_statuses
                and (not isinstance(override_evidence, list) or not override_evidence)
            ):
                report.fail(
                    "GATE_OVERRIDE_EVIDENCE",
                    f"{source}.override {override.get('status')} requires resolved evidence_refs",
                )
            if override.get("status") == "SATISFIED":
                terminal_authority = override.get("authority")
                if (
                    not isinstance(terminal_authority, Mapping)
                    or terminal_authority.get("state") not in {"NOT_REQUIRED", "CONFIRMED"}
                ):
                    report.fail(
                        "GATE_OVERRIDE_AUTHORITY",
                        f"{source}.override SATISFIED cannot retain unresolved authority",
                    )
            if passing and override.get("status") in {"EXPIRED", "REVOKED"}:
                report.fail(
                    "GATE_OVERRIDE_INVARIANT",
                    f"{source}.override {override.get('status')} cannot be carried by a passing gate",
                )
            reduced_gates = override.get("reduced_gates")
            if isinstance(reduced_gates, list):
                unknown_gates = sorted(
                    item
                    for item in reduced_gates
                    if isinstance(item, str) and item not in set(contracts.get("semantic_gates", []))
                )
                if unknown_gates:
                    report.fail("GATE_OVERRIDE", f"{source}.override has unknown reduced_gates: {unknown_gates}")
            if override.get("status") == "ACTIVE":
                override_rules = contracts.get("override_invariants", {})
                eligible_types = set(override_rules.get("eligible_active_types", []))
                if override.get("type") not in eligible_types:
                    report.fail(
                        "GATE_OVERRIDE_TYPE",
                        f"{source}.override.type={override.get('type')!r} is not eligible for an ACTIVE override",
                    )
                for field in ("scope", "reason", "expires_or_revalidates"):
                    if not is_nonempty_string(override.get(field)):
                        report.fail(
                            "GATE_OVERRIDE",
                            f"{source}.override.{field} must be a non-empty string when ACTIVE",
                        )
                expiry_time = parse_iso8601(override.get("expires_at"))
                gate_time = parse_iso8601(record.get("timestamp"))
                if expiry_time is None or gate_time is None or expiry_time <= gate_time:
                    report.fail(
                        "GATE_OVERRIDE_EXPIRY",
                        f"{source}.override.expires_at must be a zoned time after the gate decision",
                    )
                controls = override.get("compensating_controls")
                if not isinstance(controls, list) or not controls:
                    report.fail("GATE_OVERRIDE", f"{source}.override.compensating_controls must be non-empty when ACTIVE")
                if override_rules.get("active_requires_nonempty_reduced_gates_and_follow_up"):
                    for field in ("reduced_gates", "follow_up"):
                        if not isinstance(override.get(field), list) or not override.get(field):
                            report.fail(
                                "GATE_OVERRIDE",
                                f"{source}.override.{field} must be non-empty when ACTIVE",
                            )
                if (
                    override_rules.get("active_reduced_gates_must_include_record_gate")
                    and isinstance(override.get("reduced_gates"), list)
                    and record.get("gate_id") not in override.get("reduced_gates")
                ):
                    report.fail(
                        "GATE_OVERRIDE_BINDING",
                        f"{source}.override must include the current gate_id in reduced_gates",
                    )
                forbidden_residual = set(override_rules.get("active_forbidden_residual_risks", []))
                forbidden_risk_levels = set(
                    override_rules.get("active_forbidden_risk_levels", [])
                )
                if override.get("risk_level") in forbidden_risk_levels:
                    report.fail(
                        "GATE_OVERRIDE_RISK",
                        f"{source}.override risk level {override.get('risk_level')} cannot be accepted by an ACTIVE override",
                    )
                if (
                    isinstance(override.get("residual_risk"), str)
                    and override.get("residual_risk") in forbidden_residual
                ):
                    report.fail(
                        "GATE_OVERRIDE_RISK",
                        f"{source}.override residual risk {override.get('residual_risk')} cannot be accepted by an ACTIVE override",
                    )
                authority_risks = set(
                    override_rules.get("active_risk_levels_requiring_confirmed_authority", [])
                )
                override_must_confirm = (
                    isinstance(override.get("risk_level"), str)
                    and override.get("risk_level") in authority_risks
                )
            else:
                override_must_confirm = False
            _check_authority(
                root,
                override.get("authority"),
                contracts,
                report,
                prefix=f"{source}.override.authority",
                pass_decision=override.get("status") == "ACTIVE",
                must_confirm=override_must_confirm,
                expected_scope=override.get("scope"),
                expected_scope_ref=override.get("scope_ref"),
                expected_subject_type="OVERRIDE",
                expected_subject_id=override.get("override_id"),
                not_after=record.get("timestamp"),
            )


def _validate_legacy_gate_record(
    record: Mapping[str, Any],
    contracts: Mapping[str, Any],
    report: Report,
    *,
    source: str,
) -> None:
    """Admit one explicitly superseded, non-governing pre-contract record."""

    for field in ("record_id", "timestamp", "gate_id", "scope", "decision"):
        if field not in record:
            report.fail("GATE_LEGACY", f"{source}: legacy gate lacks identity field {field}")
    if not is_nonempty_string(record.get("record_id")):
        report.fail("GATE_LEGACY", f"{source}: legacy record_id must be non-empty")
    if parse_iso8601(record.get("timestamp")) is None:
        report.fail("GATE_LEGACY", f"{source}: legacy timestamp must be zoned")
    if record.get("gate_id") not in contracts.get("semantic_gates", []):
        report.fail("GATE_LEGACY", f"{source}: legacy gate_id is not canonical")
    if record.get("decision") not in enum_values(contracts, "gate_status"):
        report.fail("GATE_LEGACY", f"{source}: legacy decision is not canonical")
    if record.get("conditions") not in (None, []):
        report.fail("GATE_LEGACY", f"{source}: unresolved legacy conditions cannot use degraded migration")
    if record.get("override") is not None:
        report.fail("GATE_LEGACY", f"{source}: legacy override cannot use degraded migration")


def _check_gate_files(
    root: Path,
    contracts: Mapping[str, Any],
    report: Report,
) -> list[tuple[str, Mapping[str, Any]]]:
    gate_dir = root / ".agent" / "gates"
    if not gate_dir.is_dir():
        return []
    records: list[tuple[str, Mapping[str, Any]]] = []
    for path in sorted(gate_dir.rglob("*.json")):
        source = path.relative_to(root).as_posix()
        try:
            record = load_json_object(path)
        except (OSError, UnicodeError, ValueError) as exc:
            report.fail("GATE_RECORD", str(exc), path.relative_to(root))
            continue
        records.append((source, record))
    superseded_ids = {
        str(record["supersedes"])
        for _, record in records
        if is_nonempty_string(record.get("supersedes"))
    }
    rules = contracts.get("runtime_gate_rules", {})
    allowed_legacy_missing = set(rules.get("legacy_gate_allowed_missing_fields", []))
    for source, record in records:
        missing = set(require_fields(record, contracts.get("gate_required_fields", [])))
        legacy = (
            bool(missing)
            and missing <= allowed_legacy_missing
            and rules.get("legacy_gate_requires_superseding_record")
            and record.get("record_id") in superseded_ids
        )
        if legacy:
            _validate_legacy_gate_record(record, contracts, report, source=source)
        else:
            validate_gate_record(record, contracts, report, root=root, source=source)
    _check_gate_history(records, contracts, report)
    return records


def _check_gate_history(
    records: list[tuple[str, Mapping[str, Any]]],
    contracts: Mapping[str, Any],
    report: Report,
) -> None:
    """Validate the observable append-only gate chain in the current snapshot."""

    history_rules = contracts.get("gate_history_invariants", {})
    by_id: dict[str, tuple[str, Mapping[str, Any]]] = {}
    identifiers: list[str] = []
    for source, record in records:
        identifier = record.get("record_id")
        if is_nonempty_string(identifier):
            identifiers.append(str(identifier))
            by_id.setdefault(str(identifier), (source, record))
    duplicates = unique_duplicates(identifiers)
    if history_rules.get("record_id_must_be_unique") and duplicates:
        report.fail("GATE_HISTORY_ID", f"duplicate gate record IDs: {', '.join(sorted(duplicates))}")

    predecessor_of: dict[str, str] = {}
    for source, record in records:
        identifier = record.get("record_id")
        supersedes = record.get("supersedes")
        if not is_nonempty_string(identifier) or supersedes is None:
            continue
        if not is_nonempty_string(supersedes) or supersedes not in by_id:
            if history_rules.get("supersedes_must_be_null_or_existing_older_record_id"):
                report.fail("GATE_HISTORY_SUPERSEDES", f"{source}: supersedes does not resolve to an existing record ID")
            continue
        old_source, old = by_id[str(supersedes)]
        predecessor_of[str(identifier)] = str(supersedes)
        current_time = parse_iso8601(record.get("timestamp"))
        old_time = parse_iso8601(old.get("timestamp"))
        if (
            history_rules.get("supersedes_must_be_null_or_existing_older_record_id")
            and current_time is not None
            and old_time is not None
            and current_time <= old_time
        ):
            report.fail(
                "GATE_HISTORY_ORDER",
                f"{source}: superseded record {old_source} must have an older timestamp",
            )
        legacy_scope_ref = (
            not is_nonempty_string(old.get("scope_ref"))
            and "scope_ref"
            in set(
                contracts.get("runtime_gate_rules", {}).get(
                    "legacy_gate_allowed_missing_fields", []
                )
            )
        )
        if history_rules.get("superseded_record_must_match_gate_and_scope") and (
            old.get("gate_id") != record.get("gate_id")
            or old.get("scope") != record.get("scope")
            or (not legacy_scope_ref and old.get("scope_ref") != record.get("scope_ref"))
        ):
            report.fail(
                "GATE_HISTORY_SCOPE",
                f"{source}: superseded record must match gate_id and scope",
            )

    if history_rules.get("supersession_cycles_are_forbidden"):
        for identifier in predecessor_of:
            seen: set[str] = set()
            current = identifier
            while current in predecessor_of:
                if current in seen:
                    report.fail("GATE_HISTORY_CYCLE", f"supersession cycle includes {current}")
                    break
                seen.add(current)
                current = predecessor_of[current]

    # Multiple records for one semantic gate/scope are an observable reopening.
    # A linear chain makes the previous immutable decision explicit rather than
    # silently replacing it or creating two simultaneous current decisions.
    groups: dict[tuple[Any, Any], list[tuple[str, Mapping[str, Any]]]] = defaultdict(list)
    for source, record in records:
        gate_id = record.get("gate_id")
        scope_ref = record.get("scope_ref")
        if not isinstance(gate_id, str) or not isinstance(scope_ref, str):
            continue
        groups[(gate_id, scope_ref)].append((source, record))
    if contracts.get("gate_invariants", {}).get("prior_gate_decisions_are_append_only_and_reopened_by_new_record"):
        for (gate_id, scope_ref), group in groups.items():
            if len(group) < 2:
                continue
            ordered = sorted(
                group,
                key=lambda item: parse_iso8601(item[1].get("timestamp"))
                or parse_iso8601("0001-01-01T00:00:00+00:00"),
            )
            for previous, current in zip(ordered, ordered[1:]):
                previous_id = previous[1].get("record_id")
                if current[1].get("supersedes") != previous_id:
                    report.fail(
                        "GATE_HISTORY_REOPEN",
                        f"{current[0]}: reopening {gate_id!r} for scope_ref {scope_ref!r} must supersede {previous_id!r}",
                    )

    if records and not any(item.level == "FAIL" and item.code.startswith("GATE_HISTORY") for item in report.findings):
        report.pass_("GATE_HISTORY", f"validated {len(records)} append-only gate record(s)")


def _check_verification(
    root: Path,
    records: list[Mapping[str, Any]],
    items: Mapping[str, Mapping[str, Any]],
    contracts: Mapping[str, Any],
    report: Report,
) -> None:
    identifiers: list[str] = []
    field_enums = contracts.get("verification_record_field_enums", {})
    invariants = contracts.get("verification_invariants", {})
    pass_evidence_kinds = set(invariants.get("pass_allowed_evidence_kinds", []))
    zero_exit_kinds = set(invariants.get("pass_evidence_kinds_requiring_zero_exit_status", []))
    null_exit_kinds = set(invariants.get("pass_evidence_kinds_allowing_null_exit_status", []))
    prior_time = None
    prior_stream_time: dict[tuple[str, str], Any] = {}
    for index, record in enumerate(records, 1):
        identifier = record.get("id", f"index-{index}")
        if is_nonempty_string(identifier):
            identifiers.append(str(identifier))
        else:
            report.fail("VERIFY_ID", f"record {index}: id must be non-empty")
        missing = require_fields(record, contracts["verification_record_required_fields"])
        if missing:
            report.fail("VERIFY_FIELDS", f"{identifier}: missing {', '.join(missing)}")
        result = record.get("result")
        task = record.get("task")
        if task is not None and not is_nonempty_string(task):
            report.fail("VERIFY_TASK", f"{identifier}: task must be null/absent or a non-empty backlog ID")
        elif is_nonempty_string(task) and task not in items:
            report.fail("VERIFY_TASK", f"{identifier}: unknown backlog task {task}")
        for field, enum_name in field_enums.items():
            _enum_field(report, contracts, record.get(field), enum_name, "VERIFY_RESULT" if field == "result" else "VERIFY_ENUM", f"{identifier}.{field}")
        timestamp = parse_iso8601(record.get("timestamp"))
        observed_at = parse_iso8601(record.get("observed_at"))
        if timestamp is None:
            report.fail("VERIFY_TIMESTAMP", f"{identifier}: timestamp must include timezone")
        elif prior_time is not None and timestamp < prior_time:
            report.fail("VERIFY_ORDER", f"{identifier}: verification ledger is not append-ordered")
        if timestamp is not None:
            prior_time = timestamp
            stream_key = _verification_stream_key(record)
            if stream_key is not None:
                previous_stream_time = prior_stream_time.get(stream_key)
                if previous_stream_time is not None and timestamp <= previous_stream_time:
                    report.fail(
                        "VERIFY_ORDER",
                        f"{identifier}: verification stream timestamps must strictly increase",
                    )
                prior_stream_time[stream_key] = timestamp
        if observed_at is None:
            report.fail("VERIFY_TIMESTAMP", f"{identifier}: observed_at must include timezone")
        if timestamp is not None and observed_at is not None and observed_at > timestamp:
            report.fail("VERIFY_TIMESTAMP", f"{identifier}: observed_at must not be later than record timestamp")
        exit_status = record.get("exit_status")
        if exit_status is not None and (not isinstance(exit_status, int) or isinstance(exit_status, bool)):
            report.fail("VERIFY_EXIT_STATUS", f"{identifier}: exit_status must be an integer or null")
        if not isinstance(record.get("artifacts"), list):
            report.fail("VERIFY_ARTIFACTS", f"{identifier}: artifacts must be a list")
        else:
            _check_evidence_refs(
                root,
                record.get("artifacts"),
                report,
                code="VERIFY_ARTIFACT_REF",
                field=f"{identifier}.artifacts",
                allow_directory=True,
            )
        if result == "PASS":
            evidence_kind = record.get("evidence_kind")
            if evidence_kind in zero_exit_kinds and exit_status != 0:
                report.fail(
                    "VERIFY_PASS_CLAIM",
                    f"{identifier}: PASS evidence_kind={evidence_kind} requires exit_status=0",
                )
            if exit_status is None and evidence_kind not in null_exit_kinds:
                report.fail(
                    "VERIFY_PASS_CLAIM",
                    f"{identifier}: PASS evidence_kind={evidence_kind!r} does not allow null exit_status",
                )
            if exit_status is not None and exit_status != 0:
                report.fail("VERIFY_PASS_CLAIM", f"{identifier}: a non-null PASS exit_status must be 0")
            if invariants.get("pass_requires_executed_procedure") and record.get("procedure_status") != "EXECUTED":
                report.fail("VERIFY_PASS_CLAIM", f"{identifier}: PASS requires procedure_status=EXECUTED")
            if not is_nonempty_string(record.get("procedure")):
                report.fail("VERIFY_PASS_CLAIM", f"{identifier}: PASS requires an executed procedure")
            if pass_evidence_kinds and record.get("evidence_kind") not in pass_evidence_kinds:
                report.fail(
                    "VERIFY_PASS_EVIDENCE_KIND",
                    f"{identifier}: evidence_kind {record.get('evidence_kind')!r} cannot support PASS",
                )
            if invariants.get("pass_requires_current_freshness") and record.get("freshness") != "CURRENT":
                report.fail("VERIFY_PASS_FRESHNESS", f"{identifier}: PASS requires CURRENT evidence")
            if invariants.get("pass_requires_nonempty_scope_environment_and_evidence"):
                for field in ("scope", "environment", "evidence"):
                    if not is_nonempty_string(record.get(field)):
                        report.fail("VERIFY_PASS_CLAIM", f"{identifier}: PASS requires non-empty {field}")
            if invariants.get("pass_requires_limitations_field_even_when_none_are_known") and not is_nonempty_string(
                record.get("limitations")
            ):
                report.fail("VERIFY_LIMITATIONS", f"{identifier}: PASS requires explicit limitations")
    duplicates = unique_duplicates(identifiers)
    if duplicates:
        report.fail("VERIFY_DUPLICATE_ID", f"duplicate verification IDs: {', '.join(sorted(duplicates))}")
    if not any(item.level == "FAIL" and item.code.startswith("VERIFY") for item in report.findings):
        report.pass_("VERIFY_CONTRACT", f"validated {len(records)} verification record(s)")


def _check_reconciliation(
    root: Path,
    state: Mapping[str, Any],
    items: Mapping[str, Mapping[str, Any]],
    log: list[Mapping[str, Any]],
    verification: list[Mapping[str, Any]],
    gate_records: list[tuple[str, Mapping[str, Any]]],
    contracts: Mapping[str, Any],
    report: Report,
) -> None:
    reconciliation_rules = contracts.get("runtime_reconciliation_rules", {})
    active_statuses = set(reconciliation_rules.get("active_backlog_statuses", []))
    if (
        reconciliation_rules.get("done_state_requires_verification_pass")
        and state.get("status") == "DONE"
        and state.get("verification_state") != "PASS"
    ):
        report.fail(
            "RECONCILE_VERIFICATION_STATE",
            "state.status=DONE requires verification_state=PASS backed by current applicable evidence",
        )
    active_task = state.get("active_task")
    if is_nonempty_string(active_task):
        item = items.get(active_task)
        if item is None:
            report.fail("RECONCILE_ACTIVE_TASK", f"state references unknown active_task {active_task}")
        else:
            if (
                not isinstance(item.get("status"), str)
                or item.get("status") not in {"IN_PROGRESS", "VERIFY", "BLOCKED"}
            ):
                report.fail("RECONCILE_ACTIVE_TASK", f"active task {active_task} has incompatible backlog status {item.get('status')}")
            if item.get("stage") != state.get("lifecycle_stage"):
                report.fail(
                    "RECONCILE_STAGE",
                    f"state stage {state.get('lifecycle_stage')} differs from active task stage {item.get('stage')}",
                )
            if (
                reconciliation_rules.get("active_task_status_must_match_state")
                and item.get("status") != state.get("status")
            ):
                report.fail(
                    "RECONCILE_STATUS",
                    f"state status {state.get('status')!r} differs from active task status {item.get('status')!r}",
                )
            if contracts.get("next_action_invariants", {}).get(
                "active_state_pointer_must_match_active_backlog_action"
            ):
                action = item.get("next_action")
                backlog_action_id = action.get("id") if isinstance(action, Mapping) else None
                if state.get("active_action_id") != backlog_action_id:
                    report.fail(
                        "RECONCILE_NEXT_ACTION",
                        "state.active_action_id does not match the active backlog item's next_action.id",
                    )
    active_items = [
        identifier
        for identifier, item in items.items()
        if isinstance(item.get("status"), str) and item.get("status") in active_statuses
    ]
    if (
        isinstance(state.get("status"), str)
        and state.get("status") in active_statuses
        and not is_nonempty_string(active_task)
    ):
        report.fail(
            "RECONCILE_ACTIVE_TASK",
            f"state status {state.get('status')} requires a resolvable active_task",
        )
    in_progress = [identifier for identifier, item in items.items() if item.get("status") == "IN_PROGRESS"]
    if active_task is None and active_items:
        report.fail(
            "RECONCILE_ACTIVE_TASK",
            f"backlog has active items but state active_task is null: {active_items}",
        )
    if (
        contracts.get("next_action_invariants", {}).get("inactive_state_forbids_action_pointer")
        and active_task is None
        and state.get("active_action_id") is not None
    ):
        report.fail("RECONCILE_NEXT_ACTION", "state without active_task must not retain active_action_id")
    if len(in_progress) > 1:
        owners = defaultdict(list)
        for identifier in in_progress:
            owners[str(items[identifier].get("owner"))].append(identifier)
        duplicate_owners = {owner: values for owner, values in owners.items() if len(values) > 1}
        if duplicate_owners:
            report.warn("RECONCILE_PARALLEL", f"multiple IN_PROGRESS items share owner: {dict(duplicate_owners)}")
    if log:
        tail_event = log[-1]
        last_id = tail_event.get("event_id")
        if state.get("last_event_id") != last_id:
            report.fail("RECONCILE_LAST_EVENT", f"state last_event_id={state.get('last_event_id')!r}, log tail={last_id!r}")
        log_action_rules = contracts.get("execution_log_action_binding", {})
        log_action_field = str(log_action_rules.get("field", "active_action_id"))
        if log_action_rules.get("tail_requires_field") and log_action_field not in tail_event:
            report.fail(
                "RECONCILE_LOG_ACTION",
                f"execution-log tail must declare {log_action_field}",
            )
        tail_action_id = tail_event.get(log_action_field)
        if (
            log_action_rules.get("tail_must_match_state")
            and tail_action_id != state.get("active_action_id")
        ):
            report.fail(
                "RECONCILE_LOG_ACTION",
                f"execution-log tail {log_action_field} must match state.active_action_id",
            )
        if (
            log_action_rules.get("tail_task_must_match_active_task")
            and is_nonempty_string(active_task)
            and tail_event.get("task") != active_task
        ):
            report.fail(
                "RECONCILE_LOG_ACTION",
                "execution-log tail task must match state.active_task",
            )
        if (
            log_action_rules.get("inactive_tail_requires_null")
            and active_task is None
            and tail_action_id is not None
        ):
            report.fail(
                "RECONCILE_LOG_ACTION",
                f"execution-log tail {log_action_field} must be null when state.active_task is null",
            )
        tail_task = tail_event.get("task")
        if is_nonempty_string(tail_task):
            expected_suffixes: set[str] = set()
            if (
                tail_task == active_task
                and is_nonempty_string(tail_action_id)
                and tail_action_id.startswith(f"{tail_task}:")
            ):
                expected_suffixes.add(tail_action_id[len(str(tail_task)) + 1 :])
            for field in log_action_rules.get("tail_authoritative_text_fields", []):
                text = tail_event.get(field)
                if not isinstance(field, str) or not isinstance(text, str):
                    continue
                mentioned = _same_task_action_suffixes(
                    text,
                    task_id=str(tail_task),
                    rules=contracts.get("next_action_invariants", {}),
                )
                if mentioned - expected_suffixes:
                    report.fail(
                        "RECONCILE_LOG_ACTION",
                        f"execution-log tail {field} references an action ID other than "
                        f"{log_action_field}",
                    )
        tail_time = parse_iso8601(tail_event.get("timestamp"))
        state_time = parse_iso8601(state.get("updated_at"))
        if tail_time is not None and state_time is not None and tail_time > state_time:
            report.fail(
                "RECONCILE_STATE_ORDER",
                "state.updated_at must be at or after the execution-log event referenced by last_event_id",
            )
    elif state.get("last_event_id") is not None:
        report.fail("RECONCILE_LAST_EVENT", "state has last_event_id but execution log is empty")
    state_time = parse_iso8601(state.get("updated_at"))
    if reconciliation_rules.get("control_ledgers_must_not_postdate_state"):
        later_verification = [
            record.get("id")
            for record in verification
            if (
                (record_time := parse_iso8601(record.get("timestamp"))) is not None
                and state_time is not None
                and record_time > state_time
            )
        ]
        if later_verification:
            report.fail(
                "RECONCILE_VERIFICATION_ORDER",
                f"verification ledger advances beyond state.updated_at: {later_verification}",
            )
        authority_path = root / str(
            contracts.get("runtime_gate_rules", {}).get(
                "authority_ledger_path", ".agent/authority.jsonl"
            )
        )
        if authority_path.is_file():
            try:
                authority_records = load_jsonl(authority_path)
            except (OSError, UnicodeError, ValueError) as exc:
                report.fail("RECONCILE_AUTHORITY_ORDER", f"cannot read authority ledger: {exc}")
            else:
                later_authority = [
                    record.get("id")
                    for record in authority_records
                    if (
                        (record_time := parse_iso8601(record.get("timestamp"))) is not None
                        and state_time is not None
                        and record_time > state_time
                    )
                ]
                if later_authority:
                    report.fail(
                        "RECONCILE_AUTHORITY_ORDER",
                        f"authority ledger advances beyond state.updated_at: {later_authority}",
                    )
        later_gates = [
            record.get("record_id")
            for _, record in gate_records
            if (
                (gate_time := parse_iso8601(record.get("timestamp"))) is not None
                and state_time is not None
                and gate_time > state_time
            )
        ]
        if later_gates:
            report.fail(
                "RECONCILE_GATE_ORDER",
                f"gate ledger advances beyond state.updated_at: {later_gates}",
            )
    last_transition_by_task: dict[str, Mapping[str, Any]] = {}
    if reconciliation_rules.get("declared_log_transitions_must_match_current_records"):
        last_lifecycle: str | None = None
        for event in log:
            task = event.get("task")
            status_to = event.get("status_to")
            lifecycle_to = event.get("lifecycle_to")
            if is_nonempty_string(task) and isinstance(status_to, str):
                last_transition_by_task[str(task)] = event
            if isinstance(lifecycle_to, str):
                last_lifecycle = lifecycle_to
        transition_required_statuses = set(
            reconciliation_rules.get("statuses_requiring_declared_transition", [])
        )
        for task, item in items.items():
            transition = last_transition_by_task.get(task)
            item_status = item.get("status")
            if (
                isinstance(item_status, str)
                and item_status in transition_required_statuses
                and transition is None
            ):
                report.fail(
                    "RECONCILE_LOG_STATUS",
                    f"{task}: backlog status {item.get('status')!r} requires a declared log transition",
                )
            elif (
                transition is not None
                and item.get("status") != "UNKNOWN"
                and item.get("status") != transition.get("status_to")
            ):
                report.fail(
                    "RECONCILE_LOG_STATUS",
                    f"latest declared transition for {task} ends at {transition.get('status_to')}, backlog is {item.get('status')!r}",
                )
        if last_lifecycle is not None and state.get("lifecycle_stage") != last_lifecycle:
            report.fail(
                "RECONCILE_LOG_LIFECYCLE",
                f"latest declared lifecycle transition ends at {last_lifecycle}, state is {state.get('lifecycle_stage')!r}",
            )
    invalidating_types = set(reconciliation_rules.get("verification_invalidating_event_types", []))
    ledger_path = str(
        contracts.get("runtime_gate_rules", {}).get(
            "verification_ledger_path", ".agent/verification.jsonl"
        )
    )
    verification_by_id = {
        str(record["id"]): record
        for record in verification
        if is_nonempty_string(record.get("id"))
    }
    for task, item in items.items():
        if item.get("status") != "DONE":
            continue
        refs = item.get("evidence_refs") if isinstance(item.get("evidence_refs"), list) else []
        cited_ids = {
            fragment
            for reference_value in refs
            if isinstance(reference_value, str)
            for kind, target, fragment in [classify_link(reference_value)]
            if kind == "internal" and Path(target).as_posix() == ledger_path and fragment
        }
        cited_pass_times = [
            parse_iso8601(record.get("observed_at"))
            for identifier in cited_ids
            for record in [verification_by_id.get(identifier, {})]
            if (
                record.get("task") == task
                and record.get("result") == "PASS"
                and record.get("freshness") == "CURRENT"
                and record.get("procedure_status") == "EXECUTED"
            )
        ]
        valid_pass_times = [timestamp for timestamp in cited_pass_times if timestamp is not None]
        completion = last_transition_by_task.get(task)
        if reconciliation_rules.get("done_requires_complete_transition"):
            required_from = reconciliation_rules.get("done_complete_status_from")
            required_to = reconciliation_rules.get("done_complete_status_to")
            if (
                completion is None
                or effective_event_type(completion, contracts) != "COMPLETE"
                or completion.get("status_from") != required_from
                or completion.get("status_to") != required_to
                or completion.get("result") != "PASS"
            ):
                report.fail(
                    "RECONCILE_DONE_TRANSITION",
                    f"{task}: DONE requires the latest transition to be a PASS COMPLETE {required_from} -> {required_to}",
                )
        if not valid_pass_times:
            continue
        newest_pass_time = max(valid_pass_times)
        cited_record_times = [
            parse_iso8601(record.get("timestamp"))
            for identifier in cited_ids
            for record in [verification_by_id.get(identifier, {})]
            if (
                record.get("task") == task
                and record.get("result") == "PASS"
                and record.get("freshness") == "CURRENT"
                and record.get("procedure_status") == "EXECUTED"
            )
        ]
        valid_record_times = [timestamp for timestamp in cited_record_times if timestamp is not None]
        newest_record_time = max(valid_record_times) if valid_record_times else newest_pass_time
        if reconciliation_rules.get("done_complete_must_not_predate_cited_pass"):
            completion_time = parse_iso8601(completion.get("timestamp")) if completion is not None else None
            if (
                valid_record_times
                and (completion_time is None or completion_time < max(valid_record_times))
            ):
                report.fail(
                    "RECONCILE_DONE_TRANSITION",
                    f"{task}: DONE completion must not predate its cited CURRENT PASS verification",
                )
        invalidating_events = [
            event
            for event in log
            if (
                event.get("task") == task
                and (
                    event.get("type") in invalidating_types
                    or event.get("result") != "PASS"
                )
                and parse_iso8601(event.get("timestamp")) is not None
                and parse_iso8601(event.get("timestamp")) >= newest_pass_time
            )
        ]
        if invalidating_events:
            latest = invalidating_events[-1]
            report.fail(
                "RECONCILE_VERIFICATION_FRESHNESS",
                f"{task}: cited CURRENT PASS predates invalidating event {latest.get('event_id')}",
            )
    _check_runtime_gate(root, state, verification, log, gate_records, contracts, report)
    if not any(item.level == "FAIL" and item.code.startswith("RECONCILE") for item in report.findings):
        report.pass_("RECONCILE", "state, backlog, log, and active pointers agree")


def _check_open_gate_obligations(
    root: Path,
    state: Mapping[str, Any],
    log: list[Mapping[str, Any]],
    gate_records: list[tuple[str, Mapping[str, Any]]],
    contracts: Mapping[str, Any],
    report: Report,
) -> None:
    """Reconcile scope-stable conditions and overrides beyond the current pointer."""

    state_time = parse_iso8601(state.get("updated_at"))
    gate_rules = contracts.get("runtime_gate_rules", {})
    risk_order = {
        value: index
        for index, value in enumerate(gate_rules.get("risk_severity_order", []))
    }

    def reconcile_obligation_risk(scope_ref: str, label: str, *values: Any) -> None:
        if (
            not gate_rules.get("active_obligation_risk_cannot_exceed_runtime_risk")
            or scope_ref != state.get("active_task")
        ):
            return
        runtime_risk = state.get("risk_level")
        if runtime_risk not in risk_order:
            return
        for value in values:
            if value in risk_order and risk_order[str(value)] > risk_order[str(runtime_risk)]:
                report.fail(
                    "RECONCILE_GATE_RISK",
                    f"{label} risk {value} exceeds runtime risk_level={runtime_risk}",
                )
    operational_records = _operational_gate_records(
        state, log, gate_records, contracts
    )
    dated_records = [
        (source, record, gate_time)
        for source, record in operational_records
        if (gate_time := parse_iso8601(record.get("timestamp"))) is not None
    ]
    dated_records.sort(key=lambda item: (item[2], item[0]))
    latest_conditions: dict[tuple[str, str], tuple[Mapping[str, Any], Mapping[str, Any], Any]] = {}
    latest_overrides: dict[tuple[str, str], tuple[Mapping[str, Any], Mapping[str, Any], Any]] = {}
    condition_times: dict[tuple[str, str], Any] = {}
    override_times: dict[tuple[str, str], Any] = {}
    condition_terminal_debt: set[tuple[str, str]] = set()
    condition_closed: set[tuple[str, str]] = set()
    override_terminal_debt: set[tuple[str, str]] = set()
    override_closed: set[tuple[str, str]] = set()

    for source, record, gate_time in dated_records:
        scope_ref = record.get("scope_ref")
        conditions = record.get("conditions")
        if isinstance(scope_ref, str) and isinstance(conditions, list):
            for condition in conditions:
                if not isinstance(condition, Mapping) or not is_nonempty_string(condition.get("id")):
                    continue
                key = (scope_ref, str(condition["id"]))
                status = condition.get("status")
                if key in condition_closed:
                    report.fail(
                        "GATE_OBLIGATION_HISTORY",
                        f"{source}: satisfied condition {condition['id']} is closed; a new obligation requires a new ID",
                    )
                elif key in condition_terminal_debt and status != "SATISFIED":
                    report.fail(
                        "GATE_OBLIGATION_HISTORY",
                        f"{source}: condition {condition['id']} must resolve terminal debt with SATISFIED before any other update",
                    )
                if status in {"EXPIRED", "CANCELLED"}:
                    condition_terminal_debt.add(key)
                elif status == "SATISFIED":
                    condition_terminal_debt.discard(key)
                    condition_closed.add(key)
                prior_time = condition_times.get(key)
                if prior_time is not None and gate_time <= prior_time:
                    report.fail(
                        "GATE_OBLIGATION_HISTORY",
                        f"{source}: condition {condition['id']} updates require a later timestamp within {scope_ref}",
                    )
                condition_times[key] = gate_time
                if state_time is not None and gate_time <= state_time:
                    latest_conditions[key] = (record, condition, gate_time)

        override = record.get("override")
        if (
            isinstance(scope_ref, str)
            and isinstance(override, Mapping)
            and is_nonempty_string(override.get("override_id"))
        ):
            key = (scope_ref, str(override["override_id"]))
            status = override.get("status")
            if key in override_closed:
                report.fail(
                    "GATE_OBLIGATION_HISTORY",
                    f"{source}: satisfied override {override['override_id']} is closed; a new activation requires a new ID and authority",
                )
            elif key in override_terminal_debt and status != "SATISFIED":
                report.fail(
                    "GATE_OBLIGATION_HISTORY",
                    f"{source}: override {override['override_id']} must resolve terminal debt with SATISFIED before any other update",
                )
            if status in {"EXPIRED", "REVOKED"}:
                override_terminal_debt.add(key)
            elif status == "SATISFIED":
                override_terminal_debt.discard(key)
                override_closed.add(key)
            prior_time = override_times.get(key)
            if prior_time is not None and gate_time <= prior_time:
                report.fail(
                    "GATE_OBLIGATION_HISTORY",
                    f"{source}: override {override['override_id']} updates require a later timestamp within {scope_ref}",
                )
            override_times[key] = gate_time
            if state_time is not None and gate_time <= state_time:
                latest_overrides[key] = (record, override, gate_time)

    for (scope_ref, condition_id), (record, condition, _) in latest_conditions.items():
        status = condition.get("status")
        if (
            contracts.get("gate_invariants", {}).get(
                "terminal_nonresolution_conditions_remain_blocking"
            )
            and status in {"EXPIRED", "CANCELLED"}
        ):
            report.fail(
                "RECONCILE_GATE_CONDITION",
                f"{status} condition {condition_id} for {scope_ref} remains blocking until a later evidenced SATISFIED update",
            )
        if status != "OPEN":
            continue
        reconcile_obligation_risk(
            scope_ref,
            f"OPEN condition {condition_id}",
            condition.get("residual_risk"),
        )
        due_time = parse_iso8601(condition.get("due_at"))
        if due_time is None or state_time is None or due_time <= state_time:
            report.fail(
                "RECONCILE_GATE_CONDITION",
                f"OPEN condition {condition_id} for {scope_ref} is due and must reopen or block a later gate",
            )
        if condition.get("authority_state") == "CONFIRMED":
            authority_risks = set(
                contracts.get("gate_invariants", {}).get(
                    "passing_gate_residual_risk_requiring_confirmed_authority", []
                )
            )
            passing = record.get("decision") in set(
                contracts.get("gate_invariants", {}).get("pass_decisions", [])
            )
            _check_authority(
                root,
                record.get("authority"),
                contracts,
                report,
                prefix=f"condition[{scope_ref}/{condition_id}].authority",
                pass_decision=passing,
                must_confirm=passing and record.get("residual_risk") in authority_risks,
                expected_scope=record.get("scope"),
                expected_scope_ref=scope_ref,
                expected_subject_type="GATE",
                expected_subject_id=record.get("record_id"),
                not_after=record.get("timestamp"),
                valid_through=state.get("updated_at"),
            )

    overlays = state.get("work_mode_overlays")
    active_overlays = overlays if isinstance(overlays, list) else []
    active_modes = {
        value
        for value in [state.get("work_mode"), *active_overlays]
        if isinstance(value, str)
    }
    for (scope_ref, override_id), (record, override, _) in latest_overrides.items():
        override_status = override.get("status")
        if (
            contracts.get("override_invariants", {}).get(
                "terminal_nonresolution_overrides_remain_blocking"
            )
            and override_status in {"EXPIRED", "REVOKED"}
        ):
            report.fail(
                "RECONCILE_OVERRIDE_TERMINAL",
                f"{override_status} override {override_id} for {scope_ref} remains blocking until a later evidenced SATISFIED update",
            )
        if override_status != "ACTIVE":
            continue
        reconcile_obligation_risk(
            scope_ref,
            f"ACTIVE override {override_id}",
            override.get("risk_level"),
            override.get("residual_risk"),
        )
        if override.get("type") not in active_modes:
            report.fail(
                "RECONCILE_OVERRIDE_MODE",
                f"ACTIVE override {override_id} for {scope_ref} has type {override.get('type')!r} "
                "absent from current work mode and overlays",
            )
        expiry_time = parse_iso8601(override.get("expires_at"))
        if expiry_time is None or state_time is None or expiry_time <= state_time:
            report.fail(
                "RECONCILE_OVERRIDE_EXPIRY",
                f"ACTIVE override {override_id} for {scope_ref} must remain unexpired at state.updated_at",
            )
        override_risks = set(
            contracts.get("override_invariants", {}).get(
                "active_risk_levels_requiring_confirmed_authority", []
            )
        )
        _check_authority(
            root,
            override.get("authority"),
            contracts,
            report,
            prefix=f"override[{scope_ref}/{override_id}].authority",
            pass_decision=True,
            must_confirm=override.get("risk_level") in override_risks,
            expected_scope=override.get("scope"),
            expected_scope_ref=scope_ref,
            expected_subject_type="OVERRIDE",
            expected_subject_id=override_id,
            not_after=record.get("timestamp"),
            valid_through=state.get("updated_at"),
        )


def _governing_gate_sources(
    state: Mapping[str, Any],
    log: list[Mapping[str, Any]],
    gate_records: list[tuple[str, Mapping[str, Any]]],
    contracts: Mapping[str, Any],
) -> set[str]:
    """Return gates that currently govern a pointer or a durable obligation."""

    rules = contracts.get("runtime_gate_rules", {})
    reference = state.get(str(rules.get("record_ref_field", "last_gate_record")))
    governing = {str(reference)} if is_nonempty_string(reference) else set()
    operational_records = _operational_gate_records(
        state, log, gate_records, contracts
    )
    operational_superseded = _operationally_superseded_ids(
        operational_records, gate_records
    )
    governing.update(
        source
        for source, record in gate_records
        if (
            not is_nonempty_string(record.get("scope_ref"))
            and record.get("record_id") not in operational_superseded
        )
    )
    state_time = parse_iso8601(state.get("updated_at"))
    dated_records = [
        (source, record, gate_time)
        for source, record in operational_records
        if (
            (gate_time := parse_iso8601(record.get("timestamp"))) is not None
            and state_time is not None
            and gate_time <= state_time
        )
    ]
    dated_records.sort(key=lambda item: (item[2], item[0]))
    latest_conditions: dict[tuple[str, str], tuple[str, Mapping[str, Any]]] = {}
    latest_overrides: dict[tuple[str, str], tuple[str, Mapping[str, Any]]] = {}
    for source, record, _ in dated_records:
        scope_ref = record.get("scope_ref")
        conditions = record.get("conditions")
        if isinstance(scope_ref, str) and isinstance(conditions, list):
            for condition in conditions:
                if isinstance(condition, Mapping) and is_nonempty_string(condition.get("id")):
                    latest_conditions[(scope_ref, str(condition["id"]))] = (source, condition)
        override = record.get("override")
        if (
            isinstance(scope_ref, str)
            and isinstance(override, Mapping)
            and is_nonempty_string(override.get("override_id"))
        ):
            latest_overrides[(scope_ref, str(override["override_id"]))] = (source, override)
    governing.update(
        source
        for source, condition in latest_conditions.values()
        if condition.get("status") in {"OPEN", "EXPIRED", "CANCELLED"}
    )
    governing.update(
        source
        for source, override in latest_overrides.values()
        if override.get("status") in {"ACTIVE", "EXPIRED", "REVOKED"}
    )
    return governing


def _gate_decision_events(
    source: str,
    record: Mapping[str, Any],
    log: list[Mapping[str, Any]],
    contracts: Mapping[str, Any],
    *,
    not_after: Any,
) -> list[Mapping[str, Any]]:
    """Return exact canonical decision events observable by a runtime snapshot."""

    rules = contracts.get("runtime_gate_rules", {})
    source_field = str(rules.get("gate_event_source_field", "gate_ref"))
    record_id_field = str(rules.get("gate_event_record_id_field", "gate_record_id"))
    decision_field = str(rules.get("gate_event_decision_field", "gate_decision"))
    fingerprint_field = str(rules.get("gate_event_fingerprint_field", "gate_fingerprint"))
    event_types = rules.get("gate_event_types_by_decision", {})
    event_results = rules.get("gate_event_results_by_decision", {})
    allowed_types = set(event_types.get(record.get("decision"), []))
    allowed_results = set(event_results.get(record.get("decision"), []))
    recovery_type = rules.get("legacy_gate_recovery_event_type")
    recovery_field = str(rules.get("legacy_gate_recovery_state_field", "prehistory_state"))
    recovery_value = rules.get("legacy_gate_recovery_state_value")
    gate_time = parse_iso8601(record.get("timestamp"))
    state_time = parse_iso8601(not_after)
    if gate_time is None or state_time is None or gate_time > state_time:
        return []
    return [
        event
        for event in log
        if (
            (
                event.get("type") in allowed_types
                or (
                    event.get("type") == recovery_type
                    and event.get(recovery_field) == recovery_value
                )
            )
            and event.get(source_field) == source
            and event.get(record_id_field) == record.get("record_id")
            and event.get(decision_field) == record.get("decision")
            and event.get(fingerprint_field) == gate_fingerprint(record)
            and (
                event.get("task") == record.get("scope_ref")
                or (
                    event.get("type") == recovery_type
                    and event.get(recovery_field) == recovery_value
                    and not is_nonempty_string(record.get("scope_ref"))
                    and is_nonempty_string(event.get("task"))
                )
            )
            and event.get("result") in allowed_results
            and (event_time := parse_iso8601(event.get("timestamp"))) is not None
            and event_time > gate_time
            and event_time <= state_time
        )
    ]


def _operational_gate_records(
    state: Mapping[str, Any],
    log: list[Mapping[str, Any]],
    gate_records: list[tuple[str, Mapping[str, Any]]],
    contracts: Mapping[str, Any],
) -> list[tuple[str, Mapping[str, Any]]]:
    """Project saved gate files onto the decisions that actually became operational."""

    state_time = state.get("updated_at")
    return [
        (source, record)
        for source, record in gate_records
        if len(
            _gate_decision_events(
                source, record, log, contracts, not_after=state_time
            )
        )
        == 1
    ]


def _operationally_superseded_ids(
    operational_records: list[tuple[str, Mapping[str, Any]]],
    gate_records: list[tuple[str, Mapping[str, Any]]],
) -> set[str]:
    """Return every lineage ancestor retired by an operational successor."""

    by_id = {
        str(record["record_id"]): record
        for _, record in gate_records
        if is_nonempty_string(record.get("record_id"))
    }
    superseded: set[str] = set()
    for _, record in operational_records:
        predecessor = record.get("supersedes")
        visited: set[str] = set()
        while is_nonempty_string(predecessor) and str(predecessor) not in visited:
            identifier = str(predecessor)
            visited.add(identifier)
            superseded.add(identifier)
            prior = by_id.get(identifier)
            predecessor = prior.get("supersedes") if prior is not None else None
    return superseded


def gate_fingerprint(record: Mapping[str, Any]) -> str:
    """Return the stable canonical fingerprint used by gate lifecycle events."""

    encoded = json.dumps(
        record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def override_fingerprint(override: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        override, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def effective_event_type(event: Mapping[str, Any], contracts: Mapping[str, Any]) -> Any:
    rules = contracts.get("runtime_reconciliation_rules", {})
    if event.get("type") == rules.get("correction_event_type", "CORRECTION"):
        return event.get("corrected_event_type")
    return event.get("type")


def _check_override_event_bindings(
    log: list[Mapping[str, Any]],
    gate_records: list[tuple[str, Mapping[str, Any]]],
    contracts: Mapping[str, Any],
    report: Report,
) -> None:
    rules = contracts.get("override_invariants", {})
    if not rules.get("active_requires_bound_override_event"):
        return
    event_type = rules.get("override_event_type", "OVERRIDE")
    id_field = str(rules.get("override_event_id_field", "override_id"))
    fingerprint_field = str(
        rules.get("override_event_fingerprint_field", "override_fingerprint")
    )
    gate_rules = contracts.get("runtime_gate_rules", {})
    source_field = str(gate_rules.get("gate_event_source_field", "gate_ref"))
    record_id_field = str(gate_rules.get("gate_event_record_id_field", "gate_record_id"))
    for source, gate in gate_records:
        override = gate.get("override")
        if not isinstance(override, Mapping) or override.get("status") != "ACTIVE":
            continue
        matches = [
            event
            for event in log
            if (
                event.get("type") == event_type
                and event.get(source_field) == source
                and event.get(record_id_field) == gate.get("record_id")
                and event.get(id_field) == override.get("override_id")
            )
        ]
        if len(matches) != 1:
            report.fail(
                "RECONCILE_OVERRIDE_EVENT",
                f"{source}#{override.get('override_id')}: expected exactly one bound override activation event, found {len(matches)}",
            )
            continue
        event = matches[0]
        if event.get("result") != rules.get("override_event_required_result", "PASS"):
            report.fail(
                "RECONCILE_OVERRIDE_EVENT",
                f"{event.get('event_id')}: override activation result must be PASS",
            )
        if event.get(fingerprint_field) != override_fingerprint(override):
            report.fail(
                "RECONCILE_OVERRIDE_EVENT",
                f"{event.get('event_id')}: override fingerprint does not match the governed record",
            )
        gate_rules = contracts.get("runtime_gate_rules", {})
        allowed_decision_types = set(
            gate_rules.get("gate_event_types_by_decision", {}).get(gate.get("decision"), [])
        )
        decision_times = [
            parse_iso8601(candidate.get("timestamp"))
            for candidate in log
            if (
                candidate.get(gate_rules.get("gate_event_source_field", "gate_ref")) == source
                and candidate.get("type") in allowed_decision_types
                and parse_iso8601(candidate.get("timestamp")) is not None
            )
        ]
        event_time = parse_iso8601(event.get("timestamp"))
        if (
            rules.get("entry_requires_override_event_after_gate_decision")
            and (
                not decision_times
                or event_time is None
                or event_time <= max(decision_times)
            )
        ):
            report.fail(
                "RECONCILE_OVERRIDE_EVENT",
                f"{event.get('event_id')}: override activation must follow the bound gate decision event",
            )


def _active_override_authorizes_entry(
    state: Mapping[str, Any],
    source: str,
    gate: Mapping[str, Any],
    required_gate: Any,
    log: list[Mapping[str, Any]],
    gate_records: list[tuple[str, Mapping[str, Any]]],
    contracts: Mapping[str, Any],
) -> bool:
    rules = contracts.get("override_invariants", {})
    override = gate.get("override")
    if not isinstance(override, Mapping) or override.get("status") != "ACTIVE":
        return False
    state_time = parse_iso8601(state.get("updated_at"))
    scope_ref = gate.get("scope_ref")
    override_id = override.get("override_id")
    operational_sources = {
        source
        for source, _ in _operational_gate_records(
            state, log, gate_records, contracts
        )
    }
    latest_candidates = [
        (gate_time, candidate_source, candidate, candidate_override)
        for candidate_source, candidate in gate_records
        for candidate_override in [candidate.get("override")]
        if (
            isinstance(scope_ref, str)
            and isinstance(override_id, str)
            and candidate_source in operational_sources
            and candidate.get("scope_ref") == scope_ref
            and isinstance(candidate_override, Mapping)
            and candidate_override.get("override_id") == override_id
            and (gate_time := parse_iso8601(candidate.get("timestamp"))) is not None
            and state_time is not None
            and gate_time <= state_time
        )
    ]
    if not latest_candidates:
        return False
    _, latest_source, latest_gate, latest_override = max(
        latest_candidates, key=lambda item: (item[0], item[1])
    )
    if (
        latest_source != source
        or latest_gate.get("record_id") != gate.get("record_id")
        or override_fingerprint(latest_override) != override_fingerprint(override)
    ):
        return False
    active_modes = {
        value
        for value in [state.get("work_mode"), *(state.get("work_mode_overlays") or [])]
        if isinstance(value, str)
    }
    criteria = gate.get("criteria")
    allowed_statuses = set(rules.get("entry_authorizing_criterion_statuses", []))
    if (
        gate.get("gate_id") != required_gate
        or gate.get("decision") not in set(rules.get("entry_authorizing_gate_decisions", []))
        or override.get("type") not in set(rules.get("entry_authorizing_types", []))
        or override.get("type") not in active_modes
        or override.get("risk_level") in set(rules.get("active_forbidden_risk_levels", []))
        or override.get("residual_risk") in set(rules.get("active_forbidden_residual_risks", []))
        or required_gate not in (override.get("reduced_gates") or [])
        or (
            rules.get("entry_requires_nonempty_evidence_refs")
            and not override.get("evidence_refs")
        )
        or (
            rules.get("entry_requires_confirmed_authority")
            and (
                not isinstance(override.get("authority"), Mapping)
                or override.get("authority", {}).get("required") is not True
                or override.get("authority", {}).get("state") != "CONFIRMED"
            )
        )
        or not isinstance(criteria, list)
        or not criteria
        or any(
            not isinstance(criterion, Mapping)
            or criterion.get("status") not in allowed_statuses
            for criterion in criteria
        )
        or (
            rules.get("entry_requires_deferred_criterion")
            and not any(
                isinstance(criterion, Mapping) and criterion.get("status") != "PASS"
                for criterion in criteria
            )
        )
    ):
        return False
    gate_rules = contracts.get("runtime_gate_rules", {})
    return any(
        event.get("type") == rules.get("override_event_type", "OVERRIDE")
        and event.get(gate_rules.get("gate_event_source_field", "gate_ref")) == source
        and event.get(rules.get("override_event_id_field", "override_id"))
        == override.get("override_id")
        and event.get(rules.get("override_event_fingerprint_field", "override_fingerprint"))
        == override_fingerprint(override)
        and event.get("result") == rules.get("override_event_required_result", "PASS")
        for event in log
    )


def _check_gate_event_bindings(
    state: Mapping[str, Any],
    log: list[Mapping[str, Any]],
    gate_records: list[tuple[str, Mapping[str, Any]]],
    contracts: Mapping[str, Any],
    report: Report,
) -> None:
    """Bind gate lifecycle events and reject reopened governing decisions."""

    rules = contracts.get("runtime_gate_rules", {})
    if not rules.get("referenced_and_obligation_gates_require_bound_events"):
        return
    source_field = str(rules.get("gate_event_source_field", "gate_ref"))
    record_id_field = str(rules.get("gate_event_record_id_field", "gate_record_id"))
    decision_field = str(rules.get("gate_event_decision_field", "gate_decision"))
    fingerprint_field = str(rules.get("gate_event_fingerprint_field", "gate_fingerprint"))
    event_results = rules.get("gate_event_results_by_decision", {})
    recovery_type = rules.get("legacy_gate_recovery_event_type")
    recovery_field = str(rules.get("legacy_gate_recovery_state_field", "prehistory_state"))
    recovery_value = rules.get("legacy_gate_recovery_state_value")
    reopen_type = rules.get("gate_reopen_event_type", "GATE_REOPENED")
    lifecycle_types = set(rules.get("gate_lifecycle_event_types", []))
    by_source = {source: record for source, record in gate_records}
    successor_by_id = {
        str(record["supersedes"]): record
        for _, record in gate_records
        if is_nonempty_string(record.get("supersedes"))
    }
    bound_by_source: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    legacy_event_id_field = str(rules.get("legacy_gate_event_id_field", "legacy_event_id"))
    recovered_legacy_events = {
        str(event[legacy_event_id_field])
        for event in log
        if (
            event.get("type") == recovery_type
            and event.get(recovery_field) == recovery_value
            and is_nonempty_string(event.get(legacy_event_id_field))
        )
    }

    for event in log:
        has_binding = any(
            field in event
            for field in (source_field, record_id_field, decision_field, fingerprint_field)
        )
        if event.get("type") not in lifecycle_types and not has_binding:
            continue
        complete_binding = all(
            is_nonempty_string(event.get(field))
            for field in (source_field, record_id_field, decision_field, fingerprint_field)
        )
        if not complete_binding:
            if not (
                event.get("type") in lifecycle_types
                and not has_binding
                and event.get("event_id") in recovered_legacy_events
            ):
                report.fail(
                    "RECONCILE_GATE_EVENT",
                    f"{event.get('event_id')}: gate lifecycle events require a complete typed binding",
                )
            continue
        source = str(event[source_field])
        gate = by_source.get(source)
        if gate is None:
            report.fail(
                "RECONCILE_GATE_EVENT",
                f"{event.get('event_id')}: gate_ref does not resolve to a loaded gate: {source}",
            )
            continue
        expected_scope_ref = gate.get("scope_ref")
        if not is_nonempty_string(expected_scope_ref):
            successor = successor_by_id.get(str(gate.get("record_id")))
            expected_scope_ref = successor.get("scope_ref") if successor is not None else None
        if (
            event.get(record_id_field) != gate.get("record_id")
            or event.get(decision_field) != gate.get("decision")
            or event.get(fingerprint_field) != gate_fingerprint(gate)
            or event.get("task") != expected_scope_ref
        ):
            report.fail(
                "RECONCILE_GATE_EVENT",
                f"{event.get('event_id')}: gate binding does not match exact record, decision, fingerprint, and scope_ref",
            )
            continue
        if (
            event.get("type") in lifecycle_types | {recovery_type}
            and event.get("result") not in set(event_results.get(gate.get("decision"), []))
        ):
            report.fail(
                "RECONCILE_GATE_EVENT_RESULT",
                f"{event.get('event_id')}: result {event.get('result')!r} contradicts gate decision {gate.get('decision')!r}",
            )
            continue
        gate_time = parse_iso8601(gate.get("timestamp"))
        event_time = parse_iso8601(event.get("timestamp"))
        if (
            gate_time is None
            or event_time is None
            or (rules.get("gate_event_must_be_strictly_later") and event_time <= gate_time)
        ):
            report.fail(
                "RECONCILE_GATE_EVENT",
                f"{event.get('event_id')}: gate event must be strictly later than {source}",
            )
            continue
        bound_by_source[source].append(event)

    reopen_sources = {
        source
        for source, events in bound_by_source.items()
        if any(event.get("type") == reopen_type for event in events)
    }
    sources_requiring_decision = _governing_gate_sources(
        state, log, gate_records, contracts
    ) | reopen_sources
    for source in sorted(sources_requiring_decision):
        gate = by_source.get(source)
        if gate is None or not is_nonempty_string(gate.get("record_id")):
            continue
        identifier = str(gate["record_id"])
        decision_events = _gate_decision_events(
            source,
            gate,
            log,
            contracts,
            not_after=state.get("updated_at"),
        )
        if len(decision_events) != 1:
            report.fail(
                "RECONCILE_GATE_EVENT",
                f"{source}#{identifier}: expected exactly one canonical decision event, found {len(decision_events)}",
            )
            continue
        reopen_events = [
            event
            for event in bound_by_source.get(source, [])
            if (
                event.get("type") == reopen_type
                and parse_iso8601(event.get("timestamp")) is not None
            )
        ]
        latest_reopen_time = max(
            (
                parse_iso8601(event.get("timestamp"))
                for event in reopen_events
                if parse_iso8601(event.get("timestamp")) is not None
            ),
            default=None,
        )
        superseding_decisions = [
            (successor_source, successor)
            for successor_source, successor in gate_records
            if (
                successor.get("supersedes") == identifier
                and (successor_time := parse_iso8601(successor.get("timestamp"))) is not None
                and latest_reopen_time is not None
                and successor_time > latest_reopen_time
                and len(
                    _gate_decision_events(
                        successor_source,
                        successor,
                        log,
                        contracts,
                        not_after=state.get("updated_at"),
                    )
                )
                == 1
            )
        ]
        if reopen_events and not superseding_decisions:
            report.fail(
                "RECONCILE_GATE_REOPENED",
                f"{source}#{identifier}: governing gate was reopened by {reopen_events[-1].get('event_id')} and needs a later superseding decision",
            )


def _check_runtime_gate(
    root: Path,
    state: Mapping[str, Any],
    verification: list[Mapping[str, Any]],
    log: list[Mapping[str, Any]],
    gate_records: list[tuple[str, Mapping[str, Any]]],
    contracts: Mapping[str, Any],
    report: Report,
) -> None:
    rules = contracts.get("runtime_gate_rules", {})
    reference_field = str(rules.get("record_ref_field", "last_gate_record"))
    reference = state.get(reference_field)
    by_source = {source: record for source, record in gate_records}
    referenced: Mapping[str, Any] | None = None
    if reference is not None:
        if not is_nonempty_string(reference):
            report.fail("RECONCILE_GATE_REF", f"state.{reference_field} must be a relative path or null")
        elif reference not in by_source:
            report.fail("RECONCILE_GATE_REF", f"state.{reference_field} does not resolve to a loaded gate record: {reference}")
        else:
            referenced = by_source[str(reference)]

    operational_records = _operational_gate_records(
        state, log, gate_records, contracts
    )
    superseded = _operationally_superseded_ids(
        operational_records, gate_records
    )
    if (
        referenced is not None
        and is_nonempty_string(referenced.get("record_id"))
        and referenced.get("record_id") in superseded
    ):
        report.fail("RECONCILE_GATE_LATEST", f"state.{reference_field} points to a superseded gate record")
    if referenced is not None:
        gate_time = parse_iso8601(referenced.get("timestamp"))
        state_time = parse_iso8601(state.get("updated_at"))
        if gate_time is not None and state_time is not None and gate_time > state_time:
            report.fail(
                "RECONCILE_GATE_ORDER",
                f"state.updated_at predates the gate referenced by {reference_field}",
            )
        passing = referenced.get("decision") in set(
            contracts.get("gate_invariants", {}).get("pass_decisions", [])
        )
        authority_risks = set(
            contracts.get("gate_invariants", {}).get(
                "passing_gate_residual_risk_requiring_confirmed_authority", []
            )
        )
        _check_authority(
            root,
            referenced.get("authority"),
            contracts,
            report,
            prefix=f"state.{reference_field}.authority",
            pass_decision=passing,
            must_confirm=passing and referenced.get("residual_risk") in authority_risks,
            expected_scope=referenced.get("scope"),
            expected_scope_ref=referenced.get("scope_ref"),
            expected_subject_type="GATE",
            expected_subject_id=referenced.get("record_id"),
            not_after=referenced.get("timestamp"),
            valid_through=state.get("updated_at"),
        )
        if (
            is_nonempty_string(state.get("active_task"))
            and referenced.get("scope_ref") != state.get("active_task")
        ):
            report.fail(
                "RECONCILE_GATE_SCOPE",
                f"state.{reference_field} scope_ref {referenced.get('scope_ref')!r} does not bind active_task {state.get('active_task')!r}",
            )
        if rules.get("referenced_gate_residual_risk_cannot_exceed_runtime_risk"):
            risk_order = {
                value: index
                for index, value in enumerate(rules.get("risk_severity_order", []))
            }
            gate_risk = referenced.get("residual_risk")
            runtime_risk = state.get("risk_level")
            if (
                gate_risk in risk_order
                and runtime_risk in risk_order
                and risk_order[str(gate_risk)] > risk_order[str(runtime_risk)]
            ):
                report.fail(
                    "RECONCILE_GATE_RISK",
                    f"referenced gate residual_risk={gate_risk} exceeds runtime risk_level={runtime_risk}",
                )

    _check_gate_event_bindings(state, log, gate_records, contracts, report)
    _check_override_event_bindings(log, gate_records, contracts, report)

    _check_open_gate_obligations(root, state, log, gate_records, contracts, report)

    tier_requires = (
        isinstance(state.get("engineering_tier"), str)
        and state.get("engineering_tier") in set(rules.get("tiers_requiring_stage_entry_gate", []))
    )
    stage = state.get("lifecycle_stage")
    activity = state.get("active_activity")
    classification_rules = contracts.get("runtime_classification_rules", {})
    activity_gates = classification_rules.get("activity_entry_gates", {})
    activity_gate = (
        activity_gates.get(activity)
        if isinstance(activity, str) and isinstance(activity_gates, Mapping)
        else None
    )
    required_gate = activity_gate or (
        rules.get("stage_entry_gates", {}).get(stage) if isinstance(stage, str) else None
    )
    activity_requires = (
        isinstance(activity, str)
        and activity in set(rules.get("activities_requiring_entry_gate", []))
    )
    current_applicable: tuple[str, Mapping[str, Any]] | None = None
    if (
        rules.get("current_applicable_gate_cannot_be_hidden_by_pointer")
        and required_gate is not None
        and activity_requires
        and is_nonempty_string(state.get("active_task"))
    ):
        operational_records = _operational_gate_records(
            state, log, gate_records, contracts
        )
        superseded_ids = _operationally_superseded_ids(
            operational_records, gate_records
        )
        state_time = parse_iso8601(state.get("updated_at"))
        applicable_records = [
            (source, record, gate_time)
            for source, record in operational_records
            if (
                record.get("gate_id") == required_gate
                and record.get("scope_ref") == state.get("active_task")
                and record.get("record_id") not in superseded_ids
                and (gate_time := parse_iso8601(record.get("timestamp"))) is not None
                and state_time is not None
                and gate_time <= state_time
            )
        ]
        if applicable_records:
            current_source, current_record, _ = max(
                applicable_records,
                key=lambda item: (item[2], item[0]),
            )
            current_applicable = (current_source, current_record)
            if reference != current_source:
                report.fail(
                    "RECONCILE_GATE_REQUIRED",
                    f"current {required_gate} for active task is {current_source}; state pointer cannot hide it with {reference!r}",
                )
            if reference != current_source:
                risk_order = {
                    value: index
                    for index, value in enumerate(rules.get("risk_severity_order", []))
                }
                gate_risk = current_record.get("residual_risk")
                runtime_risk = state.get("risk_level")
                if (
                    gate_risk in risk_order
                    and runtime_risk in risk_order
                    and risk_order[str(gate_risk)] > risk_order[str(runtime_risk)]
                ):
                    report.fail(
                        "RECONCILE_GATE_RISK",
                        f"current applicable gate residual_risk={gate_risk} exceeds runtime risk_level={runtime_risk}",
                    )
    governing_entry = current_applicable or (
        (str(reference), referenced) if referenced is not None else None
    )
    if (
        rules.get("referenced_applicable_gate_decision_governs_all_tiers")
        and governing_entry is not None
        and required_gate is not None
        and activity_requires
        and governing_entry[1].get("gate_id") == required_gate
    ):
        entry_source, entry_record = governing_entry
        override_entry = _active_override_authorizes_entry(
            state,
            entry_source,
            entry_record,
            required_gate,
            log,
            gate_records,
            contracts,
        )
        if (
            entry_record.get("decision") not in set(rules.get("required_entry_gate_decisions", []))
            and not override_entry
        ):
            report.fail(
                "RECONCILE_GATE_DECISION",
                f"current applicable gate decision {entry_record.get('decision')!r} blocks {activity} for every tier",
            )
    if tier_requires and required_gate is not None and activity_requires:
        if referenced is None:
            report.fail(
                "RECONCILE_GATE_REQUIRED",
                f"{state.get('engineering_tier')} {state.get('lifecycle_stage')}/{state.get('active_activity')} requires {required_gate}",
            )
        else:
            override_entry = _active_override_authorizes_entry(
                state,
                str(reference),
                referenced,
                required_gate,
                log,
                gate_records,
                contracts,
            )
            if referenced.get("scope_ref") != state.get("active_task"):
                report.fail(
                    "RECONCILE_GATE_SCOPE",
                    f"stage-entry gate scope_ref {referenced.get('scope_ref')!r} does not bind active_task {state.get('active_task')!r}",
                )
            if referenced.get("gate_id") != required_gate:
                report.fail(
                    "RECONCILE_GATE_REQUIRED",
                    f"stage entry requires {required_gate}, referenced gate is {referenced.get('gate_id')!r}",
                )
            if (
                not isinstance(referenced.get("decision"), str)
                or referenced.get("decision") not in set(rules.get("required_entry_gate_decisions", []))
            ) and not override_entry:
                report.fail(
                    "RECONCILE_GATE_DECISION",
                    f"referenced entry gate decision {referenced.get('decision')!r} does not permit entry",
                )
    if rules.get("passing_verification_state_requires_gate_record") and state.get("verification_state") == "PASS":
        if referenced is None:
            report.fail("RECONCILE_GATE_VERIFICATION", "verification_state=PASS requires an applicable gate record")
            return
        if is_nonempty_string(state.get("active_task")) and referenced.get("scope_ref") != state.get("active_task"):
            report.fail(
                "RECONCILE_GATE_SCOPE",
                f"verification gate scope_ref {referenced.get('scope_ref')!r} does not bind active_task {state.get('active_task')!r}",
            )
        allowed_gate_ids = set(rules.get("passing_verification_state_required_gate_ids", []))
        if not isinstance(referenced.get("gate_id"), str) or referenced.get("gate_id") not in allowed_gate_ids:
            report.fail(
                "RECONCILE_GATE_VERIFICATION",
                f"verification_state=PASS requires one of {sorted(allowed_gate_ids)}, not {referenced.get('gate_id')!r}",
            )
        if (
            rules.get("passing_verification_state_requires_passing_gate_decision")
            and (
                not isinstance(referenced.get("decision"), str)
                or referenced.get("decision") not in set(rules.get("required_entry_gate_decisions", []))
            )
        ):
            report.fail(
                "RECONCILE_GATE_VERIFICATION",
                "verification_state=PASS requires a passing VERIFIED/RELEASE_READY gate decision",
            )
        if rules.get("passing_verification_state_requires_cited_record_fragment"):
            evidence_refs: list[str] = []
            gate_evidence = referenced.get("evidence")
            if isinstance(gate_evidence, list):
                evidence_refs.extend(item for item in gate_evidence if isinstance(item, str))
            criteria = referenced.get("criteria")
            if isinstance(criteria, list):
                for criterion in criteria:
                    if not isinstance(criterion, Mapping):
                        continue
                    refs = criterion.get("evidence_refs")
                    if isinstance(refs, list):
                        evidence_refs.extend(item for item in refs if isinstance(item, str))
            ledger_path = str(rules.get("verification_ledger_path", ".agent/verification.jsonl"))
            cited_ids = {
                fragment
                for reference_value in evidence_refs
                for kind, target, fragment in [classify_link(reference_value)]
                if kind == "internal" and Path(target).as_posix() == ledger_path and fragment
            }
            records_by_id = {
                str(record["id"]): record
                for record in verification
                if isinstance(record, Mapping) and is_nonempty_string(record.get("id"))
            }
            cited_current_pass = False
            for identifier in cited_ids:
                record = records_by_id.get(identifier)
                if (
                    _verification_record_supports_gate(
                        record,
                        verification,
                        referenced,
                        log,
                        contracts,
                        current_through=parse_iso8601(state.get("updated_at")),
                    )
                    and (
                        not rules.get("passing_verification_state_requires_matching_scope")
                        or record.get("scope") == referenced.get("scope")
                    )
                ):
                    cited_current_pass = True
                    break
            if not cited_current_pass:
                report.fail(
                    "RECONCILE_VERIFICATION_EVIDENCE",
                    "verification_state=PASS requires the gate to cite an exact CURRENT PASS record as "
                    f"{ledger_path}#VER-ID observed no later than the gate",
                )


def check(root: Path, contracts_root: Path | None = None) -> Report:
    report = Report()
    contract_source = contracts_root or (
        root if (root / "references" / "contracts.json").is_file() else FRAMEWORK_ROOT
    )
    try:
        contracts = load_contracts(contract_source)
    except (OSError, UnicodeError, ValueError) as exc:
        report.fail("CONTRACTS", str(exc))
        return report
    state, backlog, log, verification = _read_artifacts(root, report)
    _check_authority_ledger(root, contracts, report)
    if state is not None:
        _check_state(root, state, contracts, report)
    items: dict[str, Mapping[str, Any]] = {}
    if backlog is not None:
        items = _check_backlog(root, backlog, verification or [], contracts, report)
    if log is not None:
        _check_log(log, items, contracts, report)
    if verification is not None:
        _check_verification(root, verification, items, contracts, report)
    gate_records = _check_gate_files(root, contracts, report)
    if state is not None and backlog is not None and log is not None:
        _check_reconciliation(root, state, items, log, verification or [], gate_records, contracts, report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", help="Target project root; defaults to the parent of this script.")
    parser.add_argument(
        "--contracts-root",
        help="Installed skill root owning references/contracts.json; defaults to the parent of this script.",
    )
    parser.add_argument("--quiet", action="store_true", help="Hide individual PASS findings.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = resolve_root(args.root, __file__)
    except ValueError as exc:
        report = Report()
        report.fail("ROOT", str(exc))
        return emit(report)
    contracts_root = (
        Path(args.contracts_root).expanduser().resolve()
        if args.contracts_root
        else FRAMEWORK_ROOT
    )
    return emit(check(root, contracts_root), include_passes=not args.quiet)


if __name__ == "__main__":
    raise SystemExit(main())
