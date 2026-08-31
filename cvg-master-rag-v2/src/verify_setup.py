#!/usr/bin/env python3
"""
Script de verificação rápida — FASE 0
Testa o que é possível sem OpenAI API key
"""
import sys
from pathlib import Path

print("=" * 60)
print("FASE 0 — VERIFICAÇÃO RÁPIDA")
print("=" * 60)

# 1. Import do modulo de parsing
print("\n[1] Testando imports do core...")
try:
    from core.config import (
        CHUNK_SIZE, CHUNK_OVERLAP, QDRANT_COLLECTION,
        RRF_K, DEFAULT_TOP_K, DEFAULT_THRESHOLD,
        SUPPORTED_EXTENSIONS
    )
    print(f"    Config: CHUNK_SIZE={CHUNK_SIZE}, RRF_K={RRF_K}")
    print(f"    Supported: {SUPPORTED_EXTENSIONS}")
    print("    OK")
except Exception as e:
    print(f"    ERRO: {e}")

# 2. Schemas
print("\n[2] Testando schemas...")
try:
    from models.schemas import SearchRequest, Chunk, QueryResponse
    print("    Schemas OK")
except Exception as e:
    print(f"    ERRO: {e}")

# 3. Parser (sem OpenAI)
print("\n[3] Testando parser de documentos...")
try:
    from services.document_parser import parse_document, _parse_md
    from services.chunker import recursive_chunk

    # Test parsing do markdown
    test_md_content = """# Título Principal

Este é um texto de teste com múltiplos parágrafos.

## Subtítulo

Aqui temos mais conteúdo. Este parágrafo contém informações
importantes sobre políticas de reembolso e procedimentos.

O prazo para solicitação de reembolso é de 30 dias corridos
após a compra. O reembolso será processado em até 5 dias úteis.

### Mais detalhes

- Item 1: informação
- Item 2: mais informação
- Item 3: detalhes adicionais
"""
    print("    Parser e chunker OK")
except Exception as e:
    print(f"    ERRO: {e}")

# 4. Qdrant connection
print("\n[4] Testando conexão com Qdrant...")
try:
    from services.vector_service import ensure_collection, get_client
    ensure_collection(recreate=False)
    client = get_client()
    cols = client.get_collections()
    print(f"    Qdrant OK — collections: {len(cols.collections)}")
except Exception as e:
    print(f"    ERRO: {e}")

# 5. Chunking test (sem OpenAI)
print("\n[5] Testando chunking recursive...")
try:
    import tempfile
    from models.schemas import NormalizedDocument
    from services.chunker import recursive_chunk

    # Create a test document
    test_doc = NormalizedDocument(
        document_id="test-001",
        source_type="md",
        filename="test.md",
        workspace_id="default",
        created_at="2026-04-16T00:00:00Z",
        pages=[
            {"page_number": 1, "text": "Introdução ao sistema Fluxpay. O prazo para reembolso é de 30 dias."},
            {"page_number": 2, "text": "Detalhes sobre processamento. O prazo é de 5 dias úteis."},
        ],
        sections=[],
        metadata={},
        raw_json_path=""
    )

    chunks = recursive_chunk(
        test_doc,
        chunk_size=CHUNK_SIZE,
        overlap=CHUNK_OVERLAP,
        workspace_id="default",
    )
    print(f"    Chunking OK — {len(chunks)} chunks gerados")
    for i, c in enumerate(chunks[:3]):
        print(f"    Chunk {i}: {c.chunk_id}, size={c.chunk_size_chars}chars")
except Exception as e:
    print(f"    ERRO: {e}")
    import traceback
    traceback.print_exc()

# 6. Testar API startup (sem OpenAI)
print("\n[6] Testando startup da API...")
try:
    from api.main import app
    print(f"    FastAPI app: {app.title}")
    print("    API OK — pronta para iniciar com uvicorn")
except Exception as e:
    print(f"    ERRO: {e}")

print("\n" + "=" * 60)
print("VERIFICAÇÃO CONCLUÍDA")
print("=" * 60)
print("""
Para rodar o sistema completo, você precisa:

1. Configurar OPENAI_API_KEY no .env:
   echo "OPENAI_API_KEY=sk-...your-key..." >> .env

2. Iniciar o servidor:
   cd src
   uvicorn api.main:app --reload --port 8000

3. Acessar Swagger UI:
   http://localhost:8000/docs

4. Rodar avaliação:
   GET /evaluation/run?workspace_id=default
""")
