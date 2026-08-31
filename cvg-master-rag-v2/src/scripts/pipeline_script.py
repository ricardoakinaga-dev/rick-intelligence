#!/usr/bin/env python3
"""
Script para testar o pipeline completo da Fase 0
Faz upload do documento de políticas e depois roda avaliação
"""
import sys
import os
import time
from pathlib import Path

# Setup paths
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import json
from models.schemas import SearchRequest, QueryRequest
from services.document_parser import parse_document, save_raw_json
from services.chunker import recursive_chunk
from services.embedding_service import get_embeddings_batch
from services.vector_service import index_chunks, search_hybrid, ensure_collection
from services.search_service import search_and_answer
from core.config import DATA_DIR, CHUNK_SIZE, CHUNK_OVERLAP
from scripts.corpus_utils import load_normalized_document, raw_document_path


def test_pipeline():
    print("=" * 60)
    print("TESTE COMPLETO — FASE 0 FOUNDATION RAG")
    print("=" * 60)

    # ── 1. Setup ───────────────────────────────────────────────
    print("\n[1] Setup: inicializando Qdrant collection...")
    try:
        ensure_collection(recreate=False)
        print("    ✅ Collection pronta")
    except Exception as e:
        print(f"    ❌ Erro: {e}")
        return False

    # ── 2. Upload Documento ────────────────────────────────
    print("\n[2] Upload: carregando documento canônico...")
    dataset_path = DATA_DIR / "default" / "dataset.json"
    if not dataset_path.exists():
        print(f"    ❌ Dataset não encontrado: {dataset_path}")
        return False

    try:
        with open(dataset_path, "r", encoding="utf-8") as f:
            dataset = json.load(f)

        doc_id = dataset["questions"][0]["document_id"]
        canonical_raw = raw_document_path("default", doc_id)

        if canonical_raw.exists():
            normalized = load_normalized_document("default", doc_id)
            print(f"    ✅ Documento canônico carregado: {doc_id}")
            print(f"       - source_type: {normalized.source_type}")
            print(f"       - pages: {len(normalized.pages)}")
            print(f"       - chars: {sum(len(p['text']) for p in normalized.pages)}")
        else:
            doc_path = DATA_DIR / "default" / "politicas_fluxpay.md"
            if not doc_path.exists():
                print(f"    ❌ Documento não encontrado: {doc_path}")
                return False

            normalized, metadata = parse_document(doc_path, workspace_id="default")
            save_raw_json(normalized, DATA_DIR / "default")
            print(f"    ✅ Documento parseado e salvo: {normalized.document_id}")
            print(f"       - source_type: {normalized.source_type}")
            print(f"       - pages: {len(normalized.pages)}")
            print(f"       - chars: {sum(len(p['text']) for p in normalized.pages)}")
    except Exception as e:
        print(f"    ❌ Erro no ingest: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Build chunks and index from the canonical normalized document.
    try:
        chunks = recursive_chunk(
            normalized,
            chunk_size=CHUNK_SIZE,
            overlap=CHUNK_OVERLAP,
            workspace_id="default"
        )
        embeddings = get_embeddings_batch([c.text for c in chunks])
        index_chunks(chunks, embeddings, "default")
        print(f"    ✅ Indexado: {len(chunks)} chunks")
    except Exception as e:
        print(f"    ❌ Erro ao indexar: {e}")
        import traceback
        traceback.print_exc()
        return False

    # ── 3. Retrieval Test ─────────────────────────────────────
    print("\n[3] Retrieval: testando busca híbrida...")

    test_queries = [
        "Qual o prazo para reembolso?",
        "Quanto tempo demora o processamento de reembolso?",
        "Como solicitar estorno de transação?",
        "Qual a taxa do Pix?",
        "Quem aprova despesas acima de 10 mil?",
    ]

    hit_count = 0
    for q_text in test_queries:
        try:
            req = SearchRequest(query=q_text, workspace_id="default", top_k=5, threshold=0.70)
            resp = search_hybrid(req)

            print(f"\n    Query: '{q_text}'")
            print(f"    Results: {len(resp.results)} | Low confidence: {resp.low_confidence}")

            if resp.results:
                for i, r in enumerate(resp.results[:3]):
                    print(f"      [{i+1}] score={r.score:.3f} | {r.text[:80]}...")
            else:
                print(f"      ⚠️  Nenhum resultado acima de threshold")

        except Exception as e:
            print(f"    ❌ Erro: {e}")

    # ── 4. Query Test ─────────────────────────────────────────
    print("\n[4] Query: testando busca + resposta...")

    query_text = "Qual o prazo para solicitar reembolso?"
    try:
        req = QueryRequest(query=query_text, workspace_id="default", top_k=5, threshold=0.70)
        resp = search_and_answer(req)

        print(f"\n    Query: '{query_text}'")
        print(f"    Answer: {resp.answer[:200]}...")
        print(f"    Confidence: {resp.confidence}")
        print(f"    Grounded: {resp.grounded}")
        print(f"    Chunks used: {len(resp.chunks_used)}")
        print(f"    Latency: {resp.latency_ms}ms")

    except Exception as e:
        print(f"    ❌ Erro: {e}")
        import traceback
        traceback.print_exc()

    # ── 5. Evaluation ─────────────────────────────────────────
    print("\n[5] Evaluation: rodando avaliação no dataset...")

    if dataset_path.exists():
        questions = dataset["questions"]
        print(f"    Dataset: {len(questions)} perguntas")

        hits_top1 = 0
        hits_top5 = 0

        for q in questions:
            try:
                req = SearchRequest(
                    query=q["pergunta"],
                    workspace_id="default",
                    top_k=5,
                    threshold=0.70
                )
                resp = search_hybrid(req)

                retrieved_docs = [r.document_id for r in resp.results]
                expected_doc = q.get("document_id", "")

                # Match by filename
                hit_top1 = len(retrieved_docs) > 0 and expected_doc in retrieved_docs[0]
                hit_top5 = expected_doc in retrieved_docs

                if hit_top1:
                    hits_top1 += 1
                if hit_top5:
                    hits_top5 += 1

            except Exception as e:
                print(f"      ❌ Erro na pergunta {q['id']}: {e}")

        total = len(questions)
        hr_top1 = hits_top1 / total if total > 0 else 0
        hr_top5 = hits_top5 / total if total > 0 else 0

        print(f"\n    📊 RESULTADOS:")
        print(f"       Hit Rate Top-1: {hits_top1}/{total} = {hr_top1:.1%}")
        print(f"       Hit Rate Top-5: {hits_top5}/{total} = {hr_top5:.1%}")
        print(f"       Target F0: >= 60%")

        if hr_top5 >= 0.60:
            print(f"    ✅ GATE F0 APROVADO!")
        else:
            print(f"    ⚠️  Gate F0 não aprovado ({hr_top5:.1%} < 60%)")

    print("\n" + "=" * 60)
    print("TESTE COMPLETO FINALIZADO")
    print("=" * 60)

    return True


if __name__ == "__main__":
    test_pipeline()
