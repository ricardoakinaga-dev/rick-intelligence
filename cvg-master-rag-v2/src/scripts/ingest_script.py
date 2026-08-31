#!/usr/bin/env python3
"""Test ingest of the real document into Qdrant"""
import sys
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT.parent))

from scripts.corpus_utils import load_normalized_document, raw_document_path

print("=" * 60)
print("INGESTING REAL DOCUMENT INTO QDRANT")
print("=" * 60)

# 1. Load the canonical document
print("\n[1] Loading canonical document...")
from services.document_parser import parse_document, save_raw_json
from core.config import DOCUMENTS_DIR, DATA_DIR
from services.chunker import recursive_chunk
from core.config import CHUNK_SIZE, CHUNK_OVERLAP

try:
    dataset_path = DATA_DIR / "default" / "dataset.json"
    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    doc_id = dataset["questions"][0]["document_id"]
    canonical_raw = raw_document_path("default", doc_id)

    if canonical_raw.exists():
        normalized = load_normalized_document("default", doc_id)
        print(f"  OK: loaded canonical raw document {doc_id}")
    else:
        doc_path = DATA_DIR / "default" / "politicas_fluxpay.md"
        if not doc_path.exists():
            print(f"  ERRO: Documento nao encontrado: {doc_path}")
            sys.exit(1)

        normalized, metadata = parse_document(doc_path, workspace_id="default")
        print(f"  OK: parsed markdown fallback document_id={normalized.document_id}")
        print(f"  OK: source_type={normalized.source_type}, pages={len(normalized.pages)}")
        print(f"  OK: total_chars={sum(len(p['text']) for p in normalized.pages)}")

        save_path = save_raw_json(normalized, DOCUMENTS_DIR / "default")
        print(f"  OK: JSON salvo em {save_path}")

    # 2. Chunk
    print("\n[2] Chunking...")
    chunks = recursive_chunk(
        normalized,
        chunk_size=CHUNK_SIZE,
        overlap=CHUNK_OVERLAP,
        workspace_id="default"
    )
    print(f"  OK: {len(chunks)} chunks gerados")
    for i, c in enumerate(chunks[:5]):
        print(f"    Chunk {i}: id={c.chunk_id}, {c.chunk_size_chars} chars, page_hint={c.page_hint}")
        print(f"      Text: {c.text[:80].replace(chr(10), ' ')}...")
except Exception as e:
    print(f"  ERRO: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 3. Show what happens next
print("\n[3] Proximo passo: gerar embeddings e indexar...")
print("  Para completar a indexacao, voce precisa de OPENAI_API_KEY configurada.")
print("  O script de ingest completo (com embeddings) requer a API key.")
print("\n  Instrucoes:")
print("  1. Configure a API key: echo 'OPENAI_API_KEY=sk-...' >> .env")
print("  2. Use a ferramenta de busca para fazer o upload real")
print("  3. Ou aguarde proxima atualizacao do sistema")

# 4. Save chunks JSON for reference in the canonical corpus location
chunks_file = DOCUMENTS_DIR / "default" / f"{normalized.document_id}_chunks.json"
with open(chunks_file, "w", encoding="utf-8") as f:
    json.dump([c.model_dump() for c in chunks], f, ensure_ascii=False, indent=2)
print(f"\n[4] Chunks salvos em: {chunks_file}")

print("\n" + "=" * 60)
print(f"DOCUMENTO PARSED: {len(chunks)} CHUNKS PRONTOS")
print("=" * 60)
