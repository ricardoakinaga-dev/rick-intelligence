#!/usr/bin/env python3
"""
Chunking Tuning Script — testa diferentes configurações de chunk_size/overlap.

Testa: 500/750/1000/1500 para chunk_size e 100/200/300 para overlap.
Compara hit rates para identificar melhor configuração.

Uso:
    python scripts/tune_chunking.py
    python scripts/tune_chunking.py --top-k 3

Ref: 0016-backlog-priorizado.md (P1 - Tuning chunk_size/overlap)
"""
import argparse
import json
import sys
import time
from pathlib import Path
from itertools import product

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.vector_service import ensure_collection, search_hybrid, index_chunks, delete_document_chunks
from services.chunker import recursive_chunk
from services.embedding_service import get_embeddings_batch
from models.schemas import SearchRequest
from scripts.corpus_utils import load_dataset as load_workspace_dataset, load_normalized_document


CHUNK_SIZES = [500, 750, 1000, 1500]
OVERLAPS = [100, 200, 300]


def parse_args():
    parser = argparse.ArgumentParser(description="Tuning de chunk_size/overlap")
    parser.add_argument("--top-k", type=int, default=5, help="Top-K para retrieval (default: 5)")
    parser.add_argument("--threshold", type=float, default=0.0, help="Threshold (default: 0.0)")
    parser.add_argument("--workspace-id", default="default")
    return parser.parse_args()


def load_dataset():
    """Load evaluation dataset."""
    return load_workspace_dataset("default")


def test_config(
    chunk_size: int,
    overlap: int,
    workspace_id: str,
    dataset: dict,
    top_k: int,
    threshold: float
) -> dict:
    """
    Test a single chunk_size/overlap configuration.
    Returns hit rate metrics.
    """
    # Get the actual document ID from the dataset
    actual_doc_id = dataset["questions"][0]["document_id"]

    try:
        normalized = load_normalized_document(workspace_id, actual_doc_id)
    except FileNotFoundError:
        return {
            "chunk_size": chunk_size,
            "overlap": overlap,
            "chunk_count": 0,
            "hit_rate_top1": 0.0,
            "hit_rate_top5": 0.0,
            "error": f"Document {actual_doc_id} not found in canonical corpus"
        }

    # Chunk with this configuration
    chunks = recursive_chunk(
        normalized,
        chunk_size=chunk_size,
        overlap=overlap,
        workspace_id=workspace_id
    )

    if not chunks:
        return {
            "chunk_size": chunk_size,
            "overlap": overlap,
            "chunk_count": 0,
            "hit_rate_top1": 0.0,
            "hit_rate_top5": 0.0,
            "error": "No chunks generated"
        }

    # Generate embeddings
    texts = [c.text for c in chunks]
    embeddings = get_embeddings_batch(texts)

    # Delete old test chunks and index new ones
    delete_document_chunks(actual_doc_id)
    index_chunks(chunks, embeddings, workspace_id)

    # Test against dataset
    hits_top1 = 0
    hits_top5 = 0
    total = len(dataset["questions"])
    avg_latency = 0

    for q in dataset["questions"]:
        search_req = SearchRequest(
            query=q["pergunta"],
            workspace_id=workspace_id,
            top_k=top_k,
            threshold=threshold
        )
        start = time.time()
        search_resp = search_hybrid(search_req)
        latency_ms = (time.time() - start) * 1000

        retrieved_docs = [r.document_id for r in search_resp.results]
        expected_doc = q["document_id"]

        # Check if expected doc is retrieved
        hit1 = len(retrieved_docs) > 0 and retrieved_docs[0] == expected_doc
        hit5 = expected_doc in retrieved_docs

        hits_top1 += 1 if hit1 else 0
        hits_top5 += 1 if hit5 else 0
        avg_latency += latency_ms

    avg_latency /= total if total > 0 else 1

    return {
        "chunk_size": chunk_size,
        "overlap": overlap,
        "chunk_count": len(chunks),
        "hit_rate_top1": hits_top1 / total,
        "hit_rate_top5": hits_top5 / total,
        "avg_latency_ms": avg_latency
    }


def run_tuning(workspace_id: str, top_k: int, threshold: float):
    """Run tuning across all configurations."""
    dataset = load_dataset()
    total = len(dataset["questions"])

    print("=" * 70)
    print("CHUNKING TUNING")
    print("=" * 70)
    print(f"Dataset: {dataset['dataset_id']} ({total} perguntas)")
    print(f"Configurations to test: {len(CHUNK_SIZES) * len(OVERLAPS)}")
    print(f"Top-K: {top_k}, Threshold: {threshold}")
    print()

    results = []
    for size, overlap in product(CHUNK_SIZES, OVERLAPS):
        print(f"Testing chunk_size={size}, overlap={overlap}... ", end="", flush=True)
        try:
            result = test_config(size, overlap, workspace_id, dataset, top_k, threshold)
            results.append(result)
            print(f"hit@5={result['hit_rate_top5']:.1%}, chunks={result['chunk_count']}")
        except Exception as e:
            print(f"ERROR: {e}")
            results.append({
                "chunk_size": size,
                "overlap": overlap,
                "chunk_count": 0,
                "hit_rate_top1": 0.0,
                "hit_rate_top5": 0.0,
                "error": str(e)
            })

    # Find best configuration
    valid_results = [r for r in results if "error" not in r]
    if valid_results:
        best = max(valid_results, key=lambda r: (r["hit_rate_top5"], -r["avg_latency_ms"]))

        print()
        print("=" * 70)
        print("RESULTS SUMMARY")
        print("=" * 70)
        print(f"{'Size':>6} {'Overlap':>8} {'Chunks':>7} {'Hit@1':>8} {'Hit@5':>8} {'Latency':>10}")
        print("-" * 70)
        for r in sorted(results, key=lambda x: (x["chunk_size"], x["overlap"])):
            error = r.get("error", "")
            if error:
                print(f"{r['chunk_size']:>6} {r['overlap']:>8} {'ERR':>7} {'--':>8} {'--':>8} {'--':>10}")
            else:
                print(f"{r['chunk_size']:>6} {r['overlap']:>8} {r['chunk_count']:>7} "
                      f"{r['hit_rate_top1']:>7.1%} {r['hit_rate_top5']:>7.1%} {r['avg_latency_ms']:>9.0f}ms")

        print()
        print(f"BEST: chunk_size={best['chunk_size']}, overlap={best['overlap']} "
              f"(hit@5={best['hit_rate_top5']:.1%}, chunks={best['chunk_count']})")
        print("=" * 70)

        return best
    else:
        print("No valid results!")
        return None


def main():
    args = parse_args()

    ensure_collection()

    best = run_tuning(
        workspace_id=args.workspace_id,
        top_k=args.top_k,
        threshold=args.threshold
    )

    if best:
        print()
        print("Para aplicar a melhor configuração, atualize no .env:")
        print(f"  CHUNK_SIZE={best['chunk_size']}")
        print(f"  CHUNK_OVERLAP={best['overlap']}")


if __name__ == "__main__":
    main()
