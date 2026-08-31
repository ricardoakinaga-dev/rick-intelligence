#!/usr/bin/env python3
"""
Benchmark Controlado — compara 4 estratégias de chunking com 3-5 perguntas.

Este é um benchmark CONTROLADO (não automático):
- Usa dataset real de 3-5 perguntas代表性的es
- Compara 4 estratégias de chunking
- Análise manual para determinar winners

Uso:
    python scripts/benchmark_controlado.py
    python scripts/benchmark_controlado.py --questions 5

Ref: 0016-backlog-priorizado.md (P2 - Benchmark controlado REPROJETAR)
     0011-contratos-de-avaliacao.md (Contrato 7: Benchmark Result)
"""
import argparse
import json
import sys
import time
from pathlib import Path
from datetime import datetime, timezone
from itertools import product

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.vector_service import ensure_collection, search_hybrid, index_chunks, delete_document_chunks
from services.chunker import recursive_chunk
from services.embedding_service import get_embeddings_batch
from models.schemas import SearchRequest, NormalizedDocument
from core.config import LOGS_DIR
from scripts.corpus_utils import load_dataset as load_workspace_dataset, load_normalized_document, canonical_document_ids


# 4 estratégias de chunking testadas
STRATEGIES = {
    "recursive_1000_200": {"chunk_size": 1000, "overlap": 200},
    "recursive_500_100": {"chunk_size": 500, "overlap": 100},
    "recursive_750_200": {"chunk_size": 750, "overlap": 200},
    "recursive_1500_300": {"chunk_size": 1500, "overlap": 300},
}


def parse_args():
    parser = argparse.ArgumentParser(description="Benchmark controlado de estratégias de chunking")
    parser.add_argument("--questions", type=int, default=5, help="Número de perguntas para testar (default: 5)")
    parser.add_argument("--top-k", type=int, default=5, help="Top-K para retrieval (default: 5)")
    parser.add_argument("--workspace-id", default="default")
    return parser.parse_args()


def load_dataset():
    """Load evaluation dataset."""
    return load_workspace_dataset("default")


def get_source_document(dataset: dict, workspace_id: str) -> tuple[str, NormalizedDocument]:
    """Get the source document used for chunking tests."""
    doc_id = dataset["questions"][0]["document_id"]
    canonical_ids = canonical_document_ids(workspace_id)
    if canonical_ids and doc_id not in canonical_ids:
        raise ValueError(f"Document {doc_id} is not part of the canonical corpus for {workspace_id}")
    return doc_id, load_normalized_document(workspace_id, doc_id)


def test_strategy(
    strategy_name: str,
    chunk_size: int,
    overlap: int,
    doc_id: str,
    normalized: NormalizedDocument,
    questions: list,
    workspace_id: str,
    top_k: int
) -> dict:
    """Test a single chunking strategy."""
    print(f"  Testing {strategy_name}... ", end="", flush=True)

    try:
        # Chunk with this configuration
        chunks = recursive_chunk(
            normalized,
            chunk_size=chunk_size,
            overlap=overlap,
            workspace_id=workspace_id
        )

        if not chunks:
            return {"strategy": strategy_name, "error": "No chunks", "hit_rate_top1": 0, "hit_rate_top5": 0, "avg_latency_ms": 0}

        # Generate embeddings
        texts = [c.text for c in chunks]
        embeddings = get_embeddings_batch(texts)

        # Delete old chunks and index new ones
        delete_document_chunks(doc_id)
        index_chunks(chunks, embeddings, workspace_id)

        # Test against questions
        hits_top1 = 0
        hits_top5 = 0
        latencies = []

        for q in questions:
            search_req = SearchRequest(
                query=q["pergunta"],
                workspace_id=workspace_id,
                top_k=top_k,
                threshold=0.0
            )
            start = time.time()
            search_resp = search_hybrid(search_req)
            latency_ms = (time.time() - start) * 1000
            latencies.append(latency_ms)

            retrieved_docs = [r.document_id for r in search_resp.results]
            expected_doc = q["document_id"]

            if retrieved_docs and retrieved_docs[0] == expected_doc:
                hits_top1 += 1
            if expected_doc in retrieved_docs:
                hits_top5 += 1

        total = len(questions)
        avg_latency = sum(latencies) / len(latencies) if latencies else 0

        print(f"hit@5={hits_top5/total:.0%}, chunks={len(chunks)}, latency={avg_latency:.0f}ms")

        return {
            "strategy": strategy_name,
            "chunk_size": chunk_size,
            "overlap": overlap,
            "chunk_count": len(chunks),
            "hit_rate_top1": hits_top1 / total,
            "hit_rate_top3": 0,  # Simplified
            "hit_rate_top5": hits_top5 / total,
            "avg_latency_ms": avg_latency,
            "total_questions": total,
            "hits_top1": hits_top1,
            "hits_top5": hits_top5,
        }

    except Exception as e:
        print(f"ERROR: {e}")
        return {
            "strategy": strategy_name,
            "error": str(e),
            "hit_rate_top1": 0,
            "hit_rate_top3": 0,
            "hit_rate_top5": 0,
            "avg_latency_ms": 0,
        }


