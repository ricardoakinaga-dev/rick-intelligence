# PHASE 2 — SPRINT 2.1: Retrieval Module

## Objetivo
Implementar busca vetorial híbrida (dense + sparse + RRF).

## Escopo
- Dense vector search
- Sparse vector search (BM25)
- RRF fusion
- Top-K ranking

## Tasks

### Task 2.1.1: Dense Vector Search
**O QUE:** Implementar busca com dense vectors (OpenAI embeddings)
**ONDE:** src/retrieval/service.py
**COMO:** Qdrant client com query vector dense
**DEPENDÊNCIA:** Sprint 0.4 (Telemetry)
**CRITÉRIO DE PRONTO:** Busca densa retorna resultados ordenados por score

### Task 2.1.2: Sparse Vector Search (BM25)
**O QUE:** Implementar busca com BM25 para sparse vectors
**ONDE:** src/retrieval/bm25.py
**COMO:** rank_bm25 ou equivalente para sparse search
**DEPENDÊNCIA:** Sprint 2.1.1
**CRITÉRIO DE PRONTO:** Busca esparsa retorna resultados com scores BM25

### Task 2.1.3: RRF Fusion
**O QUE:** Implementar Reciprocal Rank Fusion para combinar resultados
**ONDE:** src/retrieval/fusion.py
**COMO:** Fórmula RRF: score = Σ 1/(rank + k)
**DEPENDÊNCIA:** Sprint 2.1.1 + Sprint 2.1.2
**CRITÉRIO DE PRONTO:** RRF combina resultados densos e esparsos corretamente

### Task 2.1.4: Hybrid Search API
**O QUE:** Expor API de hybrid search via POST /search
**ONDE:** src/retrieval/routes.py
**COMO:** FastAPI route aplicando dense + sparse + RRF
**DEPENDÊNCIA:** Sprint 2.1.3
**CRITÉRIO DE PRONTO:** /search retorna resultados híbridos ordenados

## Riscos
- BM25 implementação pode ter performance issues (mitigação: caching)

## Critérios de Validação
- [ ] Dense search funcional
- [ ] Sparse search (BM25) funcional
- [ ] RRF fusion working
- [ ] /search retorna resultados ordenados por score RRF

## Status
⚪ PENDENTE