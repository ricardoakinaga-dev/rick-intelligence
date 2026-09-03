"""Lexical substrate — behavioral mirror of validated sparse retrieval.

MD5 token hash % 100_000, min_len=2, stop-token filtering, tf log(1+c) with
collision aggregation. Deterministic across processes and restarts.
"""

from __future__ import annotations

import hashlib
import math
import re

SPARSE_MODULUS = 100_000

MEANINGLESS_QUERY_TOKENS = frozenset({
    "a", "ao", "aos", "as", "ate", "até", "com", "como", "da", "das", "de", "do", "dos",
    "e", "em", "essa", "esse", "esta", "este", "foi", "na", "nas", "no", "nos", "o", "os",
    "ou", "para", "por", "qual", "quais", "quando", "quanto", "que", "se", "sem", "ser",
    "sao", "são", "sua", "suas", "seu", "seus", "uma", "um", "usa", "usada", "usado",
    "utiliza", "utilizado",
})

LOW_SIGNAL_DOMAIN_TOKENS = frozenset({
    "animal", "animais", "paciente", "pacientes",
    "gato", "gatos", "felino", "felinos", "cat", "cats", "feline", "felines",
    "cao", "caes", "cão", "cães", "cachorro", "cachorros", "cachorra", "cachorras",
    "canino", "caninos", "dog", "dogs", "canine", "canines",
    "sintoma", "sintomas", "sinal", "sinais",
    "doenca", "doenças", "doença", "doencas",
    "protocolo", "protocolos", "protocol", "protocols", "approach", "management",
})


def sparse_hash(token: str) -> int:
    return int(hashlib.md5(token.encode()).hexdigest(), 16) % SPARSE_MODULUS


def tokenize_terms(text: str, min_len: int = 2) -> list[str]:
    tokens = []
    for token in re.findall(r"\w{2,}", (text or "").lower()):
        if len(token) < min_len:
            continue
        if token in MEANINGLESS_QUERY_TOKENS:
            continue
        tokens.append(token)
    return tokens


def content_query_terms(text: str) -> set[str]:
    return {t for t in tokenize_terms(text) if t not in LOW_SIGNAL_DOMAIN_TOKENS and not t.isdigit()}


def sparse_vector(text: str) -> dict[int, float]:
    """BM25-style sparse vector: {index: log(1+tf)} with collision aggregation."""
    freq: dict[str, int] = {}
    for tok in tokenize_terms(text):
        freq[tok] = freq.get(tok, 0) + 1
    index_scores: dict[int, float] = {}
    for tok, count in freq.items():
        idx = sparse_hash(tok)
        index_scores[idx] = index_scores.get(idx, 0.0) + math.log(1 + count)
    return index_scores


def sparse_overlap_score(query: str, text: str) -> float:
    """Deterministic lexical overlap in 0..1 (normalized sparse dot product)."""
    qvec = sparse_vector(query)
    tvec = sparse_vector(text)
    if not qvec or not tvec:
        return 0.0
    dot = sum(score * tvec.get(idx, 0.0) for idx, score in qvec.items())
    qnorm = math.sqrt(sum(v * v for v in qvec.values()))
    tnorm = math.sqrt(sum(v * v for v in tvec.values()))
    if qnorm <= 0 or tnorm <= 0:
        return 0.0
    return dot / (qnorm * tnorm)
