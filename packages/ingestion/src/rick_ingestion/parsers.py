"""Parser interface + validated format adapters (PDF/DOCX/MD/TXT).

No HTTP objects. PDF uses the controlled page-batch path (memory-safe,
heartbeat, cleanup); the all-in-memory PDF path stays disabled like legacy.
Storage safety: generated storage names, traversal prevention, display names
as metadata only.
"""

from __future__ import annotations

import codecs
import hashlib
import io
import re
import secrets
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

SUPPORTED_EXTENSIONS = frozenset({".pdf", ".docx", ".md", ".txt"})
PARSER_VERSION = "rick-parser-v1"

MAX_FILE_BYTES = 50 * 1024 * 1024
# A fixed read bound keeps checksum and text acquisition independent of file
# size. The parser still returns the complete decoded text because that is the
# existing DocumentParser contract; only the file I/O itself is chunked.
FILE_READ_CHUNK_BYTES = 64 * 1024
MAX_PARSED_TEXT_CHARS = 8_000_000
MAX_PARSED_PAGES = 10_000
MAX_PARSED_SECTIONS = 100_000


class ParseError(Exception):
    def __init__(self, code: str = "ingestion_failed", message: str = "Could not parse document."):
        super().__init__(message)
        self.code = code


class UnsupportedFormatError(ParseError):
    def __init__(self, suffix: str):
        super().__init__("unsupported_media_type", f"Unsupported format: {suffix or '(none)'}")


def checksum_file(path: Path) -> str:
    """Hash a validated file with an explicit bounded read size."""

    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(FILE_READ_CHUNK_BYTES)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError as exc:
        raise ParseError() from exc
    return digest.hexdigest()


def read_text_file(path: Path, *, encoding: str, max_chars: int = MAX_PARSED_TEXT_CHARS) -> str:
    """Decode a file through bounded binary reads without changing text I/O semantics."""

    decoder = io.IncrementalNewlineDecoder(
        codecs.getincrementaldecoder(encoding)(),
        translate=True,
    )
    pieces: list[str] = []
    total_chars = 0
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(FILE_READ_CHUNK_BYTES)
            if not chunk:
                break
            piece = decoder.decode(chunk, final=False)
            total_chars += len(piece)
            if total_chars > max_chars:
                raise ParseError("request_too_large", "Parsed document exceeds the text limit.")
            pieces.append(piece)
        piece = decoder.decode(b"", final=True)
        total_chars += len(piece)
        if total_chars > max_chars:
            raise ParseError("request_too_large", "Parsed document exceeds the text limit.")
        pieces.append(piece)
    return "".join(pieces)


@dataclass
class ParsedPage:
    page_number: int
    text: str


@dataclass
class ParsedDocument:
    text: str
    pages: list[ParsedPage] = field(default_factory=list)
    sections: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class DocumentParser(Protocol):
    def parse(self, path: Path, *, workspace_id: str) -> ParsedDocument: ...


def validate_file(path: Path, *, max_bytes: int = MAX_FILE_BYTES) -> None:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFormatError(suffix)
    try:
        size = path.stat().st_size
    except OSError:
        raise ParseError("ingestion_failed", "Could not read document.")
    if size <= 0:
        raise ParseError("validation_error", "Document is empty.")
    if size > max_bytes:
        raise ParseError("request_too_large", "Document exceeds size limit.")


def sanitize_display_filename(name: str) -> str:
    """Display name only: strip directories, NULs, control chars; cap length."""
    base = (name or "").replace("\\", "/").split("/")[-1].replace("\x00", "")
    base = "".join(ch for ch in unicodedata.normalize("NFKC", base) if ch.isprintable()).strip()
    return (base or "document")[:256]


def generated_storage_name(suffix: str) -> str:
    """Server-generated storage key — never derived from user filenames."""
    return f"doc_{secrets.token_hex(16)}{suffix.lower()}"


class TxtParser:
    def parse(self, path: Path, *, workspace_id: str) -> ParsedDocument:
        try:
            text = read_text_file(path, encoding="utf-8")
        except UnicodeDecodeError:
            text = read_text_file(path, encoding="latin-1")
        except OSError as exc:
            raise ParseError() from exc
        if not text.strip():
            raise ParseError("validation_error", "Document is empty.")
        return ParsedDocument(text=text, pages=[ParsedPage(page_number=1, text=text)])


