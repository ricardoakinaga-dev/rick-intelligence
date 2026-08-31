"""
Recursive Chunker — chunk_size=1200, overlap=240
Respects word boundaries, prefers paragraph breaks.
"""
import re
import uuid
from datetime import datetime, timezone
from typing import Iterator

from models.schemas import Chunk, NormalizedDocument

MARKDOWN_SEPARATOR_PATTERN = re.compile(r"^\s*(?:---+|\*\*\*+|___+)\s*$")


def recursive_chunk(
    normalized_doc: NormalizedDocument,
    chunk_size: int = 1200,
    overlap: int = 240,
    workspace_id: str = "default"
) -> list[Chunk]:
    """
    Split document text into chunks using recursive character splitting
    that prefers paragraph and sentence boundaries.

    Args:
        normalized_doc: Parsed document
        chunk_size: Target size per chunk (characters)
        overlap: Overlap between chunks (characters)
        workspace_id: Workspace identifier

    Returns:
        List of Chunk objects
    """
    # Combine all page text preserving page boundaries for page_hint
    all_text = ""
    page_boundaries = []  # (char_start, page_number)

    char_pos = 0
    for page in normalized_doc.pages:
        page_start = char_pos
        page_text = page["text"]
        page_num = page["page_number"]
        page_boundaries.append((page_start, page_num))
        all_text += page_text + "\n"
        char_pos += len(page_text) + 1

    chunks = []
    chunk_index = 0

    # Split into paragraphs WITH POSITIONS
    paragraphs = _split_into_paragraphs_with_positions(all_text)

    current_chunk_text = ""
    current_chunk_start = 0  # Start position in all_text

    for para_start, para_text in paragraphs:
        para_text = para_text.strip()
        if not para_text:
            continue

        if MARKDOWN_SEPARATOR_PATTERN.match(para_text):
            if current_chunk_text.strip():
                chunk = _make_chunk(
                    text=current_chunk_text,
                    doc_id=normalized_doc.document_id,
                    workspace_id=workspace_id,
                    chunk_index=chunk_index,
                    start_char=current_chunk_start,
                    end_char=current_chunk_start + len(current_chunk_text),
                    page_hint=_get_page_hint(current_chunk_start, page_boundaries),
                    strategy="recursive",
                    chunk_size=chunk_size
                )
                chunks.append(chunk)
                chunk_index += 1
            current_chunk_text = ""
            current_chunk_start = para_start + len(para_text)
            continue

        para_len = len(para_text)

        # If single paragraph exceeds chunk_size, split it further
        if para_len > chunk_size:
            # Save current chunk if non-empty
            if current_chunk_text:
                chunk = _make_chunk(
                    text=current_chunk_text,
                    doc_id=normalized_doc.document_id,
                    workspace_id=workspace_id,
                    chunk_index=chunk_index,
                    start_char=current_chunk_start,
                    end_char=current_chunk_start + len(current_chunk_text),
                    page_hint=_get_page_hint(current_chunk_start, page_boundaries),
                    strategy="recursive",
                    chunk_size=chunk_size
                )
                chunks.append(chunk)
                chunk_index += 1

                # Start next chunk with overlap from current
                overlap_text = current_chunk_text[-overlap:] if overlap > 0 else ""
                prev_end = current_chunk_start + len(current_chunk_text)
                current_chunk_text = overlap_text
                current_chunk_start = prev_end - overlap if overlap > 0 else prev_end

            # Split long paragraph by sentences
            sub_chunks = _split_by_sentences_with_position(
                para_text, para_start, chunk_size, overlap,
                normalized_doc.document_id, workspace_id, chunk_index,
                page_boundaries
            )
            chunks.extend(sub_chunks)
            chunk_index += len(sub_chunks)
            current_chunk_text = ""
            current_chunk_start = para_start + para_len  # Position after this paragraph
            continue

        # If adding this paragraph exceeds chunk_size, flush current and start new
        if len(current_chunk_text) + para_len + 1 > chunk_size and current_chunk_text:
            chunk = _make_chunk(
                text=current_chunk_text,
                doc_id=normalized_doc.document_id,
                workspace_id=workspace_id,
                chunk_index=chunk_index,
                start_char=current_chunk_start,
                end_char=current_chunk_start + len(current_chunk_text),
                page_hint=_get_page_hint(current_chunk_start, page_boundaries),
                strategy="recursive",
                chunk_size=chunk_size
            )
            chunks.append(chunk)
            chunk_index += 1

            # Start new chunk with overlap
            overlap_text = current_chunk_text[-overlap:] if overlap > 0 else ""
            prev_end = current_chunk_start + len(current_chunk_text)
            current_chunk_text = overlap_text
            current_chunk_start = prev_end - overlap if overlap > 0 else prev_end

        # Append paragraph to current chunk
        if current_chunk_text:
            current_chunk_text += "\n" + para_text
            # Start position stays the same for continuation
        else:
            current_chunk_text = para_text
            current_chunk_start = para_start

    # Flush remaining
    if current_chunk_text.strip():
        chunk = _make_chunk(
            text=current_chunk_text,
            doc_id=normalized_doc.document_id,
            workspace_id=workspace_id,
            chunk_index=chunk_index,
            start_char=current_chunk_start,
            end_char=current_chunk_start + len(current_chunk_text),
            page_hint=_get_page_hint(current_chunk_start, page_boundaries),
            strategy="recursive",
            chunk_size=chunk_size
        )
        chunks.append(chunk)

    return chunks


