#!/usr/bin/env python3
"""Test pipeline F0 - standalone script"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT.parent))



def run_f0_smoke():
    """Run the FASE 0 smoke workflow."""
    print("Testing FASE 0...")

    # Test imports
    from models.schemas import SearchRequest, QueryRequest
    from services.vector_service import ensure_collection, search_hybrid
    from services.search_service import search_and_answer

    # Ensure collection
    print("[1] Qdrant connection...")
    try:
        ensure_collection(recreate=False)
        print("    OK")
    except Exception as e:
        print(f"    ERROR: Unable to connect to Qdrant ({e})")
        return

    # Test search
    print("[2] Testing search...")
    req = SearchRequest(query="Qual o prazo para reembolso?", workspace_id="default", top_k=5, threshold=0.70)
    try:
        resp = search_hybrid(req)
        print(f"    Results: {len(resp.results)}, Low conf: {resp.low_confidence}")
        for r in resp.results[:2]:
            print(f"    - score={r.score:.3f} text={r.text[:50]}...")
    except Exception as e:
        print(f"    ERROR: {e}")

    # Test query
    print("[3] Testing query...")
    req2 = QueryRequest(query="Qual o prazo para reembolso?", workspace_id="default")
    try:
        resp2 = search_and_answer(req2)
        print(f"    Answer: {resp2.answer[:100]}...")
        print(f"    Conf: {resp2.confidence}, Latency: {resp2.latency_ms}ms")
    except Exception as e:
        print(f"    ERROR: {e}")

    print("DONE")


if __name__ == "__main__":
    run_f0_smoke()
