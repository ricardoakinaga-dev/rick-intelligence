"""
Grounding Service — verificação de que respostas estão fundamentadas em citações.

Implementa os controles de grounding da Fase 2:
- Verificação de citação: cada claim da resposta tem citação?
- Coverage: quanto do texto da resposta está citado?
- Flagging: respostas sem citação são marcadas

Ref: 0016-backlog-priorizado.md (P2 - Grounding controls)
     0011-contratos-de-avaliacao.md (Contrato 3: Grounded Answer)
"""
import re
import unicodedata
from typing import Optional
from models.schemas import Citation

SEMANTIC_GROUNDING_THRESHOLD = 0.62
SEMANTIC_GROUNDING_STRICT_THRESHOLD = 0.72
_SEMANTIC_EMBED_CACHE: dict[str, list[float]] = {}


# Frases que indicam claims factuais (precisam de citação)
FACTUAL_PATTERNS = [
    r"\d+ (dias|horas|minutos|segundos|meses|anos)",
    r"R\$\s*[\d.,]+",
    r"\d+[%º°]",
    r"(taxa|tarifa|prazo|valor|montante|percentual)",
    r"(aprovado|rejeitado|bloqueado|processado)",
    r"(válido|expirado|cancelado|ativo|inativo)",
    r"https?://",
    r"\d{2}/\d{2}/\d{4}",
]

# Frases que NÃO são claims (não precisam de citação)
NON_CLAIM_PATTERNS = [
    r"^blé$",
    r"não sei",
    r"não tenho",
    r"informação suficiente",
    r"não consigo",
    r"não tenho certeza",
    r"vou verificar",
    r"pode ser que",
    r"talvez",
    r"é possível que",
]


def is_factual_claim(sentence: str) -> bool:
    """Check if a sentence contains factual claims that need citation."""
    sentence_lower = sentence.lower().strip()

    # Check non-claim patterns first
    for pattern in NON_CLAIM_PATTERNS:
        if re.search(pattern, sentence_lower, re.IGNORECASE):
            return False

    # Check factual patterns
    for pattern in FACTUAL_PATTERNS:
        if re.search(pattern, sentence, re.IGNORECASE):
            return True

    # Most declarative answer sentences still require grounding even without
    # explicit numbers or percentages.
    content_tokens = re.findall(r"\b[\wÀ-ÿ]{3,}\b", sentence_lower)
    return len(content_tokens) >= 2


def calculate_citation_coverage(
    answer: str,
    citations: list[Citation]
) -> float:
    """
    Calculate what fraction of the answer text is covered by citations.

    Returns a value between 0.0 and 1.0.
    """
    if not answer or not citations:
        return 0.0

    # Simple approach: check if key factual phrases from answer
    # appear in any citation text
    answer_lower = answer.lower()

    # Split answer into sentences
    sentences = re.split(r"[.!?]\s+", answer)
    cited_sentences = 0

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        # If this sentence has factual claims, check if it's cited
        if is_factual_claim(sentence):
            # Check if any citation covers this sentence
            sentence_cited = any(
                _citation_supports_sentence(sentence, citation.text)
                for citation in citations
            )
            if sentence_cited:
                cited_sentences += 1

    total_sentences = len([s for s in sentences if s.strip()])
    if total_sentences == 0:
        return 1.0  # No sentences to cite

    return cited_sentences / total_sentences


def _sentence_contains_context(citation_text: str, sentence: str) -> bool:
    """
    Check if the citation text contains enough context from the sentence.
    Used for short factual claims where word overlap is minimal.
    """
    citation_lower = citation_text.lower()
    sentence_lower = sentence.lower()

    # Extract key context words (exclude common stopwords)
    stopwords = {'a', 'o', 'é', 'de', 'da', 'do', 'em', 'para', 'com', 'um', 'uma', 'que', 'e', 'os', 'as', 'no', 'na', 'nos', 'nas'}
    words = [w for w in re.findall(r"\b\w{4,}\b", sentence_lower) if w not in stopwords]

    # Check if at least 2 key words appear in citation
    key_words_found = sum(1 for w in words if w in citation_lower)
    return key_words_found >= 2


def _split_citation_units(text: str) -> list[str]:
    """Split long citation text into smaller semantic units."""
    units: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip(" -*\t")
        if not line:
            continue
        parts = re.split(r"(?<=[.!?])\s+", line)
        for part in parts:
            sentence = part.strip()
            if sentence:
                units.append(sentence)
    return units or [text]


def _normalize_token(token: str) -> str:
    base = unicodedata.normalize("NFKD", token.lower())
    return "".join(ch for ch in base if not unicodedata.combining(ch))


def _shared_prefix_len(left: str, right: str) -> int:
    count = 0
    for a, b in zip(left, right):
        if a != b:
            break
        count += 1
    return count