def _split_into_paragraphs_with_positions(text: str) -> list[tuple[int, str]]:
    """
    Split text into paragraphs, returning (start_position, paragraph_text).
    Preserves the actual character position of each paragraph in the original text.
    """
    result = []
    pos = 0

    # Split by paragraph breaks (2+ newlines) or single newlines if no paragraphs
    parts = re.split(r"\n{2,}", text)
    single_parts = re.split(r"\n", text)

    # Check if we have actual paragraph breaks
    has_double_newline = "\n\n" in text

    if has_double_newline:
        # Real paragraphs - use double newline as delimiter
        current_pos = 0
        for part in parts:
            if part.strip():
                # Find the position of this part in the original text
                found_pos = text.find(part, current_pos)
                if found_pos >= 0:
                    result.append((found_pos, part))
                    current_pos = found_pos + len(part)
    else:
        # No double newlines, treat each line as a paragraph
        current_pos = 0
        for part in single_parts:
            if part.strip():
                found_pos = text.find(part, current_pos)
                if found_pos >= 0:
                    result.append((found_pos, part))
                    current_pos = found_pos + len(part)

    return result


def _split_by_sentences_with_position(
    text: str,
    text_start: int,
    chunk_size: int,
    overlap: int,
    doc_id: str,
    workspace_id: str,
    start_index: int,
    page_boundaries: list
) -> list[Chunk]:
    """Split long text by sentences while respecting chunk_size and tracking position."""
    sentence_endings = re.compile(r"(?<=[.!?])\s+")
    sentences = sentence_endings.split(text)

    chunks = []
    current = ""
    current_start_offset = 0  # Offset within the original text
    chunk_idx = start_index

    for i, sentence in enumerate(sentences):
        sentence = sentence.strip()
        if not sentence:
            continue

        sentence_len = len(sentence)

        if len(current) + sentence_len + 1 <= chunk_size:
            if current:
                current += " " + sentence
            else:
                current = sentence
                current_start_offset = text_start + _find_sentence_offset(text, sentence, i)
        else:
            if current:
                chunks.append(_make_chunk(
                    current, doc_id, workspace_id, chunk_idx,
                    start_char=current_start_offset,
                    end_char=current_start_offset + len(current),
                    page_hint=_get_page_hint(current_start_offset, page_boundaries),
                    strategy="recursive",
                    chunk_size=chunk_size
                ))
                chunk_idx += 1

                # Start next with overlap
                overlap_text = current[-overlap:] if overlap > 0 else ""
                current = overlap_text
                current_start_offset = current_start_offset + len(current) - len(overlap_text) if overlap > 0 else current_start_offset + len(current)

            # Start new sentence
            current = sentence
            # Find where this sentence starts in the original text
            current_start_offset = text_start + _find_sentence_offset(text, sentence, i)

    if current.strip():
        chunks.append(_make_chunk(
            current, doc_id, workspace_id, chunk_idx,
            start_char=current_start_offset,
            end_char=current_start_offset + len(current),
            page_hint=_get_page_hint(current_start_offset, page_boundaries),
            strategy="recursive",
            chunk_size=chunk_size
        ))

    return chunks


def _find_sentence_offset(full_text: str, sentence: str, sentence_idx: int) -> int:
    """
    Find the character offset of a sentence within the full text.
    Uses regex to find the sentence boundary.
    """
    # Build a pattern that matches up to this sentence
    sentence_endings = re.compile(r"(?<=[.!?])\s+")
    all_sentences = sentence_endings.split(full_text)

    # Sum up lengths of previous sentences
    offset = 0
    for i in range(sentence_idx):
        if i < len(all_sentences):
            offset += len(all_sentences[i]) + 1  # +1 for the separator

    return offset


