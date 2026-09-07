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
    page_end: int | None = None


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


def _trimmed_span(start: int, value: str) -> tuple[int, int]:
    """Return the source span represented by ``value.strip()``."""

    left = len(value) - len(value.lstrip())
    right = len(value.rstrip())
    return start + left, start + right


def _page_span(char_positions: list[int], boundaries: list[tuple[int, int]]) -> tuple[int | None, int | None]:
    """Map the first and last source characters in a chunk to their pages."""

    if not char_positions:
        return None, None
    first = min(char_positions)
    last = max(char_positions)
    return _page_hint(first, boundaries), _page_hint(last, boundaries)


def _sentence_spans(text: str, text_start: int) -> list[tuple[str, int, int]]:
    """Split sentences while retaining each stripped sentence's source span."""

    spans: list[tuple[str, int, int]] = []
    segment_start = 0
    for match in _SENTENCE_ENDINGS.finditer(text):
        raw_sentence = text[segment_start:match.start()]
        start, end = _trimmed_span(segment_start, raw_sentence)
        if start < end:
            spans.append((text[start:end], text_start + start, text_start + end))
        segment_start = match.end()

    raw_sentence = text[segment_start:]
    start, end = _trimmed_span(segment_start, raw_sentence)
    if start < end:
        spans.append((text[start:end], text_start + start, text_start + end))
    return spans


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
        current_positions: list[int] = []

        def append_plan(chunk_text: str, char_positions: list[int]) -> None:
            clean_text = chunk_text.strip()
            if not clean_text:
                return
            left = len(chunk_text) - len(chunk_text.lstrip())
            right = len(chunk_text) - len(chunk_text.rstrip())
            clean_positions = char_positions[left:len(char_positions) - right if right else None]
            page_start, page_end = _page_span(clean_positions, boundaries)
            plans.append(ChunkPlan(
                text=clean_text,
                chunk_index=len(plans),
                page_start=page_start,
                page_end=page_end,
                checksum=content_checksum(clean_text),
            ))

        def flush() -> None:
            nonlocal current_text, current_positions
            if current_text.strip():
                append_plan(current_text, current_positions)
                current_text = ""
                current_positions = []

        def start_with_overlap(prev_text: str, prev_positions: list[int]) -> None:
            nonlocal current_text, current_positions
            overlap_text = prev_text[-overlap:] if overlap > 0 else ""
            current_text = overlap_text
            current_positions = prev_positions[-len(overlap_text):] if overlap_text else []

        for para_start, para_text in _paragraphs_with_positions(all_text):
            para_content_start, para_content_end = _trimmed_span(para_start, para_text)
            para_text = para_text.strip()
            if not para_text:
                continue
            if _SEPARATOR_PATTERN.match(para_text):
                if current_text.strip():
                    prev, prev_positions = current_text, current_positions
                    flush()
                    start_with_overlap(prev, prev_positions)
                    current_text = ""
                    current_positions = []
                continue
            if len(para_text) > chunk_size:
                if current_text:
                    prev, prev_positions = current_text, current_positions
                    flush()
                    start_with_overlap(prev, prev_positions)
                    current_text = ""
                    current_positions = []
                for sentence_text, sentence_positions in self._split_sentences_with_positions(
                    para_text,
                    para_content_start,
                    chunk_size,
                ):
                    append_plan(sentence_text, sentence_positions)
                continue
            if len(current_text) + len(para_text) + 1 > chunk_size and current_text:
                prev, prev_positions = current_text, current_positions
                flush()
                start_with_overlap(prev, prev_positions)
            if current_text:
                current_text += "\n" + para_text
                separator_position = max(para_content_start - 1, 0)
                current_positions.append(separator_position)
                current_positions.extend(range(para_content_start, para_content_end))
            else:
                current_text = para_text
                current_positions = list(range(para_content_start, para_content_end))
        if current_text.strip():
            flush()
        return plans

    def _split_sentences_with_positions(
        self,
        text: str,
        text_start: int,
        chunk_size: int,
    ) -> list[tuple[str, list[int]]]:
        """Pack sentences and retain the source characters each chunk spans."""

        out: list[tuple[str, list[int]]] = []
        current = ""
        current_positions: list[int] = []
        for sentence, sentence_start, sentence_end in _sentence_spans(text, text_start):
            if len(current) + len(sentence) + 1 <= chunk_size:
                if current:
                    current += " " + sentence
                    current_positions.append(max(sentence_start - 1, 0))
                else:
                    current = sentence
                current_positions.extend(range(sentence_start, sentence_end))
            else:
                if current:
                    out.append((current, current_positions))
                current = sentence
                current_positions = list(range(sentence_start, sentence_end))
        if current.strip():
            out.append((current.strip(), current_positions))
        return out

    def _split_sentences_with_overlap(self, text: str, chunk_size: int, overlap: int) -> list[str]:
        """Sentence packing (legacy parity).

        Faithful mirror: when a sentence overflows the running chunk, the chunk
        is flushed and the NEXT chunk starts at that sentence boundary — the
        overlap-window assignment in the legacy sentence path is overwritten by
        the sentence restart, so sentence chunks carry no char overlap.
        """
        return [
            sentence
            for sentence, _positions in self._split_sentences_with_positions(
                text,
                0,
                chunk_size,
            )
        ]