def _cognate_overlap_count(sentence: str, citation_text: str) -> int:
    sentence_tokens = {
        _normalize_token(tok)
        for tok in re.findall(r"\b[\wÀ-ÿ]{5,}\b", sentence)
    }
    citation_tokens = {
        _normalize_token(tok)
        for tok in re.findall(r"\b[\wÀ-ÿ]{5,}\b", citation_text)
    }
    overlaps = 0
    used_citation_tokens: set[str] = set()
    for sentence_token in sentence_tokens:
        for citation_token in citation_tokens:
            if citation_token in used_citation_tokens:
                continue
            if sentence_token == citation_token:
                overlaps += 1
                used_citation_tokens.add(citation_token)
                break
            if _shared_prefix_len(sentence_token, citation_token) >= 6:
                overlaps += 1
                used_citation_tokens.add(citation_token)
                break
    return overlaps


def _number_overlap(sentence: str, citation_text: str) -> set[str]:
    numbers_in_sentence = set(re.findall(r"[\d,.]+", sentence))
    numbers_in_citation = set(re.findall(r"[\d,.]+", citation_text))
    return numbers_in_sentence & numbers_in_citation


def _semantic_similarity(text_a: str, text_b: str) -> float:
    """
    Cross-lingual semantic similarity fallback for grounding.

    This only runs when lexical checks fail. If embeddings are unavailable, the
    function degrades safely to 0.0 so grounding remains conservative offline.
    """
    try:
        from services.embedding_service import get_embedding, client as embedding_client
    except Exception:
        return 0.0

    if not getattr(embedding_client, "api_key", ""):
        return 0.0

    def _embed(text: str) -> list[float]:
        normalized = re.sub(r"\s+", " ", text.strip())
        if normalized not in _SEMANTIC_EMBED_CACHE:
            _SEMANTIC_EMBED_CACHE[normalized] = get_embedding(normalized[:1500])
        return _SEMANTIC_EMBED_CACHE[normalized]

    try:
        emb_a = _embed(text_a)
        emb_b = _embed(text_b)
    except Exception:
        return 0.0

    dot = sum(x * y for x, y in zip(emb_a, emb_b))
    norm_a = sum(x * x for x in emb_a) ** 0.5
    norm_b = sum(x * x for x in emb_b) ** 0.5
    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _citation_supports_sentence(sentence: str, citation_text: str) -> bool:
    """Return True when a citation lexically or semantically supports a sentence."""
    for citation_unit in _split_citation_units(citation_text):
        sentence_lower = sentence.lower()
        citation_text_lower = citation_unit.lower()

        words = set(re.findall(r"\b\w{4,}\b", sentence_lower))
        citation_words = set(re.findall(r"\b\w{4,}\b", citation_text_lower))
        overlap = words & citation_words
        number_overlap = _number_overlap(sentence, citation_unit)
        cognate_overlap = _cognate_overlap_count(sentence, citation_unit)

        if len(overlap) >= 3:
            return True
        if len(overlap) >= 1 and len(number_overlap) >= 1:
            return True
        if cognate_overlap >= 2:
            return True
        if cognate_overlap >= 1 and len(number_overlap) >= 1:
            return True
        if _sentence_contains_context(citation_unit, sentence):
            return True

        semantic_score = _semantic_similarity(sentence, citation_unit)
        if number_overlap and semantic_score >= SEMANTIC_GROUNDING_THRESHOLD:
            return True
        if semantic_score >= SEMANTIC_GROUNDING_STRICT_THRESHOLD:
            return True
    return False


def verify_grounding(
    answer: str,
    citations: list[Citation],
    threshold: float = 0.8
) -> dict:
    """
    Verify that an answer is properly grounded in citations.

    Returns a dict with:
    - grounded: bool (True if coverage >= threshold)
    - citation_coverage: float (0.0-1.0)
    - uncited_claims: list of sentences without citation
    - needs_review: bool (True if grounded=False)
    """
    if not answer:
        return {
            "grounded": False,
            "citation_coverage": 0.0,
            "uncited_claims": [],
            "needs_review": True,
            "reason": "Empty answer"
        }

    if not citations:
        return {
            "grounded": False,
            "citation_coverage": 0.0,
            "uncited_claims": [answer],
            "needs_review": True,
            "reason": "No citations provided"
        }

    # Calculate coverage
    coverage = calculate_citation_coverage(answer, citations)

    # Find uncited factual claims
    sentences = re.split(r"[.!?]\s+", answer)
    uncited = []

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        if is_factual_claim(sentence):
            # Check if this sentence is covered by any citation
            is_cited = any(
                _citation_supports_sentence(sentence, citation.text)
                for citation in citations
            )
            if not is_cited:
                uncited.append(sentence)

    grounded = coverage >= threshold

    return {
        "grounded": grounded,
        "citation_coverage": round(coverage, 3),
        "uncited_claims": uncited,
        "needs_review": not grounded,
        "reason": None if grounded else f"Citation coverage {coverage:.0%} < {threshold:.0%}"
    }


def enrich_citations_with_filename(
    citations: list[Citation],
    document_metadata: dict[str, str]
) -> list[Citation]:
    """
    Enrich citations with document filenames from metadata.

    Args:
        citations: List of Citation objects
        document_metadata: Dict mapping document_id -> filename

    Returns:
        Citations with document_filename populated
    """
    enriched = []
    for citation in citations:
        if citation.document_id and citation.document_id in document_metadata:
            citation.document_filename = document_metadata[citation.document_id]
        enriched.append(citation)
    return enriched
