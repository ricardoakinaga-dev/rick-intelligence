"""Parser interface + validated format adapters (PDF/DOCX/MD/TXT).

No HTTP objects. PDF uses the controlled page-batch path (memory-safe,
heartbeat, cleanup); the all-in-memory PDF path stays disabled like legacy.
Storage safety: generated storage names, traversal prevention, display names
as metadata only.
"""

from __future__ import annotations

import re
import secrets
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

SUPPORTED_EXTENSIONS = frozenset({".pdf", ".docx", ".md", ".txt"})
PARSER_VERSION = "rick-parser-v1"

MAX_FILE_BYTES = 50 * 1024 * 1024


class ParseError(Exception):
    def __init__(self, code: str = "ingestion_failed", message: str = "Could not parse document."):
        super().__init__(message)
        self.code = code


class UnsupportedFormatError(ParseError):
    def __init__(self, suffix: str):
        super().__init__("unsupported_media_type", f"Unsupported format: {suffix or '(none)'}")


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
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="latin-1")
        except OSError as exc:
            raise ParseError() from exc
        if not text.strip():
            raise ParseError("validation_error", "Document is empty.")
        return ParsedDocument(text=text, pages=[ParsedPage(page_number=1, text=text)])


class MarkdownParser:
    _HEADING = re.compile(r"^(#{1,6})\s+(.*)$")

    def parse(self, path: Path, *, workspace_id: str) -> ParsedDocument:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ParseError() from exc
        if not text.strip():
            raise ParseError("validation_error", "Document is empty.")
        sections = [
            {"heading": match.group(2).strip(), "level": len(match.group(1))}
            for match in self._HEADING.finditer(text)
        ]
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
        full_text = "\n".join(p.text.strip() for p in doc.paragraphs if p.text.strip())
        if not full_text:
            raise ParseError("validation_error", "DOCX contains no text.")
        return ParsedDocument(text=full_text, pages=[ParsedPage(page_number=1, text=full_text)])


class ControlledPdfParser:
    """Controlled PDF ingestion: page batches + heartbeat + page provenance.

    Mirrors the legacy controlled pipeline contract (bounded memory, per-batch
    heartbeat, page-number provenance). Requires pdfplumber at call time.
    """

    def __init__(self, *, pages_per_batch: int = 10, heartbeat=None) -> None:
        self.pages_per_batch = pages_per_batch
        self.heartbeat = heartbeat or (lambda **kwargs: None)

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