def run_benchmark(workspace_id: str, num_questions: int, top_k: int):
    """Run the controlled benchmark."""
    print("=" * 70)
    print("BENCHMARK CONTROLADO — 4 ESTRATÉGIAS DE CHUNKING")
    print("=" * 70)

    # Load dataset
    dataset = load_dataset()
    questions = dataset["questions"][:num_questions]

    print(f"Dataset: {dataset['dataset_id']}")
    print(f"Perguntas testadas: {len(questions)}")
    print(f"Top-K: {top_k}")
    print()

    # Get source document
    doc_id, normalized = get_source_document(dataset, workspace_id)
    print(f"Documento fonte: {doc_id}")
    print()

    # Test each strategy
    results = []
    for strategy_name, params in STRATEGIES.items():
        result = test_strategy(
            strategy_name=strategy_name,
            chunk_size=params["chunk_size"],
            overlap=params["overlap"],
            doc_id=doc_id,
            normalized=normalized,
            questions=questions,
            workspace_id=workspace_id,
            top_k=top_k
        )
        results.append(result)

    # Find winner
    valid_results = [r for r in results if "error" not in r]
    if valid_results:
        winner = max(valid_results, key=lambda r: (r["hit_rate_top5"], -r["avg_latency_ms"]))

        print()
        print("=" * 70)
        print("RESULTADOS")
        print("=" * 70)
        print(f"{'Estratégia':<22} {'Size':>5} {'Overlap':>7} {'Chunks':>7} {'Hit@1':>8} {'Hit@5':>8} {'Latency':>10}")
        print("-" * 70)

        for r in sorted(results, key=lambda x: x["strategy"]):
            if "error" in r:
                print(f"{r['strategy']:<22} {'ERR':>5} {'--':>7} {'--':>7} {'--':>8} {'--':>8} {'--':>10}")
            else:
                print(f"{r['strategy']:<22} {r['chunk_size']:>5} {r['overlap']:>7} "
                      f"{r['chunk_count']:>7} {r['hit_rate_top1']:>7.0%} {r['hit_rate_top5']:>7.0%} "
                      f"{r['avg_latency_ms']:>9.0f}ms")

        print()
        print(f"WINNER: {winner['strategy']} (chunk_size={winner['chunk_size']}, overlap={winner['overlap']})")
        print(f"        hit@5={winner['hit_rate_top5']:.0%}, {winner['chunk_count']} chunks, latency={winner['avg_latency_ms']:.0f}ms")
        print()
        print("ANÁLISE MANUAL NECESSÁRIA:")
        print("  1. A estratégia vencedora é consistente entre perguntas easy/medium/hard?")
        print("  2. O número de chunks afeta a granularidade das respostas?")
        print("  3. Latência vs qualidade: o trade-off justifica a mudança?")
        print("=" * 70)

        # Build benchmark result for logging
        benchmark_result = {
            "date": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "questions_tested": len(questions),
            "top_k": top_k,
            "results": [
                {
                    "strategy": r["strategy"],
                    "chunk_size": r.get("chunk_size"),
                    "overlap": r.get("overlap"),
                    "chunk_count": r.get("chunk_count", 0),
                    "hit_rate_top1": r.get("hit_rate_top1", 0),
                    "hit_rate_top5": r.get("hit_rate_top5", 0),
                    "avg_latency_ms": r.get("avg_latency_ms", 0),
                }
                for r in results
            ],
            "winner": {
                "strategy": winner["strategy"],
                "hit_rate_top5": winner["hit_rate_top5"],
            }
        }

        # Save to file
        output_path = LOGS_DIR / "benchmark_latest.json"
        with open(output_path, "w") as f:
            json.dump(benchmark_result, f, ensure_ascii=False, indent=2)
        print(f"\nResultado salvo em: {output_path}")

        return benchmark_result
    else:
        print("Nenhum resultado válido!")
        return None


def main():
    args = parse_args()

    ensure_collection()

    run_benchmark(
        workspace_id=args.workspace_id,
        num_questions=args.questions,
        top_k=args.top_k
    )


if __name__ == "__main__":
    main()