def _get_page_hint(char_pos: int, page_boundaries: list[tuple[int, int]]) -> int | None:
    """Find which page a character position belongs to."""
    for i in range(len(page_boundaries) - 1):
        start, page = page_boundaries[i]
        end, _ = page_boundaries[i + 1]
        if start <= char_pos < end:
            return page
    # Last page
    if page_boundaries:
        return page_boundaries[-1][1]
    return None


def _make_chunk(
    text: str,
    doc_id: str,
    workspace_id: str,
    chunk_index: int,
    start_char: int,
    end_char: int,
    page_hint: int | None,
    strategy: str,
    chunk_size: int
) -> Chunk:
    return Chunk(
        chunk_id=f"chunk_{doc_id}_{chunk_index:04d}",
        document_id=doc_id,
        workspace_id=workspace_id,
        chunk_index=chunk_index,
        text=text.strip(),
        start_char=start_char,
        end_char=end_char,
        page_hint=page_hint,
        strategy=strategy,
        chunk_size_chars=len(text.strip()),
        created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )


# ── Semantic Chunker ──────────────────────────────────────────────────────────

SENTENCE_ENDINGS = re.compile(r"(?<=[.!?])\s+")


def _split_into_sentences(text: str) -> list[str]:
    """Split text into sentences."""
    sentences = SENTENCE_ENDINGS.split(text)
    return [s.strip() for s in sentences if s.strip()]


def semantic_chunk(
    normalized_doc: NormalizedDocument,
    chunk_size: int = 300,
    overlap: int = 50,
    coherence_threshold: float = 0.7,
    workspace_id: str = "default"
) -> list[Chunk]:
    """
    Chunk document using sentence-level grouping with semantic coherence.

    Strategy:
    1. Split document into sentences.
    2. Accumulate sentences greedily into chunks up to chunk_size.
    3. Use embeddings (when available) to detect coherence break points —
       start a new chunk when consecutive sentences have low cosine similarity.
    4. When embeddings are unavailable (offline), falls back to greedy
       sentence accumulation without coherence breaks.

    Args:
        normalized_doc: Parsed document
        chunk_size: Target size per chunk (characters, smaller than recursive for sentence fidelity)
        overlap: Overlap between chunks (characters)
        coherence_threshold: fraction of running average similarity below which to break
        workspace_id: Workspace identifier

    Returns:
        List of Chunk objects with strategy="semantic"
    """
    all_text = ""
    page_boundaries = []

    char_pos = 0
    for page in normalized_doc.pages:
        page_start = char_pos
        page_num = page["page_number"]
        page_boundaries.append((page_start, page_num))
        page_text = page["text"]
        all_text += page_text + "\n"
        char_pos += len(page_text) + 1

    sentences = _split_into_sentences(all_text)
    if not sentences:
        return []

    # Build initial sentence-level chunks greedily
    raw_chunks: list[list[str]] = []
    current_sentences: list[str] = []
    current_len = 0

    for sent in sentences:
        if current_len + len(sent) + 1 <= chunk_size:
            current_sentences.append(sent)
            current_len += len(sent) + 1
        else:
            if current_sentences:
                raw_chunks.append(current_sentences)
            current_sentences = [sent]
            current_len = len(sent) + 1

    if current_sentences:
        raw_chunks.append(current_sentences)

    # Optionally merge/break chunks based on embedding coherence
    final_chunks = _coherence_breakpoints(
        raw_chunks,
        coherence_threshold=coherence_threshold,
        chunk_size=chunk_size,
    )

    # Convert to Chunk objects
    chunks: list[Chunk] = []
    chunk_index = 0
    global_pos = 0

    for raw in final_chunks:
        text = " ".join(raw)
        # Find position of this text in all_text
        found_pos = all_text.find(text, global_pos)
        if found_pos < 0:
            found_pos = global_pos
        start = found_pos
        end = start + len(text)

        chunk = Chunk(
            chunk_id=f"chunk_{normalized_doc.document_id}_{chunk_index:04d}",
            document_id=normalized_doc.document_id,
            workspace_id=workspace_id,
            chunk_index=chunk_index,
            text=text,
            start_char=start,
            end_char=end,
            page_hint=_get_page_hint(start, page_boundaries),
            strategy="semantic",
            chunk_size_chars=len(text),
            created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        )
        chunks.append(chunk)
        chunk_index += 1
        global_pos = end

    return chunks


