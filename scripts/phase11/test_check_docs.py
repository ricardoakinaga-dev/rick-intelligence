"""Documentation links must fail on missing and nonportable targets."""

from pathlib import Path

from scripts.phase11.check_docs import check_links


def documents(root: Path, source: str) -> None:
    (root / "docs").mkdir()
    for name in ("README.md", "CONTRIBUTING.md", "docs/INDEX.md"):
        (root / name).write_text(source, encoding="utf-8")


def test_missing_target_is_rejected(tmp_path: Path) -> None:
    documents(tmp_path, "[broken](absent.md)")
    errors, count = check_links(tmp_path)
    assert count == 3 and len(errors) == 3
    assert all("broken local link" in error for error in errors)


def test_absolute_link_is_not_portable_even_if_target_exists(tmp_path: Path) -> None:
    documents(tmp_path, f"[local](<{tmp_path}/README.md:12>)")
    errors, _ = check_links(tmp_path)
    assert len(errors) == 3
    assert all("nonportable" in error for error in errors)


def test_relative_links_line_numbers_and_external_urls(tmp_path: Path) -> None:
    documents(tmp_path, "[root](README.md:1) [web](https://example.invalid) [anchor](#section)")
    (tmp_path / "docs/README.md").write_text("root", encoding="utf-8")
    assert check_links(tmp_path) == ([], 3)


def test_archived_evidence_and_code_examples_are_not_document_links(tmp_path: Path) -> None:
    documents(tmp_path, "```md\n[example](missing.md)\n```")
    archived = tmp_path / "docs" / "reports" / "evidence" / "historical.md"
    archived.parent.mkdir(parents=True)
    archived.write_text("[historical](missing.md)", encoding="utf-8")
    assert check_links(tmp_path) == ([], 0)


def test_reference_style_missing_target_is_rejected(tmp_path: Path) -> None:
    documents(tmp_path, "[reference]: absent.md\n")
    errors, count = check_links(tmp_path)
    assert len(errors) == count == 3
