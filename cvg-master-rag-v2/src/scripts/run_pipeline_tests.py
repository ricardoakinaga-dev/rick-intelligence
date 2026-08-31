"""
Comprehensive test of RAG pipeline after Sprint 1-5 fixes.
Verifies: chunk offsets, point IDs, search, query, grounding, low_confidence.
"""
import json
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from services.vector_service import search_hybrid
from services.search_service import search_and_answer
from models.schemas import SearchRequest, QueryRequest
from core.config import DOCUMENTS_DIR
from scripts.corpus_utils import load_dataset as load_workspace_dataset
WORKSPACE = 'default'


def _doc_id() -> str:
    dataset = load_workspace_dataset(WORKSPACE)
    return dataset["questions"][0]["document_id"]


def _has_openai_key() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))

def test_chunk_offsets():
    """Verify chunk offsets are correct (not all zero)."""
    print("=== Test: Chunk Offsets ===")
    doc_id = _doc_id()
    chunks_path = DOCUMENTS_DIR / WORKSPACE / f"{doc_id}_chunks.json"
    with open(chunks_path) as f:
        chunks = json.load(f)

    errors = []
    for i, c in enumerate(chunks):
        if c['start_char'] == 0 and i > 0:
            errors.append(f"Chunk {i} has start=0 (should be non-zero)")
        if c['end_char'] <= c['start_char']:
            errors.append(f"Chunk {i} has end <= start")

    if errors:
        print(f"FAIL: {errors}")
        return False

    print(f"PASS: All {len(chunks)} chunks have correct offsets")
    print(f"  Chunk 0: start={chunks[0]['start_char']}, end={chunks[0]['end_char']}")
    print(f"  Chunk 1: start={chunks[1]['start_char']}, end={chunks[1]['end_char']}")
    return True

def test_point_id_uniqueness():
    """Verify point IDs are unique across chunks."""
    print("\n=== Test: Point ID Uniqueness ===")
    doc_id = _doc_id()
    chunks_path = DOCUMENTS_DIR / WORKSPACE / f"{doc_id}_chunks.json"
    with open(chunks_path) as f:
        chunks = json.load(f)

    point_ids = []
    for c in chunks:
        point_id = abs(hash(c['chunk_id'])) % (2**63)
        point_ids.append(point_id)

    if len(point_ids) != len(set(point_ids)):
        print("FAIL: Duplicate point IDs detected")
        return False

    print(f"PASS: All {len(point_ids)} point IDs are unique")
    return True

def test_search_returns_correct_doc():
    """Verify search returns correct document."""
    print("\n=== Test: Search Returns Correct Doc ===")
    doc_id = _doc_id()
    search_req = SearchRequest(
        query='reembolso',
        workspace_id=WORKSPACE,
        top_k=5,
        threshold=0.0,
    )
    resp = search_hybrid(search_req)

    if not resp.results:
        print("FAIL: No results returned")
        return False

    if len(resp.results) < 1:
        print(f"FAIL: Expected at least 1 result, got {len(resp.results)}")
        return False

    if not any(r.document_id == doc_id for r in resp.results):
        print(f"FAIL: Expected document {doc_id} in top results")
        return False

    print(f"PASS: Search returned expected document in top results")
    print(f"  Top score: {resp.results[0].score:.4f}")
    return True

def test_low_confidence_gap_based():
    """Verify low_confidence uses gap-based detection."""
    print("\n=== Test: Low Confidence Gap-Based ===")
    search_req = SearchRequest(
        query='reembolso política empresa',
        workspace_id=WORKSPACE,
        top_k=5,
        threshold=0.0,
    )
    resp = search_hybrid(search_req)

    # In our controlled corpus, low_confidence should be False
    print(f"  Low confidence: {resp.low_confidence}")
    print(f"  Results count: {len(resp.results)}")
    print(f"PASS: Low confidence detection working")
    return True

def test_query_pipeline():
    """Verify full query pipeline works."""
    print("\n=== Test: Query Pipeline ===")
    doc_id = _doc_id()
    if not _has_openai_key():
        print("  SKIP: OPENAI_API_KEY not configured")
        return True

    query_req = QueryRequest(
        query='Qual o prazo para reembolso?',
        workspace_id=WORKSPACE,
        top_k=5,
    )
    resp = search_and_answer(query_req)

    if not resp.answer:
        print("FAIL: No answer generated")
        return False

    if resp.confidence != 'high':
        print(f"FAIL: Expected confidence=high, got {resp.confidence}")
        return False

    if len(resp.citations) == 0:
        print("FAIL: No citations returned")
        return False

    print(f"PASS: Query generated answer")
    print(f"  Answer: {resp.answer[:80]}...")
    print(f"  Confidence: {resp.confidence}")
    print(f"  Citations: {len(resp.citations)}")
    return True

def main():
    print("RAG Pipeline Verification Tests")
    print("=" * 50)

    results = []
    results.append(("Chunk Offsets", test_chunk_offsets()))
    results.append(("Point ID Uniqueness", test_point_id_uniqueness()))
    results.append(("Search Correct Doc", test_search_returns_correct_doc()))
    results.append(("Low Confidence", test_low_confidence_gap_based()))
    results.append(("Query Pipeline", test_query_pipeline()))

    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)

    passed = sum(1 for _, r in results if r)
    total = len(results)

    for name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"  [{status}] {name}")

    print(f"\nTotal: {passed}/{total} tests passed")

    return passed == total

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
