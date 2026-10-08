"""Write a location-free coverage summary for a single CI suite."""

import json
import sys
from pathlib import Path, PurePosixPath

WEB_COVERAGE_SOURCES = frozenset({
    "lib/navigation.ts", "lib/permissions.ts", "lib/presentation.ts",
    "lib/chat-response.ts", "lib/api-error.ts", "lib/session-scope.ts",
    "components/session-provider.tsx", "components/app-shell.tsx",
    "components/cases/case-workspace.tsx", "components/ui.tsx",
})


def _web_source(path: str) -> str:
    normalized = PurePosixPath(path.replace("\\", "/"))
    if ".." in normalized.parts:
        raise SystemExit("web coverage source must stay under apps/web")
    parts = normalized.parts
    anchors = [i for i in range(len(parts) - 1) if parts[i:i + 2] == ("apps", "web")]
    if anchors:
        parts = parts[anchors[-1] + 2:]
    elif normalized.is_absolute():
        raise SystemExit("web coverage source must stay under apps/web")
    return PurePosixPath(*parts).as_posix()


def main() -> int:
    if len(sys.argv) != 5 or sys.argv[1] not in {"api", "web", "worker"}:
        raise SystemExit("usage: summarize_coverage.py api|web|worker INPUT OUTPUT MIN_COVERAGE_PERCENT")
    suite, source, destination, minimum_text = sys.argv[1:]
    minimum = int(minimum_text)
    if minimum < 0 or minimum > 100:
        raise SystemExit("minimum coverage must be between 0 and 100")
    report = json.loads(Path(source).read_text(encoding="utf-8"))
    if suite == "api":
        files = report["files"]
        if not isinstance(files, dict) or not files:
            raise SystemExit("API coverage must list production files under apps/api/src")
        normalized = [PurePosixPath(str(path).replace("\\", "/")) for path in files]
        if any(
            path.is_absolute()
            or ".." in path.parts
            or len(path.parts) < 4
            or path.parts[:3] != ("apps", "api", "src")
            or path.suffix != ".py"
            for path in normalized
        ):
            raise SystemExit("API coverage files must stay under apps/api/src")
        if len(set(normalized)) != len(normalized):
            raise SystemExit("API coverage contains duplicate source files")
        counts = report["totals"]
        covered = counts["covered_lines"]
        total = counts["num_statements"]
        excluded = counts["excluded_lines"]
        file_counts = [entry["summary"] for entry in files.values()]
        values = [covered, total, excluded, *(entry[key] for entry in file_counts
            for key in ("covered_lines", "num_statements", "excluded_lines"))]
        if any(type(value) is not int or value < 0 for value in values):
            raise SystemExit("API coverage counts must be non-negative integers")
        if sum(entry["covered_lines"] for entry in file_counts) != covered or \
                sum(entry["num_statements"] for entry in file_counts) != total or \
                sum(entry["excluded_lines"] for entry in file_counts) != excluded:
            raise SystemExit("API total coverage differs from production-file summaries")
        scope = "apps/api/src/**/*.py"
    elif suite == "worker":
        files = report["files"]
        if not files or any("/tests/" in path.replace("\\", "/") for path in files):
            raise SystemExit("worker coverage must include production modules and exclude tests")
        counts = report["totals"]
        covered = counts["covered_lines"]
        total = counts["num_statements"]
        scope = "apps/worker/*.py (excluding tests)"
    else:
        files = {path: data for path, data in report.items() if path != "total"}
        sources = [_web_source(path) for path in files]
        if len(set(sources)) != len(sources) or set(sources) != WEB_COVERAGE_SOURCES:
            raise SystemExit("web coverage source list differs from the declared unit suite")
        counts = report["total"]["lines"]
        covered = counts["covered"]
        total = counts["total"]
        values = [covered, total, *(entry["lines"][key] for entry in files.values() for key in ("covered", "total"))]
        if any(type(value) is not int or value < 0 for value in values):
            raise SystemExit("web coverage counts must be non-negative integers")
        if any(entry["lines"]["covered"] > entry["lines"]["total"] for entry in files.values()):
            raise SystemExit("invalid web source coverage counts")
        if sum(entry["lines"]["covered"] for entry in files.values()) != covered or \
                sum(entry["lines"]["total"] for entry in files.values()) != total:
            raise SystemExit("web total coverage differs from production-file summaries")
        scope = "apps/web/{" + ",".join(sorted(WEB_COVERAGE_SOURCES)) + "}"
    if total <= 0 or covered < 0 or covered > total:
        raise SystemExit("invalid coverage counts")
    percent = covered * 100 / total
    unit = "statements" if suite == "api" else "lines"
    if covered * 100 < minimum * total:
        raise SystemExit(f"{suite} {unit} coverage {percent:.2f}% is below {minimum}%")
    summary = {
        "schema_version": 1,
        "suite": suite,
        "scope": scope,
        "source_file_count": len(files),
    }
    if suite == "api":
        summary.update({"minimum_statements_percent": minimum, "covered_statements": covered,
            "total_statements": total, "statements_percent": round(percent, 2), "excluded_lines": excluded})
    else:
        summary.update({"minimum_lines_percent": minimum, "covered_lines": covered,
            "total_lines": total, "lines_percent": round(percent, 2)})
    Path(destination).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
