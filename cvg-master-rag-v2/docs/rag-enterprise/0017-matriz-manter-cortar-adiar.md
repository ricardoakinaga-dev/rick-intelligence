# 0017 — Matriz: Manter / Cortar / Adiar / Reprojetar

## Objetivo

Matriz consolidada de todas as decisões sobre cada item do plano original, com justificativas e referência ao documento que fundamentou a decisão.

---

## Como Ler Esta Matriz

| Classificação | Significado |
|---|---|
| **MANTER AGORA** | Implementar na Fase 0 |
| **ADIAR** | Não na Fase 0, entra quando a fase correta justificar |
| **CORTAR** | Remover do backlog (não faz sentido para contexto atual) |
| **REPROJETAR** | Manter a ideia, mas mudar forma de implementação |

---

## Matriz Completa

### INGESTÃO

| Item | Classificação | Justificativa | Ref |
|---|---|---|---|
| Document Service | REPROJETAR | Manter lógica, usar filesystem em vez de MinIO na F0 | 0002, 0004 |
| PDF parsing | MANTER AGORA | Core essencial | 0002 |
| DOCX parsing | MANTER AGORA | Core essencial | 0002 |
| MD parsing | MANTER AGORA | Core essencial | 0002 |
| TXT parsing | MANTER AGORA | Core essencial | 0002 |
| XLSX parsing | ADIAR | Complexidade tabular diferente; validar texto primeiro | 0002 |
| PPT parsing | ADIAR | Não é core | 0002 |
| HTML parsing | ADIAR | Não é core | 0002 |
| Tabelas complexas | ADIAR | Requer pipeline específico | 0002 |
| Metadados por documento | MANTER AGORA | Essencial para segregação futura | 0002 |
| MinIO storage | ADIAR (FASE 3) | Só faz sentido com plataforma mais distribuída | 0002, 0004, 0008 |

---

### CHUNKING

| Item | Classificação | Justificativa | Ref |
|---|---|---|---|
| Recursive chunking | MANTER AGORA | Baseline sólido, sem custo adicional | 0002, 0004 |
| Semantic chunking | ADIAR (FASE 2) | Experimental, entra após baseline validado | 0002, 0006 |
| Page by page | ADIAR (FASE 2) | Só para jurídicos após dataset validar | 0002, 0006 |
| Agentic chunking | REPROJETAR (ADIAR FASE 2) | Custo alto, benefício não provado ainda | 0002, 0006 |
| chunk_size 1000 | MANTER AGORA | Padrão recursive | 0004 |
| chunk_overlap 200 | MANTER AGORA | Padrão recursive | 0004 |
| Overlap 800 (agentic) | ADIAR (FASE 2) | Só para agentic | 0002 |

---

### RETRIEVAL

| Item | Classificação | Justificativa | Ref |
|---|---|---|---|
| Vetor denso (OpenAI) | MANTER AGORA | Core essencial | 0002, 0004 |
| Vetor esparso (BM25) | MANTER AGORA | Core do diferencial | 0002, 0004 |
| RRF Fusion | MANTER AGORA | Matematicamente simples e sólido | 0002, 0004 |
| Busca híbrida | MANTER AGORA | Padrão enterprise, não "luxo" | 0002 |
| Reranking (Cohere) | ADIAR (FASE 1) | Útil mas não crítico em F0 | 0002, 0005 |
| HyDE | REPROJETAR (ADIAR FASE 2) | Custo 2x LLM, benefício não comprovado | 0002, 0006 |
| Web Search | ADIAR (FASE 2/3) | Só depois do core validar | 0002, 0006 |
| Threshold configurável | MANTER AGORA | Essencial para tuning | 0004, 0005 |
| Top-K configurável | MANTER AGORA | Essencial para tuning | 0004, 0005 |

---

### AVALIAÇÃO

| Item | Classificação | Justificativa | Ref |
|---|---|---|---|
| LLM Judge | REPROJETAR | Usar como triagem, não como veredicto | 0002, 0011 |
| Revisão humana | MANTER AGORA | Obrigatória para decisões de gate | 0002, 0011 |
| Dataset real | MANTER AGORA (CRÍTICO) | Nenhum benchmark é válido sem isso | 0002, 0004 |
| Evaluation por documento | ADIAR (FASE 1) | Avaliação estruturada depois de baseline | 0002, 0005 |
| Benchmark 12 cenários | CORTAR (FASE 0/1) | Prematura, cara, misleading | 0002, 0003 |
| Perguntas sintéticas | REPROJETAR | Podem ajudar, não são a verdade | 0002, 0011 |

---

### ARQUITETURA

