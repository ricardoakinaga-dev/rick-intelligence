#!/usr/bin/env python3
"""Check portable local Markdown links, excluding archived evidence (AUD07-24)."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
LINK = re.compile(r"\[[^\]\n]*\]\((<[^>\n]+>|[^\s)]+)(?:\s+\"[^\"]*\")?\)")
REFERENCE = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*(<[^>\n]+>|\S+)", re.MULTILINE)


def prose(source: str) -> str:
    lines = []
    fence = ""
    for line in source.splitlines():
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            token = marker[1]
            if not fence:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = ""
            continue
        if not fence:
            lines.append(line)
    return "\n".join(lines)


def check_links(root: Path) -> tuple[list[str], int]:
    root = root.resolve()
    files = [root / name for name in ("README.md", "CONTRIBUTING.md", "docs/INDEX.md")]
    files.extend(sorted(path for path in (root / "docs").rglob("*.md")
                        if "evidence" not in path.relative_to(root / "docs").parts))
    errors = []
    count = 0
    for path in dict.fromkeys(files):
        if not path.is_file():
            errors.append(f"{path.relative_to(root)}: document is missing")
            continue
        source = prose(path.read_text(encoding="utf-8"))
        for match in [*LINK.finditer(source), *REFERENCE.finditer(source)]:
            target = match[1].strip("<>")
            # Codex file links may carry a line number. urlsplit treats a colon
            # in a relative filename as a scheme, so strip that suffix first.
            target = re.sub(r":\d+(?=#|$)", "", target)
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            count += 1
            local = Path(unquote(parsed.path))
            if local.is_absolute():
                errors.append(f"{path.relative_to(root)}: nonportable absolute link: {target}")
            elif not (path.parent / local).exists():
                errors.append(f"{path.relative_to(root)}: broken local link: {target}")
    return errors, count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    errors, count = check_links(args.root)
    for error in errors:
        print(f"FAIL: {error}")
    print(f"{'FAIL' if errors else 'PASS'}: {count} local documentation links; {len(errors)} errors")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
