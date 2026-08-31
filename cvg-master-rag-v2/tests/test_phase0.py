"""
Tests for Phase 0 Foundation RAG
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from fastapi.testclient import TestClient

# We'll use httpx for async tests later
# For now, basic import tests

def test_imports():
    """Test that all modules can be imported."""
    from core.config import (
        CHUNK_SIZE, CHUNK_OVERLAP, QDRANT_COLLECTION,
        RRF_K, DEFAULT_TOP_K, DEFAULT_THRESHOLD,
        SUPPORTED_EXTENSIONS
    )
    assert CHUNK_SIZE == 1200
    assert CHUNK_OVERLAP == 240
    assert RRF_K == 60
    assert ".pdf" in SUPPORTED_EXTENSIONS
    assert ".docx" in SUPPORTED_EXTENSIONS
    assert ".md" in SUPPORTED_EXTENSIONS
    assert ".txt" in SUPPORTED_EXTENSIONS


def test_chunk_schema():
    """Test chunk schema validation."""
    from models.schemas import Chunk
    from datetime import datetime, timezone

    chunk = Chunk(
        chunk_id="chunk_doc1_0000",
        document_id="doc1",
        workspace_id="default",
        chunk_index=0,
        text="Este é um texto de teste com mais de 20 caracteres.",
        start_char=0,
        end_char=50,
        page_hint=None,
        strategy="recursive",
        chunk_size_chars=50,
        created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )

    assert chunk.chunk_id == "chunk_doc1_0000"
    assert chunk.strategy == "recursive"
    assert chunk.chunk_size_chars == 50


def test_search_request():
    """Test search request schema."""
    from models.schemas import SearchRequest

    req = SearchRequest(
        query="Qual o prazo de reembolso?",
        workspace_id="default",
        top_k=5,
        threshold=0.70
    )

    assert req.query == "Qual o prazo de reembolso?"
    assert req.threshold == 0.70
    assert req.retrieval_mode == "híbrida"


def test_query_request():
    """Test query request schema."""
    from models.schemas import QueryRequest

    req = QueryRequest(
        query="Como funciona o reembolso?",
        workspace_id="default"
    )

    assert req.top_k == 5
    assert req.threshold == 0.70


def test_evaluation_question():
    """Test evaluation question schema."""
    from models.schemas import EvaluationQuestion

    q = EvaluationQuestion(
        id=1,
        pergunta="Qual o prazo?",
        document_id="doc001",
        trecho_esperado="30 dias",
        resposta_esperada="30 dias corridos",
        dificuldade="easy",
        categoria="procedimento"
    )

    assert q.dificuldade == "easy"
    assert q.categoria == "procedimento"


def test_chunker_import():
    """Test that chunker module can be imported."""
    from services.chunker import recursive_chunk
    assert callable(recursive_chunk)


def test_document_parser_import():
    """Test that parser module can be imported."""
    from services.document_parser import parse_document, SUPPORTED_EXTENSIONS
    assert ".pdf" in SUPPORTED_EXTENSIONS
    assert ".docx" in SUPPORTED_EXTENSIONS


def test_active_corpus_has_matching_chunks():
    """Active corpus must keep raw/chunks paired 1:1 for non-legacy path."""
    from core.config import DATA_DIR

    docs_dir = DATA_DIR / "documents" / "default"
    raw_ids = {p.stem.removesuffix("_raw") for p in docs_dir.glob("*_raw.json")}
    chunk_ids = {p.stem.removesuffix("_chunks") for p in docs_dir.glob("*_chunks.json")}
    assert not (raw_ids - chunk_ids), (
        f"Orphan raw files in active corpus without chunks: {sorted(raw_ids - chunk_ids)}"
    )
    assert raw_ids == chunk_ids


def test_no_legacy_test_scripts_in_src_root():
    """Only `src/tests` should contain pytest-style `test_*.py` modules."""
    src_root = Path(__file__).resolve().parent.parent / "src"
    legacy = [
        p.name for p in src_root.glob("test_*.py")
        if p.is_file()
    ]
    assert not legacy, f"Legacy pytest-style script files in src root: {legacy}"


def test_no_legacy_document_field_in_operational_code():
    """Contract migration should keep `documento_fonte` out of operational src code."""
    src_root = Path(__file__).resolve().parent.parent / "src"
    tests_root = src_root / "tests"
    operational_py_files = [
        p for p in src_root.rglob("*.py")
        if p.is_file() and p.name != "test_sprint5.py" and tests_root not in p.parents
    ]
    offenders = []
    for p in sorted(operational_py_files):
        if "documento_fonte" in p.read_text(encoding="utf-8"):
            offenders.append(str(p.relative_to(src_root.parent)))

    assert not offenders, (
        "Legacy contract field found in operational code:\n- "
        + "\n- ".join(offenders)
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
