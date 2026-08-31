"""
Embedding Service — OpenAI text-embedding-3-small
Generates dense vectors for chunks.
"""
import os
import hashlib
import math
from typing import Iterable

from openai import OpenAI

from core.config import EMBEDDING_MODEL, EMBEDDING_DIM


client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
EMBEDDING_MAX_CHARS_PER_ITEM = 8000
# Keep a healthy margin below the provider batch limit to avoid request-level
# failures on large corpora or token-dense documents.
EMBEDDING_MAX_ESTIMATED_TOKENS_PER_REQUEST = 200_000
EMBEDDING_ESTIMATED_CHARS_PER_TOKEN = 3


def _offline_embedding(text: str, dim: int = EMBEDDING_DIM) -> list[float]:
    """
    Deterministic local fallback embedding.

    This keeps the pipeline operational in environments without OpenAI access.
    The vector is derived from token hashes, so equal text yields equal vectors.
    """
    vector = [0.0] * dim
    tokens = [tok for tok in text.lower().split() if tok]
    if not tokens:
        return vector

    for token in tokens[:2048]:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "big") % dim
        weight = 1.0 + (digest[4] / 255.0)
        vector[idx] += weight

    norm = math.sqrt(sum(v * v for v in vector))
    if norm <= 0:
        return vector
    return [v / norm for v in vector]


def _truncate_for_embedding(text: str) -> str:
    """Apply the per-item payload ceiling used by the embedding endpoint."""
    return (text or "")[:EMBEDDING_MAX_CHARS_PER_ITEM]


def _estimate_tokens(text: str) -> int:
    """Cheap conservative token estimate used only for batch sizing."""
    if not text:
        return 1
    return max(1, math.ceil(len(text) / EMBEDDING_ESTIMATED_CHARS_PER_TOKEN))


def _iter_embedding_batches(texts: list[str]) -> Iterable[list[str]]:
    """
    Split embedding inputs into request-safe batches while preserving order.

    The OpenAI embeddings endpoint enforces a request-level token ceiling.
    Large documents can produce many chunks, so sending every chunk in a single
    request can fail even when each chunk is individually short enough.
    """
    current_batch: list[str] = []
    current_tokens = 0

    for raw_text in texts:
        text = _truncate_for_embedding(raw_text)
        estimated_tokens = _estimate_tokens(text)

        if current_batch and current_tokens + estimated_tokens > EMBEDDING_MAX_ESTIMATED_TOKENS_PER_REQUEST:
            yield current_batch
            current_batch = [text]
            current_tokens = estimated_tokens
            continue

        current_batch.append(text)
        current_tokens += estimated_tokens

    if current_batch:
        yield current_batch


def get_embedding(text: str, model: str = EMBEDDING_MODEL) -> list[float]:
    """
    Generate embedding for a single text.
    Truncates to 8000 tokens (safe for embedding models).

    Returns:
        List of 1536 floats (embedding vector)
    """
    if not client.api_key:
        return _offline_embedding(text)

    # Truncate if too long (embedding models have context limits)
    truncated = _truncate_for_embedding(text)

    response = client.embeddings.create(
        model=model,
        input=truncated
    )

    return response.data[0].embedding


def get_embeddings_batch(texts: list[str], model: str = EMBEDDING_MODEL) -> list[list[float]]:
    """
    Generate embeddings for multiple texts in batch.
    Qdrant client handles batching internally but we wrap here for convenience.

    Returns:
        List of embedding vectors (1536 dims each)
    """
    if not client.api_key:
        return [_offline_embedding(text) for text in texts]

    if not texts:
        return []

    embeddings: list[list[float]] = []
    for batch in _iter_embedding_batches(texts):
        response = client.embeddings.create(
            model=model,
            input=batch
        )
        embeddings.extend(item.embedding for item in response.data)

    return embeddings


def estimate_cost(texts: list[str], model: str = EMBEDDING_MODEL) -> float:
    """
    Estimate embedding cost in USD.
    text-embedding-3-small: $0.02 per 1M tokens (Mar 2024)
    Approximate: 1 token ≈ 4 chars
    """
    total_chars = sum(len(t) for t in texts)
    total_tokens = total_chars / 4
    price_per_million = 0.02
    return (total_tokens / 1_000_000) * price_per_million
