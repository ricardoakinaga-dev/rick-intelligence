"""Recursive chunking strategy — behavioral mirror of the validated legacy splitter.

chunk_size=1200, overlap=240, word/paragraph boundaries, sentence fallback for
oversized paragraphs, char-overlap windows between paragraph chunks,
page-hint tracking, stable chunk_{doc}_{index:04d} identity. No
smarter/experimental chunking in migration.

Port notes (differentially proven): the legacy sentence path restarts each
overflowed chunk at the sentence boundary (its overlap assignment is
overwritten), so sentence chunks carry no char overlap — mirrored exactly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from rick_knowledge import chunk_id_for_document, content_checksum

CHUNKER_VERSION = "rick-chunker-recursive-v1"
DEFAULT_CHUNK_SIZE = 1200
DEFAULT_OVERLAP = 240

_SEPARATOR_PATTERN = re.compile(r"^\s*(?:---+|\*\*\*+|___+)\s*$")
_SENTENCE_ENDINGS = re.compile(r"(?<=[.!?])\s+")


@dataclass
class ChunkPlan:
    text: str
    chunk_index: int
    page_start: int | None
    checksum: str


class ChunkingStrategy(Protocol):
    def chunk(self, *, text: str, pages: list[tuple[int, str]], document_id: str,
              chunk_size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_OVERLAP) -> list[ChunkPlan]: ...


def _page_hint(char_pos: int, boundaries: list[tuple[int, int]]) -> int | None:
    for i in range(len(boundaries) - 1):
        start, page = boundaries[i]
        end, _ = boundaries[i + 1]
        if start <= char_pos < end:
            return page
    return boundaries[-1][1] if boundaries else None


def _paragraphs_with_positions(text: str) -> list[tuple[int, str]]:
    result: list[tuple[int, str]] = []
    if "\n\n" in text:
        current_pos = 0
        for part in re.split(r"\n{2,}", text):
            if part.strip():
                found = text.find(part, current_pos)
                if found >= 0:
                    result.append((found, part))
                    current_pos = found + len(part)
    else:
        current_pos = 0
        for part in text.split("\n"):
            if part.strip():
                found = text.find(part, current_pos)
                if found >= 0:
                    result.append((found, part))
                    current_pos = found + len(part)
    return result


class RecursiveChunkingStrategy:
    """One strategy implementation: the validated recursive splitter."""

    def chunk(self, *, text, pages, document_id, chunk_size=DEFAULT_CHUNK_SIZE, overlap=DEFAULT_OVERLAP) -> list[ChunkPlan]:
        all_text = ""
        boundaries: list[tuple[int, int]] = []
        char_pos = 0
        for page_number, page_text in pages:
            boundaries.append((char_pos, page_number))
            all_text += page_text + "\n"
            char_pos += len(page_text) + 1

        plans: list[ChunkPlan] = []
        current_text = ""
        current_start = 0

        def flush() -> None:
            nonlocal current_text, current_start
            if current_text.strip():
                plans.append(ChunkPlan(
                    text=current_text.strip(),
                    chunk_index=len(plans),
                    page_start=_page_hint(current_start, boundaries),
                    checksum=content_checksum(current_text.strip()),
                ))
                current_text = ""
                current_start = 0

        def start_with_overlap(prev_text: str, prev_start: int) -> None:
            nonlocal current_text, current_start
            overlap_text = prev_text[-overlap:] if overlap > 0 else ""
            prev_end = prev_start + len(prev_text)
            current_text = overlap_text
            current_start = prev_end - overlap if overlap > 0 else prev_end

        for para_start, para_text in _paragraphs_with_positions(all_text):
            para_text = para_text.strip()
            if not para_text:
                continue
            if _SEPARATOR_PATTERN.match(para_text):
                if current_text.strip():
                    prev, prev_start = current_text, current_start
                    flush()
                    start_with_overlap(prev, prev_start)
                    current_text = ""
                current_start = para_start + len(para_text)
                continue
            if len(para_text) > chunk_size:
                if current_text:
                    prev, prev_start = current_text, current_start
                    flush()
                    start_with_overlap(prev, prev_start)
                    current_text = ""
                for sentence_text in self._split_sentences_with_overlap(para_text, chunk_size, overlap):
                    plans.append(ChunkPlan(
                        text=sentence_text,
                        chunk_index=len(plans),
                        page_start=_page_hint(para_start, boundaries),
                        checksum=content_checksum(sentence_text),
                    ))
                current_start = para_start + len(para_text)
                continue
            if len(current_text) + len(para_text) + 1 > chunk_size and current_text:
                prev, prev_start = current_text, current_start
                flush()
                start_with_overlap(prev, prev_start)
            if current_text:
                current_text += "\n" + para_text
            else:
                current_text = para_text
                current_start = para_start
        if current_text.strip():
            prev_start = current_start
            flush()
        return plans

    def _split_sentences_with_overlap(self, text: str, chunk_size: int, overlap: int) -> list[str]:
        """Sentence packing (legacy parity).

        Faithful mirror: when a sentence overflows the running chunk, the chunk
        is flushed and the NEXT chunk starts at that sentence boundary — the
        overlap-window assignment in the legacy sentence path is overwritten by
        the sentence restart, so sentence chunks carry no char overlap.
        """
        sentences = [s.strip() for s in _SENTENCE_ENDINGS.split(text) if s.strip()]
        out: list[str] = []
        current = ""
        for sentence in sentences:
            if len(current) + len(sentence) + 1 <= chunk_size:
                current = f"{current} {sentence}".strip()
            else:
                if current:
                    out.append(current)
                current = sentence
        if current.strip():
            out.append(current.strip())
        return out