def _coherence_breakpoints(
    raw_chunks: list[list[str]],
    coherence_threshold: float,
    chunk_size: int,
) -> list[list[str]]:
    """
    Detect semantic coherence break points between consecutive sentence groups.

    Uses embeddings (when available) to compute cosine similarity between consecutive
    chunk texts. Breaks before a chunk when similarity to next chunk is significantly
    lower than the running average.

    Falls back to returning raw_chunks unchanged when embeddings are unavailable.
    """
    if len(raw_chunks) <= 1:
        return raw_chunks

    try:
        texts_to_embed = []
        indices = []
        for i, chunk_sentences in enumerate(raw_chunks):
            text = " ".join(chunk_sentences)
            if text.strip():
                texts_to_embed.append(text[:8000])
                indices.append(i)

        if not texts_to_embed:
            return raw_chunks

        from services.embedding_service import get_embeddings_batch
        embeddings = get_embeddings_batch(texts_to_embed)
    except Exception:
        # Offline or API error — return raw chunks without coherence breaks
        return raw_chunks

    if len(embeddings) != len(indices):
        return raw_chunks

    # Compute cosine similarity between consecutive chunks
    similarities: list[float | None] = [None] * len(raw_chunks)
    import math
    for idx in range(len(indices) - 1):
        e1 = embeddings[idx]
        e2 = embeddings[idx + 1]
        dot = sum(a * b for a, b in zip(e1, e2))
        norm1 = math.sqrt(sum(a * a for a in e1))
        norm2 = math.sqrt(sum(b * b for b in e2))
        if norm1 > 0 and norm2 > 0:
            similarities[indices[idx]] = dot / (norm1 * norm2)
        else:
            similarities[indices[idx]] = 0.0

    # Running average similarity
    valid_sims = [s for s in similarities if s is not None and s > 0]
    if not valid_sims:
        return raw_chunks

    avg_sim = sum(valid_sims) / len(valid_sims)
    threshold = avg_sim * coherence_threshold

    # Merge chunks where similarity is above threshold
    merged: list[list[str]] = []
    current_group: list[str] = []

    for i, sentences in enumerate(raw_chunks):
        sim = similarities[i]
        if sim is not None and sim < threshold and current_group:
            # Coherence break — finalize current group
            merged.append(current_group)
            current_group = sentences
        else:
            # Keep accumulating
            current_group.extend(sentences)

    if current_group:
        merged.append(current_group)

    # Ensure we haven't over-merged (each original chunk at least as candidate)
    if not merged:
        return raw_chunks

    # If everything merged into one, keep original granularity
    if len(merged) == 1 and len(raw_chunks) > 1:
        return raw_chunks

    return merged
# Keep old functions for compatibility
def _split_into_paragraphs(text: str) -> list[str]:
    """Split text by double newlines (paragraphs) or single newlines."""
    parts = re.split(r"\n{2,}", text)
    if len(parts) == 1:
        parts = re.split(r"\n", text)
    return [p for p in parts if p.strip()]


def _find_text_start(full_text: str, chunk_text: str) -> int:
    """Find the start position of chunk_text in full_text."""
    idx = full_text.find(chunk_text)
    return idx if idx >= 0 else 0


def _split_by_sentences(text: str, chunk_size: int, overlap: int, page_boundaries, doc_id, workspace_id, start_index: int) -> list[Chunk]:
    """Legacy function - returns chunks without position info."""
    sentence_endings = re.compile(r"(?<=[.!?])\s+")
    sentences = sentence_endings.split(text)

    chunks = []
    current = ""
    chunk_idx = start_index

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        if len(current) + len(sentence) + 1 <= chunk_size:
            current = (current + " " + sentence).strip() if current else sentence
        else:
            if current:
                chunks.append(_make_chunk(
                    current, doc_id, workspace_id, chunk_idx,
                    start_char=0, end_char=len(current),
                    page_hint=None, strategy="recursive", chunk_size=chunk_size
                ))
                chunk_idx += 1

            overlap_text = current[-overlap:] if overlap > 0 and current else ""
            current = (overlap_text + " " + sentence).strip() if overlap_text else sentence

    if current.strip():
        chunks.append(_make_chunk(
            current, doc_id, workspace_id, chunk_idx,
            start_char=0, end_char=len(current),
            page_hint=None, strategy="recursive", chunk_size=chunk_size
        ))

    return chunks
