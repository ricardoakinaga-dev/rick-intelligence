"""Adversarial, non-clinical fixtures for the file-ingestion boundary."""

from __future__ import annotations

from pathlib import Path
import pickle
import stat
import sys
import time
from types import SimpleNamespace
import warnings
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "knowledge" / "src"))

from rick_ingestion import (  # noqa: E402
    ArchiveLimitError,
    ControlledPdfParser,
    FilenameValidationError,
    MarkdownParser,
    MimeMismatchError,
    MAX_PARSED_TEXT_CHARS,
    ParseError,
    ParsedDocument,
    ParserLimits,
    ParserTimeoutError,
    ProcessParserRunner,
    execute_parser,
    generated_storage_name,
    inspect_file,
    normalize_filename,
    sanitize_display_filename,
    TxtParser,
    validate_archive,
    validate_filename,
    validate_file,
)
import rick_ingestion.parsers as parser_module  # noqa: E402


def _write(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


def _docx(path: Path, *, extras: tuple[tuple[str, bytes], ...] = ()) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", b"<Types/>")
        archive.writestr("word/document.xml", b"<document/>")
        for name, data in extras:
            archive.writestr(name, data)
    return path


class _BlockingParser:
    def parse(self, path: Path, *, workspace_id: str) -> ParsedDocument:
        time.sleep(2.0)
        return ParsedDocument(text="late")


class _OversizedParser:
    def parse(self, path: Path, *, workspace_id: str) -> ParsedDocument:
        return ParsedDocument(text="x" * (MAX_PARSED_TEXT_CHARS + 1))


@pytest.mark.parametrize(
    ("suffix", "data", "mime", "kind"),
    [
        (".txt", b"plain payload\n", "text/plain; charset=utf-8", "text"),
        (".md", b"# heading\n", "text/markdown", "text"),
        (".pdf", b"%PDF-1.7\n", "application/pdf", "pdf"),
    ],
)
def test_extension_magic_and_declared_mime_agree(
    tmp_path: Path, suffix: str, data: bytes, mime: str, kind: str,
) -> None:
    path = _write(tmp_path / f"payload{suffix}", data)

    inspection = inspect_file(path, declared_mime=mime)

    assert inspection.suffix == suffix
    assert inspection.detected_kind == kind
    assert inspection.declared_mime == mime.split(";", 1)[0]


@pytest.mark.parametrize(
    ("name", "data", "declared_mime"),
    [
        ("renamed.txt", b"%PDF-1.7\n", None),
        ("renamed.pdf", b"ordinary text", None),
        ("payload.txt", b"ordinary text", "application/pdf"),
        ("payload.pdf", b"%PDF-1.7\n", "text/plain"),
        ("payload.txt", b"\x00\x01binary", "text/plain"),
    ],
)
def test_magic_or_mime_mismatch_fails_closed(
    tmp_path: Path, name: str, data: bytes, declared_mime: str | None,
) -> None:
    path = _write(tmp_path / name, data)

    with pytest.raises(MimeMismatchError):
        validate_file(path, declared_mime=declared_mime)


def test_filename_normalization_removes_encoded_traversal_aliases() -> None:
    assert normalize_filename("%252e%252e%252fprivate%252fnotes.txt") == "notes.txt"
    assert normalize_filename("..\\..\\private\\notes.txt") == "notes.txt"
    assert normalize_filename("．．／private／notes.txt") == "notes.txt"
    assert sanitize_display_filename("a\x00b") == "ab"


@pytest.mark.parametrize(
    "name",
    [
        "../escape.txt",
        "..\\escape.txt",
        "/absolute.txt",
        "C:/absolute.txt",
        "%2e%2e%2fescape.txt",
        "stream.txt:alternate",
        "CON.txt",
        "trailing.",
    ],
)
def test_path_segment_validation_rejects_traversal_and_aliases(name: str) -> None:
    with pytest.raises(FilenameValidationError):
        validate_filename(name)


def test_generated_storage_name_accepts_only_known_suffixes() -> None:
    generated = generated_storage_name(".TXT")
    assert generated.startswith("doc_")
    assert generated.endswith(".txt")
    assert "/" not in generated and "\\" not in generated
    with pytest.raises(ParseError):
        generated_storage_name("../payload.txt")


def test_regular_file_and_size_limits_fail_closed(tmp_path: Path) -> None:
    path = _write(tmp_path / "payload.txt", b"12345")
    with pytest.raises(ParseError) as too_large:
        validate_file(path, max_bytes=4)
    assert too_large.value.code == "request_too_large"

    directory = tmp_path / "directory.txt"
    directory.mkdir()
    with pytest.raises(ParseError):
        validate_file(directory)

    target = _write(tmp_path / "target.txt", b"safe text")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks are unavailable in this test environment")
    with pytest.raises(ParseError):
        validate_file(link)


def test_binary_tail_cannot_evade_the_magic_probe(tmp_path: Path) -> None:
    path = _write(tmp_path / "tail.txt", b"safe text\n" + b"a" * 4_096 + b"\x00hidden")

    with pytest.raises(MimeMismatchError):
        validate_file(path)


def test_text_parser_applies_configured_character_limit(tmp_path: Path) -> None:
    path = _write(tmp_path / "payload.txt", b"123456")
    parser = __import__("rick_ingestion", fromlist=["TxtParser"]).TxtParser(
        limits=ParserLimits(max_text_chars=5),
    )

    with pytest.raises(ParseError) as error:
        parser.parse(path, workspace_id="workspace")
    assert error.value.code == "request_too_large"


@pytest.mark.parametrize(("suffix", "parser_cls"), [(".txt", TxtParser), (".md", MarkdownParser)])
def test_text_parsers_reject_invalid_utf8(tmp_path: Path, suffix: str, parser_cls: type) -> None:
    path = _write(tmp_path / f"payload{suffix}", b"valid text\xff\xfe")

    with pytest.raises(ParseError) as error:
        parser_cls().parse(path, workspace_id="workspace")

    assert error.value.code == "validation_error"


def test_docx_archive_inspection_streams_a_valid_container(tmp_path: Path) -> None:
    path = _docx(tmp_path / "payload.docx", extras=(("word/styles.xml", b"<styles/>"),))

    inspection = inspect_file(
        path,
        declared_mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    assert inspection.detected_kind == "zip"
    assert inspection.archive is not None
    assert inspection.archive.member_count == 3
    assert inspection.archive.uncompressed_bytes > 0


@pytest.mark.parametrize(
    "entry_name",
    ["../escape.txt", "/absolute.txt", "..\\escape.txt", "C:/absolute.txt"],
)
def test_docx_zip_slip_names_are_rejected(tmp_path: Path, entry_name: str) -> None:
    path = _docx(tmp_path / "zip-slip.docx", extras=((entry_name, b"escape"),))

    with pytest.raises(ParseError) as error:
        validate_file(path)
    assert error.value.code == "validation_error"


def test_docx_duplicate_names_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.docx"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("[Content_Types].xml", b"<Types/>")
            archive.writestr("word/document.xml", b"<document/>")
            archive.writestr("word/document.xml", b"<second/>")

    with pytest.raises(ParseError):
        validate_file(path)


def test_docx_symlink_member_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "symlink.docx"
    link = zipfile.ZipInfo("word/link.xml")
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", b"<Types/>")
        archive.writestr("word/document.xml", b"<document/>")
        archive.writestr(link, b"target")

    with pytest.raises(ParseError):
        validate_file(path)


def test_archive_member_and_total_decompression_limits_are_enforced(tmp_path: Path) -> None:
    path = _docx(tmp_path / "large-member.docx", extras=(("word/data.bin", b"x" * 100),))
    limits = ParserLimits(max_archive_member_bytes=32, max_archive_uncompressed_bytes=64)

    with pytest.raises(ArchiveLimitError):
        validate_archive(path, limits=limits, require_docx=True)


def test_archive_compression_ratio_limit_rejects_bomb_like_payload(tmp_path: Path) -> None:
    path = _docx(tmp_path / "compressed.docx", extras=(("word/data.bin", b"A" * 8_192),))
    limits = ParserLimits(max_archive_compression_ratio=2.0)

    with pytest.raises(ArchiveLimitError):
        validate_archive(path, limits=limits, require_docx=True)


def test_archive_member_count_limit_is_enforced(tmp_path: Path) -> None:
    path = _docx(
        tmp_path / "many-members.docx",
        extras=tuple((f"word/item-{index}.bin", b"x") for index in range(4)),
    )
    limits = ParserLimits(max_archive_members=3)

    with pytest.raises(ArchiveLimitError):
        validate_archive(path, limits=limits, require_docx=True)


def test_pdf_page_limit_is_checked_before_page_extraction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _write(tmp_path / "many-pages.pdf", b"%PDF-1.7\n")
    extracted = []

    class Page:
        def extract_text(self):
            extracted.append(True)
            return "page"

        def close(self):
            pass

    class Pdf:
        pages = [Page(), Page()]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setitem(sys.modules, "pdfplumber", SimpleNamespace(open=lambda _path: Pdf()))
    parser = ControlledPdfParser(limits=ParserLimits(max_pages=1))

    with pytest.raises(ParseError) as error:
        parser.parse(path, workspace_id="workspace")
    assert error.value.code == "request_too_large"
    assert extracted == []


def test_in_process_runner_reports_cooperative_timeout() -> None:
    class SlowParser:
        def parse(self, path: Path, *, workspace_id: str) -> ParsedDocument:
            time.sleep(0.01)
            return ParsedDocument(text="late")

    with pytest.raises(ParserTimeoutError):
        execute_parser(SlowParser(), Path("payload.txt"), workspace_id="workspace", timeout_seconds=0.001)


def test_process_runner_parses_in_a_fresh_child(tmp_path: Path) -> None:
    path = _write(tmp_path / "payload.txt", b"isolated text\n")

    result = execute_parser(
        __import__("rick_ingestion", fromlist=["TxtParser"]).TxtParser(),
        path,
        workspace_id="workspace",
        runner=ProcessParserRunner(),
        timeout_seconds=5,
    )

    assert result.text == "isolated text\n"


def test_process_runner_rejects_an_oversized_result_before_transport(tmp_path: Path) -> None:
    path = _write(tmp_path / "payload.txt", b"payload\n")

    with pytest.raises(ParseError) as error:
        execute_parser(
            _OversizedParser(),
            path,
            workspace_id="workspace",
            runner=ProcessParserRunner(),
            timeout_seconds=5,
        )

    assert error.value.code == "request_too_large"


def test_parser_result_wire_rejects_pickle_payload() -> None:
    payload = pickle.dumps(("error", "ingestion_failed"), protocol=pickle.HIGHEST_PROTOCOL)

    with pytest.raises(ValueError):
        parser_module._decode_parser_envelope(payload)


def test_process_runner_hard_stops_a_blocking_parser(tmp_path: Path) -> None:
    path = _write(tmp_path / "payload.txt", b"payload\n")

    with pytest.raises(ParserTimeoutError):
        execute_parser(
            _BlockingParser(),
            path,
            workspace_id="workspace",
            runner=ProcessParserRunner(),
            timeout_seconds=0.05,
        )


def test_custom_runner_is_the_explicit_isolation_seam() -> None:
    observed = {}

    class Runner:
        def run(self, parser, path, *, workspace_id, timeout_seconds):
            observed.update({"path": path, "workspace_id": workspace_id, "timeout": timeout_seconds})
            return ParsedDocument(text="isolated result")

    result = execute_parser(
        object(),
        Path("payload.txt"),
        workspace_id="workspace",
        runner=Runner(),
        timeout_seconds=3,
    )

    assert result.text == "isolated result"
    assert observed == {"path": Path("payload.txt"), "workspace_id": "workspace", "timeout": 3.0}


def test_custom_runner_failure_and_invalid_result_fail_closed() -> None:
    class ExplodingRunner:
        def run(self, *args, **kwargs):
            raise RuntimeError("secret path must not escape")

    with pytest.raises(ParseError) as error:
        execute_parser(object(), Path("payload.txt"), workspace_id="workspace", runner=ExplodingRunner())
    assert str(error.value) == "Could not parse document."

    class InvalidRunner:
        def run(self, *args, **kwargs):
            return {"text": "not a parsed document"}

    with pytest.raises(ParseError):
        execute_parser(object(), Path("payload.txt"), workspace_id="workspace", runner=InvalidRunner())

    class OversizedRunner:
        def run(self, *args, **kwargs):
            return ParsedDocument(text="x" * (MAX_PARSED_TEXT_CHARS + 1))

    with pytest.raises(ParseError) as error:
        execute_parser(object(), Path("payload.txt"), workspace_id="workspace", runner=OversizedRunner())
    assert error.value.code == "request_too_large"
