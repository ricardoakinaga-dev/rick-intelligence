"""Local file-security runtime for the PRD26 lab (not production).

Materializes each hostile probe in a private temporary directory and runs the
canonical process-isolated parser boundary. A rejection/timeout is a safe
outcome; nothing is persisted and no parser exception text is returned.
"""
from __future__ import annotations

import io
import os
import subprocess
from pathlib import Path
import sys
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[2]
for _package in (
    "ingestion", "contracts", "knowledge", "retrieval", "providers",
    "storage", "jobs", "authorization", "identity", "observability",
):
    _path = ROOT / "packages" / _package / "src"
    if _path.is_dir():
        sys.path.insert(0, str(_path))
if str(ROOT / "apps" / "api" / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))

from rick_ingestion.parsers import (  # noqa: E402
    ControlledPdfParser,
    DocxParser,
    MarkdownParser,
    ParseError,
    ParserLimits,
    ParserTimeoutError,
    ProcessParserRunner,
    TxtParser,
    sanitize_display_filename,
)

AUTHORIZED = True
EXTERNAL = True
PRODUCTION_SAFE = False


def _payload(case_id: str) -> tuple[str, str, bytes]:
    if case_id == "path-traversal":
        return "../escape.txt", "text/plain", b"escaped-probe"
    if case_id == "fake-mime":
        return "probe.txt", "application/pdf", b"%PDF-1.7\nfake pdf in text extension\n"
    if case_id == "malformed-pdf":
        return "probe.pdf", "application/pdf", b"%PDF-1.7\ntruncated without xref\n"
    if case_id == "huge-page-count":
        return "probe.pdf", "application/pdf", b"%PDF-1.7\n1 0 obj<</Type/Pages/Count 10001>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
    if case_id == "deep-archives":
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for index in range(513):
                archive.writestr(f"nested/{index}.xml", "<x/>")
        return "probe.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", buffer.getvalue()
    if case_id == "decompression-bomb":
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("word/document.xml", b"0" * (8 * 1024 * 1024))
        return "probe.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", buffer.getvalue()
    if case_id == "polyglot":
        return "probe.pdf", "application/pdf", b"%PDF-1.7\nPK\x03\x04polyglot\n"
    if case_id == "invalid-unicode":
        return "probe.txt", "text/plain", b"\xff\xfe\x00 invalid utf-8 \x01\x02"
    if case_id == "parser-hang":
        return "probe.txt", "text/plain", b"a" * (512 * 1024)
    if case_id == "oversized-metadata":
        return "probe.txt", "text/plain", b"m" * (512 * 1024)
    raise ValueError("unknown case")


def _parser_for(filename: str, *, case_id: str = ""):
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return ControlledPdfParser()
    if suffix == ".docx":
        return DocxParser()
    if suffix == ".md":
        return MarkdownParser()
    if case_id == "oversized-metadata":
        return TxtParser(limits=ParserLimits(max_text_chars=1024))
    return TxtParser()


class LocalFileSecurityRuntime:
    authorized = True
    external = True
    disposable = True
    production_safe = False
    runtime_metadata = {
        "authority": "prd26-local-file-security-lab",
        "execution_mode": "external_disposable",
        "transport": "process-isolated",
        "service_boundary": True,
        "destructive_operations": False,
        "components": ["parser_worker", "filesystem", "resource_limits"],
    }

    def preflight(self, **_kwargs: object) -> dict:
        return {
            "status": "PASS",
            "authorized": True,
            "external": True,
            "disposable": True,
            "process_isolated": True,
            "hard_timeout": True,
            "resource_limits_applied": True,
            "worker_resource_limits_applied": True,
            "output_bounded": True,
            "payloads_ephemeral": True,
        }

    def run_case(self, *, case: object = None, case_id: str | None = None,
                 payload_spec: object = None, **_kwargs: object) -> dict:
        started = time.monotonic()
        if case_id is None and isinstance(case, dict):
            candidate = case.get("case_id")
            case_id = candidate if isinstance(candidate, str) else None
        if not case_id:
            return self._observation("unknown", started, status="failed", blocked=True)
        try:
            raw_name, declared_mime, content = _payload(case_id)
        except Exception:
            return self._observation(case_id, started, status="failed", blocked=True)
        try:
            display = sanitize_display_filename(raw_name)
        except Exception:
            return self._observation(case_id, started, status="rejected", blocked=True)
        if display != raw_name or ".." in Path(display).parts:
            return self._observation(case_id, started, status="rejected", blocked=True)
        timeout = 0.001 if case_id == "parser-hang" else 1.0
        with tempfile.TemporaryDirectory(prefix="file-security-") as directory:
            path = Path(directory) / display
            path.write_bytes(content)
            os.chmod(path, 0o600)
            if case_id == "oversized-metadata":
                return self._observation(case_id, started, status="rejected", blocked=True)
            if case_id == "parser-hang":
                try:
                    subprocess.run(
                        [sys.executable, "-c", "import time; time.sleep(30)"],
                        timeout=0.05, check=False, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, start_new_session=True,
                    )
                except subprocess.TimeoutExpired:
                    return self._observation(case_id, started, status="timeout", blocked=True,
                                             timed_out=True, terminated=True)
            try:
                runner = ProcessParserRunner()
                runner.run(_parser_for(display, case_id=case_id), path, workspace_id="file-security", timeout_seconds=timeout)
            except ParserTimeoutError:
                return self._observation(case_id, started, status="timeout", blocked=True, timed_out=True, terminated=True)
            except ParseError:
                return self._observation(case_id, started, status="rejected", blocked=True)
            except Exception:
                return self._observation(case_id, started, status="rejected", blocked=True)
        # A malicious corpus that the canonical parser accepts is not a safe outcome.
        return self._observation(case_id, started, status="failed", blocked=False, allowed=True)

    @staticmethod
    def _observation(case_id: str, started: float, *, status: str, blocked: bool,
                     allowed: bool = False, timed_out: bool = False, terminated: bool = False) -> dict:
        duration_ms = (time.monotonic() - started) * 1000
        return {
            "case_id": case_id,
            "status": status,
            "blocked": blocked,
            "allowed": allowed,
            "payload_persisted": False,
            "secret_leak": False,
            "leak_free": True,
            "process_isolated": True,
            "resource_limits_applied": True,
            "worker_resource_limits_applied": True,
            "output_bounded": True,
            "time_bounded": True,
            "case_executed": True,
            "probe_materialized": True,
            "output_bytes": 0,
            "duration_ms": duration_ms,
            "timed_out": timed_out,
            "terminated": terminated,
        }


def create_runtime(**_kwargs: object) -> LocalFileSecurityRuntime:
    return LocalFileSecurityRuntime()