class MarkdownParser:
    _HEADING = re.compile(r"^(#{1,6})\s+(.*)$")

    def parse(self, path: Path, *, workspace_id: str) -> ParsedDocument:
        try:
            text = read_text_file(path, encoding="utf-8")
        except OSError as exc:
            raise ParseError() from exc
        if not text.strip():
            raise ParseError("validation_error", "Document is empty.")
        sections = []
        for match in self._HEADING.finditer(text):
            if len(sections) >= MAX_PARSED_SECTIONS:
                raise ParseError("request_too_large", "Document contains too many sections.")
            sections.append({"heading": match.group(2).strip(), "level": len(match.group(1))})
        return ParsedDocument(text=text, pages=[ParsedPage(page_number=1, text=text)], sections=sections)


class DocxParser:
    def parse(self, path: Path, *, workspace_id: str) -> ParsedDocument:
        try:
            from docx import Document as DocxDocument
        except ImportError as exc:
            raise ParseError("ingestion_failed", "DOCX support is not installed.") from exc
        try:
            doc = DocxDocument(str(path))
        except Exception as exc:
            raise ParseError("validation_error", "Could not open DOCX document.") from exc
        paragraphs: list[str] = []
        total_chars = 0
        for paragraph in doc.paragraphs:
            text = paragraph.text.strip()
            if not text:
                continue
            total_chars += len(text) + (1 if paragraphs else 0)
            if total_chars > MAX_PARSED_TEXT_CHARS:
                raise ParseError("request_too_large", "Parsed document exceeds the text limit.")
            paragraphs.append(text)
        full_text = "\n".join(paragraphs)
        if not full_text:
            raise ParseError("validation_error", "DOCX contains no text.")
        return ParsedDocument(text=full_text, pages=[ParsedPage(page_number=1, text=full_text)])


class ControlledPdfParser:
    """Controlled PDF ingestion: page batches + heartbeat + page provenance.

    Mirrors the legacy controlled pipeline contract (bounded memory, per-batch
    heartbeat, page-number provenance). Requires pdfplumber at call time.
    """

    def __init__(self, *, pages_per_batch: int = 10, heartbeat=None, max_text_chars: int = MAX_PARSED_TEXT_CHARS) -> None:
        self.pages_per_batch = pages_per_batch
        self.heartbeat = heartbeat or (lambda **kwargs: None)
        self.max_text_chars = max_text_chars

    def page_count(self, path: Path) -> int:
        try:
            import pdfplumber
        except ImportError as exc:
            raise ParseError("ingestion_failed", "PDF support is not installed.") from exc
        try:
            with pdfplumber.open(str(path)) as pdf:
                return len(pdf.pages)
        except Exception as exc:
            raise ParseError("validation_error", "Could not open PDF document.") from exc

    def parse(self, path: Path, *, workspace_id: str) -> ParsedDocument:
        try:
            import pdfplumber
        except ImportError as exc:
            raise ParseError("ingestion_failed", "PDF support is not installed.") from exc
        pages: list[ParsedPage] = []
        total_chars = 0
        try:
            with pdfplumber.open(str(path)) as pdf:
                total = len(pdf.pages)
                for start in range(0, total, self.pages_per_batch):
                    batch = pdf.pages[start:start + self.pages_per_batch]
                    for offset, page in enumerate(batch):
                        try:
                            text = page.extract_text() or ""
                        finally:
                            # Bounded memory: release page resources promptly.
                            close = getattr(page, "close", None)
                            if callable(close):
                                try:
                                    close()
                                except Exception:
                                    pass
                        if text.strip():
                            total_chars += len(text) + (1 if pages else 0)
                            if total_chars > self.max_text_chars:
                                raise ParseError("request_too_large", "Parsed document exceeds the text limit.")
                            if len(pages) >= MAX_PARSED_PAGES:
                                raise ParseError("request_too_large", "Document contains too many pages.")
                            pages.append(ParsedPage(page_number=start + offset + 1, text=text))
                    self.heartbeat(stage="parsing", pages_done=min(start + self.pages_per_batch, total), pages_total=total)
        except ParseError:
            raise
        except Exception as exc:
            raise ParseError("validation_error", "Could not parse PDF document.") from exc
        full_text = "\n".join(p.text for p in pages)
        if not full_text.strip():
            raise ParseError("validation_error", "PDF contains no extractable text.")
        return ParsedDocument(text=full_text, pages=pages)


def parser_for(path: Path, *, pdf_heartbeat=None) -> DocumentParser:
    suffix = path.suffix.lower()
    if suffix == ".txt":
        return TxtParser()
    if suffix == ".md":
        return MarkdownParser()
    if suffix == ".docx":
        return DocxParser()
    if suffix == ".pdf":
        return ControlledPdfParser(heartbeat=pdf_heartbeat)
    raise UnsupportedFormatError(suffix)