| Item | Classificação | Justificativa | Ref |
|---|---|---|---|
| FastAPI | MANTER AGORA | Escolha correta | 0002, 0004 |
| Modular Monolith | MANTER AGORA | Suficiente até F3 | 0002, 0008 |
| Microserviços | CORTAR (FASE 0) | Sem necessidade operacional | 0002, 0003 |
| LangGraph | ADIAR (FASE 2/3) | Só entra se a orquestração premium justificar | 0002, 0008 |
| Qdrant | MANTER AGORA | Dense + sparse nativamente | 0008 |
| MinIO | ADIAR (FASE 3) | Só ganha prioridade na plataforma enterprise | 0002, 0008 |
| Next.js frontend | ADIAR (FASE 1/2) | Não bloqueia a fundação, mas é central no produto final | 0003, 0005, 0006, 0008 |
| Supabase Auth | ADIAR (FASE 3) | Multitenancy não é F0 | 0002, 0007 |

---

### MULTITENANCY

| Item | Classificação | Justificativa | Ref |
|---|---|---|---|
| workspace_id em todas tabelas | MANTER AGORA | Preparação para multi sem complicar | 0012 |
| Isolamento lógico (F0) | MANTER AGORA | Filter por workspace_id | 0012 |
| Collections separadas | ADIAR (FASE 3) | Só quando multitenancy real | 0007, 0012 |
| White label | ADIAR (FASE 3) | Depende de multitenancy | 0002, 0007 |
| Painel técnico simples | ADIAR (FASE 1) | Primeira camada visual operacional | 0003, 0005 |
| Frontend premium robusto | ADIAR (FASE 2) | Camada central do produto premium | 0003, 0006, 0008 |
| Admin panel completo | ADIAR (FASE 3) | Admin completo só na plataforma enterprise | 0002, 0005, 0007 |

---

### AUDIO E OUTPUT

| Item | Classificação | Justificativa | Ref |
|---|---|---|---|
| Audio (FasterWhisper) | ADIAR (FASE 1/2) | Não é core RAG | 0002, 0005 |
| Citações estruturadas | REPROJETAR | Já existem no núcleo; evoluem visualmente na F2 | 0006, 0020 |
| Grounding controls | REPROJETAR | Já existem no núcleo; amadurecem na F2 | 0006, 0020 |
| Streaming responses | ADIAR (FASE 2) | Complexidade adicional | 0006 |

---

## Resumo por Classificação

### MANTER AGORA (Fase 0)

```
Ing:
  ✅ PDF parser
  ✅ DOCX parser
  ✅ MD parser
  ✅ TXT parser
  ✅ Metadados por documento

Chunk:
  ✅ Recursive chunking (1000/200)

Retrieval:
  ✅ Vetor denso (OpenAI)
  ✅ Vetor esparso (BM25)
  ✅ RRF Fusion
  ✅ Busca híbrida
  ✅ Threshold configurável
  ✅ Top-K configurável

Arch:
  ✅ FastAPI
  ✅ Modular Monolith
  ✅ Qdrant

Data:
  ✅ workspace_id em todas tabelas
  ✅ Dataset 20+ perguntas reais
  ✅ Logging de queries

Avaliação:
  ✅ Revisão humana
```

### ADIAR

```
Ing: XLSX, PPT, HTML, tabelas complexas, MinIO
Chunk: Semantic, Page-by-page, Agentic
Retrieval: Reranking (F1), HyDE (F2), Web search (F2/3)
Arch: LangGraph (F2/3), Supabase Auth (F3), Next.js frontend (F1/2)
Multi/UI: Collections separadas (F3), White label (F3), Frontend premium (F2)
Audio: FasterWhisper (F1/2)
Avaliação: Evaluation estruturada (F1), Benchmark automático (F2)
Output: Streaming (F2), evolução visual de citações/grounding (F2)
Admin/UI: Painel mínimo (F1), Frontend premium (F2), Painel completo (F3)
```

### CORTAR

```
Ing: MinIO em F0
Chunk: nenhuma
Retrieval: nenhuma
Arch: Microserviços em F0
Avaliação: Benchmark automático 12 cenários em F0/F1
Multi: nenhuma (replanejado)
Audio: nenhuma
Output: nenhuma
```

### REPROJETAR

```
Ing: Document Service (usar filesystem, não MinIO)
Retrieval: HyDE (entra como fallback controlado, não padrão)
Avaliação: LLM Judge (triagem, não veredicto)
Arch: LangGraph (se e quando orquestração ficar complexa)
```

---

## Próximo Passo

Ir para `0018-plano-de-validacao-com-dataset-real.md` — plano de validação com dataset real.
